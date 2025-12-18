from flask import Flask, request, jsonify
from PIL import Image
import requests
import io
import os
import logging
import time
from threading import Lock

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# 環境変数から設定を読み込み
STORAGE_URL = os.getenv('STORAGE_URL', 'http://storage')
TILE_SIZE = int(os.getenv('TILE_SIZE', '512'))
CACHE_TTL = int(os.getenv('CACHE_TTL', '60'))  # キャッシュ保持時間（秒）

# 画像キャッシュ
image_cache = {}
cache_lock = Lock()

class CacheEntry:
    def __init__(self, image: Image.Image):
        self.image = image
        self.timestamp = time.time()
        self.access_count = 0

def get_cached_image(image_path: str) -> Image.Image:
    """キャッシュから画像を取得、なければダウンロードしてキャッシュ"""
    current_time = time.time()
    
    with cache_lock:
        # キャッシュのクリーンアップ（期限切れエントリを削除）
        expired_keys = [k for k, v in image_cache.items()
                       if current_time - v.timestamp > CACHE_TTL]
        for key in expired_keys:
            image_cache[key].image.close()
            del image_cache[key]
            logger.debug(f"キャッシュエントリ削除: {key}")
        
        # キャッシュヒット
        if image_path in image_cache:
            entry = image_cache[image_path]
            entry.access_count += 1
            logger.debug(f"キャッシュヒット: {image_path} (アクセス数: {entry.access_count})")
            return entry.image.copy()  # コピーを返す
    
    # キャッシュミス: ダウンロード
    logger.info(f"画像ダウンロード: {image_path}")
    image = download_image(image_path)
    
    with cache_lock:
        image_cache[image_path] = CacheEntry(image)
    
    return image.copy()

def download_image(image_path: str) -> Image.Image:
    """storage から画像をダウンロードして PIL.Image オブジェクトを返す"""
    try:
        response = requests.get(
            f"{STORAGE_URL}{image_path}",
            timeout=30
        )
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content))
    except requests.exceptions.RequestException as e:
        logger.error(f"画像ダウンロード失敗: {image_path}, エラー: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"画像読み込み失敗: {image_path}, エラー: {str(e)}")
        raise

def upload_tile(tile_path: str, image_data: bytes) -> None:
    """タイル画像を storage にアップロード"""
    try:
        response = requests.put(
            f"{STORAGE_URL}{tile_path}",
            data=image_data,
            headers={'Content-Type': 'image/png'},
            timeout=30
        )
        response.raise_for_status()
        logger.info(f"タイル保存成功: {tile_path}")
    except requests.exceptions.RequestException as e:
        logger.error(f"タイル保存失敗: {tile_path}, エラー: {str(e)}")
        raise

@app.route('/cut', methods=['POST'])
def cut_tile():
    """
    画像切り出しエンドポイント
    
    リクエスト: 
    {
        "images": [
            {
                "path": "/images/screenshots/shot_xxx.png",
                "x": <スクショ座標系でのX位置（ピクセル、負もあり得る）>,
                "y": <スクショ座標系でのY位置（ピクセル、負もあり得る）>
            }
        ],
        "cut_area": {
            "x": <スクショ座標系での切り出し左上X（ピクセル、負もあり得る）>,
            "y": <スクショ座標系での切り出し左上Y（ピクセル、負もあり得る）>
        },
        "output_path": "/images/rawtiles/z/tx/ty.png"
    }
    
    レスポンス: {"output_path": string}
    
    注意: cut_area.x, cut_area.y はスクショ座標系のピクセル座標です。
          地図タイル座標やゲーム内タイル座標ではありません。
    """
    try:
        # リクエストパラメータの取得と検証
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON payload"}), 400
        
        images = data.get('images', [])
        cut_area = data.get('cut_area')
        output_path = data.get('output_path')
        
        if images is None:
            return jsonify({"error": "images parameter is required"}), 400
        if cut_area is None:
            return jsonify({"error": "cut_area parameter is required"}), 400
        if output_path is None:
            return jsonify({"error": "output_path parameter is required"}), 400
        
        if not isinstance(images, list) or len(images) == 0:
            return jsonify({"error": "images must be a non-empty list"}), 400
        
        # cut_area の検証
        cut_x = cut_area.get('x')
        cut_y = cut_area.get('y')
        
        if cut_x is None or cut_y is None:
            return jsonify({"error": "cut_area must contain 'x' and 'y'"}), 400
        
        # 切り出し範囲の計算（スクショ座標系、ピクセル単位）
        # cut_x, cut_y は既にスクショ座標系のピクセル値（変換不要）
        tile_left = cut_x
        tile_top = cut_y
        tile_right = tile_left + TILE_SIZE
        tile_bottom = tile_top + TILE_SIZE
        
        logger.info(f"タイル切り出し開始: スクショ座標=({tile_left},{tile_top})-({tile_right},{tile_bottom}), "
                   f"出力先={output_path}")
        
        # 透明なタイル画像を作成
        tile_image = Image.new('RGBA', (TILE_SIZE, TILE_SIZE), (0, 0, 0, 0))
        
        processed_images = 0
        
        # 各スクリーンショット画像を処理
        for img_info in images:
            try:
                # 必須フィールドの検証
                img_path = img_info.get('path')
                img_x = img_info.get('x')
                img_y = img_info.get('y')
                
                if not all([img_path, img_x is not None, img_y is not None]):
                    logger.warning(f"画像情報が不完全: {img_info}")
                    continue
                
                # 画像をキャッシュから取得（またはダウンロード）
                img = get_cached_image(img_path)
                img_width, img_height = img.size
                
                # 画像の範囲（スクショ座標系、ピクセル単位）
                # img_x, img_y は画像の左上のスクショ座標
                img_left = img_x
                img_top = img_y
                img_right = img_left + img_width
                img_bottom = img_top + img_height
                
                # オーバーラップ判定（スクショ座標系）
                if img_right <= tile_left or img_left >= tile_right or \
                   img_bottom <= tile_top or img_top >= tile_bottom:
                    logger.debug(f"オーバーラップなし: {img_path} "
                               f"img=({img_left},{img_top})-({img_right},{img_bottom}) "
                               f"tile=({tile_left},{tile_top})-({tile_right},{tile_bottom})")
                    img.close()
                    continue  # オーバーラップなし
                
                # オーバーラップ領域の計算（スクショ座標系）
                overlap_left = max(img_left, tile_left)
                overlap_top = max(img_top, tile_top)
                overlap_right = min(img_right, tile_right)
                overlap_bottom = min(img_bottom, tile_bottom)
                
                # 画像内の切り出し矩形（画像内座標系、左上が原点）
                crop_left = overlap_left - img_left
                crop_top = overlap_top - img_top
                crop_right = overlap_right - img_left
                crop_bottom = overlap_bottom - img_top
                
                # タイル内の貼り付け位置（タイル内座標系、左上が原点）
                paste_left = overlap_left - tile_left
                paste_top = overlap_top - tile_top
                
                logger.info(f"オーバーラップ処理: {img_path} "
                          f"img_pos=({img_left},{img_top}) img_size=({img_width}x{img_height}) "
                          f"overlap=({overlap_left},{overlap_top})-({overlap_right},{overlap_bottom}) "
                          f"crop=({crop_left},{crop_top})-({crop_right},{crop_bottom}) "
                          f"paste=({paste_left},{paste_top})")
                
                # オーバーラップ領域を切り出してタイルに貼り付け
                overlap_img = img.crop((crop_left, crop_top, crop_right, crop_bottom))
                tile_image.paste(overlap_img, (paste_left, paste_top))
                
                img.close()
                overlap_img.close()
                processed_images += 1
                
            except Exception as e:
                logger.warning(f"画像処理中にエラー: {img_info}, エラー: {str(e)}", exc_info=True)
                continue
        
        logger.info(f"処理した画像数: {processed_images}/{len(images)}")
        
        # PNG形式でエンコード（未圧縮）
        output_buffer = io.BytesIO()
        tile_image.save(output_buffer, format='PNG', compress_level=0)
        tile_image.close()
        output_buffer.seek(0)
        tile_data = output_buffer.getvalue()
        
        # storageに保存
        upload_tile(output_path, tile_data)
        
        return jsonify({"output_path": output_path})
        
    except Exception as e:
        logger.error(f"画像切り出し処理で予期しないエラー: {str(e)}", exc_info=True)
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """ヘルスチェックエンドポイント"""
    with cache_lock:
        cache_size = len(image_cache)
    return jsonify({
        "status": "healthy",
        "cache_entries": cache_size
    }), 200

if __name__ == '__main__':
    # 開発用に直接実行する場合
    app.run(host='0.0.0.0', port=5002, debug=False)
