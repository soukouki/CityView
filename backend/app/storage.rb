require 'httparty'

module Storage
  BASE_URL = ENV['STORAGE_URL'] || 'http://storage'

  def self.delete_map(map_id)
    %w[screenshots rawtiles tiles panels].each do |category|
      url = "#{BASE_URL}/images/#{category}/#{map_id}/"
      response = HTTParty.delete(url)
      # ディレクトリが存在しない場合は200以外のステータスコードが返ることがあるので、エラーにはしない
      unless response.code == 200
        puts "Warning: Failed to delete #{url}, status code: #{response.code}"
      end
    end
  end
end
