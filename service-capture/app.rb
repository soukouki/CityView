# frozen_string_literal: true

require "json"
require "securerandom"
require "sinatra/base"
require "sinatra/json"
require "concurrent"

require_relative "lib/game_process_manager"
require_relative "lib/screenshot_service"
require_relative "lib/storage_client"
require_relative "lib/x11_controller"
require_relative "lib/image_processor"

module ServiceCapture
  class App < Sinatra::Base
    configure do
      set :server, :puma
      set :bind, "0.0.0.0"
      set :port, ENV.fetch("PORT", "5000").to_i
      set :show_exceptions, false
    end

    before do
      content_type :json
    end

    helpers do
      def parse_json_body!
        request.body.rewind
        body = request.body.read
        JSON.parse(body.empty? ? "{}" : body)
      rescue JSON::ParserError
        halt 400, json(error: "invalid_json")
      end

      def require_fields!(obj, *fields)
        missing = fields.reject { |f| obj.key?(f.to_s) }
        halt 400, json(error: "missing_fields", missing:) unless missing.empty?
      end
    end

    # ---- Global singletons per process ----
    CAPTURE_LOCK = Mutex.new

    STORAGE = ServiceCapture::StorageClient.new(
      base_url: ENV.fetch("STORAGE_URL", "http://storage"),
    )

    X11_CONTROLLER = ServiceCapture::X11Controller.new(
      screen_width: ENV.fetch("CAPTURE_SCREEN_WIDTH", "4352").to_i,
      screen_height: ENV.fetch("CAPTURE_SCREEN_HEIGHT", "2048").to_i,
    )

    GAME_MANAGER = ServiceCapture::GameProcessManager.new(
      executable: ENV.fetch("GAME_EXECUTABLE", "simutrans-extended"),
      # Host expects binaries mounted at /app/bin by compose
      executable_dir: ENV.fetch("GAME_EXECUTABLE_DIR", "/app/bin"),
      pakset_name: ENV.fetch("PAKSET_NAME"),
      pakset_size: ENV.fetch("PAKSET_SIZE", "64").to_i,
      display: ENV.fetch("DISPLAY", ":99"),
      screen_width: ENV.fetch("CAPTURE_SCREEN_WIDTH", "4352").to_i,
      screen_height: ENV.fetch("CAPTURE_SCREEN_HEIGHT", "2048").to_i,
      ttl_seconds: ENV.fetch("CAPTURE_TTL_SECONDS", "600").to_i,
      boot_timeout_seconds: ENV.fetch("GAME_BOOT_TIMEOUT_SECONDS", "180").to_i,
      boot_poll_interval_seconds: ENV.fetch("GAME_BOOT_POLL_INTERVAL_SECONDS", "2").to_i,
      boot_check_x: ENV.fetch("GAME_BOOT_CHECK_X", "256").to_i,
      boot_check_y: ENV.fetch("GAME_BOOT_CHECK_Y", "256").to_i,
      x11_controller: X11_CONTROLLER,
    )

    SCREENSHOT = ServiceCapture::ScreenshotService.new(
      storage_client: STORAGE,
      crop_width: ENV.fetch("CAPTURE_CROP_WIDTH", "3840").to_i,
      crop_height: ENV.fetch("CAPTURE_CROP_HEIGHT", "1920").to_i,
      crop_offset_x: ENV.fetch("CAPTURE_CROP_OFFSET_X", "256").to_i,
      crop_offset_y: ENV.fetch("CAPTURE_CROP_OFFSET_Y", "64").to_i,
      x11_controller: X11_CONTROLLER,
    )

    # TTL watcher (best-effort)
    TTL_TASK = Concurrent::TimerTask.new(execution_interval: 15) do
      GAME_MANAGER.check_ttl_and_stop
    rescue => e
      warn "[ttl] error=#{e.class} msg=#{e.message}"
    end
    TTL_TASK.execute

    get "/health" do
      json(ok: true)
    end

    # POST /capture
    # request: { "save_data_name": "...", "x": 0, "y": 0 }
    # response: { "image_path": "/images/screenshots/{id}.png", "screenshot_id": "{id}" }
    post "/capture" do
      payload = parse_json_body!
      require_fields!(payload, :save_data_name, :x, :y)

      save_data_name = payload["save_data_name"].to_s
      x = Integer(payload["x"])
      y = Integer(payload["y"])

      # Only one capture at a time per container.
      result = nil
      CAPTURE_LOCK.synchronize do
        # Ensure game process for this save is running (restart if save differs).
        GAME_MANAGER.ensure_running(save_data_name)

        # Generate screenshot id with save/x/y + container hint + random.
        screenshot_id = ServiceCapture::ScreenshotService.build_screenshot_id(
          save_data_name:,
          x:,
          y:,
          container_hint: ENV["HOSTNAME"],
          random: SecureRandom.alphanumeric(8)
        )

        image_path = SCREENSHOT.capture!(
          screenshot_id:,
          x:,
          y:
        )

        GAME_MANAGER.touch
        result = { screenshot_id:, image_path: }
      end

      json(result)
    rescue ServiceCapture::Errors::BadRequest => e
      warn "[/capture] bad_request msg=#{e.message}"
      halt 400, json(error: e.code, message: e.message)
    rescue ServiceCapture::Errors::GameBootTimeout => e
      warn "[/capture] game_boot_timeout msg=#{e.message}"
      halt 503, json(error: "game_boot_timeout", message: e.message)
    rescue ServiceCapture::Errors::CommandFailed => e
      warn "[/capture] command_failed msg=#{e.message}"
      halt 500, json(error: "command_failed", message: e.message)
    rescue ServiceCapture::Errors::StorageError => e
      warn "[/capture] storage_error msg=#{e.message}"
      halt 502, json(error: "storage_error", message: e.message)
    rescue => e
      warn "[/capture] error=#{e.class} msg=#{e.message}\n#{e.backtrace&.first(10)&.join("\n")}"
      halt 500, json(error: "internal_error")
    end

    error do
      e = env["sinatra.error"]
      warn "[sinatra] error=#{e.class} msg=#{e.message}"
      halt 500, json(error: "internal_error")
    end
  end
end
