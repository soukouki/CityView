from flask import Flask, request, jsonify
import cv2
import numpy as np
import requests
import os
import gc
from math import sqrt

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
MARGIN_AVG = (IMAGE_MARGIN_WIDTH + IMAGE_MARGIN_HEIGHT) / 2

# スコアリングパラメータ
TOP_N_MATCHES = 100
SIFT_MAX_DISTANCE = 300.0
PROXIMITY_REJECT_FACTOR = 3
PROXIMITY_ZERO_FACTOR = 2


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


def calculate_sift_score(match_distance):
    """
    SIFTマッチのdistanceをスコア化（線形、0-1）
    
    Args:
        match_distance: cv2.DMatchのdistance値
    
    Returns:
        スコア（0.0-1.0、小さいdistanceほど高スコア）
    """
    score = max(0.0, 1.0 - match_distance / SIFT_MAX_DISTANCE)
    return score


def calculate_proximity_score(x, y, hint_x, hint_y):
    """
    ヒント座標との近さをスコア化（線形、0-1）
    
    Args:
        x, y: 推定座標
        hint_x, hint_y: ヒント座標
    
    Returns:
        スコア（0.0-1.0、近いほど高スコア）、または None（除外対象）
    """
    distance = sqrt((x - hint_x)**2 + (y - hint_y)**2)
    
    # 距離がMARGIN_AVGの3倍を超えたら除外
    if distance > PROXIMITY_REJECT_FACTOR * MARGIN_AVG:
        return None
    
    # 線形スコア計算（2倍で0）
    score = max(0.0, 1.0 - distance / (PROXIMITY_ZERO_FACTOR * MARGIN_AVG))
    return score


def collect_sift_candidates(target_img, ref_img, ref_x, ref_y, hint_x, hint_y, source_id):
    """
    1つの参照画像からSIFT候補を複数収集
    
    Args:
        target_img: 座標未知の画像
        ref_img: 参照画像
        ref_x, ref_y: 参照画像の座標
        hint_x, hint_y: ヒント座標
        source_id: デバッグ用の識別子
    
    Returns:
        候補のリスト（辞書のリスト）
    """
    candidates = []
    
    try:
        # 縮小する(0.125倍)
        # 予想として、シムトラのスクショのズレは標高などの影響を受けるため、キリの良い値になる
        target_resized = cv2.resize(target_img, (0, 0), fx=0.125, fy=0.125, interpolation=cv2.INTER_LINEAR)
        ref_resized = cv2.resize(ref_img, (0, 0), fx=0.125, fy=0.125, interpolation=cv2.INTER_LINEAR)
        
        # グレースケール変換
        gray1 = cv2.cvtColor(target_resized, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(ref_resized, cv2.COLOR_BGR2GRAY)
        
        # SIFT検出器
        sift = cv2.SIFT_create()
        kp1, des1 = sift.detectAndCompute(gray1, None)
        kp2, des2 = sift.detectAndCompute(gray2, None)
        
        if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
            print(f"SIFT detection failed for {source_id}: insufficient keypoints", flush=True)
            return []
        
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
            print(f"SIFT matching failed for {source_id}: only {len(good_matches)} good matches", flush=True)
            return []
        
        # 距離でソート（良い順）
        good_matches.sort(key=lambda m: m.distance)
        
        # 上位TOP_N_MATCHESを処理
        for match in good_matches[:TOP_N_MATCHES]:
            # このマッチから座標を推定
            pt1 = kp1[match.queryIdx].pt
            pt2 = kp2[match.trainIdx].pt
            
            # 移動量を計算（縮小前の座標系に戻す）
            dx = (pt2[0] - pt1[0]) * 8
            dy = (pt2[1] - pt1[1]) * 8
            
            # 推定座標
            estimated_x = ref_x + dx
            estimated_y = ref_y + dy
            
            # SIFTスコア計算
            sift_score = calculate_sift_score(match.distance)
            
            # 近さスコア計算
            proximity_score = calculate_proximity_score(
                estimated_x, estimated_y, hint_x, hint_y
            )
            
            # 除外判定
            if proximity_score is None:
                continue
            
            # 総合スコア
            total_score = sift_score + proximity_score
            
            # 候補に追加
            candidates.append({
                'x': int(estimated_x),
                'y': int(estimated_y),
                'sift_score': sift_score,
                'proximity_score': proximity_score,
                'total_score': total_score,
                'raw_sift_distance': match.distance,
                'raw_proximity': sqrt((estimated_x - hint_x)**2 + (estimated_y - hint_y)**2),
                'source': f'sift:{source_id}'
            })
        
        print(f"Collected {len(candidates)} candidates from {source_id}", flush=True)
        return candidates
        
    except Exception as e:
        print(f"SIFT candidate collection failed for {source_id}: {str(e)}", flush=True)
        return []


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
    print(f"MARGIN_AVG: {MARGIN_AVG}", flush=True)
    print(f"Hint coordinates: ({hint_x}, {hint_y})", flush=True)
    
    all_candidates = []
    
    # 各参照画像から候補を収集
    for idx, (ref_img, ref_x, ref_y) in enumerate(adjacent_images):
        print(f"Processing reference image {idx} at ({ref_x}, {ref_y})", flush=True)
        
        candidates = collect_sift_candidates(
            target_img, ref_img, ref_x, ref_y,
            hint_x, hint_y, f'ref_{idx}'
        )
        
        all_candidates.extend(candidates)
    
    # ヒント座標を候補として追加
    hint_candidate = {
        'x': hint_x,
        'y': hint_y,
        'sift_score': 0.0,
        'proximity_score': 1.0,
        'total_score': 1.0,
        'raw_sift_distance': float('inf'),
        'raw_proximity': 0.0,
        'source': 'hint'
    }
    all_candidates.append(hint_candidate)
    
    print(f"Total candidates (including hint): {len(all_candidates)}", flush=True)
    
    # 総合スコアでソート
    all_candidates.sort(key=lambda c: c['total_score'], reverse=True)
    
    # トップ5をログ出力
    print("Top 5 candidates:", flush=True)
    for i, c in enumerate(all_candidates[:5]):
        print(f"  {i+1}. ({c['x']}, {c['y']}) "
              f"total={c['total_score']:.3f} "
              f"(sift={c['sift_score']:.3f}, prox={c['proximity_score']:.3f}) "
              f"source={c['source']}", flush=True)
    
    # 最良の候補を返す
    best = all_candidates[0]
    print(f"Selected: ({best['x']}, {best['y']}) from {best['source']}", flush=True)
    
    return best['x'], best['y']


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
