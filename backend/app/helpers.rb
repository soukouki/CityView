require 'json'

module Helpers
  # ========================================
  # パラメータ計算
  # ========================================

  ZOOM_LEVEL_MULTIPLIERS = {
    'one_eighth' => 0.125,
    'quarter' => 0.25,
    'half' => 0.5,
    'normal' => 1.0,
    'double' => 2.0
  }

  def self.calculate_adjusted_paksize(paksize, zoom_level)
    multiplier = ZOOM_LEVEL_MULTIPLIERS[zoom_level] || 1.0
    (paksize * multiplier).to_i
  end

  def self.calculate_capture_params
    {
      crop_offset_x: ENV['CROP_OFFSET_X'].to_i,
      crop_offset_y: ENV['CROP_OFFSET_Y'].to_i,
      margin_width: ENV['IMAGE_MARGIN_WIDTH'].to_i,
      margin_height: ENV['IMAGE_MARGIN_HEIGHT'].to_i,
      effective_width: ENV['IMAGE_EFFECTIVE_WIDTH'].to_i,
      effective_height: ENV['IMAGE_EFFECTIVE_HEIGHT'].to_i,
      image_width: ENV['IMAGE_WIDTH'].to_i,
      image_height: ENV['IMAGE_HEIGHT'].to_i,
      capture_width: ENV['CAPTURE_WIDTH'].to_i,
      capture_height: ENV['CAPTURE_HEIGHT'].to_i
    }
  end

  # ========================================
  # ゲームフォルダスキャン
  # ========================================

  def self.scan_game_folders
    # /app/bin以下にあるground.Outside.pakを探し、その1つ上のフォルダをゲームフォルダとする
    base_dir = '/app/bin'
    game_folders = Dir
      .glob(File.join(base_dir, '**', 'ground.Outside.pak'))
      .map{ |path| File.dirname(path, 2) }
      .uniq

    game_folders.map do |folder_path|
      {
        folder_path: folder_path,
        binaries: list_binaries(folder_path),
        paksets: list_paksets(folder_path),
        save_datas: list_save_data(folder_path)
      }
    end
  end

  def self.list_binaries(folder)
    Dir
      .glob(File.join(folder, '*'))
      .select{ |path| File.file?(path) && File.executable?(path) }
      .map{ |path| { name: File.basename(path), path: path } }
  end

  def self.list_paksets(folder)
    Dir
      .glob(File.join(folder, '*'))
      .select{ |path| File.directory?(path) && File.exist?(File.join(path, 'ground.Outside.pak')) }
      .map{ |path| { name: File.basename(path) } }
  end

  def self.list_save_data(folder)
    save_dir = File.join(folder, 'save')
    return [] unless Dir.exist?(save_dir)

    Dir.glob(File.join(save_dir, '*.sve'))
       .map { |f| { name: File.basename(f, '.sve') } }
  end

  # ========================================
  # レスポンス整形（公開用 - ポート8000）
  # ========================================

  def self.format_public_map_response(map, panels)
    {
      map_id: map[:id],
      status: map[:status],
      description: map[:description],
      copyright: map[:copyright],
      game_path: map[:game_path],
      pakset: map[:pakset],
      paksize: map[:paksize],
      save_data: map[:save_data],
      map_size: {
        width: map[:map_size_width],
        height: map[:map_size_height]
      },
      panels: panels.map do |panel|
        {
          filename: File.basename(panel[:path]),
          name: panel[:name],
          path: panel[:path],
          resolution: {
            width: panel[:resolution_width],
            height: panel[:resolution_height]
          }
        }
      end,
      zoom_level: map[:zoom_level],
      published_at: map[:published_at]&.iso8601
    }
  end

  # ========================================
  # レスポンス整形（管理画面用 - ポート8001）
  # ========================================

  def self.format_admin_map_response(map, panels)
    {
      map_id: map[:id],
      status: map[:status],
      description: map[:description],
      copyright: map[:copyright],
      game_path: map[:game_path],
      pakset: map[:pakset],
      paksize: map[:paksize],
      save_data: map[:save_data],
      map_size: {
        width: map[:map_size_width],
        height: map[:map_size_height]
      },
      panels: panels.map do |panel|
        {
          name: panel[:name],
          path: panel[:path],
          resolution: {
            width: panel[:resolution_width],
            height: panel[:resolution_height]
          }
        }
      end,
      zoom_level: map[:zoom_level],
      published_at: map[:published_at]&.iso8601,
      started_at: map[:started_at]&.iso8601,
      created_at: map[:created_at]&.iso8601
    }
  end

  def self.format_job_response(job, flow_run_state)
    {
      job_id: job[:id].to_s,
      job_name: job[:name],
      map_id: job[:map_id],
      state: flow_run_state,
      progress: {
        completed: 0,
        total: 0
      },
      started_at: nil,
      created_at: job[:created_at]&.iso8601
    }
  end

  def self.format_status_response(maps, jobs)
    {
      maps: maps.map do |map|
        panels = DB.list_panels_by_map_id(map[:id])
        format_admin_map_response(map, panels)
      end,
      jobs: jobs.map do |job|
        begin
          state = Prefect.get_flow_run_state(job[:prefect_run_id])
        rescue => e
          state = 'Unknown'
        end
        format_job_response(job, state)
      end
    }
  end

  def self.format_options_response
    {
      folders: scan_game_folders,
      threads: {
        all: 10,
        'service-capture' => 2,
        'service-estimate' => 2,
        'service-tile-cut' => 4,
        'service-tile-merge' => 2,
        'service-tile-compress' => 2,
        'service-create-panel' => 1
      }
    }
  end
end
