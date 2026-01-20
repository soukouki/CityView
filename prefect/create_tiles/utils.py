import sys
import requests
from create_tiles.flow_params import CreateTilesParams
from create_tiles.config import STORAGE_URL

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
def check_exists(output_path: str) -> bool:
    url = f"{STORAGE_URL}{output_path}"
    response = requests.head(url)
    return response.status_code == 200

def log(*args):
    print(*args, file=sys.stdout, flush=True)

# 今はparmasの追加で動かなくなってしまったコードだけれど、何かに使えそうなのでとりあえず残しておく
# if __name__ == "__main__":
#     print("原点")
#     sx1, sy1 = game_tile_to_screen_coord(0, 0)
#     print(f"ゲーム内タイル座標 (0,0) -> スクショ座標 ({sx1},{sy1})")
#     sx2, sy2 = game_tile_to_screen_lefttop_coord(0, 0)
#     print(f"ゲーム内タイル座標 (0,0) -> スクショ左上座標 ({sx2},{sy2})")
#     assert 0 == sx2, f"Expected: 0, Actual: {sx2}"
#     assert 0 == sy2, f"Expected: 0, Actual: {sy2}"
#     gx1, gy1 = screen_coord_to_game_tile(sx1, sy1)
#     print(f"スクショ座標 ({sx1},{sy1}) -> ゲーム内タイル座標 ({gx1},{gy1})")
#     assert 0 == gx1, f"Expected: 0, Actual: {gx1}"
#     assert 0 == gy1, f"Expected: 0, Actual: {gy1}"
#     mx1, my1 = screen_coord_to_map_tile(sx1, sy1, 10)
#     print(f"スクショ座標 ({sx1},{sy1}) -> 地図タイル座標 (10,{mx1},{my1})")
#     sx3, sy3 = map_tile_to_screen_coord(mx1, my1, 10)
#     print(f"地図タイル座標 (10,{mx1},{my1}) -> スクショ座標 ({sx3},{sy3})")
#     gx2, gy2 = screen_coord_to_game_tile(sx3, sy3)
#     print(f"スクショ座標 ({sx3},{sy3}) -> ゲーム内タイル座標 ({gx2},{gy2})") # 十分に(0,0)付近であればOK

#     print("\n左端")
#     sx4, sy4 = game_tile_to_screen_lefttop_coord(0, MAP_TILES_Y)
#     print(f"ゲーム内タイル座標 (0,{MAP_TILES_Y}) -> スクショ左上座標 ({sx4},{sy4})")
#     mx2, my2 = screen_coord_to_map_tile(sx4, sy4, 10)
#     print(f"スクショ座標 ({sx4},{sy4}) -> 地図タイル座標 (10,{mx2},{my2})") # xは0付近になればOK
#     sx5, sy5 = map_tile_to_screen_coord(mx2, my2, 10)
#     print(f"地図タイル座標 (10,{mx2},{my2}) -> スクショ座標 ({sx5},{sy5})")
#     gx3, gy3 = screen_coord_to_game_tile(sx5, sy5)
#     print(f"スクショ座標 ({sx5},{sy5}) -> ゲーム内タイル座標 ({gx3},{gy3})") # 十分に(0,MAP_TILES_Y)付近であればOK

#     print("\n右端")
#     sx6, sy6 = game_tile_to_screen_lefttop_coord(MAP_TILES_X, 0)
#     print(f"ゲーム内タイル座標 ({MAP_TILES_X},0) -> スクショ左上座標 ({sx6},{sy6})")
#     mx3, my3 = screen_coord_to_map_tile(sx6, sy6, 10)
#     print(f"スクショ座標 ({sx6},{sy6}) -> 地図タイル座標 (10,{mx3},{my3})")
#     sx7, sy7 = map_tile_to_screen_coord(mx3, my3, 10)
#     print(f"地図タイル座標 (10,{mx3},{my3}) -> スクショ座標 ({sx7},{sy7})")
#     gx4, gy4 = screen_coord_to_game_tile(sx7, sy7)
#     print(f"スクショ座標 ({sx7},{sy7}) -> ゲーム内タイル座標 ({gx4},{gy4})") # 十分に(MAP_TILES_X,0)付近であればOK
