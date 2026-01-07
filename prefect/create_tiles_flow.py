from prefect import flow
from datetime import timedelta, datetime
import math
from collections import defaultdict
from create_tiles.priority_task_runner import PriorityTaskRunner
from create_tiles.capture_strategy import CaptureStrategy
from create_tiles.config import (
    DELTA,
    MAP_TILES_X,
    MAP_TILES_Y,
    IMAGE_WIDTH,
    IMAGE_HEIGHT,
    IMAGE_MARGIN_WIDTH,
    IMAGE_MARGIN_HEIGHT,
    TILE_GROUP_SIZE,
    TILE_QUALITY_MAX_ZOOM,
    TILE_QUALITY_OTHER,
    TILE_SIZE,
    MAX_Z,
    FULL_WIDTH,
    FULL_HEIGHT,
)
from create_tiles.utils import (
    game_tile_to_screen_coord,
    game_tile_to_screen_lefttop_coord,
    screen_coord_to_map_tile,
    map_tile_to_screen_coord,
)
from create_tiles.tasks.capture_g import capture_g
from create_tiles.tasks.estimate_g import estimate_g
from create_tiles.tasks.tile_cut_g import tile_cut_g
from create_tiles.tasks.tile_merge_g import tile_merge_g
from create_tiles.tasks.tile_compress_g import tile_compress_g
from create_tiles.tasks.create_panel import create_panel

@flow(
    name='create_tiles',
    task_runner=PriorityTaskRunner(
        max_workers=14,
        concurrency_limits={
            "capture": 9,       # 2 replicas x 4 threads + 1
            "estimate": 5,      # 2 replicas x 2 workers + 1
            "tile-cut": 10,     # 4 replicas x 2 workers + 2 (本当は4 threadsあるが一旦保留)
            "tile-merge": 5,    # 2 replicas x 2 workers + 1 (本当は4 threadsあるが一旦保留)
            "tile-compress": 5, # 2 replicas x 2 workers + 1 (本当は4 threadsあるが一旦保留)
            "panel": 3,         # 1 replica  x 2 workers + 1 (本当は4 threadsあるが一旦保留)
        },
    ),
)
def create_tiles():
    strategy = CaptureStrategy(
        map_x=MAP_TILES_X,
        map_y=MAP_TILES_Y,
        delta=DELTA,
    )
    areas_groups = strategy.generate_capture_areas_groups()
    areas_to_group = {}
    for group in areas_groups:
        for area in group:
            areas_to_group[(area['x'], area['y'])] = group
    print(f"Total capture areas: {len(areas_to_group)}")

    # ---------- スクショ撮影タスク ----------
    capture_tasks = {}
    for group in areas_groups:
        tasks_in_group = []
        for area in group:
            tasks_in_group.append({
                "x": area['x'],
                "y": area['y'],
            })
        gx = group[0]['x']
        gy = group[0]['y']
        task_id = f"capture_g_x{gx}_y{gy}"
        priority = group[0]['priority']
        capture_tasks[task_id] = capture_g.with_options(
            name=task_id,
            retries=3,
            retry_delay_seconds=300,
            priority=priority,
        ).submit(tasks=tasks_in_group)
    # 撮影には依存関係は不要
    
    print(f"Total capture tasks: {len(capture_tasks)}")

    # ---------- スクショ座標推定タスク ----------
    estimate_tasks = {}
    for group in areas_groups:
        # capture_gの結果の複数のoutput_pathをestimate_gの外で分解することはできないので、関数に渡してから分解する必要がある
        # なので、具体的なestimate関数の引数の組み立てはestimate_gで行う
        # しかし、すべての情報を与えると依存関係が増えすぎるので、必要なものだけを渡す
        needed_capture_tasks = []
        needed_estimate_tasks = []

        gx = group[0]['x']
        gy = group[0]['y']
        # 同じエリアグループのcaptureタスクも必要
        needed_capture_tasks.append(capture_tasks[f"capture_g_x{gx}_y{gy}"])

        for area in group:
            for comp in area['compare']:
                belonging_group = areas_to_group[(comp['x'], comp['y'])]
                gxb = belonging_group[0]['x']
                gyb = belonging_group[0]['y']
                needed_capture_tasks.append(capture_tasks[f"capture_g_x{gxb}_y{gyb}"])
                if belonging_group[0]['area_id'] != group[0]['area_id']: # 自分自身のestimateは不要
                    needed_estimate_tasks.append(estimate_tasks[f"estimate_g_x{gxb}_y{gyb}"])
        # 重複を排除
        needed_capture_tasks = list(set(needed_capture_tasks))
        needed_estimate_tasks = list(set(needed_estimate_tasks))
        task_id = f"estimate_g_x{gx}_y{gy}"
        priority = group[0]['priority']
        estimate_tasks[task_id] = estimate_g.with_options(
            name=task_id,
            retries=3,
            retry_delay_seconds=300,
            priority=priority,
        ).submit(
            group=group, # estimate用のグループの情報をそのまま渡す
            capture_results=needed_capture_tasks,
            estimate_results=needed_estimate_tasks,
        )

    print(f"Total estimate tasks: {len(estimate_tasks)}")

    # ---------- 最大ズームタイル切り出しタスク ----------
    # タイル数が多いので、TILE_GROUP_SIZE x TILE_GROUP_SIZEごとにまとめて処理する

    # タイルの総数
    total_tiles_per_axis = 2 ** MAX_Z
    
    # マップが極端に小さい場合、グループサイズを調整
    actual_group_size = min(TILE_GROUP_SIZE, total_tiles_per_axis)

    # 各エリアのカバー範囲を事前計算
    print("Calculating area coverage...")
    area_coverage = []
    for group in areas_groups:
        for area in group:
            # areaのx, y座標はゲーム内タイル座標
            screen_coord = game_tile_to_screen_lefttop_coord(area['x'], area['y'])
            screen_x = screen_coord[0]
            screen_y = screen_coord[1]
            # 念の為もうちょっと余裕を持たせてキャプチャ範囲を計算
            capture_x_min = screen_x - IMAGE_MARGIN_WIDTH
            capture_y_min = screen_y - IMAGE_MARGIN_HEIGHT
            capture_x_max = screen_x + IMAGE_WIDTH + IMAGE_MARGIN_WIDTH
            capture_y_max = screen_y + IMAGE_HEIGHT + IMAGE_MARGIN_HEIGHT
            
            # スクショの4つの角のスクショ座標系での位置を計算
            corners_in_screen_coords = [
                (capture_x_min, capture_y_min),  # 左上
                (capture_x_max, capture_y_min),  # 右上
                (capture_x_min, capture_y_max),  # 左下
                (capture_x_max, capture_y_max),  # 右下
            ]

            # 4つの角をすべてタイル座標に変換
            corners_in_tile_coords = [
                screen_coord_to_map_tile(sx, sy, MAX_Z)
                for sx, sy in corners_in_screen_coords
            ]
            
            # 変換後のタイル座標の最小値と最大値を取得して、正確なタイル範囲を計算
            tile_x_min = min(p[0] for p in corners_in_tile_coords)
            tile_x_max = max(p[0] for p in corners_in_tile_coords)
            tile_y_min = min(p[1] for p in corners_in_tile_coords)
            tile_y_max = max(p[1] for p in corners_in_tile_coords)
            
            area_coverage.append({
                'area': area,
                'tile_x_min': tile_x_min,
                'tile_x_max': tile_x_max,
                'tile_y_min': tile_y_min,
                'tile_y_max': tile_y_max,
            })

    # エリアからtile_cutグループへのマッピングを作成
    print("Building group to areas mapping...")
    group_to_areas = defaultdict(set)
    for cov in area_coverage:
        # このエリアがカバーするグループ範囲を計算
        group_x_min = (max(0, cov['tile_x_min']) // actual_group_size) * actual_group_size
        group_x_max = (min(total_tiles_per_axis - 1, cov['tile_x_max']) // actual_group_size) * actual_group_size
        group_y_min = (max(0, cov['tile_y_min']) // actual_group_size) * actual_group_size
        group_y_max = (min(total_tiles_per_axis - 1, cov['tile_y_max']) // actual_group_size) * actual_group_size
        
        # 該当するすべてのグループにこのエリアを登録
        for gx in range(group_x_min, group_x_max + 1, actual_group_size):
            for gy in range(group_y_min, group_y_max + 1, actual_group_size):
                group_to_areas[(gx, gy)].add((cov['area']['x'], cov['area']['y']))

    # 各ズームレベルで存在するグループを計算
    print("Calculating existing groups for each zoom level...")
    existing_groups = {}
    existing_groups[MAX_Z] = set(group_to_areas.keys())
    
    for z in range(MAX_Z - 1, -1, -1):
        existing_groups[z] = set()
        for (cgx, cgy) in existing_groups[z + 1]:
            # 子グループのタイル範囲 → 親タイル範囲
            parent_tile_x_min = cgx // 2
            parent_tile_y_min = cgy // 2
            parent_tile_x_max = (cgx + actual_group_size - 1) // 2
            parent_tile_y_max = (cgy + actual_group_size - 1) // 2
            
            # 親タイル範囲 → 親グループ範囲
            parent_group_x_min = (parent_tile_x_min // actual_group_size) * actual_group_size
            parent_group_y_min = (parent_tile_y_min // actual_group_size) * actual_group_size
            parent_group_x_max = (parent_tile_x_max // actual_group_size) * actual_group_size
            parent_group_y_max = (parent_tile_y_max // actual_group_size) * actual_group_size
            
            # 親グループを登録
            for pgx in range(parent_group_x_min, parent_group_x_max + 1, actual_group_size):
                for pgy in range(parent_group_y_min, parent_group_y_max + 1, actual_group_size):
                    existing_groups[z].add((pgx, pgy))

    # グループ化してタイル切り出しタスクを生成
    print("Creating tile cut tasks...")
    tile_cut_tasks = {}
    for (gx, gy) in existing_groups[MAX_Z]:
        area_coords_set = group_to_areas[(gx, gy)]
        # capture_gとestimate_gの結果をtile_cut_gの外で分解することはできないので、関数に渡してから分解する必要がある
        # なので、具体的なtile_cut関数の引数の組み立てはtile_cut_gで行う
        # しかし、すべての情報を与えると依存関係が増えすぎるので、必要なものだけを渡す
        needed_capture_tasks = []
        needed_estimate_tasks = []
        
        # このグループに関連するエリアの座標リストを作成
        related_areas = []
        for (ax, ay) in area_coords_set:
            belonging_group = areas_to_group[(ax, ay)]
            gxb = belonging_group[0]['x']
            gyb = belonging_group[0]['y']
            
            # 依存タスクの登録
            needed_capture_tasks.append(capture_tasks[f"capture_g_x{gxb}_y{gyb}"])
            needed_estimate_tasks.append(estimate_tasks[f"estimate_g_x{gxb}_y{gyb}"])
            
            related_areas.append({"x": ax, "y": ay})
        
        # 重複を排除
        needed_capture_tasks = list(set(needed_capture_tasks))
        needed_estimate_tasks = list(set(needed_estimate_tasks))

        task_id = f"tile_cut_g_z{MAX_Z}_gx{gx}_gy{gy}"
        tile_cut_tasks[task_id] = tile_cut_g.with_options(
            name=task_id,
            retries=3,
            retry_delay_seconds=300,
        ).submit(
            gx=gx,
            gy=gy,
            related_areas=related_areas,
            capture_results=needed_capture_tasks,
            estimate_results=needed_estimate_tasks,
        )

    print(f"Total tile cut group tasks: {len(tile_cut_tasks)}")

    # ---------- タイルマージタスク ----------
    print("Creating tile merge tasks...")
    tile_merge_tasks = {}
    for z in range(MAX_Z - 1, -1, -1):
        for (gx, gy) in existing_groups[z]:
            child_results = []
            child_z = z + 1
            
            # 4つの子グループ座標を計算
            child_coords = [
                (gx * 2, gy * 2),
                (gx * 2 + actual_group_size, gy * 2),
                (gx * 2, gy * 2 + actual_group_size),
                (gx * 2 + actual_group_size, gy * 2 + actual_group_size),
            ]
            
            for (cgx, cgy) in child_coords:
                if child_z == MAX_Z:
                    child_task_id = f"tile_cut_g_z{child_z}_gx{cgx}_gy{cgy}"
                    if child_task_id in tile_cut_tasks:
                        child_results.append(tile_cut_tasks[child_task_id])
                else:
                    child_task_id = f"tile_merge_g_z{child_z}_gx{cgx}_gy{cgy}"
                    if child_task_id in tile_merge_tasks:
                        child_results.append(tile_merge_tasks[child_task_id])
            
            # 子タスクが1つもなければスキップ
            if len(child_results) == 0:
                continue
            
            task_id = f"tile_merge_g_z{z}_gx{gx}_gy{gy}"
            tile_merge_tasks[task_id] = tile_merge_g.with_options(
                name=task_id,
                retries=3,
                retry_delay_seconds=300,
            ).submit(
                z=z,
                gx=gx,
                gy=gy,
                child_results=child_results,
            )

    print(f"Total tile merge tasks: {len(tile_merge_tasks)}")

    # ---------- タイル圧縮タスク ----------
    print("Creating tile compress tasks...")
    tile_compress_tasks = {}
    
    # z=MAX_Zはtile_cut_gから
    for (gx, gy) in existing_groups[MAX_Z]:
        task_id = f"tile_cut_g_z{MAX_Z}_gx{gx}_gy{gy}"
        if task_id not in tile_cut_tasks:
            continue
        
        compress_task_id = f"tile_compress_g_z{MAX_Z}_gx{gx}_gy{gy}"
        tile_compress_tasks[compress_task_id] = tile_compress_g.with_options(
            name=compress_task_id,
            retries=3,
            retry_delay_seconds=300,
        ).submit(
            z=MAX_Z,
            gx=gx,
            gy=gy,
            tile_results=tile_cut_tasks[task_id],
            quality=TILE_QUALITY_MAX_ZOOM,
        )
    
    # z=MAX_Z-1〜0はtile_merge_gから
    for z in range(MAX_Z - 1, -1, -1):
        for (gx, gy) in existing_groups[z]:
            task_id = f"tile_merge_g_z{z}_gx{gx}_gy{gy}"
            if task_id not in tile_merge_tasks:
                continue
            
            compress_task_id = f"tile_compress_g_z{z}_gx{gx}_gy{gy}"
            tile_compress_tasks[compress_task_id] = tile_compress_g.with_options(
                name=compress_task_id,
                retries=3,
                retry_delay_seconds=300,
            ).submit(
                z=z,
                gx=gx,
                gy=gy,
                tile_results=tile_merge_tasks[task_id],
                quality=TILE_QUALITY_OTHER,
            )

    # ---------- 一枚絵生成タスク ----------
    print("Creating final panel task...")
    resolutions = [
        {"width": 1280, "height": 720, "id": "hd"}, # HD
        {"width": 1920, "height": 1080, "id": "fhd"}, # Full HD
        {"width": 2560, "height": 1440, "id": "wqhd"}, # WQHD
        {"width": 3440, "height": 1440, "id": "uwqhd"}, # UWQHD
        {"width": 3840, "height": 2160, "id": "4k"}, # 4K
        {"width": 5120, "height": 2880, "id": "5k"}, # 5K
        {"width": 7680, "height": 4320, "id": "8k"}, # 8K
    ]
    create_panel_tasks = {}
    for res in resolutions:
        # 解像度を満たすのに必要なzoomレベルを計算
        scale_x = res['width'] / TILE_SIZE # 横方向に必要なタイル数
        scale_y = res['height'] / TILE_SIZE # 縦方向に必要なタイル数
        scale = max(scale_x, scale_y)
        z_plus = math.log2(scale) # scaleで倍率が上がるので、その分を補正
        z = min(
            MAX_Z,
            max(0, int(math.ceil(math.log2(scale) + z_plus)))
        )
        print(f"Resolution {res['id']} ({res['width']}x{res['height']}) requires zoom level {z}")
        # このズームレベルで存在するグループをすべて収集
        needed_tile_cut_merge_tasks = []
        for (gx, gy) in existing_groups[z]:
            tile_cut_task_id = f"tile_cut_g_z{z}_gx{gx}_gy{gy}"
            tile_merge_task_id = f"tile_merge_g_z{z}_gx{gx}_gy{gy}"
            if z == MAX_Z and tile_cut_task_id in tile_cut_tasks:
                needed_tile_cut_merge_tasks.append(tile_cut_tasks[tile_cut_task_id])
            elif z < MAX_Z and tile_merge_task_id in tile_merge_tasks:
                needed_tile_cut_merge_tasks.append(tile_merge_tasks[tile_merge_task_id])
        task_id = f"panel_{res['id']}"
        create_panel_tasks[task_id] = create_panel.with_options(
            name=task_id,
            retries=3,
            retry_delay_seconds=300,
        ).submit(
            z=z,
            resolution=res,
            tile_results=needed_tile_cut_merge_tasks,
        )

    print(f"Total panel tasks: {len(create_panel_tasks)}")
