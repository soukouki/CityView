from .config import (
    IMAGE_MARGIN_WIDTH,
    IMAGE_MARGIN_HEIGHT,
    ENABLE_WIDTH,
    ENABLE_HEIGHT,
    MAP_TILES_Y,
    TILE_SIZE,
)

# ゲーム内タイル座標系とスクショ座標系の変換式
def game_tile_to_screen_coord(tile_x: int, tile_y: int) -> tuple[int, int]:
    screen_x = 256 * (tile_x - tile_y) + (ENABLE_WIDTH // 2) + IMAGE_MARGIN_WIDTH
    screen_y = 128 * (tile_x + tile_y) + (ENABLE_HEIGHT // 2) + IMAGE_MARGIN_HEIGHT
    return screen_x, screen_y

def screen_coord_to_game_tile(screen_x: int, screen_y: int) -> tuple[int, int]:
    X = screen_x - IMAGE_MARGIN_WIDTH
    Y = screen_y - IMAGE_MARGIN_HEIGHT
    tile_x = (X + 2 * Y) // 512
    tile_y = (2 * Y - X) // 512
    return tile_x, tile_y

def screen_coord_to_map_tile(screen_x: int, screen_y: int, z: int, z_max: int, y_max: int) -> tuple[int, int]:
    scale = 2 ** (z_max - z)
    tile_x = (screen_x + 256 * y_max + IMAGE_MARGIN_WIDTH * 2) // (512 * scale)
    tile_y = screen_y // (512 * scale)
    return tile_x, tile_y

def map_tile_to_screen_coord(tile_x: int, tile_y: int, z: int, z_max: int, y_max: int) -> tuple[int, int]:
    scale = 2 ** (z_max - z)
    screen_x_min = tile_x * 512 * scale - 256 * y_max - IMAGE_MARGIN_WIDTH * 2
    screen_y_min = tile_y * 512 * scale
    return screen_x_min, screen_y_min
