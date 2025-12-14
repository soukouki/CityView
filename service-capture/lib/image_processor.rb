# frozen_string_literal: true

require "mini_magick"

module ServiceCapture
  module ImageProcessor
    module_function

    def crop_center_fixed!(input_path:, output_path:, crop_width:, crop_height:, offset_x:, offset_y:)
      image = MiniMagick::Image.open(input_path)

      # Crop format: WxH+X+Y
      image.crop("#{crop_width}x#{crop_height}+#{offset_x}+#{offset_y}")
      image.format("png")
      image.write(output_path)
    ensure
      image&.destroy!
    end
  end
end
