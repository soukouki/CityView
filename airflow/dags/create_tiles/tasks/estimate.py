from airflow.decorators import task

@task
def estimate(image_path: str, adjacent_images: list, hint_x: int, hint_y: int):
    print(f"Estimating coords for {image_path} with hints ({hint_x}, {hint_y})")
    for adj in adjacent_images:
        print(f"Using adjacent image {adj['image_path']} at offset ({adj['x']}, {adj['y']})")
    return {"x": hint_x + 1, "y": hint_y + 1}
