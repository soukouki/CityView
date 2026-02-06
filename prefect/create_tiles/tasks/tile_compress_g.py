import requests
from prefect import task
from create_tiles.config import SERVICE_TILE_COMPRESS_URL
from create_tiles.utils import parse_zxy_str, check_exists, log, get_session, close_session
from create_tiles.flow_params import CreateTilesParams

@task(tags=["all", "tile-compress"], retries=5, retry_delay_seconds=20)
def tile_compress_g(params: CreateTilesParams, z: int, gx: int, gy: int, tile_results: dict, quality: str):
    session = get_session()
    try:
        log(f"Processing tile compress group at z={z}, ({gx}, {gy}) with {len(tile_results)} tiles")
        
        for key, input_path in tile_results.items():
            log(f"  Compressing tile: {key} -> {input_path}")
            # 出力パスを生成（rawtiles -> tiles, .png -> .avif）
            output_path = input_path.replace("/rawtiles/", "/tiles/").replace(".png", ".avif")
            if check_exists(output_path, session=session):
                log(f"  Output already exists at {output_path}, skipping compression.")
                continue
            tile_compress(
                params,
                input_path,
                output_path,
                quality,
                session,
            )
        
        log(f"Compression complete for {len(tile_results)} tiles")
        return True
    finally:
        close_session(session)

def tile_compress(params: CreateTilesParams, input_path: str, output_path: str, quality: str, session: requests.Session):
    url = f"{SERVICE_TILE_COMPRESS_URL}/compress"
    payload = {
        "input_path": input_path,
        "output_path": output_path,
        "quality": quality,
    }
    response = session.post(url, json=payload)
    log(f"status code: {response.status_code}")
    log(f"response text: {response.text}")
    log("payload:", payload)
    response.raise_for_status()
    log(f"Tile compressed successfully: {output_path}")
    return True
