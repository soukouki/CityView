import requests
from prefect import task
from create_tiles.config import SERVICE_CAPTURE_URL, BACKEND_INTERNAL_URL
from create_tiles.utils import check_exists, log, get_session, close_session
from create_tiles.flow_params import CreateTilesParams

@task(tags=["all", "capture"], retries=5, retry_delay_seconds=20)
def capture_g(params: CreateTilesParams, tasks: list):
    session = get_session()
    try:
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
            if check_exists(output_path, session=session):
                log(f"  Output already exists at {output_path}, checking if registered...")
                # 既存のスクリーンショット情報を取得
                screenshot_info = get_screenshot_by_tile(params.map_id, x, y, session=session)
                
                if screenshot_info:
                    # 既に登録済み
                    screenshot_id = screenshot_info['id']
                    log(f"  Screenshot already registered with ID: {screenshot_id}")
                else:
                    # ファイルは存在するが未登録の場合、登録する
                    log(f"  File exists but not registered. Registering...")
                    screenshot_id = register_screenshot(
                        params=params,
                        x=x,
                        y=y,
                        screenshot_path=output_path,
                        session=session,
                    )
                
                captured_results[f"x{x}_y{y}"] = {
                    "path": output_path,
                    "screenshot_id": screenshot_id,
                }
                continue
            
            # 新規キャプチャ
            capture(
                params=params,
                x=x,
                y=y,
                output_path=output_path,
                session=session,
            )
            screenshot_id = register_screenshot(
                params=params,
                x=x,
                y=y,
                screenshot_path=output_path,
                session=session,
            )
            captured_results[f"x{x}_y{y}"] = {
                "path": output_path,
                "screenshot_id": screenshot_id,
            }
        return captured_results
    finally:
        close_session(session)

def capture(params: CreateTilesParams, x: int, y: int, output_path: str, session: requests.Session):
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
    response = session.post(url, json=payload)
    log(f"status code: {response.status_code}")
    log(f"response text: {response.text}")
    log("payload:", payload)
    response.raise_for_status()
    data = response.json() # {"status": "success"} を想定
    return output_path

def get_screenshot_by_tile(map_id: int, x: int, y: int, session: requests.Session):
    """ゲームタイル座標から既存のスクリーンショット情報を取得"""
    url = f"{BACKEND_INTERNAL_URL}/api/screenshots/by-tile"
    payload = {
        "map_id": map_id,
        "x": x,
        "y": y,
    }
    try:
        response = session.get(url, json=payload)
        if response.status_code == 404:
            log(f"Screenshot not found for map_id={map_id}, x={x}, y={y}")
            return None
        response.raise_for_status()
        data = response.json() # nullable
        return data
    except requests.RequestException as e:
        log(f"Error fetching screenshot by tile: {e}")
        return None

def register_screenshot(params: CreateTilesParams, x: int, y: int, screenshot_path: str, session: requests.Session):
    url = f"{BACKEND_INTERNAL_URL}/api/screenshots"
    payload = {
        "map_id": params.map_id,
        "path": screenshot_path,
        "game_tile": {
            "x": x,
            "y": y
        }
    }
    response = session.post(url, json=payload)
    log(f"Register screenshot status code: {response.status_code}")
    log(f"Register screenshot response text: {response.text}")
    log("Register screenshot payload:", payload)
    response.raise_for_status()
    data = response.json() # {"screenshot_id": "string"} を想定
    return data['screenshot_id']
