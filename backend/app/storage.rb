require 'httparty'

module Storage
  BASE_URL = ENV['STORAGE_URL'] || 'http://storage'

  # 将来の削除機能用（現在は空実装）
  def self.delete(path)
    # TODO: 実装予定
    # HTTParty.delete("#{BASE_URL}#{path}")
  end
end
