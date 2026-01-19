# frozen_string_literal: true

require_relative "command_runner"

module ServiceCapture
  class X11Controller
    def initialize(screen_width:, screen_height:)
      @screen_width = screen_width
      @screen_height = screen_height
    end

    def key(keysym)
      ServiceCapture::CommandRunner.run!(["xdotool", "key", "--delay", "10", keysym])
    end

    def type(text)
      ServiceCapture::CommandRunner.run!(["xdotool", "type", "--delay", "10", text.to_s])
    end

    def mousemove(x, y)
      ServiceCapture::CommandRunner.run!(["xdotool", "mousemove", x.to_i.to_s, y.to_i.to_s])
    end

    def mousemove_to_center
      mousemove(@screen_width / 2, @screen_height / 2)
    end

    def move_to_coordinate(x, y)
      # Assumption: Shift+J opens jump dialog; then we can type "x,y" and Enter.
      # If dialog uses tab-separated fields, comma still often works; adjust if needed.
      key("shift+j")
      sleep 0.02
      type("#{x},#{y}")
      sleep 0.02
      key("Return")
      sleep 0.02
      key("BackSpace")
    end

    def hide_cursor(map_x:, map_y:)
      # Move cursor to top-left margin to avoid appearing in crop
      # Fixed position outside typical crop area
      mousemove(10, 120)
    end

    def screenshot_full(output_path)
      # remove old file if exists
      File.delete(output_path) if File.exist?(output_path)
      # scrot captures root window in Xvfb
      ServiceCapture::CommandRunner.run!(["scrot", "-z", "-F", output_path], env: {"DISPLAY" => ENV["DISPLAY"]})
    end

    def pause
      key("p")
    end

    def unpause
      key("p")
    end

    def zoom_in
      # 画面の中央にマウスを移動してPage_Up
      mousemove_to_center()
      sleep 0.05
      key("Page_Up")
    end

    def zoom_out
      # 画面の中央にマウスを移動してPage_Down
      mousemove_to_center()
      sleep 0.05
      key("Page_Down")
    end
  end
end
