import requests
from airflow.operators.python import get_current_context
from airflow.decorators import task
from create_tiles.config import SERVICE_CAPTURE_URL, STORAGE_URL

@task
def capture_g(tasks: list):
    # raise NotImplementedError("debugging") # すべてのタスクを失敗させたいときに使う
    save_data_name = get_current_context()['params']['save_data_name']
    print(f"Capturing group with {len(tasks)} tasks")
    captured_results = {}
    for task in tasks:
        x = task['x']
        y = task['y']
        print(f"Capturing area {save_data_name} at ({x}, {y})")
        output_path = f"/images/screenshots/{save_data_name}/x{x}_y{y}.png"
        # 撮影はあまりにも時間がかかるので、すでにストレージに存在する場合はスキップする
        if check_exists(output_path):
            print(f"  Output already exists at {output_path}, skipping capture.")
            captured_results[f"x{x}_y{y}"] = output_path
            continue
        capture(
            save_data_name=save_data_name,
            x=x,
            y=y,
            output_path=output_path,
        )
        captured_results[f"x{x}_y{y}"] = output_path
    return captured_results

# ストレージにすでに存在するかを確認する
def check_exists(output_path: str) -> bool:
    url = f"{STORAGE_URL}{output_path}"
    response = requests.head(url)
    return response.status_code == 200

def capture(save_data_name: str, x: int, y: int, output_path: str):
    url = f"{SERVICE_CAPTURE_URL}/capture"
    payload = {
        "save_data_name": save_data_name,
        "x": x,
        "y": y,
        "output_path": output_path,
    }
    response = requests.post(url, json=payload)
    print(f"status code: {response.status_code}")
    print(f"response text: {response.text}")
    print("payload:", payload)
    response.raise_for_status()
    data = response.json() # {"status": "success"} を想定
    return output_path
