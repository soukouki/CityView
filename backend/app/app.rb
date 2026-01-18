require 'sinatra/base'
require 'json'
require 'rack'
require 'puma'
require 'rack/handler/puma'

require_relative 'db'
require_relative 'prefect'
require_relative 'storage'
require_relative 'helpers'

DB.connect!

# ========================================
# MainApp (ポート 4567)
# メイン画面API
# ========================================
class MainApp < Sinatra::Base
  set :show_exceptions, false
  set :raise_errors, false

  error do
    content_type :json
    status 500
    { error: 'Internal server error', details: env['sinatra.error']&.message }.to_json
  end

  not_found do
    content_type :json
    { error: 'Not found' }.to_json
  end

  # ヘルスチェック
  get '/health' do
    content_type :json
    { status: 'ok' }.to_json
  end

  # マップ一覧取得（公開済みのみ、公開用フォーマット）
  get '/api/maps' do
    content_type :json
    
    maps = DB.list_maps(status: 'completed')
    response = maps.map do |map|
      panels = DB.list_panels_by_map_id(map[:id])
      Helpers.format_public_map_response(map, panels)
    end
    
    response.to_json
  end
end

# ========================================
# AdminApp (ポート 4568)
# 管理画面API
# ========================================
class AdminApp < Sinatra::Base
  set :show_exceptions, false
  set :raise_errors, false

  error do
    content_type :json
    status 500
    { error: 'Internal server error', details: env['sinatra.error']&.message }.to_json
  end

  not_found do
    content_type :json
    { error: 'Not found' }.to_json
  end

  # サービスステータス取得（全マップ、管理画面用フォーマット）
  get '/api/status' do
    content_type :json
    
    maps = DB.list_maps
    jobs = DB.list_jobs
    
    Helpers.format_status_response(maps, jobs).to_json
  end

  # マップ生成オプション取得
  get '/api/options' do
    content_type :json
    Helpers.format_options_response.to_json
  end

  # マップ生成ジョブ作成・Flow起動
  post '/api/maps' do
    content_type :json
    
    begin
      request_body = JSON.parse(request.body.read)
    rescue JSON::ParserError
      halt 400, { error: 'Invalid JSON' }.to_json
    end

    # バリデーション
    required_fields = %w[
      folder_path binary_name pakset_name paksize save_data_name zoom_level
      tile_quality_max_zoom tile_quality_other tile_group_size delta
      capture_redraw_wait_seconds
    ]
    
    missing_fields = required_fields - request_body.keys
    unless missing_fields.empty?
      halt 400, { error: 'Missing required fields', details: missing_fields }.to_json
    end

    # マップ作成
    map_id = DB.create_map(
      description: request_body['description'] || '',
      copyright: request_body['copyright'] || '',
      game_path: request_body['folder_path'],
      pakset: request_body['pakset_name'],
      paksize: request_body['paksize'],
      save_data: request_body['save_data_name'],
      map_size_x: request_body.dig('map_size', 'x') || 0,
      map_size_y: request_body.dig('map_size', 'y') || 0,
      zoom_level: request_body['zoom_level'],
      status: 'processing'
    )

    # Prefect Flow起動
    deployment_name = 'create_tiles/create-tiles'

    begin
      deployment_response = HTTParty.get(
        "#{ENV['PREFECT_API_URL']}/deployments/name/#{deployment_name}",
        headers: { 'Content-Type' => 'application/json' }
      )

      unless deployment_response.success?
        halt 502, { error: 'Failed to get deployment', details: deployment_response.body }.to_json
      end

      deployment = JSON.parse(deployment_response.body)
      deployment_id = deployment['id']

      flow_response = Prefect.create_flow_run(deployment_id, request_body.merge(map_id: map_id))
      flow_run_id = flow_response['id']
    rescue => e
      DB.update_map_status(map_id, 'failed')
      halt 502, { error: 'Failed to start Prefect flow', details: e.message }.to_json
    end

    # ジョブ作成
    job_id = DB.create_job(
      map_id: map_id,
      prefect_run_id: flow_run_id,
      name: "Map #{map_id} - #{request_body['save_data_name']}"
    )

    { job_id: job_id.to_s }.to_json
  end
end

# ========================================
# InternalApp (ポート 8002)
# Prefect Agent専用内部API
# ========================================
class InternalApp < Sinatra::Base
  set :show_exceptions, false
  set :raise_errors, false

  error do
    content_type :json
    status 500
    { error: 'Internal server error', details: env['sinatra.error']&.message }.to_json
  end

  not_found do
    content_type :json
    { error: 'Not found' }.to_json
  end

  # スクリーンショット作成
  post '/api/screenshots' do
    content_type :json
    
    begin
      request_body = JSON.parse(request.body.read)
    rescue JSON::ParserError
      halt 400, { error: 'Invalid JSON' }.to_json
    end

    required_fields = %w[map_id path]
    missing_fields = required_fields - request_body.keys
    unless missing_fields.empty?
      halt 400, { error: 'Missing required fields', details: missing_fields }.to_json
    end

    screenshot_id = DB.create_screenshot(
      map_id: request_body['map_id'],
      game_tile_x: request_body.dig('game_tile', 'x') || 0,
      game_tile_y: request_body.dig('game_tile', 'y') || 0,
      path: request_body['path']
    )

    { screenshot_id: screenshot_id.to_s }.to_json
  end

  # スクリーンショット取得
  get '/api/screenshots/:id' do
    content_type :json
    
    screenshot = DB.find_screenshot(params[:id].to_i)
    halt 404, { error: 'Screenshot not found' }.to_json unless screenshot

    screenshot.to_json
  end

  # スクリーンショット座標更新
  put '/api/screenshots/:id' do
    content_type :json
    
    begin
      request_body = JSON.parse(request.body.read)
    rescue JSON::ParserError
      halt 400, { error: 'Invalid JSON' }.to_json
    end

    screenshot = DB.find_screenshot(params[:id].to_i)
    halt 404, { error: 'Screenshot not found' }.to_json unless screenshot

    DB.update_screenshot_coordinates(
      params[:id].to_i,
      estimated_screen_x: request_body['estimated_screen_x'],
      estimated_screen_y: request_body['estimated_screen_y']
    )

    { status: 'ok' }.to_json
  end

  # パネル作成
  post '/api/panels' do
    content_type :json
    
    begin
      request_body = JSON.parse(request.body.read)
    rescue JSON::ParserError
      halt 400, { error: 'Invalid JSON' }.to_json
    end

    required_fields = %w[map_id name path]
    missing_fields = required_fields - request_body.keys
    unless missing_fields.empty?
      halt 400, { error: 'Missing required fields', details: missing_fields }.to_json
    end

    panel_id = DB.create_panel(
      map_id: request_body['map_id'],
      name: request_body['name'],
      path: request_body['path'],
      resolution_width: request_body.dig('resolution', 'width') || 0,
      resolution_height: request_body.dig('resolution', 'height') || 0
    )

    { panel_id: panel_id.to_s }.to_json
  end

  # マップ開始日時更新
  put '/api/maps/:id/started_at' do
    content_type :json
    
    map = DB.find_map(params[:id].to_i)
    halt 404, { error: 'Map not found' }.to_json unless map

    DB.update_map_started_at(params[:id].to_i)
    { status: 'ok' }.to_json
  end

  # マップステータス更新
  put '/api/maps/:id/status' do
    content_type :json
    
    begin
      request_body = JSON.parse(request.body.read)
    rescue JSON::ParserError
      halt 400, { error: 'Invalid JSON' }.to_json
    end

    map = DB.find_map(params[:id].to_i)
    halt 404, { error: 'Map not found' }.to_json unless map

    status = request_body['status']
    unless %w[processing completed failed].include?(status)
      halt 400, { error: 'Invalid status', details: 'Must be processing, completed, or failed' }.to_json
    end

    DB.update_map_status(params[:id].to_i, status)
    
    if status == 'completed'
      DB.update_map_published_at(params[:id].to_i)
    end

    { status: 'ok' }.to_json
  end
end

# ========================================
# 1プロセスで3ポート起動
# ========================================
if __FILE__ == $PROGRAM_NAME
  Thread.new do
    Rack::Handler::Puma.run(MainApp, Port: 4567, Host: '0.0.0.0')
  end

  Thread.new do
    Rack::Handler::Puma.run(AdminApp, Port: 4568, Host: '0.0.0.0')
  end

  Rack::Handler::Puma.run(InternalApp, Port: 8002, Host: '0.0.0.0')
end
