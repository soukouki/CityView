from airflow import DAG
from airflow.decorators import task
from datetime import datetime
from lib.capture_strategy import CaptureStrategy
import os
import math

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

# ゲーム内タイル座標系とスクショ座標系の変換式
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

# スクショ座標系と地図タイル座標系の変換式
# | 変換 | 式 |
# |------|-----|
# | **スクショ → タイル** | $tx = \left\lfloor \dfrac{X + 256y_{max} + w \times 2}{512 \times 2^{z_{max} - z}} \right\rfloor$ <br> $ty = \left\lfloor \dfrac{Y}{512 \times 2^{z_{max} - z}} \right\rfloor$ |
# | **タイル → スクショ(最小値)** | $X_{min} = tx \times 512 \times 2^{z_{max} - z} - 256y_{max} - w \times 2$ <br> $Y_{min} = ty \times 512 \times 2^{z_{max} - z}$ |
def screen_coord_to_map_tile(screen_x: int, screen_y: int, z: int, z_max: int, y_max: int) -> tuple[int, int]:
    scale = 2 ** (z_max - z)
    tile_x = (screen_x + 256 * y_max + IMAGE_MARGIN_WIDTH * 2) // (512 * scale)
    tile_y = screen_y // (512 * scale)
    return tile_x, tile_y

# 地図タイルのうちの最小値スクショ座標を取得
def map_tile_to_screen_coord(tile_x: int, tile_y: int, z: int, z_max: int, y_max: int) -> tuple[int, int]:
    scale = 2 ** (z_max - z)
    screen_x_min = tile_x * 512 * scale - 256 * y_max - IMAGE_MARGIN_WIDTH * 2
    screen_y_min = tile_y * 512 * scale
    return screen_x_min, screen_y_min

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

    # ---------- スクショ撮影タスク ----------

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

    # ---------- スクショ座標推定タスク ----------

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

    # ---------- 最大ズームタイル切り出しタスク ----------

    @task
    def tile_cut(images: list, cut_area: dict, output_path: str):
        print(f"Cutting tile at ({cut_area['x']}, {cut_area['y']}) from {len(images)} images")
        for img in images:
            print(f"Using image {img['path']} at area ({img['x']}, {img['y']})")
        return output_path

    max_width = 256 * (MAP_TILES_X + MAP_TILES_Y) + IMAGE_MARGIN_WIDTH * 4
    max_height = 128 * (MAP_TILES_X + MAP_TILES_Y) + IMAGE_MARGIN_HEIGHT * 2
    max_z = math.ceil(math.log2(max(max_width, max_height) / TILE_SIZE))

    # 最大ズームの全タイルを生成する
    # 描画範囲外のタイルも生成する(黒塗りになる)
    tile_cut_tasks = {}
    for tx in range(0, 2 ** max_z):
        for ty in range(0, 2 ** max_z):
            task_id = f"tile_cut_z{max_z}_x{tx}_y{ty}"
            # このタイルをカバーするスクショ座標の範囲を計算
            screen_min = map_tile_to_screen_coord(tx, ty, max_z, max_z, MAP_TILES_Y)
            screen_max = map_tile_to_screen_coord(tx + 1, ty + 1, max_z, max_z, MAP_TILES_Y)
            # タイルの範囲のスクショ座標を計算
            screen_x_min = screen_min[0]
            screen_y_min = screen_min[1]
            screen_x_max = screen_max[0]
            screen_y_max = screen_max[1]
            # その範囲をカバーする座標を持つスクショを探す
            # DAG生成時にはまだスクショの正確な位置がわからないので、撮影予定座標から推定する
            # covering_images = [] # [{x: number, y: number}]
            # for area in areas:
            #     est_task_id = f"estimate_x{area['x']}_y{area['y']}"
            #     est_coords = estimate_tasks[est_task_id]
            #     # 撮影予定座標を計算
            #     screen_coord = game_tile_to_screen_coord(area['x'], area['y'])
            #     screen_x = screen_coord[0]
            #     screen_y = screen_coord[1]
            #     # スクショのカバー範囲を計算
            #     capture_x_min = screen_x - (IMAGE_WIDTH // 2)
            #     capture_y_min = screen_y - (IMAGE_HEIGHT // 2)
            #     capture_x_max = screen_x + (IMAGE_WIDTH // 2)
            #     capture_y_max = screen_y + (IMAGE_HEIGHT // 2)
            #     # タイル範囲とスクショ範囲が重なるか？
            #     if not (capture_x_max < screen_x_min or capture_x_min > screen_x_max or
            #             capture_y_max < screen_y_min or capture_y_min > screen_y_max):
            #         covering_images.append({
            #             "x": area['x'],
            #             "y": area['y'],
            #         })
            # images = []
            # for img in covering_images:
            #     coords = estimate_tasks[f"estimate_x{img['x']}_y{img['y']}"]
            #     images.append({
            #         "path": capture_tasks[f"capture_x{img['x']}_y{img['y']}"],
            #         "x": coords['x'],
            #         "y": coords['y'],
            #     })
            tile_cut_tasks[task_id] = tile_cut.override(task_id=task_id)(
                images=images,
                cut_area={
                    "x": tx,
                    "y": ty,
                },
                output_path=f"/images/rawtiles/{max_z}/{tx}/{ty}.png",
            )

    # ---------- 低ズームタイル生成タスク ----------
