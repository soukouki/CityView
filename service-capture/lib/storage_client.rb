# frozen_string_literal: true

require "httparty"
require_relative "errors"

module ServiceCapture
  class StorageClient
    def initialize(base_url:)
      @base_url = base_url.sub(%r{/\z}, "")
    end

    def put_file!(remote_path:, local_path:)
      url = "#{@base_url}#{remote_path}"
      body = File.binread(local_path)

      res = HTTParty.put(
        url,
        body:,
        headers: {
          "Content-Type" => "image/png"
        },
        timeout: 60
      )

      unless res.code.between?(200, 299)
        raise ServiceCapture::Errors::StorageError, "PUT failed (#{res.code}) url=#{url}"
      end

      true
    rescue SocketError, Errno::ECONNREFUSED, Net::OpenTimeout, Net::ReadTimeout => e
      raise ServiceCapture::Errors::StorageError, "storage connection error: #{e.class}: #{e.message}"
    end
  end
end
