from airflow.decorators import task

@task
def tile_merge_g(tasks: list):
    print(f"Merging tile group with {len(tasks)} tasks")
    for task in tasks:
        print(f"Merging tiles into {task['output_path']} using {len(task['tiles'])} tiles")
        for tile in task['tiles']:
            print(f" - Using tile {tile['path']} at position {tile['position']}")
    return True
