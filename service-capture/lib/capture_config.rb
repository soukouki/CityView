# frozen_string_literal: true

module ServiceCapture
  class CaptureConfig
    attr_reader :folder_path, :binary_name, :pakset_name, :save_data_name
    attr_reader :crop_offset_x, :crop_offset_y
    attr_reader :margin_width, :margin_height
    attr_reader :effective_width, :effective_height
    attr_reader :capture_redraw_wait_seconds
    attr_reader :zoom_level, :x, :y, :output_path

    def initialize(params)
      @folder_path = params["folder_path"].to_s
      @binary_name = params["binary_name"].to_s
      @pakset_name = params["pakset_name"].to_s
      @save_data_name = params["save_data_name"].to_s
      
      @crop_offset_x = Integer(params["crop_offset_x"])
      @crop_offset_y = Integer(params["crop_offset_y"])
      @margin_width = Integer(params["margin_width"])
      @margin_height = Integer(params["margin_height"])
      @effective_width = Integer(params["effective_width"])
      @effective_height = Integer(params["effective_height"])
      
      @capture_redraw_wait_seconds = Float(params["capture_redraw_wait_seconds"])
      
      @zoom_level = params["zoom_level"].to_s
      @x = Integer(params["x"])
      @y = Integer(params["y"])
      @output_path = params["output_path"].to_s
    end

    def executable_path
      "/app/bin/#{folder_path}/#{binary_name}"
    end

    def save_path
      "/app/bin/#{folder_path}/save/#{save_data_name}.sve"
    end

    def image_width
      effective_width + margin_width * 2
    end

    def image_height
      effective_height + margin_height * 2
    end

    def capture_width
      image_width + crop_offset_x * 2
    end

    def capture_height
      image_height + crop_offset_y * 2
    end

    # ゲームプロセス再利用可否の判定
    # すべてのゲーム起動パラメータが一致している必要がある
    def game_compatible?(other)
      return false if other.nil?

      folder_path == other.folder_path &&
        binary_name == other.binary_name &&
        pakset_name == other.pakset_name &&
        save_data_name == other.save_data_name &&
        capture_width == other.capture_width &&
        capture_height == other.capture_height
    end

    def valid?
      return false if folder_path.empty?
      return false if binary_name.empty?
      return false if pakset_name.empty?
      return false if save_data_name.empty?
      return false if output_path.empty?
      return false if x < 0
      return false if y < 0
      return false if crop_offset_x < 0
      return false if crop_offset_y < 0
      return false if margin_width < 0
      return false if margin_height < 0
      return false if effective_width <= 0
      return false if effective_height <= 0
      return false if capture_redraw_wait_seconds < 0
      return false unless ["one_eighth", "quarter", "half", "normal", "double"].include?(zoom_level)

      true
    end

    def validation_error
      return "folder_path cannot be empty" if folder_path.empty?
      return "binary_name cannot be empty" if binary_name.empty?
      return "pakset_name cannot be empty" if pakset_name.empty?
      return "save_data_name cannot be empty" if save_data_name.empty?
      return "output_path cannot be empty" if output_path.empty?
      return "x must be non-negative" if x < 0
      return "y must be non-negative" if y < 0
      return "crop_offset_x must be non-negative" if crop_offset_x < 0
      return "crop_offset_y must be non-negative" if crop_offset_y < 0
      return "margin_width must be non-negative" if margin_width < 0
      return "margin_height must be non-negative" if margin_height < 0
      return "effective_width must be positive" if effective_width <= 0
      return "effective_height must be positive" if effective_height <= 0
      return "capture_redraw_wait_seconds must be non-negative" if capture_redraw_wait_seconds < 0
      return "zoom_level must be one of: one_eighth, quarter, half, normal, double" unless ["one_eighth", "quarter", "half", "normal", "double"].include?(zoom_level)

      nil
    end
  end
end
