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
TILE_SIZE = int(os.getenv('TILE_SIZE', '512'))  # タイルサイズを環境変数から取得

def download_tile(tile_path: str) -> Image.Image:
    """storage からタイルをダウンロードして PIL.Image オブジェクトを返す"""
    try:
        response = requests.get(
            f"{STORAGE_URL}{tile_path}",
            timeout=30
        )
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content))
    except requests.exceptions.RequestException as e:
        logger.error(f"タイルダウンロード失敗: {tile_path}, エラー: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"タイル読み込み失敗: {tile_path}, エラー: {str(e)}")
        raise

def upload_tile(tile_path: str, image_data: bytes) -> None:
    """タイルを storage にアップロード"""
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

@app.route('/merge', methods=['POST'])
def merge_tiles():
    """
    タイルマージエンドポイント
    リクエスト: {"child_tiles": [{"path": "string"}], "parent_z": number, "parent_x": number, "parent_y": number}
    レスポンス: {"tile_path": "string"}
    """
    try:
        # リクエストパラメータの取得と検証
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON payload"}), 400
        
        child_tiles = data.get('child_tiles', [])
        parent_z = data.get('parent_z')
        parent_x = data.get('parent_x')
        parent_y = data.get('parent_y')
        
        if not all([child_tiles, parent_z is not None, parent_x is not None, parent_y is not None]):
            return jsonify({"error": "Missing required parameters"}), 400
        
        if not isinstance(child_tiles, list) or len(child_tiles) != 4:
            return jsonify({"error": "child_tiles must be exactly 4 items"}), 400
        
        logger.info(f"タイルマージ開始: parent_z={parent_z}, parent_x={parent_x}, parent_y={parent_y}, tile_size={TILE_SIZE}")
        
        # 子タイルをダウンロード（2x2の順序で）
        child_images = []
        for i, child_info in enumerate(child_tiles):
            try:
                path = child_info.get('path')
                if not path:
                    return jsonify({"error": f"child_tiles[{i}] missing path"}), 400
                
                img = download_tile(path)
                child_images.append(img)
                
            except Exception as e:
                logger.error(f"子タイル{i}のダウンロードに失敗: {str(e)}")
                # すでに読み込んだ画像をクローズ
                for img in child_images:
                    img.close()
                raise
        
        # 2x2配置で結合（2 * TILE_SIZE の正方形画像）
        merged_width = TILE_SIZE * 2
        merged_height = TILE_SIZE * 2
        merged_image = Image.new('RGBA', (merged_width, merged_height), (0, 0, 0, 0))
        
        # 子タイルを配置（左上、右上、左下、右下）
        positions = [(0, 0), (TILE_SIZE, 0), (0, TILE_SIZE), (TILE_SIZE, TILE_SIZE)]
        for img, (x, y) in zip(child_images, positions):
            merged_image.paste(img, (x, y))
            img.close()
        
        # 1/2にリサイズ（TILE_SIZE の正方形画像）
        merged_image = merged_image.resize((TILE_SIZE, TILE_SIZE), Image.Resampling.LANCZOS)
        
        # PNG形式でエンコード（未圧縮）
        output_buffer = io.BytesIO()
        merged_image.save(output_buffer, format='PNG', compress_level=0)  # compress_level=0 で無圧縮
        merged_image.close()
        output_buffer.seek(0)
        tile_data = output_buffer.getvalue()
        
        # storageに保存（設計書通りのパス）
        tile_path = f"/images/rawtiles/{parent_z}/{parent_x}/{parent_y}.png"
        upload_tile(tile_path, tile_data)
        
        return jsonify({"tile_path": tile_path})
        
    except Exception as e:
        logger.error(f"タイルマージ処理で予期しないエラー: {str(e)}", exc_info=True)
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """ヘルスチェックエンドポイント"""
    return jsonify({"status": "healthy", "service": "service-tile-merge"}), 200

if __name__ == '__main__':
    # 開発用に直接実行する場合
    app.run(host='0.0.0.0', port=5003, debug=False)
