from .config import (
    ADJUSTED_PAKSIZE,
    IMAGE_MARGIN_WIDTH,
    IMAGE_MARGIN_HEIGHT,
    ENABLE_WIDTH,
    ENABLE_HEIGHT,
    MAP_TILES_Y,
    TILE_SIZE,
    MAX_Z,
)

# ゲーム内タイル座標系とスクショ座標系の変換式
def game_tile_to_screen_coord(tile_x: int, tile_y: int) -> tuple[int, int]:
    screen_x = (ADJUSTED_PAKSIZE // 2) * (tile_x - tile_y) + (ENABLE_WIDTH // 2) + IMAGE_MARGIN_WIDTH
    screen_y = (ADJUSTED_PAKSIZE // 4) * (tile_x + tile_y) + (ENABLE_HEIGHT // 2) + IMAGE_MARGIN_HEIGHT
    return screen_x, screen_y

# ゲーム内タイル座標系とスクショ座標系の変換式で、スクショの糊代部分も含めた左上座標を求める関数
def game_tile_to_screen_lefttop_coord(tile_x: int, tile_y: int) -> tuple[int, int]:
    screen_x = (ADJUSTED_PAKSIZE // 2) * (tile_x - tile_y)
    screen_y = (ADJUSTED_PAKSIZE // 4) * (tile_x + tile_y)
    return screen_x, screen_y

# スクショ座標系からゲーム内タイル座標系への変換式
def screen_coord_to_game_tile(screen_x: int, screen_y: int) -> tuple[int, int]:
    X = screen_x - IMAGE_MARGIN_WIDTH
    Y = screen_y - IMAGE_MARGIN_HEIGHT
    tile_x = (X + 2 * Y) // (ADJUSTED_PAKSIZE)
    tile_y = (2 * Y - X) // (ADJUSTED_PAKSIZE)
    return tile_x, tile_y

# スクショ座標系と地図タイル座標系の変換式
def screen_coord_to_map_tile(screen_x: int, screen_y: int, z: int) -> tuple[int, int]:
    scale = 2 ** (MAX_Z - z)
    tile_x = (screen_x + ADJUSTED_PAKSIZE * MAP_TILES_Y + IMAGE_MARGIN_WIDTH * 2) // (TILE_SIZE * scale)
    tile_y = screen_y // (TILE_SIZE * scale)
    return tile_x, tile_y

# 地図タイル座標系とスクショ座標系の変換式
# 左上隅の座標を返す
def map_tile_to_screen_coord(tile_x: int, tile_y: int, z: int) -> tuple[int, int]:
    scale = 2 ** (MAX_Z - z)
    screen_x_min = tile_x * TILE_SIZE * scale - ADJUSTED_PAKSIZE * MAP_TILES_Y - IMAGE_MARGIN_WIDTH * 2
    screen_y_min = tile_y * TILE_SIZE * scale
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
