import requests
from airflow.decorators import task
from create_tiles.config import SERVICE_TILE_COMPRESS_URL

@task
def tile_compress_g(tasks: list):
    print(f"Compressing tile group with {len(tasks)} tasks")
    for task in tasks:
        print(f"Compressing tile ({task['z']}, {task['x']}, {task['y']})")
        tile_compress(*task.values())
    return True

def tile_compress(z: int, x: int, y: int):
    url = f"{SERVICE_TILE_COMPRESS_URL}/compress"
    payload = {
        "z": z,
        "x": x,
        "y": y,
    }
    response = requests.post(url, json=payload)
    print(f"status code: {response.status_code}")
    print(f"response text: {response.text}")
    print("payload:", payload)
    response.raise_for_status()
    # 空のレスポンスを想定
    print(f"Tile compressed at: z={z}, x={x}, y={y}")
    return True
