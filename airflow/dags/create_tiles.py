from airflow import DAG
from airflow.decorators import task
from datetime import datetime
from lib.capture_strategy import CaptureStrategy
import os
import math
from collections import defaultdict

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

# タイルグループ化のサイズ
TILE_GROUP_SIZE = 16

# ゲーム内タイル座標系とスクショ座標系の変換式
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

def screen_coord_to_map_tile(screen_x: int, screen_y: int, z: int, z_max: int, y_max: int) -> tuple[int, int]:
    scale = 2 ** (z_max - z)
    tile_x = (screen_x + 256 * y_max + IMAGE_MARGIN_WIDTH * 2) // (512 * scale)
    tile_y = screen_y // (512 * scale)
    return tile_x, tile_y

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
        capture_tasks[task_id] = capture.override(task_id=task_id, queue="capture")(
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
        estimate_tasks[task_id] = estimate.override(task_id=task_id, queue="coords")(
            image_path=capture_tasks[f"capture_x{area['x']}_y{area['y']}"],
            adjacent_images=[
                {
                    "image_path": capture_tasks[f"capture_x{comp['x']}_y{comp['y']}"],
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
    def tile_cut_group(tiles_info: list, output_dir: str):
        """複数タイルをグループでまとめて処理"""
        print(f"Cutting {len(tiles_info)} tiles in group to {output_dir}")
        for tile_info in tiles_info:
            print(f"Tile ({tile_info['x']}, {tile_info['y']}): {len(tile_info['images'])} images")
            for img in tile_info['images']:
                # 実行時にcoordsから取り出す
                actual_x = img['coords']['x']
                actual_y = img['coords']['y']
                print(f"  Using image {img['path']} at ({actual_x}, {actual_y})")
        return output_dir

    max_width = 256 * (MAP_TILES_X + MAP_TILES_Y) + IMAGE_MARGIN_WIDTH * 4
    max_height = 128 * (MAP_TILES_X + MAP_TILES_Y) + IMAGE_MARGIN_HEIGHT * 2
    max_z = math.ceil(math.log2(max(max_width, max_height) / TILE_SIZE))

    # タイルの総数
    total_tiles_per_axis = 2 ** max_z
    
    # マップが極端に小さい場合、グループサイズを調整
    actual_group_size = min(TILE_GROUP_SIZE, total_tiles_per_axis)

    # 各エリアのカバー範囲を事前計算し、空間インデックスを作成
    area_coverage = []
    for area in areas:
        screen_coord = game_tile_to_screen_coord(area['x'], area['y'])
        screen_x = screen_coord[0]
        screen_y = screen_coord[1]
        capture_x_min = screen_x - (IMAGE_WIDTH // 2)
        capture_y_min = screen_y - (IMAGE_HEIGHT // 2)
        capture_x_max = screen_x + (IMAGE_WIDTH // 2)
        capture_y_max = screen_y + (IMAGE_HEIGHT // 2)
        
        # タイル座標系に変換して空間インデックスを作成
        tile_x_min, tile_y_min = screen_coord_to_map_tile(
            capture_x_min, capture_y_min, max_z, max_z, MAP_TILES_Y
        )
        tile_x_max, tile_y_max = screen_coord_to_map_tile(
            capture_x_max, capture_y_max, max_z, max_z, MAP_TILES_Y
        )
        
        area_coverage.append({
            'area': area,
            'tile_x_min': tile_x_min,
            'tile_x_max': tile_x_max,
            'tile_y_min': tile_y_min,
            'tile_y_max': tile_y_max,
            'screen_x_min': capture_x_min,
            'screen_y_min': capture_y_min,
            'screen_x_max': capture_x_max,
            'screen_y_max': capture_y_max,
        })

    # タイル座標からカバーするエリアへの逆引きマップを作成
    tile_to_areas = defaultdict(list)
    for cov in area_coverage:
        # このエリアがカバーするタイル範囲を列挙
        for tx in range(max(0, cov['tile_x_min']), min(total_tiles_per_axis, cov['tile_x_max'] + 1)):
            for ty in range(max(0, cov['tile_y_min']), min(total_tiles_per_axis, cov['tile_y_max'] + 1)):
                tile_to_areas[(tx, ty)].append(cov)

    # グループ化してタイル切り出しタスクを生成
    tile_cut_tasks = {}
    for gx in range(0, total_tiles_per_axis, actual_group_size):
        for gy in range(0, total_tiles_per_axis, actual_group_size):
            # グループ内の全タイル情報を収集
            tiles_in_group = []
            group_has_images = False  # このグループに画像が1つでもあるか
            
            for tx in range(gx, min(gx + actual_group_size, total_tiles_per_axis)):
                for ty in range(gy, min(gy + actual_group_size, total_tiles_per_axis)):
                    # このタイルをカバーするスクショ座標の範囲を計算
                    screen_min = map_tile_to_screen_coord(tx, ty, max_z, max_z, MAP_TILES_Y)
                    screen_max = map_tile_to_screen_coord(tx + 1, ty + 1, max_z, max_z, MAP_TILES_Y)
                    screen_x_min = screen_min[0]
                    screen_y_min = screen_min[1]
                    screen_x_max = screen_max[0]
                    screen_y_max = screen_max[1]
                    
                    # 空間インデックスから候補を取得し、正確な重なり判定のみ実行
                    candidate_areas = tile_to_areas.get((tx, ty), [])
                    covering_images = []
                    
                    for cov in candidate_areas:
                        # 正確な重なり判定(念のため再確認)
                        if not (cov['screen_x_max'] < screen_x_min or cov['screen_x_min'] > screen_x_max or
                                cov['screen_y_max'] < screen_y_min or cov['screen_y_min'] > screen_y_max):
                            covering_images.append({
                                "x": cov['area']['x'],
                                "y": cov['area']['y'],
                            })
                    
                    images = []
                    for img in covering_images:
                        coords = estimate_tasks[f"estimate_x{img['x']}_y{img['y']}"]
                        images.append({
                            "path": capture_tasks[f"capture_x{img['x']}_y{img['y']}"],
                            "coords": coords,  # ← estimate結果全体を渡す
                        })
                    
                    # 画像があるかチェック
                    if len(images) > 0:
                        group_has_images = True
                    
                    tiles_in_group.append({
                        "x": tx,
                        "y": ty,
                        "images": images,
                    })
            
            # 画像が1つもない(=完全にマップ外)グループはタスクを作らない
            if not group_has_images:
                continue
            
            task_id = f"tile_cut_group_z{max_z}_gx{gx}_gy{gy}"
            tile_cut_tasks[task_id] = tile_cut_group.override(task_id=task_id, queue="tile_cut")(
                tiles_info=tiles_in_group,
                output_dir=f"/images/rawtiles/{max_z}/group_{gx}_{gy}",
            )

    # ---------- 低ズームタイル生成タスク ----------
