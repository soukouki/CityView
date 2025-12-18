import requests
from airflow.decorators import task
from create_tiles.config import SERVICE_TILE_CUT_URL, TILE_SIZE, MAX_Z
from create_tiles.utils import map_tile_to_screen_coord

@task
def tile_cut_g(tasks: list):
    print(f"Processing tile cut group with {len(tasks)} tasks")
    for task in tasks:
        print(f"Cutting tile at ({task['x']}, {task['y']}) into {task['output_path']} using {len(task['images'])} images")
        for img in task['images']:
            print(f" - Using image {img['path']} with coords {img['coords']}")
        tile_cut(*task.values())
    return True

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
