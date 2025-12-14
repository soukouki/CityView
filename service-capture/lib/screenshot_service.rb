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

      FileUtils.mkdir_p("/tmp/service-capture")
    end

    def self.build_screenshot_id(save_data_name:, x:, y:, container_hint:, random:)
      # requirements:
      # - include save_data_name, x, y
      # - include container id OR random (we include both when available)
      # - safe characters for URL paths
      save = normalize_component(save_data_name)
      cont = normalize_component(container_hint.to_s)
      "shot_#{save}_x#{x}_y#{y}_#{cont}_#{random}"
    end

    def capture!(screenshot_id:, x:, y:)
      raw_path = "/tmp/service-capture/#{screenshot_id}_raw.png"
      cropped_path = "/tmp/service-capture/#{screenshot_id}.png"

      # Move, hide cursor, wait a little for redraw, then screenshot.
      puts "Taking a screenshot at x=#{x}, y=#{y}"
      puts "mousemove_to_center()"
      @x11_controller.mousemove_to_center
      puts "move_to_coordinate(#{x}, #{y})"
      @x11_controller.move_to_coordinate(x, y)
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

      remote_path = "/images/screenshots/#{screenshot_id}.png"
      @storage.put_file!(remote_path:, local_path: cropped_path)

      puts "Saved a screenshot for #{remote_path}"

      remote_path
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
  end
end
