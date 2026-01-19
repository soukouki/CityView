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
    end

    # 一瞬だけunpauseして、建物表示を行ってからまたpauseする
    def wait_for_building_display!
      @x11_controller.unpause
      sleep 0.5
      @x11_controller.pause
    end

    def pixel_black?(image_path, x, y)
      # Use ImageMagick convert to get pixel as rgb integer.
      # Example output: "srgb(0,0,0)" or "srgb(12,34,56)"
      res = ServiceCapture::CommandRunner.run!(
        ["convert", image_path, "-format", "%[pixel:p{#{x},#{y}}]", "info:"]
      )
      val = res[:stdout].strip
      # Accept both srgb() and rgb() forms; treat exactly 0,0,0 as black.
      val.match?(/\A(?:s?rgb)\(0,0,0\)\z/)
    rescue ServiceCapture::Errors::CommandFailed
      # If check fails, assume still booting
      true
    end
  end
end
