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
      status: status,
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
      created_at: Time.now
    )
  end

  def self.find_map(id)
    @db[:maps].where(id: id).first
  end

  def self.list_maps(status: nil)
    dataset = @db[:maps]
    dataset = dataset.where(status: status) if status
    dataset.order(:id).all
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
    @db[:panels].where(map_id: map_id).order(:id).all
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
