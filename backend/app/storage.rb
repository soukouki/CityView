require 'httparty'

module Storage
  BASE_URL = ENV['STORAGE_URL'] || 'http://storage'

  def self.delete_map(map_id)
    # screenshots/:map_id, rawtiles/:map_id, tiles/:map_id, panels/:map_idをディレクトリごと削除する
    %w[screenshots rawtiles tiles panels].each do |category|
      url = "#{BASE_URL}/images/#{category}/#{map_id}"
      return unless Storage.check_exists(url)
      response = HTTParty.delete(url)
      unless response.code == 200
        raise "Failed to delete #{category} for map_id #{map_id}: #{response.body}"
      end
    end
  end

  def self.check_exists(path)
    url = "#{BASE_URL}/files/exists"
    response = HTTParty.head(url, query: { path: path })
    response.code == 200
  end
end
