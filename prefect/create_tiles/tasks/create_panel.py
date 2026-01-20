import requests
from create_tiles.priority_task import priority_task
from create_tiles.config import (SERVICE_CREATE_PANEL_URL, BACKEND_INTERNAL_URL)
from create_tiles.utils import (
    game_tile_to_screen_coord,
    screen_coord_to_map_tile,
    check_exists,
    parse_zxy_str,
    log,
)
from create_tiles.flow_params import CreateTilesParams

@priority_task(task_type="panel", retries=3, retry_delay_seconds=300)
def create_panel(params: CreateTilesParams, z: int, resolution: dict, tile_results: list):
    log(f"Creating panel at zoom level {z} with resolution {resolution}")
    log(f"Received {len(tile_results)} tile groups")
    for tile_result in tile_results:
        log(" Tile result:")
        for key, path in tile_result.items():
            log(f"  - key:{key}, path: {path}")
    # tile_cut_gとtile_merge_gの両方の結果を受け取ることがある
    tiles = [] # {"path": str, "x": int, "y": int}
    for tile_result in tile_results:
        for key, path in tile_result.items():
            cz, cx, cy = parse_zxy_str(key)
            tiles.append({
                "path": path,
                "x": cx,
                "y": cy,
            })
    output_path = f"/images/panels/{params.map_id}/panel_{resolution['id']}_x{resolution['width']}_y{resolution['height']}.png"
    if check_exists(output_path):
        log(f"  Output already exists at {output_path}, skipping panel creation.")
        return output_path
    
    url = f"{SERVICE_CREATE_PANEL_URL}/create_panel"
    map_scale = 2 ** (params.max_z - z)
    map_size = {
        "width": (params.full_width + 2 * params.capture.margin_width) // map_scale,
        "height": (params.full_height + 2 * params.capture.margin_height) // map_scale,
    }
    # 上端と左端の、最大ズームレベルでの座標をオフセットにする
    up_screen_x, up_screen_y = game_tile_to_screen_coord(params, 0, 0)
    up_map_x, up_map_y = screen_coord_to_map_tile(params, up_screen_x, up_screen_y, z)
    left_screen_x, left_screen_y = game_tile_to_screen_coord(params, 0, params['map_tiles_y'])
    left_map_x, left_map_y = screen_coord_to_map_tile(params, left_screen_x, left_screen_y, z)
    tile_size = params.tile_size
    offsets = {
        "x": int(left_map_x * tile_size / 1.5), # なんかズレているので気合で微修正
        "y": up_map_y * tile_size,
    }
    payload = {
        "z": z,
        "tiles": tiles,
        "map_size": map_size,
        "offsets": offsets,
        "resolution": {"width": resolution['width'], "height": resolution['height']},
        "output_path": output_path,
    }
    response = requests.post(url, json=payload)
    log(f"status code: {response.status_code}")
    log(f"response text: {response.text}")
    log("payload:", payload)
    response.raise_for_status()
    log(f"Panel created successfully: {output_path}")
    panel_id = register_panel(params, resolution, output_path)
    return {
        "path": output_path,
        "panel_id": panel_id,
    }

def register_panel(params: CreateTilesParams, resolution: dict, panel_path: str):
    url = f"{BACKEND_INTERNAL_URL}/api/panels"
    payload = {
        "map_id": params.map_id,
        "name": f"{resolution['id']} ({resolution['width']}x{resolution['height']})",
        "path": panel_path,
        "resolution": {
            "width": resolution['width'],
            "height": resolution['height'],
        },
    }
    response = requests.post(url, json=payload)
    log(f"status code: {response.status_code}")
    log(f"response text: {response.text}")
    log("payload:", payload)
    response.raise_for_status()
    data = response.json() # {"panel_id": "string"} を想定
    panel_id = data['panel_id']
    log(f"Panel registered successfully with panel_id: {panel_id}")
    return panel_id
