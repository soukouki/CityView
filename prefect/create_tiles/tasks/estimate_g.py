import requests
from prefect import task
from create_tiles.config import SERVICE_ESTIMATE_URL, BACKEND_INTERNAL_URL
from create_tiles.utils import game_tile_to_screen_lefttop_coord, parse_xy_str, log
from create_tiles.flow_params import CreateTilesParams

@task(tags=["estimate"], retries=5, retry_delay_seconds=20)
def estimate_g(params: CreateTilesParams, group: list, capture_results: list, estimate_results: list):
    # どんなデータが来るか確認するためのデバッグ出力
    log("Estimating group")
    log(f"Group has {len(group)} areas")
    for area in group:
        log(f"  x:{area['x']}, y:{area['y']}")
        for comp in area['compare']:
            log(f"    compare x:{comp['x']}, y:{comp['y']}")
    log(f"Received {len(capture_results)} capture results groups")
    for capture_result in capture_results:
        log(" Capture result:")
        for xy_str, capture_dict in capture_result.items():
            x, y = parse_xy_str(xy_str)
            log(f"  coords: ({x}, {y}), capture_dict: {capture_dict}")
    log(f"Received {len(estimate_results)} estimate results groups")
    for estimate_result in estimate_results:
        log(" Estimate result:")
        for xy_str, coords in estimate_result.items():
            x, y = parse_xy_str(xy_str)
            log(f"  coords: ({x}, {y}), estimated coords: ({coords['x']}, {coords['y']})")

    # capture_resultsとestimate_resultsを辞書に変換しておく
    capture_multi_dict = {}
    for capture_result in capture_results:
        for xy_str, capture_dict in capture_result.items():
            x, y = parse_xy_str(xy_str)
            capture_multi_dict[(x, y)] = capture_dict
    estimate_dict = {}
    for estimate_result in estimate_results:
        for xy_str, coords in estimate_result.items():
            x, y = parse_xy_str(xy_str)
            estimate_dict[(x, y)] = coords

    estimated_results = {} # こちらのkeyは "x{X}_y{Y}" の形式にする(XComのため)
    for area in group:
        log(f"Estimating coords for x:{area['x']}, y:{area['y']}")
        capture_dict = capture_multi_dict[(area['x'], area['y'])]
        hint_coord = game_tile_to_screen_lefttop_coord(params, area['x'], area['y'])
        adjustment_images = []
        for comp in area['compare']:
            adj_image_path = capture_multi_dict[(comp['x'], comp['y'])]['path']
            adj_coords = estimate_dict[(comp['x'], comp['y'])]
            adjustment_images.append({
                "image_path": adj_image_path,
                "coords": adj_coords,
            })
            log(f"  Using adjacent image {adj_image_path} at offset ({adj_coords['x']}, {adj_coords['y']})")
        estimated_coords = estimate(
            params=params,
            image_path=capture_dict['path'],
            adjacent_images=adjustment_images,
            hint_x=hint_coord[0],
            hint_y=hint_coord[1]
        )
        register_estimated_coords(
            screenshot_id=capture_dict['screenshot_id'],
            estimated_x=estimated_coords['x'],
            estimated_y=estimated_coords['y'],
        )
        estimated_results[f"x{area['x']}_y{area['y']}"] = estimated_coords
        estimate_dict[(area['x'], area['y'])] = estimated_coords

    return estimated_results

def estimate(params: CreateTilesParams, image_path: str, adjacent_images: list, hint_x: int, hint_y: int):
    url = f"{SERVICE_ESTIMATE_URL}/estimate"
    adjustment_images_info = [
        {
            "image_path": adj["image_path"],
            "x": adj["coords"]["x"],
            "y": adj["coords"]["y"]
        }
        for adj in adjacent_images
    ]
    payload = {
        "image_path": image_path,
        "adjacent_images": adjustment_images_info,
        "hint_x": hint_x,
        "hint_y": hint_y,
        "margin_width": params.capture.margin_width,
        "margin_height": params.capture.margin_height,
        "effective_width": params.capture.effective_width,
        "effective_height": params.capture.effective_height,
    }
    response = requests.post(url, json=payload)
    log(f"status code: {response.status_code}")
    log(f"response text: {response.text}")
    log("payload:", payload)
    response.raise_for_status()
    data = response.json()
    estimated_x = data["estimated_x"]
    estimated_y = data["estimated_y"]
    log(f"Estimated coords: ({estimated_x}, {estimated_y})")
    return {"x": estimated_x, "y": estimated_y}

def register_estimated_coords(screenshot_id: str, estimated_x: int, estimated_y: int):
    url = f"{BACKEND_INTERNAL_URL}/api/screenshots/{screenshot_id}"
    payload = {
        "estimated_screen_x": estimated_x,
        "estimated_screen_y": estimated_y,
    }
    response = requests.put(url, json=payload)
    log(f"status code: {response.status_code}")
    log(f"response text: {response.text}")
    log("payload:", payload)
    response.raise_for_status()
    data = response.json() # {"status": "ok"} を想定
    return data
