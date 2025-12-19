import requests
from airflow.decorators import task
from create_tiles.config import SERVICE_CAPTURE_URL

@task
def capture(save_data_name: str, x: int, y: int, output_path: str):
    print(f"Capturing area {save_data_name} at ({x}, {y})")

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
