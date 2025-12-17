from airflow.decorators import task

@task
def tile_cut_g(tasks: list):
    print(f"Processing tile cut group with {len(tasks)} tasks")
    for task in tasks:
        print(f"Cutting tile at ({task['x']}, {task['y']}) into {task['output_path']} using {len(task['images'])} images")
        for img in task['images']:
            print(f" - Using image {img['path']} with coords {img['coords']}")
    return True
