from airflow import DAG
from datetime import datetime
import math
from collections import defaultdict
from create_tiles.capture_strategy import CaptureStrategy
from create_tiles.config import (
    DELTA,
    MAP_TILES_X,
    MAP_TILES_Y,
    IMAGE_WIDTH,
    IMAGE_HEIGHT,
    IMAGE_MARGIN_WIDTH,
    IMAGE_MARGIN_HEIGHT,
    ENABLE_WIDTH,
    ENABLE_HEIGHT,
    TILE_GROUP_SIZE,
    MAX_Z,
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

with DAG(
    dag_id='create_tiles',
    catchup=False,
    start_date=datetime(2024, 1, 1),
    schedule=None,
    params={
        "save_data_name": "demo",
    },
) as dag:

    strategy = CaptureStrategy(
        map_x=MAP_TILES_X,
        map_y=MAP_TILES_Y,
        delta=DELTA,
    )
    areas_groups = strategy.generate_capture_areas_groups()
    save_data_name = dag.params["save_data_name"]
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
                "save_data_name": save_data_name,
                "x": area['x'],
                "y": area['y'],
                "output_path": f"/images/screenshots/{save_data_name}/x{area['x']}_y{area['y']}.png",
            })
        gx = group[0]['x']
        gy = group[0]['y']
        task_id = f"capture_g_x{gx}_y{gy}"
        capture_tasks[task_id] = capture_g.override(
            task_id=task_id,
            queue="capture",
            priority_weight=group[0]['priority'],
        )(tasks=tasks_in_group)
    # 撮影には依存関係は不要
    
    print(f"Total capture tasks: {len(capture_tasks)}")

    # ---------- スクショ座標推定タスク ----------
    estimate_tasks = {}
    for group in areas_groups:
        # capture_gの結果の複数のoutput_pathをestimate_gの外で分解することはできないので、関数に渡してから分解する必要がある
        # なので、具体的なestimate関数の引数の組み立てはestimate_gで行う
        # しかし、すべての情報を与えると依存関係が増えすぎるので、必要なものだけを渡す
        needed_tasks_gx_gy = []
        needed_capture_tasks = []
        needed_estimate_tasks = []

        for area in group:
            for comp in area['compare']:
                belonging_group = areas_to_group[(comp['x'], comp['y'])]
                gx = belonging_group[0]['x']
                gy = belonging_group[0]['y']
                if (gx, gy) in needed_tasks_gx_gy: # 重複チェック
                    continue
                needed_tasks_gx_gy.append((gx, gy))
                needed_capture_tasks.append(capture_tasks[f"capture_g_x{gx}_y{gy}"])
                if belonging_group != group: # 自分自身のestimateは不要
                    needed_estimate_tasks.append(estimate_tasks[f"estimate_g_x{gx}_y{gy}"])
        gx = group[0]['x']
        gy = group[0]['y']
        task_id = f"estimate_g_x{gx}_y{gy}"
        estimate_tasks[task_id] = estimate_g.override(
            task_id=f"estimate_g_x{gx}_y{gy}",
            queue="estimate",
            priority_weight=group[0]['priority'],
        )(
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

    # 各エリアのカバー範囲を事前計算し、空間インデックスを作成
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
                'screen_x_min': capture_x_min,
                'screen_y_min': capture_y_min,
                'screen_x_max': capture_x_max,
                'screen_y_max': capture_y_max,
            })

    # タイル座標からカバーするエリアへの逆引きマップを作成
    tile_to_areas = defaultdict(list)
    for cov in area_coverage:
        # このエリアがカバーするタイル範囲を列挙
        for tx in range(max(0, cov['tile_x_min']), min(total_tiles_per_axis, cov['tile_x_max'] + 1)):
            for ty in range(max(0, cov['tile_y_min']), min(total_tiles_per_axis, cov['tile_y_max'] + 1)):
                tile_to_areas[(tx, ty)].append(cov)

    # グループ化してタイル切り出しタスクを生成
    tile_cut_tasks = {}
    tiles = {} # 後のタイルマージ用に記録しておく
    for gx in range(0, total_tiles_per_axis, actual_group_size):
        for gy in range(0, total_tiles_per_axis, actual_group_size):
            # capture_gとestimate_gの結果をtile_cut_gの外で分解することはできないので、関数に渡してから分解する必要がある
            # なので、具体的なtile_cut関数の引数の組み立てはtile_cut_gで行う
            # しかし、すべての情報を与えると依存関係が増えすぎるので、必要なものだけを渡す
            needed_tasks_gx_gy = []
            needed_capture_tasks = []
            needed_estimate_tasks = []
            tasks = [] # tile_cut_gにおいて、どんなタスクを処理すれば良いのかを渡すための情報

            for tx in range(gx, min(gx + actual_group_size, total_tiles_per_axis)):
                for ty in range(gy, min(gy + actual_group_size, total_tiles_per_axis)):
                    # このタイルをカバーするスクショ座標の範囲を計算
                    screen_min = map_tile_to_screen_coord(tx, ty, MAX_Z)
                    screen_max = map_tile_to_screen_coord(tx + 1, ty + 1, MAX_Z)
                    screen_x_min = screen_min[0]
                    screen_y_min = screen_min[1]
                    screen_x_max = screen_max[0]
                    screen_y_max = screen_max[1]
                    
                    # 空間インデックスから候補を取得し、正確な重なり判定のみ実行
                    candidate_areas = tile_to_areas.get((tx, ty), [])
                    covering_images = []
                    
                    for cov in candidate_areas:
                        # 正確な重なり判定(念のため再確認)
                        if not (cov['screen_x_max'] < screen_x_min or cov['screen_x_min'] > screen_x_max or
                                cov['screen_y_max'] < screen_y_min or cov['screen_y_min'] > screen_y_max):
                            covering_images.append({
                                "x": cov['area']['x'],
                                "y": cov['area']['y'],
                            })

                    # 該当タイルをカバーする画像があれば、tile_cutタスク用の情報に追加する
                    images = []
                    for img in covering_images:
                        belonging_group = areas_to_group[(img['x'], img['y'])]
                        gxb = belonging_group[0]['x']
                        gyb = belonging_group[0]['y']
                        if (gxb, gyb) in needed_tasks_gx_gy: # 重複チェック
                            continue
                        needed_tasks_gx_gy.append((gxb, gyb))
                        needed_capture_tasks.append(capture_tasks[f"capture_g_x{gxb}_y{gyb}"])
                        needed_estimate_tasks.append(estimate_tasks[f"estimate_g_x{gxb}_y{gyb}"])
                        images.append({
                            "x": img['x'], # tile_cut_g内で処理するための情報として渡すので、pathではなく座標のみ
                            "y": img['y'], # この座標はゲーム内タイル座標。estimate_gの結果からスクショ座標を取得してtile_cut_g内で処理する
                        })

                    # 画像が1つもないとき(=地図タイルがマップ外)はタスクを作らない
                    if images == []:
                        continue
                    
                    tasks.append({
                        "x": tx,
                        "y": ty,
                        "images": images,
                        "output_path": f"/images/rawtiles/{save_data_name}/{MAX_Z}/{tx}/{ty}.png",
                    })
        
            # タスクが1つもないとき(=グループごとマップ外)はグループタスクを作らない
            if len(needed_tasks_gx_gy) == 0:
                continue

            task_id = f"tile_cut_g_z{MAX_Z}_gx{gx}_gy{gy}"
            tile_cut_tasks[task_id] = tile_cut_g.override(
                task_id=task_id,
                queue="tile_cut",
            )(
                gx=gx,
                gy=gy,
                tasks=tasks,
                capture_results=needed_capture_tasks,
                estimate_results=needed_estimate_tasks,
            )

    print(f"Total tile cut group tasks: {len(tile_cut_tasks)}")
    exit()

    # # ---------- タイルマージタスク ----------
    # tile_merge_tasks = {}
    # for z in range(MAX_Z - 1, -1, -1): # MAX_Z-1から0まで
    #     tiles_per_axis = 2 ** MAX_Z
    #     for gx in range(0, tiles_per_axis, TILE_GROUP_SIZE):
    #         for gy in range(0, tiles_per_axis, TILE_GROUP_SIZE):
    #             tasks_in_group = []
    #             for tx in range(gx, gx + TILE_GROUP_SIZE, 1):
    #                 for ty in range(gy, gy + TILE_GROUP_SIZE, 1):
    #                     merge_tiles = []
    #                     positions = ["top-left", "bottom-left", "top-right", "bottom-right"]
    #                     for dx in range(2):
    #                         for dy in range(2):
    #                             child_z = z + 1
    #                             child_x = tx * 2 + dx
    #                             child_y = ty * 2 + dy
    #                             if (child_z, child_x, child_y) in tiles:
    #                                 merge_tiles.append({
    #                                     "path": f"/images/rawtiles/{save_data_name}/{child_z}/{child_x}/{child_y}.png",
    #                                     "position": positions[dx * 2 + dy],
    #                                 })
    #                     if len(merge_tiles) == 0:
    #                         continue
    #                     tasks_in_group.append({
    #                         "tiles": merge_tiles,
    #                         "output_path": f"/images/rawtiles/{save_data_name}/{z}/{tx}/{ty}.png",
    #                     })
    #                     tiles[(z, tx, ty)] = True
    #             if len(tasks_in_group) == 0:
    #                 continue
    #             task_id = f"tile_merge_g_z{z}_gx{gx}_gy{gy}"
    #             tile_merge_tasks[task_id] = tile_merge_g.override(task_id=task_id, queue="tile_merge")(
    #                 tasks=tasks_in_group,
    #             )

    # # 依存関係の設定
    # # 最大ズーム-1ならtile_cutタスクから、それ以外は下位のtile_mergeタスクから依存関係を設定
    # for task_id, _ in tile_merge_tasks.items():
    #     parts = task_id.split('_')
    #     z = int(parts[3][1:])
    #     gx = int(parts[4][2:])
    #     gy = int(parts[5][2:])
    #     child_coords = []
    #     for tx in range(gx, gx + TILE_GROUP_SIZE, 1):
    #         for ty in range(gy, gy + TILE_GROUP_SIZE, 1):
    #             child_coords.append((z + 1, tx * 2, ty * 2))
    #     if z + 1 == MAX_Z:
    #         for coord in child_coords:
    #             child_task_id = f"tile_cut_g_z{z+1}_gx{(coord[1]//TILE_GROUP_SIZE)*TILE_GROUP_SIZE}_gy{(coord[2]//TILE_GROUP_SIZE)*TILE_GROUP_SIZE}"
    #             if child_task_id in tile_cut_tasks:
    #                 tile_cut_tasks[child_task_id] >> tile_merge_tasks[task_id]
    #     else:
    #         for coord in child_coords:
    #             child_task_id = f"tile_merge_g_z{z+1}_gx{(coord[1]//TILE_GROUP_SIZE)*TILE_GROUP_SIZE}_gy{(coord[2]//TILE_GROUP_SIZE)*TILE_GROUP_SIZE}"
    #             if child_task_id in tile_merge_tasks:
    #                 tile_merge_tasks[child_task_id] >> tile_merge_tasks[task_id]

    # print(f"Total tile merge tasks: {len(tile_merge_tasks)}")

    # # ---------- タイル圧縮タスク ----------
    # tile_compress_tasks = {}
    # # tile_cutタスクに対応する圧縮タスクを作成
    # for task_id, _ in tile_cut_tasks.items():
    #     parts = task_id.split('_') # 例: tile_cut_g_z{z}_gx{gx}_gy{gy}
    #     z = int(parts[3][1:])
    #     gx = int(parts[4][2:])
    #     gy = int(parts[5][2:])
    #     tasks_in_group = []
    #     # tilesを参照して、そのグループに存在するタイルを列挙
    #     for tx in range(gx, gx + TILE_GROUP_SIZE):
    #         for ty in range(gy, gy + TILE_GROUP_SIZE):
    #             if (z, tx, ty) in tiles:
    #                 tasks_in_group.append({
    #                     "input_path": f"/images/rawtiles/{save_data_name}/{z}/{tx}/{ty}.png",
    #                     "output_path": f"/images/tiles/{save_data_name}/{z}/{tx}/{ty}.avif",
    #                 })
    #     if len(tasks_in_group) == 0:
    #         continue
    #     compress_task_id = f"tile_compress_g_z{z}_gx{gx}_gy{gy}"
    #     tile_compress_tasks[compress_task_id] = tile_compress_g.override(task_id=compress_task_id, queue="tile_compress")(
    #         tasks=tasks_in_group,
    #     )
    #     # 依存関係の設定
    #     tile_cut_tasks[task_id] >> tile_compress_tasks[compress_task_id]
    
    # # tile_mergeタスクに対応する圧縮タスクを作成
    # for task_id, _ in tile_merge_tasks.items():
    #     parts = task_id.split('_') # 例: tile_merge_g_z{z}_gx{gx}_gy{gy}
    #     z = int(parts[3][1:])
    #     gx = int(parts[4][2:])
    #     gy = int(parts[5][2:])
    #     tasks_in_group = []
    #     # tilesを参照して、そのグループに存在するタイルを列挙
    #     for tx in range(gx, gx + TILE_GROUP_SIZE):
    #         for ty in range(gy, gy + TILE_GROUP_SIZE):
    #             if (z, tx, ty) in tiles:
    #                 tasks_in_group.append({
    #                     "input_path": f"/images/rawtiles/{save_data_name}/{z}/{tx}/{ty}.png",
    #                     "output_path": f"/images/tiles/{save_data_name}/{z}/{tx}/{ty}.avif",
    #                 })
    #     if len(tasks_in_group) == 0:
    #         continue
    #     compress_task_id = f"tile_compress_g_z{z}_gx{gx}_gy{gy}"
    #     tile_compress_tasks[compress_task_id] = tile_compress_g.override(task_id=compress_task_id, queue="tile_compress")(
    #         tasks=tasks_in_group,
    #     )
    #     # 依存関係の設定
    #     tile_merge_tasks[task_id] >> tile_compress_tasks[compress_task_id]

    # print(f"Total compress tile group tasks: {len(tile_compress_tasks)}")
