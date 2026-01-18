from typing import List, Dict, Tuple

PRIORITY_CONSTANT = 1000000 # 適当な大きい数値
LARGE_GROUP_SIZE = 100 # 基本的なグループ分割のサイズ
SMALL_GROUP_SIZE = 5 # 最初の斜め移動用のグループ分割のサイズ(早く依存タスクを開始するために小さめの値を指定する)

class CaptureStrategy:
    def __init__(self, map_x: int, map_y: int, delta: int):
        self.map_x = map_x - 1 # うっかりマップサイズと最大座標を間違えてしまったので、-1しておく
        self.map_y = map_y - 1
        self.delta = delta
    
    def generate_capture_areas_groups(self) -> List[List[Dict]]:
        """撮影エリアリストを生成（グループ化）"""
        screenshots = [[]]  # リストのリストとして初期化
        
        if self.map_x >= self.map_y:
            self._generate_x_ge_y(screenshots)
        else:
            self._generate_x_lt_y(screenshots)

        screenshots = self._remove_duplicates(screenshots)
        
        # 空のグループを除去
        screenshots = [group for group in screenshots if group]
        
        return screenshots

    # 重複を削除
    def _remove_duplicates(self, screenshots: List[List[Dict]]) -> List[List[Dict]]:
        seen = set()
        result = []
        
        for group in screenshots:
            unique_group = []
            for shot in group:
                identifier = (shot['x'], shot['y'])
                if identifier not in seen:
                    seen.add(identifier)
                    unique_group.append(shot)
            if unique_group:  # 空でないグループのみ追加
                result.append(unique_group)
        
        return result
    
    def _left(self, x: int, y: int) -> Tuple[int, int]:
        """左側への移動（境界制限付き）"""
        ideal_x = x - self.delta // 2
        ideal_y = y + self.delta // 2
        
        if ideal_y > self.map_y:
            ideal_y = self.map_y
            ideal_x = x - (self.map_y - y)
        if ideal_x < 0:
            ideal_x = 0
            ideal_y = y + x
        
        return ideal_x, ideal_y
    
    def _right(self, x: int, y: int) -> Tuple[int, int]:
        """右側への移動（境界制限付き）"""
        ideal_x = x + self.delta // 2
        ideal_y = y - self.delta // 2
        
        if ideal_y < 0:
            ideal_y = 0
            ideal_x = x + y
        if ideal_x > self.map_x:
            ideal_x = self.map_x
            ideal_y = y - (self.map_x - x)
        
        return ideal_x, ideal_y
    
    def _down(self, x: int, y: int) -> Tuple[int, int]:
        """下側への移動（境界制限付き）"""
        ideal_x = x + self.delta // 2
        ideal_y = y + self.delta // 2
        
        if ideal_x > self.map_x:
            ideal_x = self.map_x
            ideal_y = y + (self.map_x - x)
        if ideal_y > self.map_y:
            ideal_y = self.map_y
            ideal_x = x + (self.map_y - y)
        
        return ideal_x, ideal_y

    def _up(self, x: int, y: int) -> Tuple[int, int]:
        """上側への移動（境界制限付き）"""
        ideal_x = x - self.delta // 2
        ideal_y = y - self.delta // 2
        
        if ideal_x < 0:
            ideal_x = 0
            ideal_y = y - x
        if ideal_y < 0:
            ideal_y = 0
            ideal_x = x - y
        
        return ideal_x, ideal_y
    
    def _exists_in_screenshots(self, x: int, y: int, screenshots: List[List[Dict]], exclude: Tuple[int, int]=None) -> bool:
        """指定座標が既にscreenshots内に存在するか確認"""
        for group in screenshots:
            for shot in group:
                if exclude and shot['x'] == exclude[0] and shot['y'] == exclude[1]:
                    continue
                if shot['x'] == x and shot['y'] == y:
                    return True
        return False
    
    def _generate_x_ge_y(self, screenshots: List[List[Dict]]):
        """map_x >= map_yの場合の生成ロジック"""
        current_x, current_y = 0, 0
        screenshots[-1].append({
            'area_id': 0,
            'x': current_x, 'y': current_y,
            'compare': [],
            'priority': PRIORITY_CONSTANT * 4,
        })
        
        flag1 = []
        area_id = 1
        
        # PHASE 1: ジグザグ走査
        priority = PRIORITY_CONSTANT * 3
        while True:
            # 下に移動
            new_x, new_y = self._down(current_x, current_y)
            screenshots[-1].append({
                'area_id': area_id,
                'x': new_x, 'y': new_y,
                'compare': [{'x': current_x, 'y': current_y}],
                'priority': priority,
            })
            area_id += 1
            current_x, current_y = new_x, new_y
            flag1.append({'x': current_x, 'y': current_y})
            # 右下辺に到達したら終了
            if current_x == self.map_x:
                break
            priority -= 1
            
            # 右に移動
            new_x, new_y = self._right(current_x, current_y)
            screenshots[-1].append({
                'area_id': area_id,
                'x': new_x, 'y': new_y,
                'compare': [{'x': current_x, 'y': current_y}],
                'priority': priority,
            })
            area_id += 1
            current_x, current_y = new_x, new_y
            # 右下辺に到達したら終了
            if current_x == self.map_x:
                break
            priority -= 1

            if len(screenshots[-1]) >= SMALL_GROUP_SIZE:
                screenshots.append([])

        if screenshots[-1] != []:
            screenshots.append([])
        
        # PHASE 2: 左方向への走査
        priority = PRIORITY_CONSTANT * 2
        for start_point in flag1:
            if start_point == flag1[-1]:  # 最後の行は優先度高め
                priority = PRIORITY_CONSTANT * 2
            current_x, current_y = start_point['x'], start_point['y']
            while True:
                new_x, new_y = self._left(current_x, current_y)
                if new_x == current_x and new_y == current_y:
                    break
                compare = [{'x': current_x, 'y': current_y}]
                up_x, up_y = self._up(new_x, new_y)
                if self._exists_in_screenshots(up_x, up_y, screenshots, exclude=(current_x, current_y)):
                    compare.append({'x': up_x, 'y': up_y})
                screenshots[-1].append({
                    'area_id': area_id,
                    'x': new_x, 'y': new_y,
                    'compare': compare,
                    'priority': priority,
                })
                area_id += 1
                current_x, current_y = new_x, new_y
                priority -= 1

                if len(screenshots[-1]) >= LARGE_GROUP_SIZE:
                    screenshots.append([])

            if screenshots[-1] != []:
                screenshots.append([])

        # PHASE 3: 下方向への走査
        last_line = flag1[-1]
        start_points = []
        current_x, current_y = last_line['x'], last_line['y']
        priority = PRIORITY_CONSTANT
        while True:
            start_points.append({'x': current_x, 'y': current_y})
            new_x, new_y = self._left(current_x, current_y)
            if new_x == current_x and new_y == current_y:
                break
            current_x, current_y = new_x, new_y
        
        for start_point in start_points:
            current_x, current_y = start_point['x'], start_point['y']
            while True:
                new_x, new_y = self._down(current_x, current_y)
                if new_x == current_x and new_y == current_y:
                    break
                compare = [{'x': current_x, 'y': current_y}]
                right_x, right_y = self._right(new_x, new_y)
                if self._exists_in_screenshots(right_x, right_y, screenshots, exclude=(current_x, current_y)):
                    compare.append({'x': right_x, 'y': right_y})
                screenshots[-1].append({
                    'area_id': area_id,
                    'x': new_x, 'y': new_y,
                    'compare': compare,
                    'priority': priority,
                })
                area_id += 1
                current_x, current_y = new_x, new_y
                priority -= 1

                if len(screenshots[-1]) >= LARGE_GROUP_SIZE:
                    screenshots.append([])

            if screenshots[-1] != []:
                screenshots.append([])
    
    def _generate_x_lt_y(self, screenshots: List[List[Dict]]):
        """map_x < map_yの場合の生成ロジック"""
        current_x, current_y = 0, 0
        screenshots[-1].append({
            'area_id': 0,
            'x': current_x, 'y': current_y,
            'compare': [],
            'priority': PRIORITY_CONSTANT * 4,
        })
        
        flag1 = []
        area_id = 1
        
        # PHASE 1: ジグザグ走査（左方向）
        privacy = PRIORITY_CONSTANT * 3
        while True:
            # 下に移動
            new_x, new_y = self._down(current_x, current_y)
            screenshots[-1].append({
                'area_id': area_id,
                'x': new_x, 'y': new_y,
                'compare': [{'x': current_x, 'y': current_y}],
                'priority': privacy,
            })
            area_id += 1
            current_x, current_y = new_x, new_y
            flag1.append({'x': current_x, 'y': current_y})
            # 左下辺に到達したら終了
            if current_y == self.map_y:
                break
            privacy -= 1
            
            # 左に移動
            new_x, new_y = self._left(current_x, current_y)
            screenshots[-1].append({
                'area_id': area_id,
                'x': new_x, 'y': new_y,
                'compare': [{'x': current_x, 'y': current_y}],
                'priority': privacy,
            })
            area_id += 1
            current_x, current_y = new_x, new_y
            # 左下辺に到達したら終了
            if current_y == self.map_y:
                break
            privacy -= 1
            
            if len(screenshots[-1]) >= SMALL_GROUP_SIZE:
                screenshots.append([])
        
        if screenshots[-1] != []:
            screenshots.append([])
        
        # PHASE 2: 右方向への走査
        priority = PRIORITY_CONSTANT * 2
        for start_point in flag1:
            if start_point == flag1[-1]:  # 最後の行は優先度高め
                priority = PRIORITY_CONSTANT * 2
            current_x, current_y = start_point['x'], start_point['y']
            while True:
                new_x, new_y = self._right(current_x, current_y)
                if new_x == current_x and new_y == current_y:
                    break
                up_x, up_y = self._up(new_x, new_y)
                compare = [{'x': current_x, 'y': current_y}]
                if self._exists_in_screenshots(up_x, up_y, screenshots, exclude=(current_x, current_y)):
                    compare.append({'x': up_x, 'y': up_y})
                screenshots[-1].append({
                    'area_id': area_id,
                    'x': new_x, 'y': new_y,
                    'compare': compare,
                    'priority': priority,
                })
                area_id += 1
                current_x, current_y = new_x, new_y
                priority -= 1
                
                if len(screenshots[-1]) >= LARGE_GROUP_SIZE:
                    screenshots.append([])
            
            if screenshots[-1] != []:
                screenshots.append([])
        
        # PHASE 3: 下方向への走査
        last_line = flag1[-1]
        start_points = []
        current_x, current_y = last_line['x'], last_line['y']
        while True:
            start_points.append({'x': current_x, 'y': current_y})
            new_x, new_y = self._right(current_x, current_y)
            if new_x == current_x and new_y == current_y:
                break
            current_x, current_y = new_x, new_y
        
        priority = PRIORITY_CONSTANT
        for start_point in start_points:
            current_x, current_y = start_point['x'], start_point['y']
            while True:
                new_x, new_y = self._down(current_x, current_y)
                if new_x == current_x and new_y == current_y:
                    break
                left_x, left_y = self._left(new_x, new_y)
                compare = [{'x': current_x, 'y': current_y}]
                if self._exists_in_screenshots(left_x, left_y, screenshots, exclude=(current_x, current_y)):
                    compare.append({'x': left_x, 'y': left_y})
                screenshots[-1].append({
                    'area_id': area_id,
                    'x': new_x, 'y': new_y,
                    'compare': compare,
                    'priority': priority,
                })
                area_id += 1
                current_x, current_y = new_x, new_y
                priority -= 1
                
                if len(screenshots[-1]) >= LARGE_GROUP_SIZE:
                    screenshots.append([])

            if screenshots[-1] != []:
                screenshots.append([])

# テスト
if __name__ == "__main__":
    import os
    map_x = 512
    map_y = 32
    delta = 20
    strategy = CaptureStrategy(map_x, map_y, delta)
    area_groups = strategy.generate_capture_areas_groups()
    
    for group_idx, group in enumerate(area_groups):
        print(f"\n=== Group {group_idx} ({len(group)} items) ===")
        for area in group:
            print(area)
