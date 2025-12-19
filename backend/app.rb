require 'sinatra'
require 'json'

set :bind, '127.0.0.1'
set :port, 4567
set :public_folder, File.dirname(__FILE__) + '/public'

# ヘルスチェック
get '/health' do
  content_type :json
  { status: 'ok' }.to_json
end

# API エンドポイント（今後実装予定）
get '/api/status' do
  content_type :json
  [].to_json
end

post '/api/tiles/create' do
  content_type :json
  { message: 'Not implemented yet' }.to_json
end
