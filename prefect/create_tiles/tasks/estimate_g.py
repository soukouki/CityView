import requests
from create_tiles.custom_task import priority_task
from create_tiles.config import SERVICE_ESTIMATE_URL
from create_tiles.utils import game_tile_to_screen_lefttop_coord, parse_xy_str

@priority_task(task_type="estimate", retries=3, retry_delay_seconds=300)
def estimate_g(group: list, capture_results: list, estimate_results: list):
    # どんなデータが来るか確認するためのデバッグ出力
    print("Estimating group")
    print(f"Group has {len(group)} areas")
    for area in group:
        print(f"  x:{area['x']}, y:{area['y']}, priority:{area['priority']}")
        for comp in area['compare']:
            print(f"    compare x:{comp['x']}, y:{comp['y']}")
    print(f"Received {len(capture_results)} capture results groups")
    for capture_result in capture_results:
        print(" Capture result:")
        for xy_str, image_path in capture_result.items():
            x, y = parse_xy_str(xy_str)
            print(f"  coords: ({x}, {y}), image_path: {image_path}")
    print(f"Received {len(estimate_results)} estimate results groups")
    for estimate_result in estimate_results:
        print(" Estimate result:")
        for xy_str, coords in estimate_result.items():
            x, y = parse_xy_str(xy_str)
            print(f"  coords: ({x}, {y}), estimated coords: ({coords['x']}, {coords['y']})")

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

    estimated_results = {} # こちらのkeyは "x{X}_y{Y}" の形式にする(XComのため)
    for area in group:
        print(f"Estimating coords for x:{area['x']}, y:{area['y']}")
        image_path = capture_dict[(area['x'], area['y'])]
        hint_coord = game_tile_to_screen_lefttop_coord(area['x'], area['y'])
        adjustment_images = []
        for comp in area['compare']:
            adj_image_path = capture_dict[(comp['x'], comp['y'])]
            adj_coords = estimate_dict[(comp['x'], comp['y'])]
            adjustment_images.append({
                "image_path": adj_image_path,
                "coords": adj_coords,
            })
            print(f"  Using adjacent image {adj_image_path} at offset ({adj_coords['x']}, {adj_coords['y']})")
        estimated_coords = estimate(
            image_path=image_path,
            adjacent_images=adjustment_images,
            hint_x=hint_coord[0],
            hint_y=hint_coord[1]
        )
        estimated_results[f"x{area['x']}_y{area['y']}"] = estimated_coords
        estimate_dict[(area['x'], area['y'])] = estimated_coords

    return estimated_results

def estimate(image_path: str, adjacent_images: list, hint_x: int, hint_y: int):
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
        "hint_y": hint_y
    }
    response = requests.post(url, json=payload)
    print(f"status code: {response.status_code}")
    print(f"response text: {response.text}")
    print("payload:", payload)
    response.raise_for_status()
    data = response.json()
    estimated_x = data["estimated_x"]
    estimated_y = data["estimated_y"]
    print(f"Estimated coords: ({estimated_x}, {estimated_y})")
    return {"x": estimated_x, "y": estimated_y}
