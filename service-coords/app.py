from flask import Flask, request, jsonify
import cv2
import numpy as np
import requests
import os
import gc
from io import BytesIO

app = Flask(__name__)

# 環境変数から設定を取得
IMAGE_WIDTH = int(os.getenv('IMAGE_WIDTH'))
IMAGE_HEIGHT = int(os.getenv('IMAGE_HEIGHT'))
IMAGE_MARGIN_WIDTH = int(os.getenv('IMAGE_MARGIN_WIDTH'))
IMAGE_MARGIN_HEIGHT = int(os.getenv('IMAGE_MARGIN_HEIGHT'))
STORAGE_URL = os.getenv('STORAGE_URL')


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

        print(f"Image fetched successfully: {image_path}, shape: {img.shape if img is not None else 'None'}", flush=True)
        
        if img is None:
            raise ValueError(f"Failed to decode image: {image_path}")
        
        return img
    except Exception as e:
        raise Exception(f"Failed to fetch image {image_path}: {str(e)}")


def find_horizontal_shift(strip1, strip2, expected_dx, search_range):
    """
    水平方向の糊代ストリップ同士を比較してシフト量を検出
    
    Args:
        strip1: 比較する画像1の糊代ストリップ
        strip2: 比較する画像2の糊代ストリップ
        expected_dx: 予想される水平シフト量
        search_range: 探索範囲（±）
    
    Returns:
        シフト量 or None
    """
    h, w = strip1.shape[:2]
    
    # 探索範囲を制限
    search_start = max(expected_dx - search_range, -w)
    search_end = min(expected_dx + search_range + 1, w)
    
    for dx in range(search_start, search_end):
        try:
            # 重なり領域を計算
            if dx >= 0:
                overlap_w = min(w - dx, w)
                if overlap_w <= 0:
                    continue
                region1 = strip1[:, dx:dx+overlap_w, :]
                region2 = strip2[:, :overlap_w, :]
            else:
                overlap_w = min(w + dx, w)
                if overlap_w <= 0:
                    continue
                region1 = strip1[:, :overlap_w, :]
                region2 = strip2[:, -dx:-dx+overlap_w, :]
            
            # RGB完全一致チェック
            if region1.shape == region2.shape and np.array_equal(region1, region2):
                return dx
        except Exception:
            continue
    
    return None


def find_vertical_shift(strip1, strip2, expected_dy, search_range):
    """
    垂直方向の糊代ストリップ同士を比較してシフト量を検出
    
    Args:
        strip1: 比較する画像1の糊代ストリップ
        strip2: 比較する画像2の糊代ストリップ
        expected_dy: 予想される垂直シフト量
        search_range: 探索範囲（±）
    
    Returns:
        シフト量 or None
    """
    h, w = strip1.shape[:2]
    
    # 探索範囲を制限
    search_start = max(expected_dy - search_range, -h)
    search_end = min(expected_dy + search_range + 1, h)
    
    for dy in range(search_start, search_end):
        try:
            # 重なり領域を計算
            if dy >= 0:
                overlap_h = min(h - dy, h)
                if overlap_h <= 0:
                    continue
                region1 = strip1[dy:dy+overlap_h, :, :]
                region2 = strip2[:overlap_h, :, :]
            else:
                overlap_h = min(h + dy, h)
                if overlap_h <= 0:
                    continue
                region1 = strip1[:overlap_h, :, :]
                region2 = strip2[-dy:-dy+overlap_h, :, :]
            
            # RGB完全一致チェック
            if region1.shape == region2.shape and np.array_equal(region1, region2):
                return dy
        except Exception:
            continue
    
    return None


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
        
        return int(estimated_x), int(estimated_y)
    except Exception as e:
        print(f"SIFT estimation failed: {str(e)}")
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
    
    # 各隣接画像に対して処理
    for ref_img, ref_x, ref_y in adjacent_images:
        # ヒントから予想される相対位置
        expected_dx = hint_x - ref_x
        expected_dy = hint_y - ref_y
        print(f"Comparing with reference image at ({ref_x}, {ref_y}): expected_dx={expected_dx}, expected_dy={expected_dy}", flush=True)
        
        # 上下方向の重なりをチェック
        if abs(expected_dy) > img_h - 2 * IMAGE_MARGIN_HEIGHT:
            # target の上端 と ref の下端
            target_strip = target_img[:IMAGE_MARGIN_HEIGHT, :, :]
            ref_strip = ref_img[-IMAGE_MARGIN_HEIGHT:, :, :]
            
            print(f"Checking vertical overlap: expected_dx={expected_dx}, expected_dy={expected_dy}", flush=True)
            dx = find_horizontal_shift(target_strip, ref_strip, expected_dx, IMAGE_MARGIN_WIDTH)
            if dx is not None:
                print(f"Found vertical match at dx={dx}")
                return ref_x + dx, ref_y + img_h - IMAGE_MARGIN_HEIGHT
            
            # target の下端 と ref の上端
            target_strip = target_img[-IMAGE_MARGIN_HEIGHT:, :, :]
            ref_strip = ref_img[:IMAGE_MARGIN_HEIGHT, :, :]
            
            print(f"Checking vertical overlap (bottom): expected_dx={expected_dx}, expected_dy={expected_dy}", flush=True)
            dx = find_horizontal_shift(target_strip, ref_strip, expected_dx, IMAGE_MARGIN_WIDTH)
            if dx is not None:
                print(f"Found vertical match at dx={dx} (bottom)")
                return ref_x + dx, ref_y - img_h + IMAGE_MARGIN_HEIGHT
        
        # 左右方向の重なりをチェック
        if abs(expected_dx) > img_w - 2 * IMAGE_MARGIN_WIDTH:
            # target の左端 と ref の右端
            target_strip = target_img[:, :IMAGE_MARGIN_WIDTH, :]
            ref_strip = ref_img[:, -IMAGE_MARGIN_WIDTH:, :]
            
            print(f"Checking horizontal overlap: expected_dx={expected_dx}, expected_dy={expected_dy}", flush=True)
            dy = find_vertical_shift(target_strip, ref_strip, expected_dy, IMAGE_MARGIN_HEIGHT)
            if dy is not None:
                print(f"Found horizontal match at dy={dy}")
                return ref_x + img_w - IMAGE_MARGIN_WIDTH, ref_y + dy
            
            # target の右端 と ref の左端
            target_strip = target_img[:, -IMAGE_MARGIN_WIDTH:, :]
            ref_strip = ref_img[:, :IMAGE_MARGIN_WIDTH, :]
            
            print(f"Checking horizontal overlap (right): expected_dx={expected_dx}, expected_dy={expected_dy}", flush=True)
            dy = find_vertical_shift(target_strip, ref_strip, expected_dy, IMAGE_MARGIN_HEIGHT)
            if dy is not None:
                print(f"Found horizontal match at dy={dy} (right)")
                return ref_x - img_w + IMAGE_MARGIN_WIDTH, ref_y + dy
        
        # RGB完全一致で見つからない場合、SIFTにフォールバック
        print("Falling back to SIFT feature matching", flush=True)
        sift_result = estimate_with_sift(target_img, ref_img, ref_x, ref_y)
        if sift_result is not None:
            print("SIFT matching succeeded: ", sift_result)
            return sift_result
    
    # どの方法でも推定できない場合はヒント座標を返す
    print("No matches found, returning hint coordinates")
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
        
        # レスポンス返却
        return jsonify({
            'estimated_x': int(estimated_x),
            'estimated_y': int(estimated_y)
        }), 200
        
    except Exception as e:
        # エラーハンドリング
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
