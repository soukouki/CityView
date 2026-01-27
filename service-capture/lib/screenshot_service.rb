# frozen_string_literal: true

require "fileutils"
require "cgi"
require "concurrent"

require_relative "image_processor"
require_relative "errors"

module ServiceCapture
  class ScreenshotService
    def initialize(storage_client:, worker_pool:, capture_lock:,
                   scrot_settle:, scrot_timeout:, crop_timeout:, upload_timeout:,
                   game_manager:)
      @storage = storage_client
      @worker_pool = worker_pool
      @capture_lock = capture_lock
      @scrot_settle = scrot_settle
      @scrot_timeout = scrot_timeout
      @crop_timeout = crop_timeout
      @upload_timeout = upload_timeout
      @game_manager = game_manager

      FileUtils.mkdir_p("/tmp/service-capture")
    end

    def capture!(config)
      request_start = Time.now
      screenshot_id = "#{self.class.normalize_component(config.output_path.split("/").last)}_#{Time.now.strftime("%Y%m%d%H%M%S")}_#{rand(1000)}"
      raw_path = "/tmp/service-capture/#{screenshot_id}_raw.png"
      cropped_path = "/tmp/service-capture/#{screenshot_id}_cropped.png"

      puts "[capture] request_id=#{screenshot_id} stage=start"

      # === Critical Section: Game操作 + scrot起動 ===
      # このロックは次のリクエストが画面を変更するのを防ぐ
      # scrotがフレームバッファを読み取るまで保持する必要がある
      scrot_future = nil
      lock_start = Time.now

      @capture_lock.synchronize do
        # ゲーム操作
        game_op_start = Time.now
        perform_game_operations(config)
        puts "[capture] request_id=#{screenshot_id} stage=game_operation duration=#{((Time.now - game_op_start) * 1000).round}ms"

        # 画面再描画待ち
        sleep config.capture_redraw_wait_seconds

        # scrot起動(非同期)
        scrot_start = Time.now
        scrot_future = async_scrot(raw_path)
        puts "[capture] request_id=#{screenshot_id} stage=scrot_started duration=#{((Time.now - scrot_start) * 1000).round}ms"

        # scrotがフレームバッファを読み取るまで待つ
        sleep @scrot_settle

        puts "[capture] request_id=#{screenshot_id} stage=lock_released duration=#{((Time.now - lock_start) * 1000).round}ms"
      end
      # === End of Critical Section ===

      # ここからはロック不要(画面は変更されても良い)
      # scrot圧縮完了待ち
      scrot_wait_start = Time.now
      wait_for_scrot(scrot_future, screenshot_id)
      puts "[capture] request_id=#{screenshot_id} stage=scrot_complete duration=#{((Time.now - scrot_wait_start) * 1000).round}ms"

      # crop実行(非同期)
      crop_start = Time.now
      crop_future = async_crop(raw_path, cropped_path, config, screenshot_id)
      wait_for_crop(crop_future, screenshot_id)
      puts "[capture] request_id=#{screenshot_id} stage=crop_complete duration=#{((Time.now - crop_start) * 1000).round}ms"

      # upload実行(非同期)
      upload_start = Time.now
      upload_future = async_upload(cropped_path, config.output_path, screenshot_id)
      wait_for_upload(upload_future, screenshot_id)
      puts "[capture] request_id=#{screenshot_id} stage=upload_complete duration=#{((Time.now - upload_start) * 1000).round}ms"

      puts "[capture] request_id=#{screenshot_id} stage=complete total_duration=#{((Time.now - request_start) * 1000).round}ms"

      config.output_path
    ensure
      FileUtils.rm_f(raw_path) if defined?(raw_path)
      FileUtils.rm_f(cropped_path) if defined?(cropped_path)
    end

    def self.normalize_component(str)
      s = str.to_s.strip
      s = "unknown" if s.empty?
      # keep alnum, dash, underscore; replace others with '-'
      s.gsub(/[^0-9A-Za-z_\-]/, "-")[0, 80]
    end

    private

    def perform_game_operations(config)
      puts "[game_ops] move to center"
      @game_manager.x11_controller.mousemove_to_center()

      puts "[game_ops] move to coordinate x=#{config.x}, y=#{config.y}"
      @game_manager.x11_controller.move_to_coordinate(config.x, config.y)

      puts "[game_ops] zoom from #{@game_manager.current_zoom_level} to #{config.zoom_level}"
      zoom!(config.zoom_level, config.capture_redraw_wait_seconds)

      puts "[game_ops] hide cursor"
      @game_manager.x11_controller.hide_cursor(map_x: config.x, map_y: config.y)
    end

    def async_scrot(output_path)
      Concurrent::Future.execute(executor: @worker_pool) do
        @game_manager.x11_controller.screenshot_full(output_path)
        output_path
      end
    end

    def async_crop(input_path, output_path, config, request_id)
      Concurrent::Future.execute(executor: @worker_pool) do
        puts "[crop] request_id=#{request_id} input=#{input_path} output=#{output_path}"
        ServiceCapture::ImageProcessor.crop_center_fixed!(
          input_path: input_path,
          output_path: output_path,
          crop_width: config.image_width,
          crop_height: config.image_height,
          offset_x: config.crop_offset_x,
          offset_y: config.crop_offset_y
        )
        output_path
      end
    end

    def async_upload(local_path, output_path, request_id)
      Concurrent::Future.execute(executor: @worker_pool) do
        puts "[upload] request_id=#{request_id} local=#{local_path} remote=#{output_path}"
        @storage.put_file!(output_path: output_path, local_path: local_path)
        output_path
      end
    end

    def wait_for_scrot(future, request_id)
      begin_time = Time.now
      future.value!(@scrot_timeout)
      end_time = Time.now
      puts "[scrot] request_id=#{request_id} duration=#{((end_time - begin_time) * 1000).round}ms"
      if end_time - begin_time >= @scrot_timeout
        raise ServiceCapture::Errors::TimeoutError, @scrot_timeout, "scrot operation"
      end
    rescue => e
      warn "[scrot] request_id=#{request_id} error=#{e.class} msg=#{e.message}"
      raise
    end

    def wait_for_crop(future, request_id)
      begin_time = Time.now
      future.value!(@crop_timeout)
      end_time = Time.now
      puts "[crop] request_id=#{request_id} duration=#{((end_time - begin_time) * 1000).round}ms"
      if end_time - begin_time >= @crop_timeout
        raise ServiceCapture::Errors::TimeoutError, @crop_timeout, "crop operation"
      end
    rescue => e
      warn "[crop] request_id=#{request_id} error=#{e.class} msg=#{e.message}"
      raise
    end

    def wait_for_upload(future, request_id)
      begin_time = Time.now
      future.value!(@upload_timeout)
      end_time = Time.now
      puts "[upload] request_id=#{request_id} duration=#{((end_time - begin_time) * 1000).round}ms"
      if end_time - begin_time >= @upload_timeout
        raise ServiceCapture::Errors::TimeoutError, @upload_timeout, "upload operation"
      end
    rescue => e
      warn "[upload] request_id=#{request_id} error=#{e.class} msg=#{e.message}"
      raise
    end

    def zoom!(level, redraw_wait)
      zoom_levels = ["one_eighth", "quarter", nil, "half", nil, nil, "normal", nil, nil, "double"] # ゲーム内でのズームレベル対応
      current_index = zoom_levels.index(@game_manager.current_zoom_level)
      target_index = zoom_levels.index(level)
      raise "invalid current zoom level #{@game_manager.current_zoom_level}" if current_index.nil?
      raise "invalid target zoom level #{level}" if target_index.nil?
      puts "[zoom] from #{@game_manager.current_zoom_level}(#{current_index}) to #{level}(#{target_index})"
      if target_index < current_index
        (current_index - target_index).times { @game_manager.x11_controller.zoom_out; sleep redraw_wait }
      elsif target_index > current_index
        (target_index - current_index).times { @game_manager.x11_controller.zoom_in; sleep redraw_wait }
      else
        # no-op
      end
      @game_manager.set_zoom_level(level)
    end
  end
end
