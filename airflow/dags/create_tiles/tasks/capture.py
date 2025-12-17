from airflow.decorators import task

@task
def capture(save_data_name: str, x: int, y: int):
    print(f"Capturing area {save_data_name} at ({x}, {y})")
    return f"/images/screenshots/{save_data_name}_x{x}_y{y}.png"
