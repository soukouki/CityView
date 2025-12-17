import requests
from airflow.decorators import task
from create_tiles.config import SERVICE_CAPTURE_URL

@task
def capture(save_data_name: str, x: int, y: int):
    print(f"Capturing area {save_data_name} at ({x}, {y})")

    url = f"{SERVICE_CAPTURE_URL}/capture"
    payload = {
        "save_data_name": save_data_name,
        "x": x,
        "y": y
    }
    response = requests.post(url, json=payload)
    print(f"status code: {response.status_code}")
    print(f"response text: {response.text}")
    print("payload:", payload)
    response.raise_for_status()
    data = response.json()
    image_path = data["image_path"]
    print(f"Captured image path: {image_path}")
    return image_path
