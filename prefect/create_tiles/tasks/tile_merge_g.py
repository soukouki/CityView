import requests
from create_tiles.priority_task import priority_task
from create_tiles.config import SERVICE_TILE_MERGE_URL, TILE_GROUP_SIZE, SAVE_DATA_NAME
from create_tiles.utils import parse_zxy_str, check_exists, log

@priority_task(task_type="tile_merge", retries=3, retry_delay_seconds=300)
def tile_merge_g(z: int, gx: int, gy: int, child_results: list):
    log(f"Processing tile merge group at z={z}, ({gx}, {gy}) with {len(child_results)} child results")
    for child_result in child_results:
        log(" Child result:")
        for key, path in child_result.items():
            cz, cx, cy = parse_zxy_str(key)
            log(f"  Child tile - z:{cz}, x:{cx}, y:{cy}, path: {path}")
    
    # child_resultsは辞書のリスト。1つの辞書にマージ
    child_tiles = {}
    for result in child_results:
        child_tiles.update(result)

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
                output_path = f"/images/rawtiles/{SAVE_DATA_NAME}/{z}/{tx}/{ty}.png"
                if check_exists(output_path):
                    log(f"  Output already exists at {output_path}, skipping merge.")
                    merged_tiles[f"z{z}_x{tx}_y{ty}"] = output_path
                    continue
                tile_merge(tiles_to_merge, output_path)
                merged_tiles[f"z{z}_x{tx}_y{ty}"] = output_path

    log(f"Total merged tiles: {len(merged_tiles)}")
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
    log(f"status code: {response.status_code}")
    log(f"response text: {response.text}")
    log("payload:", payload)
    response.raise_for_status()
    data = response.json()
    saved_path = data["output_path"]
    log(f"Merged tile saved at: {saved_path}")
    return saved_path
