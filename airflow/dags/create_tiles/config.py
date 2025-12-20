import os
import math

# サービスのURL設定
SERVICE_CAPTURE_URL = os.environ.get('SERVICE_CAPTURE_URL', 'http://service-capture:5000')
SERVICE_ESTIMATE_URL = os.environ.get('SERVICE_ESTIMATE_URL', 'http://service-estimate:5001')
SERVICE_TILE_CUT_URL = os.environ.get('SERVICE_TILE_CUT_URL', 'http://service-tile-cut:5002')
SERVICE_TILE_MERGE_URL = os.environ.get('SERVICE_TILE_MERGE_URL', 'http://service-tile-merge:5003')
SERVICE_TILE_COMPRESS_URL = os.environ.get('SERVICE_TILE_COMPRESS_URL', 'http://service-tile-compress:5004')
BACKEND_INTERNAL_URL = os.environ.get('BACKEND_INTERNAL_URL', 'http://backend:8002')
STORAGE_URL = os.environ.get('STORAGE_URL', 'http://storage')

# 環境変数からの設定
PAKSET_SIZE = int(os.environ.get('PAKSET_SIZE', '128'))
TILE_SIZE = int(os.environ.get('TILE_SIZE', '512'))
DELTA = int(os.environ.get('DELTA', '40'))
MAP_TILES_X = int(os.environ.get('MAP_TILES_X', '512'))
MAP_TILES_Y = int(os.environ.get('MAP_TILES_Y', '512'))
IMAGE_WIDTH = int(os.environ.get('IMAGE_WIDTH', '5632')) # W + 2w
IMAGE_HEIGHT = int(os.environ.get('IMAGE_HEIGHT', '2816')) # H + 2h
IMAGE_MARGIN_WIDTH = int(os.environ.get('IMAGE_MARGIN_WIDTH', '256'))
IMAGE_MARGIN_HEIGHT = int(os.environ.get('IMAGE_MARGIN_HEIGHT', '128'))
ENABLE_WIDTH = IMAGE_WIDTH - 2 * IMAGE_MARGIN_WIDTH
ENABLE_HEIGHT = IMAGE_HEIGHT - 2 * IMAGE_MARGIN_HEIGHT

# タイルグループ化のサイズ
TILE_GROUP_SIZE = 64

# その他
max_width = PAKSET_SIZE * (MAP_TILES_X + MAP_TILES_Y) + IMAGE_MARGIN_WIDTH * 4
max_height = (PAKSET_SIZE // 2) * (MAP_TILES_X + MAP_TILES_Y) + IMAGE_MARGIN_HEIGHT * 2
MAX_Z = math.ceil(math.log2(max(max_width, max_height) / TILE_SIZE))
