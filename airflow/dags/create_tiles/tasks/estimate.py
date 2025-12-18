import requests
from airflow.decorators import task
from create_tiles.config import SERVICE_ESTIMATE_URL

@task
def estimate(image_path: str, adjacent_images: list, hint_x: int, hint_y: int):
    print(f"Estimating coords for {image_path} with hints ({hint_x}, {hint_y})")
    for adj in adjacent_images:
        print(f"Using adjacent image {adj['image_path']} at offset ({adj['coords']['x']}, {adj['coords']['y']})")
    
    adjustment_images_info = [
        {
            "image_path": adj["image_path"],
            "x": adj["coords"]["x"],
            "y": adj["coords"]["y"]
        }
        for adj in adjacent_images
    ]

    url = f"{SERVICE_ESTIMATE_URL}/estimate"
    payload = {
        "image_path": image_path,
        "adjacent_images": adjustment_images_info,
        "hint_x": hint_x,
        "hint_y": hint_y
    }
    response = requests.post(url, json=payload)
    print(f"status code: {response.status_code}")
    print(f"response text: {response.text}")
    print("payload:", payload)
    response.raise_for_status()
    data = response.json()
    estimated_x = data["estimated_x"]
    estimated_y = data["estimated_y"]
    print(f"Estimated coords: ({estimated_x}, {estimated_y})")
    return {"x": estimated_x, "y": estimated_y}
