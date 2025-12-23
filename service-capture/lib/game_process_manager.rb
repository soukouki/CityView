# frozen_string_literal: true

require "fileutils"
require "time"
require_relative "errors"
require_relative "command_runner"
require_relative "x11_controller"

module ServiceCapture
  class GameProcessManager
    def initialize(executable:, executable_dir:, pakset_name:, display:, screen_width:, screen_height:,
                   ttl_seconds:, boot_timeout_seconds:, boot_poll_interval_seconds:, boot_check_x:, boot_check_y:, x11_controller: nil)
      @executable = executable
      @executable_dir = executable_dir
      @pakset_name = pakset_name
      @display = display
      @screen_width = screen_width
      @screen_height = screen_height

      @ttl_seconds = ttl_seconds
      @boot_timeout_seconds = boot_timeout_seconds
      @boot_poll_interval_seconds = boot_poll_interval_seconds
      @boot_check_x = boot_check_x
      @boot_check_y = boot_check_y

      @pid = nil
      @current_save = nil
      @last_used_at = nil

      @x11_controller = x11_controller
      @zoom_level = "normal"

      FileUtils.mkdir_p("/tmp/service-capture")
    end

    def ensure_running(save_data_name)
      if running?
        if @current_save != save_data_name
          # Save data mismatch: stop and restart with new save
          stop
          start(save_data_name)
        end
      else
        # Process not running: start fresh
        start(save_data_name)
      end
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
      return false unless @pid
      Process.kill(0, @pid)
      true
    rescue Errno::ESRCH
      @pid = nil
      @current_save = nil
      false
    rescue Errno::EPERM
      true
    end

    private

    def start(save_data_name)
      puts "Game Start"

      # Best-effort cleanup of previous process
      stop if @pid

      exe_path = File.join(@executable_dir, @executable)
      unless File.exist?(exe_path)
        raise ServiceCapture::Errors::BadRequest.new(
          "missing_SIMUTRANS_EXECUTABLE",
          "game executable not found: #{exe_path}"
        )
      end

      # Build arguments with -load option for save data
      args = [
        exe_path,
        "-objects",
        @pakset_name,
        "-load",
        save_data_name,
        "-pause",
        "-fullscreen",
      ]

      env = {
        "DISPLAY" => @display
      }

      # Spawn in its own process group so we can kill descendants.
      # Redirect stdout/stderr to /dev/stdout/stderr for logging.
      @pid = Process.spawn(
        env,
        *args,
        pgroup: true,
        chdir: "/app",
        out: "/dev/stdout",
        err: "/dev/stderr"
      )
      Process.detach(@pid)

      @current_save = save_data_name
      touch

      puts "Spawned game process PID=#{@pid} for save='#{save_data_name}'"
      puts "Waiting for game boot..."
      # Try to bring it to a stable state: wait until not-black at (256,256)
      wait_for_boot!

      # There is no window manager, and since there's only one window that fills the entire screen, activation isn't necessary.

      puts "Game booted. Ensuring building display..."
      wait_for_building_display!

      puts "Game ready."
    end

    def stop
      return unless @pid

      puts "Game Stop"

      begin
        # Kill process group
        pgid = Process.getpgid(@pid)
        Process.kill("TERM", -pgid)
        sleep 1
        Process.kill("KILL", -pgid) rescue nil
      rescue Errno::ESRCH
        # already dead
      ensure
        @pid = nil
        @current_save = nil
        @last_used_at = nil
      end
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
      stop()
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
