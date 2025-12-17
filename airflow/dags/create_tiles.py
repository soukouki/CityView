from airflow import DAG
from airflow.decorators import task
from datetime import datetime
from lib.capture_strategy import CaptureStrategy
import os

# 環境変数から取ってくる
PAKSET_SIZE = int(os.environ.get('PAKSET_SIZE', '128'))
TILE_SIZE = int(os.environ.get('TILE_SIZE', '512'))
DELTA = int(os.environ.get('DELTA', '40'))
MAP_TILES_X = int(os.environ.get('MAP_TILES_X', '512'))
MAP_TILES_Y = int(os.environ.get('MAP_TILES_Y', '512'))
IMAGE_WIDTH = int(os.environ.get('IMAGE_WIDTH', '5632')) # W + 2w
IMAGE_HEIGHT = int(os.environ.get('IMAGE_HEIGHT', '2816')) # H + 2h
IMAGE_MARGIN_WIDTH = int(os.environ.get('IMAGE_MARGIN_WIDTH', '256'))
IMAGE_MARGIN_HEIGHT = int(os.environ.get('IMAGE_MARGIN_HEIGHT', '128'))
ENABLE_WIDTH = IMAGE_WIDTH - 2 * IMAGE_MARGIN_WIDTH
ENABLE_HEIGHT = IMAGE_HEIGHT - 2 * IMAGE_MARGIN_HEIGHT

# X, Y: スクショ座標
# x, y: ゲーム内タイル座標
# W, H: スクショ画像の有効幅・高さ
# w, h: スクショ画像のマージン幅・高さ
# X = 256(x-y) + W/2 + w
# Y = 128(x+y) + H/2 + h
def game_tile_to_screen_coord(tile_x: int, tile_y: int) -> tuple[int, int]:
    screen_x = 256 * (tile_x - tile_y) + (ENABLE_WIDTH // 2) + IMAGE_MARGIN_WIDTH
    screen_y = 128 * (tile_x + tile_y) + (ENABLE_HEIGHT // 2) + IMAGE_MARGIN_HEIGHT
    return screen_x, screen_y

def screen_coord_to_game_tile(screen_x: int, screen_y: int) -> tuple[int, int]:
    X = screen_x - IMAGE_MARGIN_WIDTH
    Y = screen_y - IMAGE_MARGIN_HEIGHT
    tile_x = (X + 2 * Y) // 512
    tile_y = (2 * Y - X) // 512
    return tile_x, tile_y

with DAG(
    dag_id='create_tiles',
    catchup=False,
    start_date=datetime(2024, 1, 1),
    params={
        "save_data_name": "demo",
    },
) as dag:

    strategy = CaptureStrategy(
        map_x=MAP_TILES_X,
        map_y=MAP_TILES_Y,
        delta=256,
    )
    areas = strategy.generate_capture_areas()

    @task
    def capture(save_data_name: str, x: int, y: int):
        print(f"Capturing area {save_data_name} at ({x}, {y})")
        return f"/images/screenshots/{save_data_name}_x{x}_y{y}.png"

    capture_tasks = {}
    for area in areas:
        task_id = f"capture_x{area['x']}_y{area['y']}"
        capture_tasks[task_id] = capture.override(task_id=task_id)(
            save_data_name=dag.params["save_data_name"],
            x=area['x'],
            y=area['y'],
        )
        compare_task_names = [f"capture_x{comp['x']}_y{comp['y']}" for comp in area['compare']]
        for compare_task_name in compare_task_names:
            capture_tasks[compare_task_name] >> capture_tasks[task_id]

    @task
    def estimate(image_path: str, adjacent_images: list, hint_x: int, hint_y: int):
        print(f"Estimating coords for {image_path} with hints ({hint_x}, {hint_y})")
        for adj in adjacent_images:
            print(f"Using adjacent image {adj['image_path']} at offset ({adj['x']}, {adj['y']})")
        return {"x": hint_x + 1, "y": hint_y + 1}

    estimate_tasks = {}
    for area in areas:
        task_id = f"estimate_x{area['x']}_y{area['y']}"
        hint_coord = game_tile_to_screen_coord(area['x'], area['y'])
        estimate_tasks[task_id] = estimate.override(task_id=task_id)(
            image_path=capture_tasks[f"capture_x{area['x']}_y{area['y']}"],
            adjacent_images=[
                {
                    "image_path": capture_tasks[f"capture_x{comp['x']}_y{comp['y']}"], # ここでも依存を作っている
                    "x": comp['x'],
                    "y": comp['y'],
                }
                for comp in area['compare']
            ],
            hint_x=hint_coord[0],
            hint_y=hint_coord[1],
        )
        capture_tasks[f"capture_x{area['x']}_y{area['y']}"] >> estimate_tasks[task_id]
        for comp in area['compare']:
            estimate_tasks[f"estimate_x{comp['x']}_y{comp['y']}"] >> estimate_tasks[task_id]

    @task
    def tile_cut(images: list, tile_x: int, tile_y: int):
        print(f"Cutting tile at ({tile_x}, {tile_y}) from images:")
        for img in images:
            print(f"- Image ID: {img['id']} Path: {img['path']} at ({img['x']}, {img['y']})")
        return f"/images/tiles/tile_x{tile_x}_y{tile_y}.png"

    