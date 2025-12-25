import requests
from create_tiles.priority_task import priority_task
from create_tiles.config import SERVICE_CREATE_PANEL_URL, FULL_WIDTH, FULL_HEIGHT, MAX_Z
from create_tiles.utils import check_exists, parse_zxy_str

@priority_task(task_type="panel", retries=3, retry_delay_seconds=300)
def create_panel(z: int, resolution: dict, tile_results: list):
    print(f"Creating panel at zoom level {z} with resolution {resolution}")
    print(f"Received {len(tile_results)} tile groups")
    for tile_result in tile_results:
        print(" Tile result:")
        for key, path in tile_result.items():
            print(f"  - key:{key}, path: {path}")
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
    output_path = "/images/panels/panel_{id}_x{x}_y{y}.png".format(
        id=resolution['id'],
        x=resolution['width'],
        y=resolution['height'],
    )
    if check_exists(output_path):
        print(f"  Output already exists at {output_path}, skipping panel creation.")
        return output_path
    
    url = f"{SERVICE_CREATE_PANEL_URL}/create_panel"
    map_scale = 2 ** (MAX_Z - z)
    payload = {
        "z": z,
        "tiles": tiles,
        "map_size": {"width": FULL_WIDTH // map_scale, "height": FULL_HEIGHT // map_scale},
        "resolution": {"width": resolution['width'], "height": resolution['height']},
        "output_path": output_path,
    }
    response = requests.post(url, json=payload)
    print(f"status code: {response.status_code}")
    print(f"response text: {response.text}")
    print("payload:", payload)
    response.raise_for_status()
    print(f"Panel created successfully: {output_path}")
    return output_path

