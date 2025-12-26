import requests
from create_tiles.priority_task import priority_task
from create_tiles.config import SERVICE_CAPTURE_URL, ZOOM_LEVEL, SAVE_DATA_NAME
from create_tiles.utils import check_exists, log

@priority_task(task_type="capture", retries=3, retry_delay_seconds=300)
def capture_g(tasks: list):
    # raise NotImplementedError("debugging") # すべてのタスクを失敗させたいときに使う
    log(f"Capturing group with {len(tasks)} tasks")
    for task in tasks:
        log(f"  Task: x={task['x']}, y={task['y']}")
    captured_results = {}
    for task in tasks:
        x = task['x']
        y = task['y']
        log(f"Capturing area at ({x}, {y})")
        output_path = f"/images/screenshots/{SAVE_DATA_NAME}/x{x}_y{y}.png"
        # 撮影はあまりにも時間がかかるので、すでにストレージに存在する場合はスキップする
        if check_exists(output_path):
            log(f"  Output already exists at {output_path}, skipping capture.")
            captured_results[f"x{x}_y{y}"] = output_path
            continue
        capture(
            x=x,
            y=y,
            output_path=output_path,
        )
        captured_results[f"x{x}_y{y}"] = output_path
    return captured_results

def capture(x: int, y: int, output_path: str):
    url = f"{SERVICE_CAPTURE_URL}/capture"
    payload = {
        "save_data_name": SAVE_DATA_NAME,
        "x": x,
        "y": y,
        "output_path": output_path,
        "zoom_level": ZOOM_LEVEL, # 本当はDAGのparamsから取れるようにしたいが、そのためにはAirflow以外へ移行する必要があり、面倒なので一旦雑に対応
    }
    response = requests.post(url, json=payload)
    log(f"status code: {response.status_code}")
    log(f"response text: {response.text}")
    log("payload:", payload)
    response.raise_for_status()
    data = response.json() # {"status": "success"} を想定
    return output_path
