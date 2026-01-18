import os
import math

# サービスのURL設定
SERVICE_CAPTURE_URL = os.environ.get('SERVICE_CAPTURE_URL', 'http://service-capture:5000')
SERVICE_ESTIMATE_URL = os.environ.get('SERVICE_ESTIMATE_URL', 'http://service-estimate:5001')
SERVICE_TILE_CUT_URL = os.environ.get('SERVICE_TILE_CUT_URL', 'http://service-tile-cut:5002')
SERVICE_TILE_MERGE_URL = os.environ.get('SERVICE_TILE_MERGE_URL', 'http://service-tile-merge:5003')
SERVICE_TILE_COMPRESS_URL = os.environ.get('SERVICE_TILE_COMPRESS_URL', 'http://service-tile-compress:5004')
SERVICE_CREATE_PANEL_URL = os.environ.get('SERVICE_CREATE_PANEL_URL', 'http://service-create-panel:5005')
BACKEND_INTERNAL_URL = os.environ.get('BACKEND_INTERNAL_URL', 'http://backend:8002')
STORAGE_URL = os.environ.get('STORAGE_URL', 'http://storage')
