import sys
import threading
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from create_tiles.flow_params import CreateTilesParams
from create_tiles.config import STORAGE_URL

# スレッドローカルストレージ（Prefectの並列実行に対応）
_thread_local = threading.local()

def get_session():
    """
    スレッドセーフなHTTP Sessionを取得。
    同じスレッド内では同一のSessionを使い回す（TCPコネクション再利用）。
    """
    if not hasattr(_thread_local, "session"):
        session = requests.Session()
        
        # コネクションプール設定（storage, backend, capture-service への接続を最適化）
        adapter = HTTPAdapter(
            pool_connections=50,  # 同時接続数に応じて調整
            pool_maxsize=50,      # プールサイズ
            max_retries=Retry(
                total=3,
                backoff_factor=0.5,
                status_forcelist=[500, 502, 503, 504],
                allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"]
            )
        )
        
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        _thread_local.session = session
    
    return _thread_local.session

def close_session(session: requests.Session):
    session.close()

# ゲーム内タイル座標系とスクショ座標系の変換式
def game_tile_to_screen_coord(params: CreateTilesParams, tile_x: int, tile_y: int) -> tuple[int, int]:
    adjusted_paksize = params.adjusted_paksize
    screen_x = (adjusted_paksize // 2) * (tile_x - tile_y) + (params.capture.effective_width // 2) + params.capture.margin_width
    screen_y = (adjusted_paksize // 4) * (tile_x + tile_y) + (params.capture.effective_height // 2) + params.capture.margin_height
    return screen_x, screen_y

# ゲーム内タイル座標系とスクショ座標系の変換式で、スクショの糊代部分も含めた左上座標を求める関数
def game_tile_to_screen_lefttop_coord(params: CreateTilesParams, tile_x: int, tile_y: int) -> tuple[int, int]:
    adjusted_paksize = params.adjusted_paksize
    screen_x = (adjusted_paksize // 2) * (tile_x - tile_y)
    screen_y = (adjusted_paksize // 4) * (tile_x + tile_y)
    return screen_x, screen_y

# スクショ座標系からゲーム内タイル座標系への変換式
def screen_coord_to_game_tile(params: CreateTilesParams, screen_x: int, screen_y: int) -> tuple[int, int]:
    adjusted_paksize = params.adjusted_paksize
    x = screen_x - params.capture.margin_width - (params.capture.effective_width // 2)
    y = screen_y - params.capture.margin_height - (params.capture.effective_height // 2)
    tile_x = (x + 2 * y) // adjusted_paksize
    tile_y = (2 * y - x) // adjusted_paksize
    return tile_x, tile_y

# スクショ座標系と地図タイル座標系の変換式
def screen_coord_to_map_tile(params: CreateTilesParams, screen_x: int, screen_y: int, z: int) -> tuple[int, int]:
    scale = 2 ** (params.max_z - z)
    tile_x = (screen_x + params.adjusted_paksize * params.map_size.y // 2 + params.capture.margin_width * 2) // (params.tile_size * scale)
    tile_y = screen_y // (params.tile_size * scale)
    return tile_x, tile_y

# 地図タイル座標系とスクショ座標系の変換式
# 左上隅の座標を返す
def map_tile_to_screen_coord(params: CreateTilesParams, tile_x: int, tile_y: int, z: int) -> tuple[int, int]:
    scale = 2 ** (params.max_z - z)
    screen_x_min = tile_x * params.tile_size * scale - params.adjusted_paksize * params.map_size.y // 2 - params.capture.margin_width * 2
    screen_y_min = tile_y * params.tile_size * scale
    return screen_x_min, screen_y_min

# x123_y456形式の文字列を分解する
def parse_xy_str(xy_str: str) -> tuple[int, int]:
    x_str, y_str = xy_str.split('_')
    x = int(x_str[1:])
    y = int(y_str[1:])
    return x, y

# z12_x123_y456形式の文字列を分解する
def parse_zxy_str(zxy_str: str) -> tuple[int, int, int]:
    z_str, x_str, y_str = zxy_str.split('_')
    z = int(z_str[1:])
    x = int(x_str[1:])
    y = int(y_str[1:])
    return z, x, y

# ストレージにすでに存在するかを確認する
def check_exists(output_path: str, session: requests.Session) -> bool:
    url = f"{STORAGE_URL}{output_path}"
    response = session.head(url)
    return response.status_code == 200

def log(*args):
    print(*args, file=sys.stdout, flush=True)
