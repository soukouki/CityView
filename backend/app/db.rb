require 'sequel'

module DB
  @db = nil

  def self.connect!
    database_url = ENV['DATABASE_URL'] || 'postgres://postgres@db:5432/app'
    @db = Sequel.connect(database_url)
    @db.extension :pg_enum
  end

  def self.connection
    @db
  end

  # ========================================
  # Maps
  # ========================================

  def self.create_map(
    name:,
    description:,
    copyright:,
    folder_path:,
    binary_name:,
    pakset_name:,
    paksize:,
    save_data_name:,
    map_size_x:,
    map_size_y:,
    zoom_level:,
    status: 'processing'
  )
    @db[:maps].insert(
      name: name,
      description: description,
      copyright: copyright,
      folder_path: folder_path,
      binary_name: binary_name,
      pakset_name: pakset_name,
      paksize: paksize,
      save_data_name: save_data_name,
      map_size_x: map_size_x,
      map_size_y: map_size_y,
      zoom_level: zoom_level,
      status: status,
      sort_order: @db[:maps].max(:sort_order).to_i + 1,
      created_at: Time.now
    )
  end

  def self.find_map(id)
    @db[:maps].where(id: id).first
  end

  def self.list_maps(status: nil)
    dataset = @db[:maps]
    dataset = dataset.where(status: status) if status
    dataset.order(:sort_order).all
  end

  def self.update_map_status(id, status)
    @db[:maps].where(id: id).update(status: status)
  end

  def self.update_map_started_at(id)
    @db[:maps].where(id: id).update(started_at: Time.now)
  end

  def self.update_map_published_at(id)
    @db[:maps].where(id: id).update(published_at: Time.now)
  end

  def self.update_map_metadata(
    id:,
    name:,
    description:,
    copyright:
  )
    @db[:maps].where(id: id).update(
      name: name,
      description: description,
      copyright: copyright
    )
  end

  def self.update_map_sort_order(id, new_position)
    @db.transaction do
      # 1. 移動対象のマップを一時的に退避（大きな値に設定）
      @db.run <<-SQL
        UPDATE maps
        SET sort_order = 99999
        WHERE id = #{id};
      SQL

      # 2. 挿入位置以降のマップを+1シフト
      @db.run <<-SQL
        UPDATE maps
        SET sort_order = sort_order + 1
        WHERE sort_order >= #{new_position + 1}
          AND id != #{id};
      SQL

      # 3. 移動対象を指定位置に配置
      @db.run <<-SQL
        UPDATE maps
        SET sort_order = #{new_position + 1}
        WHERE id = #{id};
      SQL

      # 4. 正規化（念のため、連番を1から振り直し）
      @db.run <<-SQL
        WITH ordered AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY sort_order) as new_order
            FROM maps
        )
        UPDATE maps
        SET sort_order = ordered.new_order
        FROM ordered
        WHERE maps.id = ordered.id;
      SQL
    end
  end

  def self.delete_map(id)
    @db[:maps].where(id: id).delete
  end

  # ========================================
  # Jobs
  # ========================================

  def self.create_job(map_id:, prefect_run_id:, name:)
    @db[:jobs].insert(
      map_id: map_id,
      prefect_run_id: prefect_run_id,
      name: name,
      created_at: Time.now
    )
  end

  def self.find_job_by_map_id(map_id)
    @db[:jobs].where(map_id: map_id).first
  end

  def self.list_jobs
    @db[:jobs].order(:id).all
  end

  # ========================================
  # Panels
  # ========================================

  def self.create_panel(
    map_id:,
    name:,
    path:,
    resolution_width:,
    resolution_height:
  )
    @db[:panels].insert(
      map_id: map_id,
      name: name,
      path: path,
      resolution_width: resolution_width,
      resolution_height: resolution_height,
      created_at: Time.now
    )
  end

  def self.list_panels_by_map_id(map_id)
    @db[:panels].where(map_id: map_id).order(:resolution_width).all
  end

  # ========================================
  # Screenshots
  # ========================================

  def self.create_screenshot(
    map_id:,
    game_tile_x:,
    game_tile_y:,
    path:
  )
    @db[:screenshots].insert(
      map_id: map_id,
      game_tile_x: game_tile_x,
      game_tile_y: game_tile_y,
      path: path,
      created_at: Time.now
    )
  end

  def self.find_screenshot(id)
    @db[:screenshots].where(id: id).first
  end

  def self.update_screenshot_coordinates(id, estimated_screen_x:, estimated_screen_y:)
    @db[:screenshots].where(id: id).update(
      estimated_screen_x: estimated_screen_x,
      estimated_screen_y: estimated_screen_y
    )
  end

  def self.list_screenshots_by_map_id(map_id, estimated: nil)
    dataset = @db[:screenshots].where(map_id: map_id)
    if estimated == true
      dataset = dataset.exclude(estimated_screen_x: nil)
    elsif estimated == false
      dataset = dataset.where(estimated_screen_x: nil)
    end
    dataset.order(:id).all
  end
end
