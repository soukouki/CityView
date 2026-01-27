# frozen_string_literal: true

require "fileutils"
require "time"
require_relative "errors"
require_relative "command_runner"
require_relative "x11_controller"

module ServiceCapture
  class GameProcessManager
    attr_reader :current_zoom_level, :x11_controller

    def initialize(display:, ttl_seconds:, boot_timeout_seconds:, boot_poll_interval_seconds:,
                   boot_check_x:, boot_check_y:)
      @display = display
      @ttl_seconds = ttl_seconds
      @boot_timeout_seconds = boot_timeout_seconds
      @boot_poll_interval_seconds = boot_poll_interval_seconds
      @boot_check_x = boot_check_x
      @boot_check_y = boot_check_y

      @xvfb_pid = nil
      @game_pid = nil
      @current_config = nil
      @current_zoom_level = "normal"
      @last_used_at = nil
      @x11_controller = nil

      FileUtils.mkdir_p("/tmp/service-capture")
    end

    def ensure_running(config)
      if running? && @current_config&.game_compatible?(config)
        # 再利用可能
        return
      end

      # 再起動が必要
      stop
      start(config)
    end

    def touch
      @last_used_at = Time.now
    end

    def check_ttl_and_stop
      return unless running?
      return if @last_used_at.nil?

      if (Time.now - @last_used_at) >= @ttl_seconds
        stop
      end
    end

    def running?
      return false unless @game_pid
      Process.kill(0, @game_pid)
      true
    rescue Errno::ESRCH
      @game_pid = nil
      @current_config = nil
      false
    rescue Errno::EPERM
      true
    end

    def set_zoom_level(level)
      @current_zoom_level = level
    end

    private

    def start(config)
      puts "Game Start"

      # Best-effort cleanup of previous process
      stop if @game_pid || @xvfb_pid

      # 1. Start Xvfb with the required resolution
      @xvfb_pid = spawn_xvfb(config.capture_width, config.capture_height)
      wait_for_xvfb

      # 2. Check executable exists
      unless File.exist?(config.executable_path)
        stop_xvfb
        raise ServiceCapture::Errors::BadRequest.new(
          "missing_executable",
          "game executable not found: #{config.executable_path}"
        )
      end

      # 3. Start game process
      args = [
        config.executable_path,
        "-objects",
        config.pakset_name,
        "-load",
        config.save_data_name,
        "-pause",
        "-fullscreen",
        "-singleuser",
      ]

      env = {
        "DISPLAY" => @display
      }

      # Spawn in its own process group so we can kill descendants.
      @game_pid = Process.spawn(
        env,
        *args,
        pgroup: true,
        chdir: "/app",
        out: "/dev/stdout",
        err: "/dev/stderr"
      )
      Process.detach(@game_pid)

      # X11Controller を初期化（この時点で解像度が確定している）
      @x11_controller = ServiceCapture::X11Controller.new(
        screen_width: config.capture_width,
        screen_height: config.capture_height
      )

      @current_config = config
      @current_zoom_level = "normal"
      touch

      puts "Spawned game process PID=#{@game_pid} for save='#{config.save_data_name}' resolution=#{config.capture_width}x#{config.capture_height}"
      puts "Waiting for game boot..."

      # Try to bring it to a stable state: wait until not-black at boot check position
      wait_for_boot!

      puts "Game booted. Ensuring building display..."
      wait_for_building_display!

      puts "Clear Window in game..."
      @x11_controller.clear_window

      # 5秒待ったとしてもうまく画面移動が出来ていないケースが頻発しているため、試しに(0,0)に移動して移動ができることを確認してから撮影を始める
      puts "Verify that screen navigation works correctly"
      wait_for_move_completion!

      puts "Game ready."
    end

    def stop
      return unless @game_pid || @xvfb_pid

      puts "Game Stop"

      stop_game
      stop_xvfb

      @current_config = nil
      @current_zoom_level = "normal"
      @last_used_at = nil
      @x11_controller = nil
    end

    def stop_game
      return unless @game_pid

      begin
        # Kill process group
        pgid = Process.getpgid(@game_pid)
        Process.kill("TERM", -pgid)
        sleep 1
        Process.kill("KILL", -pgid) rescue nil
      rescue Errno::ESRCH
        # already dead
      ensure
        @game_pid = nil
      end
    end

    def spawn_xvfb(width, height)
      puts "Starting Xvfb with resolution #{width}x#{height}"
      
      pid = Process.spawn(
        "Xvfb", @display,
        "-screen", "0", "#{width}x#{height}x24",
        "-ac", "+extension", "GLX", "+render", "-noreset",
        out: "/dev/null",
        err: "/dev/null"
      )
      Process.detach(pid)
      
      puts "Xvfb started with PID=#{pid}"
      pid
    end

    def stop_xvfb
      return unless @xvfb_pid

      puts "Stopping Xvfb PID=#{@xvfb_pid}"
      
      begin
        Process.kill("TERM", @xvfb_pid)
        sleep 0.5
        Process.kill("KILL", @xvfb_pid) rescue nil
      rescue Errno::ESRCH
        # already dead
      ensure
        @xvfb_pid = nil
      end
    end

    def wait_for_xvfb
      deadline = Time.now + 10
      
      while Time.now < deadline
        result = system("xdpyinfo -display #{@display} >/dev/null 2>&1")
        if result
          puts "Xvfb is ready"
          return
        end
        sleep 0.2
      end

      stop_xvfb
      raise ServiceCapture::Errors::CommandFailed.new(
        cmd: "xdpyinfo",
        status: -1,
        stdout: "",
        stderr: "Xvfb startup timeout"
      )
    end

    def wait_for_boot!
      deadline = Time.now + @boot_timeout_seconds
      tmp_path = "/tmp/service-capture/bootcheck.png"

      while Time.now < deadline
        # screenshot whole screen and check pixel
        @x11_controller.screenshot_full(tmp_path)

        black = pixel_black?(tmp_path, @boot_check_x, @boot_check_y)
        return unless black

        sleep @boot_poll_interval_seconds
      end

      # Timed out
      stop
      raise ServiceCapture::Errors::GameBootTimeout, "boot check timed out"
    # ピクセルの色チェックで失敗した場合もタイムアウト扱いとする
    rescue ServiceCapture::Errors::CommandFailed => e
      stop
      raise ServiceCapture::Errors::GameBootTimeout, "boot check failed: #{e.message}"
    end

    # (0,0)に移動・撮影・画面上側の適当な箇所を撮影して#404040であることを確認
    def wait_for_move_completion!
      count = 0
      max_retries = 5
      tmp_path = "/tmp/service-capture/movecheck.png"

      while count < max_retries
        puts "  Move attempt #{count + 1}/#{max_retries}"
        @x11_controller.move_to_coordinate(0, 0)
        sleep 2 # 移動待ち

        @x11_controller.screenshot_full(tmp_path)

        gray = pixel_gray?(tmp_path, 100, 100) # 画面上側の適当な箇所をチェック
        if gray
          puts "  Move verified successfully."
          return
        else
          puts "  Move verification failed, retrying..."
        end

        count += 1
      end

      # 5回試してもうまくいかない場合は例外を投げる
      stop
      raise ServiceCapture::Errors::MovingError, "failed to verify screen move after #{max_retries} attempts"
    end

    # 一瞬だけunpauseして、建物表示を行ってからまたpauseする
    def wait_for_building_display!
      @x11_controller.unpause
      sleep 0.5
      @x11_controller.pause
    end

    def pixel_black?(image_path, x, y)
      pixel_color?(image_path, x, y, [0, 0, 0])
    end

    def pixel_gray?(image_path, x, y)
      pixel_color?(image_path, x, y, [64, 64, 64]) # #404040
    end

    # This method may raise Errors::CommandFailed
    def pixel_color?(image_path, x, y, target_rgb)
      res = ServiceCapture::CommandRunner.run!(
        ["convert", image_path, "-format", "%[pixel:p{#{x},#{y}}]", "info:"]
      )
      val = res[:stdout].strip
      # Extract rgb values
      if val =~ /\A(?:s?rgb)\((\d+),(\d+),(\d+)\)\z/
        r = $1.to_i
        g = $2.to_i
        b = $3.to_i
        puts "  Pixel at (#{x},#{y}): R=#{r} G=#{g} B=#{b}"
        # 例えば背景(#404040が理想)を撮影すると、#414041のように微妙にずれることがあるため、閾値を設けて近似判定をする
        diff = (r - target_rgb[0]).abs + (g - target_rgb[1]).abs + (b - target_rgb[2]).abs
        threshold = 10
        return diff <= threshold
      end
      false
    end
  end
end
