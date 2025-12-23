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
ADJUSTED_PAKSIZE = int(os.environ.get('ADJUSTED_PAKSIZE', '128'))
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
TILE_QUALITY_MAX_ZOOM = os.environ.get('TILE_QUALITY_MAX_ZOOM', '60') # int or "lossless"
TILE_QUALITY_OTHER = os.environ.get('TILE_QUALITY_OTHER', '30')
ZOOM_LEVEL = os.environ.get('ZOOM_LEVEL', 'normal')
if ZOOM_LEVEL not in ['one_eighth', 'quarter', 'half', 'normal', 'double']:
    raise ValueError('Invalid ZOOM_LEVEL value')
TILE_GROUP_SIZE = int(os.environ.get('TILE_GROUP_SIZE', '64'))

# その他
max_width = (ADJUSTED_PAKSIZE // 2) * (MAP_TILES_X + MAP_TILES_Y) + IMAGE_MARGIN_WIDTH * 4 # 余裕を持ってマージンを倍に見ておく
max_height = (ADJUSTED_PAKSIZE // 4) * (MAP_TILES_X + MAP_TILES_Y) + IMAGE_MARGIN_HEIGHT * 2
MAX_Z = math.ceil(math.log2(max(max_width, max_height) / TILE_SIZE)) + 2
