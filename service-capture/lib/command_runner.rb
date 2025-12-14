# frozen_string_literal: true

require "open3"
require_relative "errors"

module ServiceCapture
  class CommandRunner
    def self.run!(cmd, env: {}, chdir: nil, timeout: nil)
      stdout = +""
      stderr = +""
      status = nil

      # spawn options
      opts = {}
      opts[:chdir] = chdir if chdir

      # capture3 の引数：先頭に env Hash、その後にコマンドと引数
      args = []
      args << env if env # env は先頭引数（{}でもOK）
      args.concat(cmd)

      if timeout
        require "timeout"
        Timeout.timeout(timeout) do
          stdout, stderr, status = Open3.capture3(*args, **opts)
        end
      else
        stdout, stderr, status = Open3.capture3(*args, **opts)
      end

      unless status.success?
        raise ServiceCapture::Errors::CommandFailed.new(
          cmd: cmd.join(" "),
          status: status.exitstatus,
          stdout: stdout,
          stderr: stderr
        )
      end

      { stdout: stdout, stderr: stderr, status: status.exitstatus }
    rescue Timeout::Error
      raise ServiceCapture::Errors::CommandFailed.new(
        cmd: cmd.join(" "),
        status: -1,
        stdout: stdout,
        stderr: "timeout"
      )
    end
  end
end
