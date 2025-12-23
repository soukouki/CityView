# frozen_string_literal: true

require "fileutils"
require "cgi"
require "concurrent"

require_relative "x11_controller"
require_relative "image_processor"
require_relative "errors"

module ServiceCapture
  class ScreenshotService
    def initialize(storage_client:, crop_width:, crop_height:, crop_offset_x:, crop_offset_y:,
                   x11_controller:, worker_pool:, capture_lock:,
                   redraw_wait:, scrot_settle:,
                   scrot_timeout:, crop_timeout:, upload_timeout:)
      @storage = storage_client
      @crop_width = crop_width
      @crop_height = crop_height
      @crop_offset_x = crop_offset_x
      @crop_offset_y = crop_offset_y
      @x11_controller = x11_controller
      @worker_pool = worker_pool
      @capture_lock = capture_lock
      @redraw_wait = redraw_wait
      @scrot_settle = scrot_settle
      @scrot_timeout = scrot_timeout
      @crop_timeout = crop_timeout
      @upload_timeout = upload_timeout
      @current_zoom_level = "normal" # one_eighth, quarter, half, normal, double

      FileUtils.mkdir_p("/tmp/service-capture")
    end

    def capture!(output_path:, x:, y:, zoom_level:)
      request_start = Time.now
      screenshot_id = "#{self.class.normalize_component(output_path.split("/").last)}_#{Time.now.strftime("%Y%m%d%H%M%S")}_#{rand(1000)}"
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
        perform_game_operations(x, y, zoom_level)
        puts "[capture] request_id=#{screenshot_id} stage=game_operation duration=#{((Time.now - game_op_start) * 1000).round}ms"

        # 画面再描画待ち
        sleep @redraw_wait
        
        # scrot起動（非同期）
        scrot_start = Time.now
        scrot_future = async_scrot(raw_path)
        puts "[capture] request_id=#{screenshot_id} stage=scrot_started duration=#{((Time.now - scrot_start) * 1000).round}ms"
        
        # scrotがフレームバッファを読み取るまで待つ
        sleep @scrot_settle
        
        puts "[capture] request_id=#{screenshot_id} stage=lock_released duration=#{((Time.now - lock_start) * 1000).round}ms"
      end
      # === End of Critical Section ===
      
      # ここからはロック不要（画面は変更されても良い）
      # scrot圧縮完了待ち
      scrot_wait_start = Time.now
      wait_for_scrot(scrot_future, screenshot_id)
      puts "[capture] request_id=#{screenshot_id} stage=scrot_complete duration=#{((Time.now - scrot_wait_start) * 1000).round}ms"

      # crop実行（非同期）
      crop_start = Time.now
      crop_future = async_crop(raw_path, cropped_path, screenshot_id)
      wait_for_crop(crop_future, screenshot_id)
      puts "[capture] request_id=#{screenshot_id} stage=crop_complete duration=#{((Time.now - crop_start) * 1000).round}ms"

      # upload実行（非同期）
      upload_start = Time.now
      upload_future = async_upload(cropped_path, output_path, screenshot_id)
      wait_for_upload(upload_future, screenshot_id)
      puts "[capture] request_id=#{screenshot_id} stage=upload_complete duration=#{((Time.now - upload_start) * 1000).round}ms"

      puts "[capture] request_id=#{screenshot_id} stage=complete total_duration=#{((Time.now - request_start) * 1000).round}ms"

      output_path
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

    def perform_game_operations(x, y, zoom_level)
      puts "[game_ops] move to center"
      @x11_controller.mousemove_to_center
      
      puts "[game_ops] move to coordinate x=#{x}, y=#{y}"
      @x11_controller.move_to_coordinate(x, y)
      
      puts "[game_ops] zoom from #{@current_zoom_level} to #{zoom_level}"
      zoom!(zoom_level)
      
      puts "[game_ops] hide cursor"
      @x11_controller.hide_cursor(map_x: x, map_y: y)
    end

    def async_scrot(output_path)
      Concurrent::Future.execute(executor: @worker_pool) do
        @x11_controller.screenshot_full(output_path)
        output_path
      end
    end

    def async_crop(input_path, output_path, request_id)
      Concurrent::Future.execute(executor: @worker_pool) do
        puts "[crop] request_id=#{request_id} input=#{input_path} output=#{output_path}"
        ServiceCapture::ImageProcessor.crop_center_fixed!(
          input_path: input_path,
          output_path: output_path,
          crop_width: @crop_width,
          crop_height: @crop_height,
          offset_x: @crop_offset_x,
          offset_y: @crop_offset_y
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
      future.value!(@scrot_timeout)
    rescue Concurrent::TimeoutError
      warn "[scrot] request_id=#{request_id} error=timeout"
      raise ServiceCapture::Errors::CommandFailed.new("scrot", "scrot timed out after #{@scrot_timeout}s")
    rescue => e
      warn "[scrot] request_id=#{request_id} error=#{e.class} msg=#{e.message}"
      raise
    end

    def wait_for_crop(future, request_id)
      future.value!(@crop_timeout)
    rescue Concurrent::TimeoutError
      warn "[crop] request_id=#{request_id} error=timeout"
      raise ServiceCapture::Errors::CommandFailed.new("crop", "crop timed out after #{@crop_timeout}s")
    rescue => e
      warn "[crop] request_id=#{request_id} error=#{e.class} msg=#{e.message}"
      raise
    end

    def wait_for_upload(future, request_id)
      future.value!(@upload_timeout)
    rescue Concurrent::TimeoutError
      warn "[upload] request_id=#{request_id} error=timeout"
      raise ServiceCapture::Errors::StorageError, "upload timed out after #{@upload_timeout}s"
    rescue => e
      warn "[upload] request_id=#{request_id} error=#{e.class} msg=#{e.message}"
      raise
    end

    # 愚直に書きすぎたかもしれない
    def zoom!(level)
      zoom_levels = ["one_eighth", "quarter", nil, "half", nil, nil, "normal", nil, nil, "double"] # ゲーム内でのズームレベル対応
      current_index = zoom_levels.index(@current_zoom_level)
      target_index = zoom_levels.index(level)
      raise "invalid current zoom level #{@current_zoom_level}" if current_index.nil?
      raise "invalid target zoom level #{level}" if target_index.nil?
      puts "[zoom] from #{@current_zoom_level}(#{current_index}) to #{level}(#{target_index})"
      if target_index < current_index
        (current_index - target_index).times { @x11_controller.zoom_out }
      elsif target_index > current_index
        (target_index - current_index).times { @x11_controller.zoom_in }
      else
        # no-op
      end
      @current_zoom_level = level
    end
  end
end
