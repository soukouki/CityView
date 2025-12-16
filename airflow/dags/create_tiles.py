from airflow import DAG
from airflow.decorators import task
from datetime import datetime
import env
from lib.capture_strategy import CaptureStrategy

MAP_TILES_MAX_X = env.fetch('MAP_TILES_MAX_X', 512)
MAP_TILES_MAX_Y = env.fetch('MAP_TILES_MAX_Y', 512)

with DAG(
    dag_id='custom_dependencies',
    start_date=datetime(2025, 12, 1),
    schedule_interval=None,
    catchup=False,
) as dag:

    capture_strategy = CaptureStrategy(
        map_x=MAP_TILES_MAX_X,
        map_y=MAP_TILES_MAX_Y,
        
    )
