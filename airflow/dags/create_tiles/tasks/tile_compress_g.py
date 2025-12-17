from airflow.decorators import task

@task
def tile_compress_g(tasks: list):
    print(f"Compressing tile group with {len(tasks)} tasks")
    for task in tasks:
        print(f"Compressing tile at {task['input_path']} into {task['output_path']}")
    return True
