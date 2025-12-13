-- db/init-scripts/01-create-databases.sql
-- 目的:
--   - 既定DB: gamedb（POSTGRES_DBで作成済み）
--   - 追加DB: airflow を作成

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow') THEN
    CREATE DATABASE airflow;
  END IF;
END $$;
