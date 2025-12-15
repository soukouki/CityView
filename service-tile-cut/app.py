from flask import Flask, request, jsonify
from PIL import Image
import requests
import io
import os
import logging

# ロギング設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# 環境変数から設定を読み込み
STORAGE_URL = os.getenv('STORAGE_URL', 'http://storage')
TILE_SIZE = int(os.getenv('TILE_SIZE', '512'))

# 以下、画像処理関数とエンドポイントは変更なし
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
    タイル切り出しエンドポイント
    リクエスト: {"images": [...], "tile_z": number, "tile_x": number, "tile_y": number}
    レスポンス: {"tile_path": string}
    """
    try:
        # リクエストパラメータの取得と検証
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON payload"}), 400
        
        images = data.get('images', [])
        tile_z = data.get('tile_z')
        tile_x = data.get('tile_x')
        tile_y = data.get('tile_y')
        
        if not all([images, tile_z is not None, tile_x is not None, tile_y is not None]):
            return jsonify({"error": "Missing required parameters"}), 400
        
        if not isinstance(images, list) or len(images) == 0:
            return jsonify({"error": "images must be a non-empty list"}), 400
        
        # タイルのピクセル範囲を計算
        tile_left = tile_x * TILE_SIZE
        tile_top = tile_y * TILE_SIZE
        tile_right = tile_left + TILE_SIZE
        tile_bottom = tile_top + TILE_SIZE
        
        logger.info(f"タイル切り出し開始: z={tile_z}, x={tile_x}, y={tile_y}, 範囲=({tile_left},{tile_top})-({tile_right},{tile_bottom})")
        
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
                
                # 画像をダウンロード
                img = download_image(img_path)
                img_width, img_height = img.size
                
                # 画像のピクセル範囲
                img_left = img_x
                img_top = img_y
                img_right = img_left + img_width
                img_bottom = img_top + img_height
                
                # オーバーラップ判定
                if img_right <= tile_left or img_left >= tile_right or \
                   img_bottom <= tile_top or img_top >= tile_bottom:
                    img.close()
                    continue  # オーバーラップなし
                
                # オーバーラップ領域の計算（画像座標系）
                overlap_left = max(img_left, tile_left)
                overlap_top = max(img_top, tile_top)
                overlap_right = min(img_right, tile_right)
                overlap_bottom = min(img_bottom, tile_bottom)
                
                # 画像内の切り出し矩形
                crop_left = overlap_left - img_left
                crop_top = overlap_top - img_top
                crop_right = overlap_right - img_left
                crop_bottom = overlap_bottom - img_top
                
                # タイル内の貼り付け位置
                paste_left = overlap_left - tile_left
                paste_top = overlap_top - tile_top
                
                # オーバーラップ領域を切り出してタイルに貼り付け
                overlap_img = img.crop((crop_left, crop_top, crop_right, crop_bottom))
                tile_image.paste(overlap_img, (paste_left, paste_top))
                
                img.close()
                processed_images += 1
                
            except Exception as e:
                logger.warning(f"画像処理中にエラー: {img_info}, エラー: {str(e)}")
                continue
        
        logger.info(f"処理した画像数: {processed_images}/{len(images)}")
        
        # PNG形式でエンコード（未圧縮）
        output_buffer = io.BytesIO()
        tile_image.save(output_buffer, format='PNG', compress_level=0)  # compress_level=0 で無圧縮
        tile_image.close()
        output_buffer.seek(0)
        tile_data = output_buffer.getvalue()
        
        # storageに保存
        tile_path = f"/images/rawtiles/{tile_z}/{tile_x}/{tile_y}.png"
        upload_tile(tile_path, tile_data)
        
        return jsonify({"tile_path": tile_path})
        
    except Exception as e:
        logger.error(f"タイル切り出し処理で予期しないエラー: {str(e)}", exc_info=True)
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """ヘルスチェックエンドポイント"""
    return jsonify({"status": "healthy", "service": "service-tile-cut"}), 200

if __name__ == '__main__':
    # 開発用に直接実行する場合
    app.run(host='0.0.0.0', port=5002, debug=False)
