# service-create-panel/app.py
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

# PILの画像サイズ制限を解除（巨大な画像を扱う場合のため）
# これにより DecompressionBombError を抑制します
Image.MAX_IMAGE_PIXELS = None

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

def upload_panel(panel_path: str, image_data: bytes) -> None:
    """一枚絵を storage にアップロード"""
    try:
        response = requests.put(
            f"{STORAGE_URL}{panel_path}",
            data=image_data,
            headers={'Content-Type': 'image/png'},
            timeout=60
        )
        response.raise_for_status()
        logger.info(f"一枚絵保存成功: {panel_path}")
    except requests.exceptions.RequestException as e:
        logger.error(f"一枚絵保存失敗: {panel_path}, エラー: {str(e)}")
        raise

@app.route('/create_panel', methods=['POST'])
def create_panel():
    """
    一枚絵生成エンドポイント
    リクエスト: {
        "z": int,
        "tiles": [{"path": str, "x": int, "y": int}],
        "map_size": {"width": int, "height": int},
        "resolution": {"width": int, "height": int},
        "output_path": str
    }
    レスポンス: {"output_path": str}
    """
    try:
        # リクエストパラメータの取得と検証
        data = request.get_json()
        if not data:
            return jsonify({"error": "Invalid JSON payload"}), 400
        
        z = data.get('z')
        tiles = data.get('tiles')
        map_size = data.get('map_size')
        resolution = data.get('resolution')
        output_path = data.get('output_path')
        
        # 必須パラメータの検証
        if z is None:
            logger.error("z parameter is missing")
            return jsonify({"error": "z parameter is required"}), 400
        if not tiles or not isinstance(tiles, list) or len(tiles) == 0:
            logger.error("tiles array is missing or empty")
            return jsonify({"error": "tiles array is required and must not be empty"}), 400
        if not map_size or 'width' not in map_size or 'height' not in map_size:
            logger.error("map_size parameter is missing or incomplete")
            return jsonify({"error": "map_size with width and height is required"}), 400
        if not resolution or 'width' not in resolution or 'height' not in resolution:
            logger.error("resolution parameter is missing or incomplete")
            return jsonify({"error": "resolution with width and height is required"}), 400
        if not output_path:
            logger.error("output_path parameter is missing")
            return jsonify({"error": "output_path parameter is required"}), 400
        
        # 数値の妥当性チェック
        map_width = map_size['width']  # ピクセル
        map_height = map_size['height']  # ピクセル
        target_width = resolution['width']  # ピクセル
        target_height = resolution['height']  # ピクセル
        
        if map_width <= 0 or map_height <= 0:
            logger.error("map_size dimensions must be positive")
            return jsonify({"error": "map_size dimensions must be positive"}), 400
        if target_width <= 0 or target_height <= 0:
            logger.error("resolution dimensions must be positive")
            return jsonify({"error": "resolution dimensions must be positive"}), 400
        
        logger.info(f"一枚絵生成開始: z={z}, タイル数={len(tiles)}, マップサイズ={map_width}x{map_height}px, 解像度={target_width}x{target_height}px")
        
        # ステップ3: キャンバス作成とタイル配置
        canvas = Image.new('RGB', (map_width, map_height), color=(64, 64, 64))
        
        for tile in tiles:
            logger.info(f"タイル配置中: x={tile['x']}, y={tile['y']}, path={tile['path']}")
            tile_x = tile['x']  # タイル座標
            tile_y = tile['y']  # タイル座標
            tile_path = tile['path']
            
            # タイルをダウンロード
            img = download_tile(tile_path)
            
            # RGBに変換（アルファチャンネルがある場合は背景色で合成）
            if img.mode == 'RGBA':
                # 灰色の背景を作成
                background = Image.new('RGB', img.size, (64, 64, 64))
                # アルファチャンネルを使って合成
                background.paste(img, mask=img.split()[3])  # 3番目のチャンネルがアルファ
                img.close()
                img = background
            elif img.mode != 'RGB':
                # その他のモードもRGBに変換
                converted = img.convert('RGB')
                img.close()
                img = converted
            
            # キャンバス上の貼り付け位置（ピクセル座標）を計算
            paste_x = tile_x * TILE_SIZE - int(map_width * 0.1)  # なぜか右にずれるので調整
            paste_y = tile_y * TILE_SIZE - int(map_height * 0.03) # なぜか下にずれるので調整
            
            # キャンバスに貼り付け
            canvas.paste(img, (paste_x, paste_y))
            
            # メモリ解放
            img.close()
        
        logger.info("全タイルの配置完了")
        
        # ステップ4: マップ領域のクリッピング
        # クリッピング実行（左上(0,0)からマップサイズ分を切り出し）
        map_image = canvas.crop((0, 0, map_width, map_height))
        canvas.close()  # 元のキャンバスは不要
        
        logger.info(f"マップ領域調整完了: {map_width}x{map_height}px")
        
        # ステップ5: アスペクト比を維持したリサイズ
        aspect_ratio = map_width / map_height
        target_aspect = target_width / target_height
        
        if aspect_ratio > target_aspect:
            # 横長: 幅を基準にリサイズ
            new_width = target_width
            new_height = int(target_width / aspect_ratio)
        else:
            # 縦長: 高さを基準にリサイズ
            new_height = target_height
            new_width = int(target_height * aspect_ratio)
        
        resized_image = map_image.resize((new_width, new_height), Image.LANCZOS)
        map_image.close()  # 元の画像は不要
        
        logger.info(f"リサイズ完了: {new_width}x{new_height}px")
        
        # ステップ6: 中央寄せ配置
        final_canvas = Image.new('RGB', (target_width, target_height), color=(64, 64, 64))
        
        offset_x = (target_width - new_width) // 2  # ピクセル
        offset_y = (target_height - new_height) // 2  # ピクセル
        
        final_canvas.paste(resized_image, (offset_x, offset_y))
        resized_image.close()  # リサイズ画像は不要
        
        logger.info(f"中央寄せ配置完了: オフセット=({offset_x}, {offset_y})px")
        
        # ステップ7: PNG圧縮と保存
        output_buffer = io.BytesIO()
        final_canvas.save(output_buffer, format='PNG', optimize=True, compress_level=9)
        final_canvas.close()
        output_buffer.seek(0)
        compressed_data = output_buffer.getvalue()
        
        # storageに保存
        upload_panel(output_path, compressed_data)
        
        logger.info(f"一枚絵生成完了: {output_path}")
        
        # レスポンス返却
        return jsonify({"output_path": output_path})
        
    except Exception as e:
        logger.error(f"一枚絵生成処理で予期しないエラー: {str(e)}", exc_info=True)
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """ヘルスチェックエンドポイント"""
    return jsonify({"status": "healthy"}), 200

if __name__ == '__main__':
    # 開発用に直接実行する場合
    app.run(host='0.0.0.0', port=5005, debug=False)