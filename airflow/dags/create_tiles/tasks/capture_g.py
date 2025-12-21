import requests
from airflow.operators.python import get_current_context
from airflow.decorators import task
from create_tiles.config import SERVICE_CAPTURE_URL, ZOOM_LEVEL
from create_tiles.utils import check_exists

@task
def capture_g(tasks: list):
    # raise NotImplementedError("debugging") # すべてのタスクを失敗させたいときに使う
    save_data_name = get_current_context()['params']['save_data_name']
    print(f"Capturing group with {len(tasks)} tasks")
    for task in tasks:
        print(f"  Task: x={task['x']}, y={task['y']}")
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

def capture(save_data_name: str, x: int, y: int, output_path: str):
    url = f"{SERVICE_CAPTURE_URL}/capture"
    payload = {
        "save_data_name": save_data_name,
        "x": x,
        "y": y,
        "output_path": output_path,
        "zoom_level": ZOOM_LEVEL, # 本当はDAGのparamsから取れるようにしたいが、そのためにはAirflow以外へ移行する必要があり、面倒なので一旦雑に対応
    }
    response = requests.post(url, json=payload)
    print(f"status code: {response.status_code}")
    print(f"response text: {response.text}")
    print("payload:", payload)
    response.raise_for_status()
    data = response.json() # {"status": "success"} を想定
    return output_path
