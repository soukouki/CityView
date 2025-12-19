from flask import Flask, request, jsonify
from PIL import Image
import pillow_avif
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
AVIF_QUALITY = int(os.getenv('AVIF_QUALITY', '30'))

def download_tile(tile_path: str) -> Image.Image:
    """storage から未圧縮タイルをダウンロードして PIL.Image オブジェクトを返す"""
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

def upload_compressed_tile(tile_path: str, image_data: bytes) -> None:
    """圧縮タイルを storage にアップロード"""
    try:
        response = requests.put(
            f"{STORAGE_URL}{tile_path}",
            data=image_data,
            headers={'Content-Type': 'image/avif'},
            timeout=30
        )
        response.raise_for_status()
        logger.info(f"圧縮タイル保存成功: {tile_path}")
    except requests.exceptions.RequestException as e:
        logger.error(f"圧縮タイル保存失敗: {tile_path}, エラー: {str(e)}")
        raise

@app.route('/compress', methods=['POST'])
def compress_tile():
    """
    タイル圧縮エンドポイント（新スキーマ）
    リクエスト: {"input_path": str, "output_path": str}
    レスポンス: {}
    """
    try:
        # リクエストパラメータの取得と検証
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON payload"}), 400
        
        input_path = data.get('input_path')
        if input_path is None:
            return jsonify({"error": "input_path parameter is required"}), 400
        output_path = data.get('output_path')
        if output_path is None:
            return jsonify({"error": "output_path parameter is required"}), 400
        
        logger.info(f"タイル圧縮開始: input_path={input_path}, output_path={output_path}")
        
        # 未圧縮タイルを取得
        img = download_tile(input_path)
        
        # AVIF形式で圧縮
        output_buffer = io.BytesIO()
        img.save(output_buffer, format='AVIF', quality=AVIF_QUALITY)
        img.close()
        output_buffer.seek(0)
        compressed_data = output_buffer.getvalue()
        
        # storageに保存
        upload_compressed_tile(output_path, compressed_data)
        
        # 空のオブジェクトを返却
        return jsonify({})
        
    except Exception as e:
        logger.error(f"タイル圧縮処理で予期しないエラー: {str(e)}", exc_info=True)
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """ヘルスチェックエンドポイント"""
    return jsonify({"status": "healthy", "service": "service-tile-compress"}), 200

if __name__ == '__main__':
    # 開発用に直接実行する場合
    app.run(host='0.0.0.0', port=5004, debug=False)
