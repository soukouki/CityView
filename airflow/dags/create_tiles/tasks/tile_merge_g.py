import requests
from airflow.decorators import task
from create_tiles.config import SERVICE_TILE_MERGE_URL, TILE_GROUP_SIZE
from create_tiles.utils import parse_zxy_str

@task
def tile_merge_g(save_data_name: str, z: int, gx: int, gy: int, child_results: list):
    print(f"Processing tile merge group at z={z}, ({gx}, {gy}) with {len(child_results)} child results")
    
    # child_resultsは辞書のリスト。1つの辞書にマージ
    child_tiles = {}
    for result in child_results:
        child_tiles.update(result)
    
    print(f"Total child tiles: {len(child_tiles)}")
    for key, path in child_tiles.items():
        print(f"  Child tile: {key} -> {path}")

    merged_tiles = {}
    for tx in range(gx, gx + TILE_GROUP_SIZE):
        for ty in range(gy, gy + TILE_GROUP_SIZE):
            # 子タイルのキーを生成
            child_keys = [
                f"z{z+1}_x{tx*2}_y{ty*2}",
                f"z{z+1}_x{tx*2+1}_y{ty*2}",
                f"z{z+1}_x{tx*2}_y{ty*2+1}",
                f"z{z+1}_x{tx*2+1}_y{ty*2+1}",
            ]
            positions = ["top-left", "top-right", "bottom-left", "bottom-right"]
            
            # 存在する子タイルを収集
            tiles_to_merge = []
            for i, key in enumerate(child_keys):
                if key in child_tiles:
                    tiles_to_merge.append({
                        "path": child_tiles[key],
                        "position": positions[i],
                    })
            
            # 子タイルが1つ以上あればマージ
            if tiles_to_merge:
                output_path = f"/images/rawtiles/{save_data_name}/{z}/{tx}/{ty}.png"
                tile_merge(tiles_to_merge, output_path)
                merged_tiles[f"z{z}_x{tx}_y{ty}"] = output_path

    print(f"Total merged tiles: {len(merged_tiles)}")
    return merged_tiles

def tile_merge(tiles: list, output_path: str):
    url = f"{SERVICE_TILE_MERGE_URL}/merge"
    payload = {
        "tiles": [
            {
                "path": tile["path"],
                "position": tile["position"]
            } for tile in tiles
        ],
        "output_path": output_path
    }
    response = requests.post(url, json=payload)
    print(f"status code: {response.status_code}")
    print(f"response text: {response.text}")
    print("payload:", payload)
    response.raise_for_status()
    data = response.json()
    saved_path = data["output_path"]
    print(f"Merged tile saved at: {saved_path}")
    return saved_path
