import requests
from airflow.decorators import task
from airflow.operators.python import get_current_context
from create_tiles.config import SERVICE_TILE_COMPRESS_URL, TILE_GROUP_SIZE
from create_tiles.utils import parse_zxy_str

@task
def tile_compress_g(z: int, gx: int, gy: int, tile_results: dict, quality: int):
    save_data_name = get_current_context()['params']['save_data_name']
    print(f"Processing tile compress group at z={z}, ({gx}, {gy}) with {len(tile_results)} tiles")
    
    for key, input_path in tile_results.items():
        print(f"  Compressing tile: {key} -> {input_path}")
        # 出力パスを生成（rawtiles -> tiles, .png -> .avif）
        output_path = input_path.replace("/rawtiles/", "/tiles/").replace(".png", ".avif")
        tile_compress(input_path, output_path, quality)
    
    print(f"Compression complete for {len(tile_results)} tiles")
    return True

def tile_compress(input_path: str, output_path: str, quality: int):
    url = f"{SERVICE_TILE_COMPRESS_URL}/compress"
    payload = {
        "input_path": input_path,
        "output_path": output_path,
        "quality": quality,
    }
    response = requests.post(url, json=payload)
    print(f"status code: {response.status_code}")
    print(f"response text: {response.text}")
    print("payload:", payload)
    response.raise_for_status()
    print(f"Tile compressed successfully: {output_path}")
    return True
