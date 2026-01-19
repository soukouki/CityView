# frozen_string_literal: true

require "json"
require "securerandom"
require "sinatra/base"
require "sinatra/json"
require "concurrent"

require_relative "lib/capture_config"
require_relative "lib/game_process_manager"
require_relative "lib/screenshot_service"
require_relative "lib/storage_client"
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

    GAME_MANAGER = ServiceCapture::GameProcessManager.new(
      display: ENV.fetch("DISPLAY", ":99"),
      ttl_seconds: ENV.fetch("CAPTURE_TTL_SECONDS", "600").to_i,
      boot_timeout_seconds: ENV.fetch("GAME_BOOT_TIMEOUT_SECONDS", "180").to_i,
      boot_poll_interval_seconds: ENV.fetch("GAME_BOOT_POLL_INTERVAL_SECONDS", "2").to_i,
      boot_check_x: ENV.fetch("GAME_BOOT_CHECK_X", "256").to_i,
      boot_check_y: ENV.fetch("GAME_BOOT_CHECK_Y", "256").to_i,
    )

    # Worker pool for parallel screenshot processing
    WORKER_POOL = Concurrent::FixedThreadPool.new(
      ENV.fetch("CAPTURE_WORKER_THREADS", "8").to_i
    )

    SCREENSHOT = ServiceCapture::ScreenshotService.new(
      storage_client: STORAGE,
      worker_pool: WORKER_POOL,
      capture_lock: CAPTURE_LOCK,
      scrot_settle: ENV.fetch("CAPTURE_SCROT_SETTLE_SECONDS", "0.3").to_f,
      scrot_timeout: ENV.fetch("CAPTURE_SCROT_TIMEOUT_SECONDS", "30").to_i,
      crop_timeout: ENV.fetch("CAPTURE_CROP_TIMEOUT_SECONDS", "30").to_i,
      upload_timeout: ENV.fetch("CAPTURE_UPLOAD_TIMEOUT_SECONDS", "30").to_i,
      game_manager: GAME_MANAGER,
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
    # request: {
    #   "folder_path": "...",
    #   "binary_name": "...",
    #   "pakset_name": "...",
    #   "save_data_name": "...",
    #   "crop_offset_x": 128,
    #   "crop_offset_y": 64,
    #   "margin_width": 160,
    #   "margin_height": 80,
    #   "effective_width": 3200,
    #   "effective_height": 1600,
    #   "capture_redraw_wait_seconds": 0.2,
    #   "zoom_level": "normal",
    #   "x": 0,
    #   "y": 0,
    #   "output_path": "..."
    # }
    # response: { "status": "success" }
    post "/capture" do
      payload = parse_json_body!
      require_fields!(payload,
        :folder_path, :binary_name, :pakset_name, :save_data_name,
        :crop_offset_x, :crop_offset_y,
        :margin_width, :margin_height,
        :effective_width, :effective_height,
        :capture_redraw_wait_seconds,
        :zoom_level, :x, :y, :output_path
      )

      config = ServiceCapture::CaptureConfig.new(payload)

      # Validation
      unless config.valid?
        error_msg = config.validation_error
        halt 400, json(error: "invalid_request", message: error_msg)
      end

      # Check executable exists
      unless File.exist?(config.executable_path)
        halt 400, json(error: "binary_not_found", message: "binary not found: #{config.executable_path}")
      end

      # Check save data exists
      unless File.exist?(config.save_path)
        halt 400, json(error: "save_data_not_found", message: "save data not found: #{config.save_path}")
      end

      # Ensure game process for this config is running (restart if config differs).
      CAPTURE_LOCK.synchronize do
        GAME_MANAGER.ensure_running(config)
      end

      # Screenshot service handles locking internally for optimal parallelization
      SCREENSHOT.capture!(config)

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
