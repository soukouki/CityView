# frozen_string_literal: true

require "fileutils"
require "cgi"

require_relative "x11_controller"
require_relative "image_processor"

module ServiceCapture
  class ScreenshotService
    def initialize(storage_client:, crop_width:, crop_height:, crop_offset_x:, crop_offset_y:, x11_controller: nil)
      @storage = storage_client
      @crop_width = crop_width
      @crop_height = crop_height
      @crop_offset_x = crop_offset_x
      @crop_offset_y = crop_offset_y
      @x11_controller = x11_controller
      @current_zoom_level = "normal" # quarter, half, normal or double

      FileUtils.mkdir_p("/tmp/service-capture")
    end

    def capture!(output_path:, x:, y:, zoom_level:)
      screenshot_id = "#{self.class.normalize_component(output_path.split("/").last)}_#{Time.now.strftime("%Y%m%d%H%M%S")}_#{rand(1000)}"
      raw_path = "/tmp/service-capture/#{screenshot_id}_raw.png"
      cropped_path = "/tmp/service-capture/#{screenshot_id}_cropped.png"

      # Move, hide cursor, wait a little for redraw, then screenshot.
      puts "Taking a screenshot at x=#{x}, y=#{y}, zoom=#{zoom_level}"
      puts "mousemove_to_center()"
      @x11_controller.mousemove_to_center
      puts "move_to_coordinate(#{x}, #{y})"
      @x11_controller.move_to_coordinate(x, y)
      puts "change zoom level from #{@current_zoom_level} to #{zoom_level}"
      zoom!(zoom_level)
      puts "hide_cursor()"
      @x11_controller.hide_cursor(map_x: x, map_y: y)
      puts "sleep"
      sleep 0.2 # wait for redraw
      puts "screenshot_full(#{raw_path})"
      @x11_controller.screenshot_full(raw_path)
      puts "Screenshot taken to #{raw_path}"

      ServiceCapture::ImageProcessor.crop_center_fixed!(
        input_path: raw_path,
        output_path: cropped_path,
        crop_width: @crop_width,
        crop_height: @crop_height,
        offset_x: @crop_offset_x,
        offset_y: @crop_offset_y
      )

      puts "Took a screenshot"

      @storage.put_file!(output_path:, local_path: cropped_path)

      puts "Saved a screenshot for #{output_path}"

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

    # 愚直に書きすぎたかもしれない
    def zoom!(level)
      case [@current_zoom_level, level] # [from, to]
      when ["quarter", "quarter"]
        # no-op
      when ["quarter", "half"]
        @x11_controller.zoom_in
      when ["quarter", "normal"]
        2.times { @x11_controller.zoom_in }
      when ["quarter", "double"]
        3.times { @x11_controller.zoom_in }
      when ["half", "quarter"]
        @x11_controller.zoom_out
      when ["half", "half"]
        # no-op
      when ["half", "normal"]
        @x11_controller.zoom_in
      when ["half", "double"]
        2.times { @x11_controller.zoom_in }
      when ["normal", "quarter"]
        2.times { @x11_controller.zoom_out }
      when ["normal", "half"]
        @x11_controller.zoom_out
      when ["normal", "normal"]
        # no-op
      when ["normal", "double"]
        @x11_controller.zoom_in
      when ["double", "quarter"]
        3.times { @x11_controller.zoom_out }
      when ["double", "half"]
        2.times { @x11_controller.zoom_out }
      when ["double", "normal"]
        @x11_controller.zoom_out
      when ["double", "double"]
        # no-op
      else
        raise "invalid zoom level transition: from=#{@current_zoom_level} to=#{level}"
      end
      @current_zoom_level = level
    end
  end
end
