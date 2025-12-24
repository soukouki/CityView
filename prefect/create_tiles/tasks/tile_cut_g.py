import requests
from create_tiles.custom_task import priority_task
from create_tiles.config import (
    SERVICE_TILE_CUT_URL,
    TILE_SIZE,
    MAX_Z,
    TILE_GROUP_SIZE,
    IMAGE_WIDTH,
    IMAGE_HEIGHT,
    IMAGE_MARGIN_WIDTH,
    IMAGE_MARGIN_HEIGHT,
    SAVE_DATA_NAME,
)
from create_tiles.utils import map_tile_to_screen_coord, parse_xy_str, check_exists

@priority_task(task_type="tile_cut", retries=3, retry_delay_seconds=300)
def tile_cut_g(gx: int, gy: int, related_areas: list, capture_results: list, estimate_results: list):
    print(f"Processing tile cut group at ({gx}, {gy}) with {len(related_areas)} related areas")
    for area in related_areas:
        print(f"  Related area: x{area['x']}, y{area['y']}")
    print(f"Received {len(capture_results)} capture results groups")
    for capture_result in capture_results:
        print(" Capture result:")
        for xy_str, image_path in capture_result.items():
            x, y = parse_xy_str(xy_str)
            print(f"  Capture result - coords: ({x}, {y}), image_path: {image_path}")
    print(f"Received {len(estimate_results)} estimate results groups")
    for estimate_result in estimate_results:
        print(" Estimate result:")
        for xy_str, coords in estimate_result.items():
            x, y = parse_xy_str(xy_str)
            print(f"  Estimate result - coords: ({x}, {y}), estimated coords: ({coords['x']}, {coords['y']})")

    # capture_resultsとestimate_resultsを辞書に変換しておく
    capture_dict = {}
    for capture_result in capture_results:
        for xy_str, image_path in capture_result.items():
            x, y = parse_xy_str(xy_str)
            capture_dict[(x, y)] = image_path
    estimate_dict = {}
    for estimate_result in estimate_results:
        for xy_str, coords in estimate_result.items():
            x, y = parse_xy_str(xy_str)
            estimate_dict[(x, y)] = coords

    # 各エリアのスクリーン座標範囲を事前計算
    area_screen_ranges = []
    for area in related_areas:
        ax, ay = area['x'], area['y']
        if (ax, ay) not in estimate_dict:
            continue
        estimated_coords = estimate_dict[(ax, ay)]
        screen_x = estimated_coords['x']
        screen_y = estimated_coords['y']
        area_screen_ranges.append({
            'x': ax,
            'y': ay,
            'screen_x_min': screen_x - IMAGE_MARGIN_WIDTH,
            'screen_y_min': screen_y - IMAGE_MARGIN_HEIGHT,
            'screen_x_max': screen_x + IMAGE_WIDTH + IMAGE_MARGIN_WIDTH,
            'screen_y_max': screen_y + IMAGE_HEIGHT + IMAGE_MARGIN_HEIGHT,
        })

    # グループ内の各タイルを処理
    cut_tiles = {}
    for tx in range(gx, gx + TILE_GROUP_SIZE):
        for ty in range(gy, gy + TILE_GROUP_SIZE):
            # このタイルのスクリーン座標範囲を計算
            tile_screen_min = map_tile_to_screen_coord(tx, ty, MAX_Z)
            tile_screen_max = map_tile_to_screen_coord(tx + 1, ty + 1, MAX_Z)
            tile_x_min = tile_screen_min[0]
            tile_y_min = tile_screen_min[1]
            tile_x_max = tile_screen_max[0]
            tile_y_max = tile_screen_max[1]
            
            # このタイルをカバーするエリアを判定
            images = []
            for area_range in area_screen_ranges:
                # 重なり判定
                if (area_range['screen_x_max'] < tile_x_min or
                    area_range['screen_x_min'] > tile_x_max or
                    area_range['screen_y_max'] < tile_y_min or
                    area_range['screen_y_min'] > tile_y_max):
                    continue
                
                ax, ay = area_range['x'], area_range['y']
                images.append({
                    "path": capture_dict[(ax, ay)],
                    "coords": estimate_dict[(ax, ay)],
                })
            
            # 画像が1つもないとき(=地図タイルがマップ外)はスキップ
            if not images:
                continue
            
            output_path = f"/images/rawtiles/{SAVE_DATA_NAME}/{MAX_Z}/{tx}/{ty}.png"
            if check_exists(output_path):
                print(f"  Output already exists at {output_path}, skipping tile cut.")
                cut_tiles[f"z{MAX_Z}_x{tx}_y{ty}"] = output_path
                continue
            tile_cut(
                x=tx,
                y=ty,
                images=images,
                output_path=output_path
            )
            cut_tiles[f"z{MAX_Z}_x{tx}_y{ty}"] = output_path

    return cut_tiles

def tile_cut(x: int, y: int, images: list, output_path: str):
    url = f"{SERVICE_TILE_CUT_URL}/cut"
    cut_area = map_tile_to_screen_coord(x, y, MAX_Z)
    payload = {
        "images": [
            {
                "path": img["path"],
                "x": img["coords"]["x"], # coords is {"x": int, "y": int}
                "y": img["coords"]["y"],
            } for img in images
        ],
        "cut_area": {
            "x": cut_area[0],
            "y": cut_area[1],
        },
        "output_path": output_path,
    }
    response = requests.post(url, json=payload)
    print(f"status code: {response.status_code}")
    print(f"response text: {response.text}")
    print("payload:", payload)
    response.raise_for_status()
    data = response.json()
    saved_path = data["output_path"]
    print(f"Cut tile saved at: {saved_path}")
    return saved_path
