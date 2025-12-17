import requests
from airflow.decorators import task
from create_tiles.config import SERVICE_TILE_MERGE_URL

@task
def tile_merge_g(tasks: list):
    print(f"Merging tile group with {len(tasks)} tasks")
    for task in tasks:
        print(f"Merging tiles into {task['output_path']} using {len(task['tiles'])} tiles")
        for tile in task['tiles']:
            print(f" - Using tile {tile['path']} at position {tile['position']}")
        tile_merge(*task.values())
    return True

def tile_merge(tiles: list, output_path: str):
    url = f"{SERVICE_TILE_MERGE_URL}/merge"
    payload = {
        "tiles": [
            {
                "path": tile["path"],
                "position": tile["position"]
            } for tile in tiles
        ],
        "output_path": output_path
    }
    response = requests.post(url, json=payload)
    print(f"status code: {response.status_code}")
    print(f"response text: {response.text}")
    print("payload:", payload)
    response.raise_for_status()
    data = response.json()
    saved_path = data["output_path"]
    print(f"Merged tile saved at: {saved_path}")
    return saved_path
