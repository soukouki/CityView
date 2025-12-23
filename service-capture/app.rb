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
      screen_width: ENV.fetch("CAPTURE_SCREEN_WIDTH").to_i,
      screen_height: ENV.fetch("CAPTURE_SCREEN_HEIGHT").to_i,
      redraw_wait: ENV.fetch("CAPTURE_REDRAW_WAIT_SECONDS", "0.2").to_f,
    )

    GAME_MANAGER = ServiceCapture::GameProcessManager.new(
      executable: ENV.fetch("GAME_EXECUTABLE", "simutrans-extended"),
      # Host expects binaries mounted at /app/bin by compose
      executable_dir: ENV.fetch("GAME_EXECUTABLE_DIR", "/app/bin"),
      pakset_name: ENV.fetch("PAKSET_NAME"),
      display: ENV.fetch("DISPLAY", ":99"),
      screen_width: ENV.fetch("CAPTURE_SCREEN_WIDTH").to_i,
      screen_height: ENV.fetch("CAPTURE_SCREEN_HEIGHT").to_i,
      ttl_seconds: ENV.fetch("CAPTURE_TTL_SECONDS", "600").to_i,
      boot_timeout_seconds: ENV.fetch("GAME_BOOT_TIMEOUT_SECONDS", "180").to_i,
      boot_poll_interval_seconds: ENV.fetch("GAME_BOOT_POLL_INTERVAL_SECONDS", "2").to_i,
      boot_check_x: ENV.fetch("GAME_BOOT_CHECK_X", "256").to_i,
      boot_check_y: ENV.fetch("GAME_BOOT_CHECK_Y", "256").to_i,
      x11_controller: X11_CONTROLLER,
    )

    # Worker pool for parallel screenshot processing
    WORKER_POOL = Concurrent::FixedThreadPool.new(
      ENV.fetch("CAPTURE_WORKER_THREADS", "8").to_i
    )

    SCREENSHOT = ServiceCapture::ScreenshotService.new(
      storage_client: STORAGE,
      crop_width: ENV.fetch("CAPTURE_CROP_WIDTH").to_i,
      crop_height: ENV.fetch("CAPTURE_CROP_HEIGHT").to_i,
      crop_offset_x: ENV.fetch("CAPTURE_CROP_OFFSET_X", "256").to_i,
      crop_offset_y: ENV.fetch("CAPTURE_CROP_OFFSET_Y", "64").to_i,
      x11_controller: X11_CONTROLLER,
      worker_pool: WORKER_POOL,
      capture_lock: CAPTURE_LOCK,
      redraw_wait: ENV.fetch("CAPTURE_REDRAW_WAIT_SECONDS", "0.2").to_f,
      scrot_settle: ENV.fetch("CAPTURE_SCROT_SETTLE_SECONDS", "0.3").to_f,
      scrot_timeout: ENV.fetch("CAPTURE_SCROT_TIMEOUT_SECONDS", "30").to_i,
      crop_timeout: ENV.fetch("CAPTURE_CROP_TIMEOUT_SECONDS", "30").to_i,
      upload_timeout: ENV.fetch("CAPTURE_UPLOAD_TIMEOUT_SECONDS", "30").to_i,
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
    # request: { "save_data_name": "...", "x": 0, "y": 0, "output_path": "...", "zoom_level": "..." }
    # response: { "status": "ok" }
    post "/capture" do
      payload = parse_json_body!
      require_fields!(payload, :save_data_name, :x, :y, :output_path, :zoom_level)

      save_data_name = payload["save_data_name"].to_s
      if save_data_name.empty?
        halt 400, json(error: "invalid_save_data_name", message: "save_data_name cannot be empty")
      end
      x = Integer(payload["x"])
      if x < 0
        halt 400, json(error: "invalid_x", message: "x must be non-negative")
      end
      y = Integer(payload["y"])
      if y < 0
        halt 400, json(error: "invalid_y", message: "y must be non-negative")
      end
      output_path = payload["output_path"].to_s
      if output_path.empty?
        halt 400, json(error: "invalid_output_path", message: "output_path cannot be empty")
      end
      zoom_level = payload["zoom_level"]
      if !["one_eighth", "quarter", "half", "normal", "double"].include?(zoom_level)
        halt 400, json(error: "invalid_zoom_level", message: "zoom_level must be one of one_eighth, quarter, half, normal, double")
      end

      # Ensure game process for this save is running (restart if save differs).
      CAPTURE_LOCK.synchronize do
        GAME_MANAGER.ensure_running(save_data_name)
      end

      # Screenshot service handles locking internally for optimal parallelization
      image_path = SCREENSHOT.capture!(
        output_path:,
        x:,
        y:,
        zoom_level:,
      )

      GAME_MANAGER.touch
      
      json(status: "success")
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
