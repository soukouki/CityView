from flask import Flask, request, jsonify
import cv2
import numpy as np
import requests
import os
import gc

app = Flask(__name__)

# 環境変数から設定を取得
IMAGE_WIDTH = int(os.getenv('IMAGE_WIDTH'))
IMAGE_HEIGHT = int(os.getenv('IMAGE_HEIGHT'))
IMAGE_MARGIN_WIDTH = int(os.getenv('IMAGE_MARGIN_WIDTH'))
IMAGE_MARGIN_HEIGHT = int(os.getenv('IMAGE_MARGIN_HEIGHT'))
STORAGE_URL = os.getenv('STORAGE_URL')

# 有効範囲のサイズを計算
EFFECTIVE_WIDTH = IMAGE_WIDTH - 2 * IMAGE_MARGIN_WIDTH
EFFECTIVE_HEIGHT = IMAGE_HEIGHT - 2 * IMAGE_MARGIN_HEIGHT


def fetch_image(image_path):
    """
    storageから画像を取得
    """
    try:
        url = f"{STORAGE_URL}{image_path}"
        print(f"Fetching image from URL: {url}", flush=True)
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # バイトデータからNumPy配列に変換
        img_array = np.frombuffer(response.content, np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        
        if img is None:
            raise ValueError(f"Failed to decode image: {image_path}")
        
        print(f"Image fetched successfully: {image_path}, shape: {img.shape}", flush=True)
        return img
    except Exception as e:
        raise Exception(f"Failed to fetch image {image_path}: {str(e)}")


def estimate_with_sift(target_img, ref_img, ref_x, ref_y):
    """
    SIFT特徴点マッチングで座標を推定（フォールバック用）
    
    Args:
        target_img: 座標未知の画像
        ref_img: 座標既知の画像
        ref_x, ref_y: 参照画像の座標
    
    Returns:
        推定座標 (x, y) or None
    """
    try:
        # グレースケール変換
        gray1 = cv2.cvtColor(target_img, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(ref_img, cv2.COLOR_BGR2GRAY)
        
        # SIFT検出器
        sift = cv2.SIFT_create()
        kp1, des1 = sift.detectAndCompute(gray1, None)
        kp2, des2 = sift.detectAndCompute(gray2, None)
        
        if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
            print("SIFT matching failed: insufficient keypoints", flush=True)
            return None
        
        # BFMatcherでマッチング
        bf = cv2.BFMatcher()
        matches = bf.knnMatch(des1, des2, k=2)
        
        # Lowe's ratio testで良いマッチのみ抽出
        good_matches = []
        for match_pair in matches:
            if len(match_pair) == 2:
                m, n = match_pair
                if m.distance < 0.7 * n.distance:
                    good_matches.append(m)
        
        if len(good_matches) < 4:
            print(f"SIFT matching failed: only {len(good_matches)} good matches", flush=True)
            return None
        
        # 対応点の座標を取得
        src_pts = np.float32([kp1[m.queryIdx].pt for m in good_matches])
        dst_pts = np.float32([kp2[m.trainIdx].pt for m in good_matches])
        
        # 平行移動量を計算（中央値で外れ値除去）
        translations = dst_pts - src_pts
        median_translation = np.median(translations, axis=0)
        
        # 推定座標を計算
        estimated_x = ref_x - median_translation[0]
        estimated_y = ref_y - median_translation[1]
        
        print(f"SIFT matching succeeded: estimated ({int(estimated_x)}, {int(estimated_y)})", flush=True)
        return int(estimated_x), int(estimated_y)
    except Exception as e:
        print(f"SIFT estimation failed: {str(e)}", flush=True)
        return None


def estimate_coordinate(target_img, adjacent_images, hint_x, hint_y):
    """
    座標推定のメイン処理
    
    Args:
        target_img: 座標未知の画像
        adjacent_images: [(img, x, y), ...] 座標既知の隣接画像リスト
        hint_x, hint_y: ヒント座標
    
    Returns:
        推定座標 (x, y)
    """
    img_h, img_w = target_img.shape[:2]
    print(f"Target image size: {img_w}x{img_h}", flush=True)
    print(f"Effective area: {EFFECTIVE_WIDTH}x{EFFECTIVE_HEIGHT}", flush=True)
    print(f"Margins: {IMAGE_MARGIN_WIDTH}x{IMAGE_MARGIN_HEIGHT}", flush=True)
    print(f"Hint coordinates: ({hint_x}, {hint_y})", flush=True)
    
    # 各隣接画像に対して処理
    for ref_img, ref_x, ref_y in adjacent_images:
        sift_result = estimate_with_sift(target_img, ref_img, ref_x, ref_y)
        if sift_result is not None:
            return sift_result
    
    # 推定できない場合はヒント座標を返す
    print(f"All estimation methods failed, returning hint: ({hint_x}, {hint_y})", flush=True)
    return hint_x, hint_y


@app.route('/estimate', methods=['POST'])
def estimate():
    """
    座標推定エンドポイント
    """
    try:
        data = request.get_json()
        
        # リクエストパラメータの検証
        if not data:
            return jsonify({'error': 'Invalid JSON'}), 400
        
        image_path = data.get('image_path')
        adjacent_images = data.get('adjacent_images', [])
        hint_x = data.get('hint_x', 0)
        hint_y = data.get('hint_y', 0)
        
        if not image_path:
            return jsonify({'error': 'image_path is required'}), 400
        
        print(f"\nProcessing estimation request for: {image_path}", flush=True)
        
        # 主画像を取得
        target_img = fetch_image(image_path)
        
        # 隣接画像を取得
        adjacent_data = []
        for adj in adjacent_images:
            adj_img = fetch_image(adj['image_path'])
            adjacent_data.append((adj_img, adj['x'], adj['y']))
        
        # 座標推定
        estimated_x, estimated_y = estimate_coordinate(
            target_img, adjacent_data, hint_x, hint_y
        )
        
        # メモリ解放
        del target_img
        for adj_img, _, _ in adjacent_data:
            del adj_img
        del adjacent_data
        gc.collect()
        
        print(f"Final result: ({estimated_x}, {estimated_y})", flush=True)
        
        # レスポンス返却
        return jsonify({
            'estimated_x': int(estimated_x),
            'estimated_y': int(estimated_y)
        }), 200
        
    except Exception as e:
        # エラーハンドリング
        print(f"Error occurred: {str(e)}", flush=True)
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    """
    ヘルスチェックエンドポイント
    """
    return jsonify({'status': 'healthy'}), 200


if __name__ == '__main__':
    # 本番環境ではgunicornなどのWSGIサーバーを使用することを推奨
    app.run(host='0.0.0.0', port=5001, debug=False)
