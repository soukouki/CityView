import requests
from airflow.decorators import task
from create_tiles.config import SERVICE_CAPTURE_URL, STORAGE_URL

@task
def capture_g(tasks: list):
    # raise NotImplementedError("debugging") # すべてのタスクを失敗させたいときに使う
    print(f"Capturing group with {len(tasks)} tasks")
    captured_results = {}
    for task in tasks:
        print(f"Capturing area {task['save_data_name']} at ({task['x']}, {task['y']}) to {task['output_path']}")
        # 撮影はあまりにも時間がかかるので、すでにストレージに存在する場合はスキップする
        if check_exists(task['output_path']):
            print(f"  Output already exists at {task['output_path']}, skipping capture.")
            captured_results[f"x{task['x']}_y{task['y']}"] = task['output_path']
            continue
        output_path = capture(*task.values())
        captured_results[f"x{task['x']}_y{task['y']}"] = output_path
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
