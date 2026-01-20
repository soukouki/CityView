-- PrefectメタデータDB
CREATE DATABASE prefect;

-- アプリケーションテーブル作成
\c app;

CREATE TYPE map_status as ENUM (
    'processing',
    'completed',
    'failed'
);

CREATE TYPE zoom_level as ENUM (
    'one_eighth',
    'quarter',
    'half',
    'normal',
    'double'
);

CREATE TABLE maps (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    copyright TEXT NOT NULL,
    folder_path TEXT NOT NULL,
    binary_name TEXT NOT NULL,
    pakset_name TEXT NOT NULL,
    paksize INTEGER NOT NULL
        CHECK (paksize > 0),
    save_data_name TEXT NOT NULL,
    map_size_x INTEGER NOT NULL
        CHECK (map_size_x > 0),
    map_size_y INTEGER NOT NULL
        CHECK (map_size_y > 0),
    zoom_level zoom_level NOT NULL,
    status map_status NOT NULL,
    -- マップを生成し終わって後悔した日時(nullable)
    published_at TIMESTAMP WITH TIME ZONE NULL,
    -- マップ生成ジョブが始まって撮影が始まった日時(nullable)
    started_at TIMESTAMP WITH TIME ZONE NULL,
    -- マップ生成ジョブを作ってマップを登録した日時
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE jobs (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    map_id INTEGER NOT NULL REFERENCES maps(id) ON DELETE CASCADE UNIQUE,
    prefect_run_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_jobs_map_id ON jobs(map_id);

CREATE TABLE panels (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    map_id INTEGER NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    resolution_width INTEGER NOT NULL
        CHECK (resolution_width > 0),
    resolution_height INTEGER NOT NULL
        CHECK (resolution_height > 0),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_panels_map_id ON panels(map_id);

CREATE TABLE screenshots (
    id INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    map_id INTEGER NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    game_tile_x INTEGER NOT NULL
        CHECK (game_tile_x >= 0),
    game_tile_y INTEGER NOT NULL
        CHECK (game_tile_y >= 0),
    estimated_screen_x INTEGER, -- nullable
    estimated_screen_y INTEGER, -- nullable、実際は非負だが、将来的に変更される可能性を考慮して負の値も許容する
    CHECK (
        (estimated_screen_x IS NULL AND estimated_screen_y IS NULL)
        OR (estimated_screen_x IS NOT NULL AND estimated_screen_y IS NOT NULL)
    ),
    path TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_screenshots_map_id ON screenshots(map_id);
