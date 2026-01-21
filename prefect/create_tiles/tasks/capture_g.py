import requests
from prefect import task
from create_tiles.config import SERVICE_CAPTURE_URL, BACKEND_INTERNAL_URL
from create_tiles.utils import check_exists, log
from create_tiles.flow_params import CreateTilesParams

@task(tags=["capture"], retries=3, retry_delay_seconds=20)
def capture_g(params: CreateTilesParams, tasks: list):

    log(f"Capturing group with {len(tasks)} tasks")
    for task in tasks:
        log(f"  Task: x={task['x']}, y={task['y']}")
    captured_results = {}
    for task in tasks:
        x = task['x']
        y = task['y']
        log(f"Capturing area at ({x}, {y})")
        output_path = f"/images/screenshots/{params.map_id}/x{x}_y{y}.png"
        # 撮影はあまりにも時間がかかるので、すでにストレージに存在する場合はスキップする
        if check_exists(output_path):
            log(f"  Output already exists at {output_path}, skipping capture.")
            captured_results[f"x{x}_y{y}"] = output_path
            continue
        capture(
            params=params,
            x=x,
            y=y,
            output_path=output_path
        )
        screenshot_id = register_screenshot(
            params=params,
            x=x,
            y=y,
            screenshot_path=output_path,
        )
        captured_results[f"x{x}_y{y}"] = {
            "path": output_path,
            "screenshot_id": screenshot_id,
        }
    return captured_results

def capture(params: CreateTilesParams, x: int, y: int, output_path: str):
    url = f"{SERVICE_CAPTURE_URL}/capture"
    payload = {
        "folder_path": params.folder_path,
        "binary_name": params.binary_name,
        "pakset_name": params.pakset_name,
        "save_data_name": params.save_data_name,
        "zoom_level": params.zoom_level,
        "capture_redraw_wait_seconds": params.capture_redraw_wait_seconds,
        "crop_offset_x": params.capture.crop_offset_x,
        "crop_offset_y": params.capture.crop_offset_y,
        "margin_width": params.capture.margin_width,
        "margin_height": params.capture.margin_height,
        "effective_width": params.capture.effective_width,
        "effective_height": params.capture.effective_height,
        "x": x,
        "y": y,
        "output_path": output_path,
    }
    response = requests.post(url, json=payload)
    log(f"status code: {response.status_code}")
    log(f"response text: {response.text}")
    log("payload:", payload)
    response.raise_for_status()
    data = response.json() # {"status": "success"} を想定
    return output_path

def register_screenshot(params: CreateTilesParams, x: int, y: int, screenshot_path: str):
    url = f"{BACKEND_INTERNAL_URL}/api/screenshots"
    payload = {
        "map_id": params.map_id,
        "path": screenshot_path,
        "game_tile": {
            "x": x,
            "y": y
        }
    }
    response = requests.post(url, json=payload)
    log(f"Register screenshot status code: {response.status_code}")
    log(f"Register screenshot response text: {response.text}")
    log("Register screenshot payload:", payload)
    response.raise_for_status()
    data = response.json() # {"screenshot_id": "string"} を想定
    return data['screenshot_id']
