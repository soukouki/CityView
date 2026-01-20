require 'json'

module Helpers
  # ========================================
  # ゲームフォルダスキャン
  # ========================================

  BASE_DIR = '/app/bin'

  def self.scan_game_folders
    # /app/bin以下にあるground.Outside.pakを探し、その1つ上のフォルダをゲームフォルダとする
    game_folders = Dir
      .glob(File.join(BASE_DIR, '**', 'ground.Outside.pak'))
      .map{ |path| File.dirname(path, 2) }
      .map{ |path| path.sub(/^#{Regexp.escape(BASE_DIR)}/, '') }
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
      .glob(File.join(BASE_DIR, folder, '*'))
      .select{ |path| File.file?(path) && File.executable?(path) }
      .map{ |path| { name: File.basename(path), path: path } }
  end

  def self.list_paksets(folder)
    Dir
      .glob(File.join(BASE_DIR, folder, '*'))
      .select{ |path| File.directory?(path) && File.exist?(File.join(path, 'ground.Outside.pak')) }
      .map{ |path| { name: File.basename(path) } }
  end

  def self.list_save_data(folder)
    save_dir = File.join(BASE_DIR, folder, 'save')
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
      name: map[:name],
      status: map[:status],
      description: map[:description],
      copyright: map[:copyright],
      binary_name: map[:binary_name],
      pakset_name: map[:pakset_name],
      paksize: map[:paksize],
      save_data_name: map[:save_data_name],
      map_size: {
        x: map[:map_size_x],
        y: map[:map_size_y]
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
      name: map[:name],
      status: map[:status],
      description: map[:description],
      copyright: map[:copyright],
      folder_path: map[:folder_path],
      binary_name: map[:binary_name],
      pakset_name: map[:pakset_name],
      paksize: map[:paksize],
      save_data_name: map[:save_data_name],
      map_size: {
        x: map[:map_size_x],
        y: map[:map_size_y]
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
        all: 14,
        'service-capture' => 9,
        'service-estimate' => 5,
        'service-tile-cut' => 10,
        'service-tile-merge' => 5,
        'service-tile-compress' => 5,
        'service-create-panel' => 3
      }
    }
  end
end
