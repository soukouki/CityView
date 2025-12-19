import requests
from airflow.decorators import task
from create_tiles.config import SERVICE_TILE_CUT_URL, TILE_SIZE, MAX_Z
from create_tiles.utils import map_tile_to_screen_coord, parse_xy_str

@task
def tile_cut_g(gx: int, gy: int, tasks: list, capture_results: list, estimate_results: list):
    print(f"Processing tile cut group at ({gx}, {gy}) with {len(tasks)} tasks")
    for task in tasks:
        print(f"Cutting tile at ({task['x']}, {task['y']}) into {task['output_path']} using {len(task['images'])} images")
        for img in task['images']:
            print(f"  x{img['x']}, y{img['y']}") # このデータにはpathなどの情報は含まれず、座標のみしかない
    for capture_result in capture_results:
        for xy_str, image_path in capture_result.items():
            x, y = parse_xy_str(xy_str)
            print(f"  Capture result - coords: ({x}, {y}), image_path: {image_path}")
    for estimate_result in estimate_results:
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

    for task in tasks:
        images = [
            {
                "path": capture_dict[(img['x'], img['y'])],
                "coords": estimate_dict[(img['x'], img['y'])],
            } for img in task['images']
        ]
        tile_cut(
            x=task['x'],
            y=task['y'],
            images=images,
            output_path=task['output_path']
        )

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
