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
    画像マージエンドポイント
    リクエスト: {"tiles": [{"path": "string", "position": "string"}], "output_path": "string"}
    レスポンス: {"output_path": "string"}
    """
    try:
        # リクエストパラメータの取得と検証
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON payload"}), 400
        
        tiles = data.get('tiles', [])
        output_path = data.get('output_path')
        
        if tiles is None:
            return jsonify({"error": "tiles parameter is required"}), 400
        if output_path is None:
            return jsonify({"error": "output_path parameter is required"}), 400
        
        logger.info(f"画像マージ開始: tile_count={len(tiles)}, tile_size={TILE_SIZE}, output={output_path}")
        
        # position文字列からタイル配置座標へのマッピング
        position_map = {
            'top-left': (0, 0),
            'top-right': (TILE_SIZE, 0),
            'bottom-left': (0, TILE_SIZE),
            'bottom-right': (TILE_SIZE, TILE_SIZE)
        }
        
        # 2x2配置用の結合画像を作成（2 * TILE_SIZE の正方形）
        merged_width = TILE_SIZE * 2
        merged_height = TILE_SIZE * 2
        merged_image = Image.new('RGBA', (merged_width, merged_height), (0, 0, 0, 0))
        
        # 各タイルをダウンロードして配置
        loaded_images = []
        for i, tile_info in enumerate(tiles):
            try:
                path = tile_info.get('path')
                position = tile_info.get('position')
                
                if not path or not position:
                    return jsonify({"error": f"tiles[{i}] missing 'path' or 'position'"}), 400
                
                if position not in position_map:
                    return jsonify({"error": f"tiles[{i}] invalid position: {position}"}), 400
                
                # タイルをダウンロード
                img = download_tile(path)
                loaded_images.append(img)
                
                # 指定位置に配置
                x, y = position_map[position]
                merged_image.paste(img, (x, y))
                
                logger.info(f"タイル配置完了: {position} at ({x}, {y})")
                
            except Exception as e:
                logger.error(f"タイル{i}の処理に失敗: {str(e)}")
                # すでに読み込んだ画像をクローズ
                for img in loaded_images:
                    img.close()
                raise
        
        # 読み込んだ画像をクローズ
        for img in loaded_images:
            img.close()
        
        # 1/2にリサイズ（TILE_SIZE x TILE_SIZE）
        resized_image = merged_image.resize((TILE_SIZE, TILE_SIZE), Image.Resampling.LANCZOS)
        merged_image.close()
        
        # PNG形式でエンコード（未圧縮）
        output_buffer = io.BytesIO()
        resized_image.save(output_buffer, format='PNG', compress_level=0)
        resized_image.close()
        output_buffer.seek(0)
        tile_data = output_buffer.getvalue()
        
        # storageに保存
        upload_tile(output_path, tile_data)
        
        return jsonify({"output_path": output_path})
        
    except Exception as e:
        logger.error(f"画像マージ処理で予期しないエラー: {str(e)}", exc_info=True)
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """ヘルスチェックエンドポイント"""
    return jsonify({"status": "healthy", "service": "service-tile-merge"}), 200

if __name__ == '__main__':
    # 開発用に直接実行する場合
    app.run(host='0.0.0.0', port=5003, debug=False)
