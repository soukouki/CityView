import requests
from create_tiles.priority_task import priority_task
from create_tiles.config import (
    SERVICE_CREATE_PANEL_URL,
    FULL_WIDTH,
    FULL_HEIGHT,
    MAX_Z,
    SAVE_DATA_NAME,
    IMAGE_MARGIN_WIDTH,
    IMAGE_MARGIN_HEIGHT,
    MAP_TILES_Y,
    TILE_SIZE,
)
from create_tiles.utils import (
    game_tile_to_screen_coord,
    screen_coord_to_map_tile,
    check_exists,
    parse_zxy_str,
    log,
)

@priority_task(task_type="panel", retries=3, retry_delay_seconds=300)
def create_panel(z: int, resolution: dict, tile_results: list):
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
    output_path = f"/images/panels/{SAVE_DATA_NAME}/panel_{resolution['id']}_x{resolution['width']}_y{resolution['height']}.png"
    if check_exists(output_path):
        log(f"  Output already exists at {output_path}, skipping panel creation.")
        return output_path
    
    url = f"{SERVICE_CREATE_PANEL_URL}/create_panel"
    map_scale = 2 ** (MAX_Z - z)
    map_size = {
        "width": (FULL_WIDTH + 2 * IMAGE_MARGIN_WIDTH) // map_scale,
        "height": (FULL_HEIGHT + 2 * IMAGE_MARGIN_HEIGHT) // map_scale,
    }
    # 上端と左端の、最大ズームレベルでの座標をオフセットにする
    up_screen_x, up_screen_y = game_tile_to_screen_coord(0, 0)
    up_map_x, up_map_y = screen_coord_to_map_tile(up_screen_x, up_screen_y, z)
    left_screen_x, left_screen_y = game_tile_to_screen_coord(0, MAP_TILES_Y)
    left_map_x, left_map_y = screen_coord_to_map_tile(left_screen_x, left_screen_y, z)
    offsets = {
        "x": left_map_x * TILE_SIZE,
        "y": up_map_y * TILE_SIZE,
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
    return output_path

