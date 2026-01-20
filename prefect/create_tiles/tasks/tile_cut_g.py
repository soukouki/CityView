import requests
from create_tiles.priority_task import priority_task
from create_tiles.config import (SERVICE_TILE_CUT_URL)
from create_tiles.utils import map_tile_to_screen_coord, parse_xy_str, check_exists, log
from create_tiles.flow_params import CreateTilesParams

@priority_task(task_type="tile_cut", retries=3, retry_delay_seconds=300)
def tile_cut_g(params: CreateTilesParams, gx: int, gy: int, related_areas: list, capture_results: list, estimate_results: list):
    log(f"Processing tile cut group at ({gx}, {gy}) with {len(related_areas)} related areas")
    for area in related_areas:
        log(f"  Related area: x{area['x']}, y{area['y']}")
    log(f"Received {len(capture_results)} capture results groups")
    for capture_result in capture_results:
        log(" Capture result:")
        for xy_str, capture_dict in capture_result.items():
            x, y = parse_xy_str(xy_str)
            log(f"  Capture result - coords: ({x}, {y}), capture_dict: {capture_dict}")
    log(f"Received {len(estimate_results)} estimate results groups")
    for estimate_result in estimate_results:
        log(" Estimate result:")
        for xy_str, coords in estimate_result.items():
            x, y = parse_xy_str(xy_str)
            log(f"  Estimate result - coords: ({x}, {y}), estimated coords: ({coords['x']}, {coords['y']})")

    # capture_resultsとestimate_resultsを辞書に変換しておく
    capture_many_dict = {}
    for capture_result in capture_results:
        for xy_str, capture_dict in capture_result.items():
            x, y = parse_xy_str(xy_str)
            capture_many_dict[(x, y)] = capture_dict
    estimate_many_dict = {}
    for estimate_result in estimate_results:
        for xy_str, coords in estimate_result.items():
            x, y = parse_xy_str(xy_str)
            estimate_many_dict[(x, y)] = coords

    # 各エリアのスクリーン座標範囲を事前計算
    area_screen_ranges = []
    for area in related_areas:
        ax, ay = area['x'], area['y']
        if (ax, ay) not in estimate_many_dict:
            continue
        estimated_coords = estimate_many_dict[(ax, ay)]
        screen_x = estimated_coords['x']
        screen_y = estimated_coords['y']
        area_screen_ranges.append({
            'x': ax,
            'y': ay,
            'screen_x_min': screen_x - params.capture.margin_width,
            'screen_y_min': screen_y - params.capture.margin_height,
            'screen_x_max': screen_x + params.capture.image_width + params.capture.margin_width,
            'screen_y_max': screen_y + params.capture.image_height + params.capture.margin_height,
        })

    # グループ内の各タイルを処理
    cut_tiles = {}
    tile_group_size = params.tile_group_size
    max_z = params.max_z
    for tx in range(gx, gx + tile_group_size):
        for ty in range(gy, gy + tile_group_size):
            # このタイルのスクリーン座標範囲を計算
            tile_screen_min = map_tile_to_screen_coord(params, tx, ty, max_z)
            tile_screen_max = map_tile_to_screen_coord(params, tx + 1, ty + 1, max_z)
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
                    "path": capture_many_dict[(ax, ay)]['path'],
                    "coords": estimate_many_dict[(ax, ay)],
                })
            
            # 画像が1つもないとき(=地図タイルがマップ外)はスキップ
            if not images:
                continue
            
            output_path = f"/images/rawtiles/{params.map_id}/{max_z}/{tx}/{ty}.png"
            if check_exists(output_path):
                log(f"  Output already exists at {output_path}, skipping tile cut.")
                cut_tiles[f"z{max_z}_x{tx}_y{ty}"] = output_path
                continue
            tile_cut(
                params=params,
                x=tx,
                y=ty,
                images=images,
                output_path=output_path
            )
            cut_tiles[f"z{max_z}_x{tx}_y{ty}"] = output_path

    return cut_tiles

def tile_cut(params: CreateTilesParams, x: int, y: int, images: list, output_path: str):
    url = f"{SERVICE_TILE_CUT_URL}/cut"
    cut_area = map_tile_to_screen_coord(params, x, y, params.max_z)
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
    log(f"status code: {response.status_code}")
    log(f"response text: {response.text}")
    log("payload:", payload)
    response.raise_for_status()
    data = response.json()
    saved_path = data["output_path"]
    log(f"Cut tile saved at: {saved_path}")
    return saved_path
