-- PrefectメタデータDB
CREATE DATABASE prefect;

-- アプリケーションテーブル作成
\c app;

CREATE TABLE IF NOT EXISTS jobs (
    job_id SERIAL PRIMARY KEY,
    game_id VARCHAR(255),
    save_data_name VARCHAR(255),
    status VARCHAR(50),
    dag_run_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS screenshots (
    screenshot_id VARCHAR(255) PRIMARY KEY,
    job_id INTEGER,
    x INTEGER,
    y INTEGER,
    estimated_x INTEGER,
    estimated_y INTEGER,
    filepath VARCHAR(500),
    status VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS tiles (
    tile_id SERIAL PRIMARY KEY,
    job_id INTEGER,
    z INTEGER,
    x INTEGER,
    y INTEGER,
    filepath VARCHAR(500),
    compressed BOOLEAN DEFAULT false,
    source_type VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS idx_tiles_coords ON tiles (z, x, y);
CREATE INDEX IF NOT EXISTS idx_screenshots_job ON screenshots(job_id);
