# frozen_string_literal: true

module ServiceCapture
  module Errors
    class Base < StandardError
      def code = "error"
    end

    class BadRequest < Base
      def initialize(code, message = nil)
        @code = code
        super(message || code)
      end

      def code = @code
    end

    class CommandFailed < Base
      attr_reader :cmd, :status, :stdout, :stderr

      def initialize(cmd:, status:, stdout:, stderr:)
        @cmd = cmd
        @status = status
        @stdout = stdout
        @stderr = stderr
        super("command failed: #{cmd} (status=#{status})")
      end
    end

    class TimeoutError < Base
      attr_reader :seconds, :operation

      def initialize(seconds, operation)
        @seconds = seconds
        @operation = operation
        super("operation timed out after #{seconds} seconds: #{operation}")
      end
    end

    class GameBootTimeout < Base; end
    class StorageError < Base; end
    class MovingError < Base; end
  end
end
