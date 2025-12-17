"""
撮影戦略のPython移植版
Rubyコードのロジックを忠実に再現
"""

from typing import List, Dict, Tuple

class CaptureStrategy:
    def __init__(self, map_x: int, map_y: int, delta: int):
        self.map_x = map_x
        self.map_y = map_y
        self.delta = delta
    
    def generate_capture_areas(self) -> List[Dict]:
        """撮影エリアリストを生成"""
        screenshots = []
        
        if self.map_x >= self.map_y:
            self._generate_x_ge_y(screenshots)
        else:
            self._generate_x_lt_y(screenshots)

        screenshots = self._remove_duplicates(screenshots)
        
        return screenshots

    # 重複を削除
    def _remove_duplicates(self, screenshots: List[Dict]) -> List[Dict]:
        seen = set()
        unique_screenshots = []
        for shot in screenshots:
            identifier = (shot['x'], shot['y'])
            if identifier not in seen:
                seen.add(identifier)
                unique_screenshots.append(shot)
        return unique_screenshots
    
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
    
    def _generate_x_ge_y(self, screenshots: List[Dict]):
        """map_x >= map_yの場合の生成ロジック"""
        current_x, current_y = 0, 0
        screenshots.append({
            'area_id': 0,
            'x': current_x, 'y': current_y,
            'compare': []
        })
        
        flag1 = []
        area_id = 1
        
        # PHASE 1: ジグザグ走査
        while True:
            # 下に移動
            new_x, new_y = self._down(current_x, current_y)
            screenshots.append({
                'area_id': area_id,
                'x': new_x, 'y': new_y,
                'compare': [{'x': current_x, 'y': current_y}]
            })
            area_id += 1
            current_x, current_y = new_x, new_y
            flag1.append({'x': current_x, 'y': current_y})
            if current_y == self.map_y:
                break
            
            # 右に移動
            new_x, new_y = self._right(current_x, current_y)
            screenshots.append({
                'area_id': area_id,
                'x': new_x, 'y': new_y,
                'compare': [{'x': current_x, 'y': current_y}]
            })
            area_id += 1
            current_x, current_y = new_x, new_y
            if current_x == self.map_x:
                break
        
        # PHASE 2: 左方向への走査
        for start_point in flag1:
            current_x, current_y = start_point['x'], start_point['y']
            while True:
                new_x, new_y = self._left(current_x, current_y)
                if new_x == current_x and new_y == current_y:
                    break
                screenshots.append({
                    'area_id': area_id,
                    'x': new_x, 'y': new_y,
                    'compare': [{'x': current_x, 'y': current_y}]
                })
                area_id += 1
                current_x, current_y = new_x, new_y
        
        # PHASE 3: 下方向への走査
        last_line = flag1[-1]
        start_points = []
        current_x, current_y = last_line['x'], last_line['y']
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
                screenshots.append({
                    'area_id': area_id,
                    'x': new_x, 'y': new_y,
                    'compare': [{'x': current_x, 'y': current_y}]
                })
                area_id += 1
                current_x, current_y = new_x, new_y
    
    def _generate_x_lt_y(self, screenshots: List[Dict]):
        """map_x < map_yの場合の生成ロジック"""
        current_x, current_y = 0, 0
        screenshots.append({
            'area_id': 0,
            'x': current_x, 'y': current_y,
            'compare': []
        })
        
        flag1 = []
        area_id = 1
        
        # PHASE 1: ジグザグ走査（左方向）
        while True:
            # 下に移動
            new_x, new_y = self._down(current_x, current_y)
            screenshots.append({
                'area_id': area_id,
                'x': new_x, 'y': new_y,
                'compare': [{'x': current_x, 'y': current_y}]
            })
            area_id += 1
            current_x, current_y = new_x, new_y
            flag1.append({'x': current_x, 'y': current_y})
            if current_y == self.map_y:
                break
            
            # 左に移動
            new_x, new_y = self._left(current_x, current_y)
            screenshots.append({
                'area_id': area_id,
                'x': new_x, 'y': new_y,
                'compare': [{'x': current_x, 'y': current_y}]
            })
            area_id += 1
            current_x, current_y = new_x, new_y
            if current_x == self.map_x:
                break
        
        # PHASE 2: 右方向への走査
        for start_point in flag1:
            current_x, current_y = start_point['x'], start_point['y']
            while True:
                new_x, new_y = self._right(current_x, current_y)
                if new_x == current_x and new_y == current_y:
                    break
                screenshots.append({
                    'area_id': area_id,
                    'x': new_x, 'y': new_y,
                    'compare': [{'x': current_x, 'y': current_y}]
                })
                area_id += 1
                current_x, current_y = new_x, new_y
        
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
        
        for start_point in start_points:
            current_x, current_y = start_point['x'], start_point['y']
            while True:
                new_x, new_y = self._down(current_x, current_y)
                if new_x == current_x and new_y == current_y:
                    break
                screenshots.append({
                    'area_id': area_id,
                    'x': new_x, 'y': new_y,
                    'compare': [{'x': current_x, 'y': current_y}]
                })
                area_id += 1
                current_x, current_y = new_x, new_y
