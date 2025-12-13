# 街づくりシミュレーションゲーム WebGISマッピングシステム 設計書

## 1. システム概要

### 1.1 目的
街づくりシミュレーションゲームのマップ画面をスクリーンショット撮影し、座標推定・タイル切り出しを経て、WebGIS形式で閲覧可能にするシステム。

### 1.2 アーキテクチャの基本原則

**依存関係の一方向性**
```
Browser → Backend → Airflow → Workers → Services → Storage
```
- すべての依存関係は一方向
- 下位層から上位層への呼び出しは一切行わない
- データの永続化は Airflow Workers が責任を持つ

**責務の分離**
- **Backend**: ビジネスロジック、DB管理、Airflow制御
- **Airflow**: ワークフロー管理、タスクオーケストレーション
- **Workers**: タスク実行、サービス呼び出し、結果の永続化
- **Services**: 専門処理のみ（DB接続なし、他コンテナ呼び出しなし）
- **Storage**: ファイル操作のみ

---

## 2. コンテナ構成

### 2.1 インフラストラクチャ層

#### db (PostgreSQL)
**役割**: データベースサーバー

**責務**:
- アプリケーションデータの永続化（gamedb）
- Airflowメタデータの永続化（airflow）

**接続元**:
- backend（gamedb への読み書き）
- airflow-webserver, airflow-scheduler（airflow への読み書き）
- airflow-worker-*（airflow への読み書き、gamedb への書き込み）

**ポート**: 5432

**データベース**:
- `gamedb`: アプリケーションデータ
  - jobs: ジョブ管理
  - screenshots: スクリーンショットメタデータ
  - coordinates: 座標推定結果
  - tiles: タイルメタデータ
  - tile_dependencies: タイル依存関係
  - screenshot_usage: スクリーンショット使用状況
- `airflow`: Airflowメタデータ
  - dag_run: DAG実行履歴
  - task_instance: タスク実行状態
  - xcom: タスク間データ受け渡し

---

#### redis
**役割**: メッセージブローカー

**責務**:
- Celery（Airflow Worker）のタスクキュー管理
- キュー: `capture`, `coords`, `tiles`, `default`

**接続元**:
- airflow-scheduler（タスク投入）
- airflow-worker-*（タスク取得）

**ポート**: 6379

---

#### storage
**役割**: ファイルストレージサーバー（nginx + WebDAV）

**責務**:
- 画像ファイルの保存（PUT）
- 画像ファイルの取得（GET）
- 画像ファイルの削除（DELETE）

**ストレージ構造**:
```
/data/
  images/
    screenshots/
      {screenshot_id}.png     # 一時データ
    tiles/
      {z}/
        {x}/
          {y}.png             # 永続データ
```

**エンドポイント**:
| メソッド | パス | 説明 |
|---------|------|------|
| PUT | `/images/screenshots/{screenshot_id}.png` | スクリーンショット保存 |
| GET | `/images/screenshots/{screenshot_id}.png` | スクリーンショット取得 |
| DELETE | `/images/screenshots/{screenshot_id}.png` | スクリーンショット削除 |
| PUT | `/images/tiles/{z}/{x}/{y}.png` | タイル保存 |
| GET | `/images/tiles/{z}/{x}/{y}.png` | タイル取得 |

**接続元**:
- capture（PUT）
- coords（GET）
- tiles（GET, PUT）
- airflow-worker-tiles（DELETE）
- backend（GET - タイル配信）

**ポート**: 80

**設定**: nginx WebDAV有効化、最大アップロードサイズ 50MB

---

### 2.2 アプリケーション層

#### backend
**役割**: バックエンドAPIサーバー（Ruby + Sinatra）

**責務**:
- ビジネスロジック実行
- gamedb への読み書き
- Airflow DAG起動
- タイル配信（nginx リバースプロキシ経由で storage から）
- 管理画面 API 提供

**DB接続**:
- gamedb: 読み書き

**呼び出し先**:
- airflow-webserver: DAG起動
- storage: タイル取得（配信用）

**エンドポイント**:

##### 管理画面 API
| メソッド | パス | 説明 | リクエスト | レスポンス |
|---------|------|------|-----------|-----------|
| POST | `/api/jobs` | ジョブ作成、Airflow DAG起動 | `{"game_id": string, "save_data_id": string}` | `{"job_id": integer, "status": string, "dag_run_id": string}` |
| GET | `/api/jobs/{job_id}/status` | ジョブステータス取得 | - | `{"job_id": integer, "status": string, "progress": float, "total_tasks": integer, "completed_tasks": integer, "tiles_created": integer}` |

##### Airflow Workers 専用内部 API
| メソッド | パス | 説明 | リクエスト | レスポンス |
|---------|------|------|-----------|-----------|
| POST | `/api/internal/screenshots` | スクリーンショットメタデータ保存 | `{"job_id": integer, "screenshot_id": string, "area_id": integer, "x": integer, "y": integer, "filepath": string}` | `{"success": boolean}` |
| POST | `/api/internal/coordinates` | 座標情報保存 | `{"screenshot_id": string, "estimated_x": integer, "estimated_y": integer, "confidence": float}` | `{"success": boolean}` |
| POST | `/api/internal/tiles` | タイルメタデータ保存 | `{"job_id": integer, "tiles": array, "source_screenshot_ids": array}` | `{"success": boolean}` |
| POST | `/api/internal/screenshots/{screenshot_id}/delete` | スクリーンショットメタデータ削除 | - | `{"success": boolean}` |

##### タイル配信 API
| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/tiles/{z}/{x}/{y}.png` | タイル画像配信（storage へプロキシ、キャッシュ有効） |

**ポート**: 4567

**nginx リバースプロキシ設定**:
```nginx
location /tiles/ {
  proxy_pass http://storage:80/images/tiles/;
  proxy_cache tiles_cache;
  proxy_cache_valid 200 30d;
  add_header Cache-Control "public, max-age=2592000";
}
```

---

### 2.3 Airflow層

#### airflow-webserver
**役割**: Airflow Web UI および REST API サーバー

**責務**:
- Airflow Web UI 提供
- DAG 実行トリガーAPI 提供
- airflow DB への読み書き

**DB接続**:
- airflow: 読み書き

**エンドポイント**:
| メソッド | パス | 説明 | リクエスト | レスポンス |
|---------|------|------|-----------|-----------|
| POST | `/api/v1/dags/{dag_id}/dagRuns` | DAG実行トリガー | `{"conf": object}` | `{"dag_run_id": string, "state": string}` |

**ポート**: 8080

**環境変数**:
- `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN`: PostgreSQL接続文字列
- `AIRFLOW__CELERY__BROKER_URL`: Redis接続文字列
- `AIRFLOW__CORE__EXECUTOR`: CeleryExecutor

---

#### airflow-scheduler
**役割**: Airflow スケジューラー

**責務**:
- DAG定義の読み込みとタスク生成
- タスクの依存関係管理
- 実行可能なタスクの検出
- Redis へのタスク投入
- タスク完了の監視と次タスクのスケジューリング

**DB接続**:
- airflow: 読み書き

**呼び出し先**:
- redis: タスク投入（LPUSH）

**環境変数**:
- `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN`: PostgreSQL接続文字列
- `AIRFLOW__CELERY__BROKER_URL`: Redis接続文字列
- `AIRFLOW__CORE__EXECUTOR`: CeleryExecutor

---

### 2.4 Airflow Worker層

#### airflow-worker-capture
**役割**: スクリーンショット撮影タスク実行ワーカー

**責務**:
- `capture` キューからタスク取得
- capture サービス呼び出し
- 結果を airflow DB（XCom）に保存
- **結果を gamedb に永続化（重要）**
- タスク状態更新

**DB接続**:
- airflow: 読み書き（タスク状態、XCom）
- gamedb: 書き込みのみ（screenshots テーブル）

**呼び出し先**:
- redis: タスク取得（BLPOP capture）
- capture: スクリーンショット撮影依頼

**レプリカ数**: 3

**環境変数**:
- `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN`: PostgreSQL接続文字列（airflow DB）
- `AIRFLOW__CELERY__BROKER_URL`: Redis接続文字列
- `BACKEND_URL`: http://backend:4567（内部API用）
- ※ gamedb接続文字列も必要

**処理フロー**:
1. Redis からタスク取得
2. airflow DB でタスクを 'running' 状態に更新
3. capture サービスを呼び出し
4. レスポンスを airflow DB の XCom に保存
5. **gamedb の screenshots テーブルに INSERT**
6. airflow DB でタスクを 'success' 状態に更新

---

#### airflow-worker-coords
**役割**: 座標推定タスク実行ワーカー

**責務**:
- `coords` キューからタスク取得
- 前タスク（capture）の結果を XCom から取得
- coords サービス呼び出し
- 結果を airflow DB（XCom）に保存
- **結果を gamedb に永続化（重要）**
- タスク状態更新

**DB接続**:
- airflow: 読み書き（タスク状態、XCom）
- gamedb: 書き込みのみ（coordinates テーブル、screenshots.status 更新）

**呼び出し先**:
- redis: タスク取得（BLPOP coords）
- coords: 座標推定依頼

**レプリカ数**: 2

**環境変数**:
- `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN`: PostgreSQL接続文字列（airflow DB）
- `AIRFLOW__CELERY__BROKER_URL`: Redis接続文字列
- `BACKEND_URL`: http://backend:4567（内部API用）
- ※ gamedb接続文字列も必要

**処理フロー**:
1. Redis からタスク取得
2. airflow DB でタスクを 'running' 状態に更新
3. airflow DB の XCom から前タスク結果取得
4. coords サービスを呼び出し
5. レスポンスを airflow DB の XCom に保存
6. **gamedb の coordinates テーブルに INSERT、screenshots.status を UPDATE**
7. airflow DB でタスクを 'success' 状態に更新

---

#### airflow-worker-tiles
**役割**: タイル切り出し・削除タスク実行ワーカー

**責務**:
- `tiles` キューからタスク取得
- 前タスク（coords）の結果を XCom から取得
- tiles サービス呼び出し
- 結果を airflow DB（XCom）に保存
- **結果を gamedb に永続化（重要）**
- スクリーンショット削除タスク実行
- タスク状態更新

**DB接続**:
- airflow: 読み書き（タスク状態、XCom）
- gamedb: 書き込みのみ（tiles テーブル、screenshot_usage 更新、削除処理）

**呼び出し先**:
- redis: タスク取得（BLPOP tiles, BLPOP default）
- tiles: タイル切り出し依頼
- storage: スクリーンショット削除（DELETE）

**レプリカ数**: 2

**環境変数**:
- `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN`: PostgreSQL接続文字列（airflow DB）
- `AIRFLOW__CELERY__BROKER_URL`: Redis接続文字列
- `BACKEND_URL`: http://backend:4567（内部API用）
- ※ gamedb接続文字列も必要

**処理フロー（タイル切り出し）**:
1. Redis からタスク取得
2. airflow DB でタスクを 'running' 状態に更新
3. airflow DB の XCom から複数の前タスク結果取得
4. tiles サービスを呼び出し
5. レスポンスを airflow DB の XCom に保存
6. **gamedb の tiles テーブルに INSERT、screenshot_usage を UPDATE**
7. airflow DB でタスクを 'success' 状態に更新

**処理フロー（削除）**:
1. Redis からタスク取得
2. airflow DB でタスクを 'running' 状態に更新
3. airflow DB の XCom からスクリーンショット情報取得
4. storage に DELETE リクエスト
5. **gamedb から coordinates, screenshots を DELETE**
6. airflow DB でタスクを 'success' 状態に更新

---

### 2.5 処理サービス層

#### capture
**役割**: スクリーンショット撮影サービス（Python + Flask）

**責務**:
- ゲームプロセス起動（Xvfb仮想ディスプレイ上）
- 指定座標へ移動
- スクリーンショット撮影
- storage へ画像保存
- 結果返却（screenshot_id, filepath）

**DB接続**: なし

**呼び出し先**:
- storage: 画像保存（PUT）

**エンドポイント**:
| メソッド | パス | 説明 | リクエスト | レスポンス |
|---------|------|------|-----------|-----------|
| POST | `/capture` | スクリーンショット撮影 | `{"area_id": integer, "x": integer, "y": integer}` | `{"screenshot_id": string, "filepath": string}` |

**レプリカ数**: 3

**環境変数**:
- `STORAGE_URL`: http://storage:80
- `DISPLAY`: :99（Xvfb用）

**処理フロー**:
1. リクエスト受信
2. ゲームプロセス起動
3. 座標へ移動
4. スクリーンショット撮影
5. screenshot_id 生成（UUID）
6. storage へ PUT リクエスト
7. ゲームプロセス終了、メモリ解放
8. レスポンス返却

**注意事項**:
- DB接続は行わない
- 他のサービスは呼び出さない
- 撮影処理のみに責務を限定

---

#### coords
**役割**: 座標推定サービス（Python + Flask + OpenCV）

**責務**:
- storage から画像取得
- 画像解析（テンプレートマッチング、特徴点検出）
- 座標推定
- 結果返却（estimated_x, estimated_y, confidence）

**DB接続**: なし

**呼び出し先**:
- storage: 画像取得（GET）

**エンドポイント**:
| メソッド | パス | 説明 | リクエスト | レスポンス |
|---------|------|------|-----------|-----------|
| POST | `/estimate` | 座標推定 | `{"screenshot_id": string, "filepath": string}` | `{"estimated_x": integer, "estimated_y": integer, "confidence": float}` |

**レプリカ数**: 2

**環境変数**:
- `STORAGE_URL`: http://storage:80

**処理フロー**:
1. リクエスト受信
2. storage から画像取得（GET）
3. 画像をメモリに展開
4. 座標推定処理実行
5. メモリ解放
6. レスポンス返却

**注意事項**:
- DB接続は行わない
- 他のサービスは呼び出さない
- 座標推定処理のみに責務を限定

---

#### tiles
**役割**: タイル切り出しサービス（Python + Flask + Pillow）

**責務**:
- storage から複数の画像取得
- 座標情報を元に画像配置
- タイル範囲切り出し
- WebP圧縮
- storage へタイル保存
- 結果返却（tiles_created, source_screenshot_ids）

**DB接続**: なし

**呼び出し先**:
- storage: 画像取得（GET）、タイル保存（PUT）

**エンドポイント**:
| メソッド | パス | 説明 | リクエスト | レスポンス |
|---------|------|------|-----------|-----------|
| POST | `/cut` | タイル切り出し | `{"tile_z": integer, "tile_x": integer, "tile_y": integer, "screenshots": array}` | `{"tiles_created": array, "source_screenshot_ids": array}` |

**リクエスト詳細**:
```json
{
  "tile_z": 1,
  "tile_x": 10,
  "tile_y": 20,
  "screenshots": [
    {
      "id": "shot_abc123",
      "filepath": "/images/screenshots/shot_abc123.png",
      "x": 1024,
      "y": 2048
    },
    {
      "id": "shot_def456",
      "filepath": "/images/screenshots/shot_def456.png",
      "x": 2048,
      "y": 2048
    },
    ...
  ]
}
```

**レスポンス詳細**:
```json
{
  "tiles_created": [
    {
      "z": 1,
      "x": 10,
      "y": 20,
      "filepath": "/images/tiles/1/10/20.png"
    },
    {
      "z": 1,
      "x": 10,
      "y": 21,
      "filepath": "/images/tiles/1/10/21.png"
    }
  ],
  "source_screenshot_ids": ["shot_abc123", "shot_def456", "shot_ghi789", "shot_jkl012"]
}
```

**レプリカ数**: 2

**環境変数**:
- `STORAGE_URL`: http://storage:80

**処理フロー**:
1. リクエスト受信
2. 各スクリーンショットを storage から取得（GET）
3. 画像をメモリに展開
4. 座標情報を元に仮想キャンバス上に配置
5. タイル範囲のピクセル座標を計算
6. 該当領域を切り出し
7. 画像圧縮（WebP）
8. 境界をまたぐ場合、複数タイル生成
9. 各タイルを storage へ保存（PUT）
10. メモリ解放
11. レスポンス返却

**注意事項**:
- DB接続は行わない
- 他のサービスは呼び出さない
- タイル切り出し処理のみに責務を限定
- **スクリーンショットは通常4枚（上下左右）使用する**

---

## 3. UseCase 1: マップタイル生成フロー

### 3.1 全体フロー概要

```
1. 管理画面でボタン押下
   ↓
2. Backend が job 作成、DAG起動
   ↓
3. Airflow Scheduler がタスク生成・スケジューリング
   ↓
4. スクリーンショット撮影（並列3タスク）
   ↓
5. 座標推定（並列2タスク）
   ↓
6. タイル切り出し（並列2タスク）
   ↓
7. スクリーンショット削除
   ↓
8. 完了、管理画面でステータス確認
```

---

### 3.2 詳細フロー

#### Step 1: 管理画面でボタン押下

**Browser**
```http
POST http://backend:4567/api/jobs
Content-Type: application/json

{
  "game_id": "city01",
  "save_data_id": "save_001"
}
```

**Backend**

処理:
1. リクエスト受信
2. DB接続（gamedb）:
   ```sql
   INSERT INTO jobs (game_id, save_data_id, status, created_at)
   VALUES ('city01', 'save_001', 'preparing', NOW())
   RETURNING id;
   ```
   → job_id = 123

3. 撮影エリアリスト生成:
   ```python
   areas = []
   for i in range(10000):
     areas.append({
       "area_id": i,
       "x": (i % 100) * 1024,
       "y": (i // 100) * 1024
     })
   ```

4. タイル依存関係計算:
   各タイルが依存するスクリーンショットの area_id を計算
   ```python
   tile_dependencies = {}
   for tile in tiles:
     # タイルの座標範囲と重なるスクリーンショットを計算
     # 通常は上下左右の4枚
     tile_dependencies[f"tile_{tile.z}_{tile.x}_{tile.y}"] = [area_0, area_1, area_128, area_129]
   ```

5. DB接続（gamedb）:
   ```sql
   INSERT INTO tile_dependencies (job_id, tile_id, area_ids)
   VALUES (123, 'tile_1_10_20', ARRAY[0,1,128,129]);
   ```

6. Airflow DAG起動:
   ```http
   POST http://airflow-webserver:8080/api/v1/dags/map_processing/dagRuns
   Content-Type: application/json
   Authorization: Basic {credentials}

   {
     "conf": {
       "job_id": 123,
       "areas": [...],
       "tile_dependencies": {...}
     }
   }
   ```

7. DB接続（gamedb）:
   ```sql
   UPDATE jobs
   SET airflow_dag_run_id = 'run_123', status = 'running', started_at = NOW()
   WHERE id = 123;
   ```

レスポンス:
```json
{
  "job_id": 123,
  "status": "running",
  "dag_run_id": "run_123"
}
```

**Browser**
- `/jobs/123/status` へ遷移
- 3秒ごとに `GET /api/jobs/123/status` をポーリング開始

---

#### Step 2: Airflow Scheduler によるタスクスケジューリング

**airflow-scheduler**

処理:
1. DB接続（airflow）:
   ```sql
   SELECT * FROM dag_run WHERE state = 'queued';
   ```
   → run_123 を検出

2. DAG定義ファイル読み込み、タスク動的生成:
   ```python
   conf = dag_run.conf
   job_id = conf['job_id']
   areas = conf['areas']
   tile_deps = conf['tile_dependencies']

   # 10,000個の capture タスク
   for area in areas:
     create_task('capture_{}'.format(area['area_id']))

   # 10,000個の coords タスク
   for area in areas:
     create_task('coords_{}'.format(area['area_id']))

   # 数十万個の tile タスク
   for tile_id, area_ids in tile_deps.items():
     create_task('tile_{}'.format(tile_id))

   # 10,000個の cleanup タスク
   for area in areas:
     create_task('cleanup_{}'.format(area['area_id']))
   ```

3. 依存関係設定:
   ```python
   capture_0 >> coords_0
   coords_0 >> tile_1_10_20
   coords_1 >> tile_1_10_20
   coords_128 >> tile_1_10_20
   coords_129 >> tile_1_10_20
   tile_1_10_20 >> cleanup_0
   tile_1_10_21 >> cleanup_0
   ...
   ```

4. DB接続（airflow）:
   ```sql
   INSERT INTO task_instance (task_id, dag_id, run_id, state, try_number)
   VALUES ('capture_0', 'map_processing', 'run_123', 'scheduled', 1);
   -- 全タスクを INSERT
   ```

5. Redis にタスク投入:
   ```
   LPUSH capture "capture_0"
   LPUSH capture "capture_1"
   ...
   ```

---

#### Step 3: スクリーンショット撮影

**airflow-worker-capture**

処理:
1. Redis からタスク取得:
   ```
   BLPOP capture 0
   → "capture_0"
   ```

2. DB接続（airflow）:
   ```sql
   UPDATE task_instance
   SET state = 'running', start_date = NOW(), hostname = 'worker-capture-1'
   WHERE task_id = 'capture_0' AND run_id = 'run_123';
   ```

3. タスク設定取得:
   ```sql
   SELECT conf FROM dag_run WHERE run_id = 'run_123';
   ```
   → area_id=0, x=0, y=0 を取得

4. capture サービス呼び出し:
   ```http
   POST http://capture:8000/capture
   Content-Type: application/json

   {
     "area_id": 0,
     "x": 0,
     "y": 0
   }
   ```

**capture**

処理:
1. リクエスト受信
2. ゲームプロセス起動（Xvfb :99）
3. ゲーム内で座標(0, 0)へ移動
4. スクリーンショット撮影
5. screenshot_id 生成:
   ```python
   screenshot_id = "shot_" + str(uuid.uuid4())
   # → "shot_abc123"
   ```

6. storage へ画像保存:
   ```http
   PUT http://storage:80/images/screenshots/shot_abc123.png
   Content-Type: image/png

   [画像バイナリデータ]
   ```

7. ゲームプロセス終了、メモリ解放

レスポンス:
```json
{
  "screenshot_id": "shot_abc123",
  "filepath": "/images/screenshots/shot_abc123.png"
}
```

**airflow-worker-capture**

処理（続き）:
5. レスポンス受信

6. DB接続（airflow）- XCom保存:
   ```sql
   INSERT INTO xcom (task_id, dag_id, run_id, key, value)
   VALUES ('capture_0', 'map_processing', 'run_123', 'return_value',
           '{"screenshot_id": "shot_abc123", "filepath": "/images/screenshots/shot_abc123.png"}');
   ```

7. **DB接続（gamedb）- データ永続化**:
   ```sql
   BEGIN;
   INSERT INTO screenshots (id, job_id, area_id, x, y, filepath, status, created_at)
   VALUES ('shot_abc123', 123, 0, 0, 0, '/images/screenshots/shot_abc123.png', 'captured', NOW());
   COMMIT;
   ```

8. DB接続（airflow）:
   ```sql
   UPDATE task_instance
   SET state = 'success', end_date = NOW(), duration = EXTRACT(EPOCH FROM (NOW() - start_date))
   WHERE task_id = 'capture_0' AND run_id = 'run_123';
   ```

**注意**:
- airflow-worker-capture が直接 gamedb に書き込む
- Backend の内部APIは使用しない

---

#### Step 4: 座標推定

**airflow-scheduler**

処理:
1. DB接続（airflow）- 完了検知:
   ```sql
   SELECT state FROM task_instance
   WHERE task_id = 'capture_0' AND run_id = 'run_123';
   ```
   → state = 'success'

2. 依存タスク coords_0 をスケジュール:

```sql
   UPDATE task_instance
   SET state = 'scheduled'
   WHERE task_id = 'coords_0' AND run_id = 'run_123';
   ```

3. Redis に投入:
   ```
   LPUSH coords "coords_0"
   ```

**airflow-worker-coords**

処理:
1. Redis からタスク取得:
   ```
   BLPOP coords 0
   → "coords_0"
   ```

2. DB接続（airflow）:
   ```sql
   UPDATE task_instance
   SET state = 'running', start_date = NOW()
   WHERE task_id = 'coords_0' AND run_id = 'run_123';
   ```

3. 前タスク結果を XCom から取得:
   ```sql
   SELECT value FROM xcom
   WHERE task_id = 'capture_0' AND run_id = 'run_123' AND key = 'return_value';
   ```
   → `{"screenshot_id": "shot_abc123", "filepath": "/images/screenshots/shot_abc123.png"}`

4. coords サービス呼び出し:
   ```http
   POST http://coords:8000/estimate
   Content-Type: application/json

   {
     "screenshot_id": "shot_abc123",
     "filepath": "/images/screenshots/shot_abc123.png"
   }
   ```

**coords**

処理:
1. リクエスト受信

2. storage から画像取得:
   ```http
   GET http://storage:80/images/screenshots/shot_abc123.png
   ```

3. 画像をメモリに展開

4. 座標推定処理実行:
   - テンプレートマッチング
   - 特徴点検出
   - 座標計算

5. メモリ解放

レスポンス:
```json
{
  "estimated_x": 1024,
  "estimated_y": 2048,
  "confidence": 0.95
}
```

**airflow-worker-coords**

処理（続き）:
5. レスポンス受信

6. DB接続（airflow）- XCom保存:
   ```sql
   INSERT INTO xcom (task_id, dag_id, run_id, key, value)
   VALUES ('coords_0', 'map_processing', 'run_123', 'return_value',
           '{"estimated_x": 1024, "estimated_y": 2048, "confidence": 0.95}');
   ```

7. **DB接続（gamedb）- データ永続化**:
   ```sql
   BEGIN;
   INSERT INTO coordinates (screenshot_id, estimated_x, estimated_y, confidence, created_at)
   VALUES ('shot_abc123', 1024, 2048, 0.95, NOW());

   UPDATE screenshots
   SET status = 'coords_estimated', updated_at = NOW()
   WHERE id = 'shot_abc123';
   COMMIT;
   ```

8. DB接続（airflow）:
   ```sql
   UPDATE task_instance
   SET state = 'success', end_date = NOW()
   WHERE task_id = 'coords_0' AND run_id = 'run_123';
   ```

---

#### Step 5: タイル切り出し

**airflow-scheduler**

処理:
1. DB接続（airflow）- 依存タスク完了チェック:
   ```sql
   SELECT state FROM task_instance
   WHERE task_id IN ('coords_0', 'coords_1', 'coords_128', 'coords_129')
   AND run_id = 'run_123';
   ```
   → すべて state = 'success'

2. tile_1_10_20 をスケジュール:
   ```sql
   UPDATE task_instance
   SET state = 'scheduled'
   WHERE task_id = 'tile_1_10_20' AND run_id = 'run_123';
   ```

3. Redis に投入:
   ```
   LPUSH tiles "tile_1_10_20"
   ```

**airflow-worker-tiles**

処理:
1. Redis からタスク取得:
   ```
   BLPOP tiles 0
   → "tile_1_10_20"
   ```

2. DB接続（airflow）:
   ```sql
   UPDATE task_instance
   SET state = 'running', start_date = NOW()
   WHERE task_id = 'tile_1_10_20' AND run_id = 'run_123';
   ```

3. タスク設定から依存する area_ids 取得:
   ```sql
   SELECT conf FROM dag_run WHERE run_id = 'run_123';
   ```
   → tile_dependencies['tile_1_10_20'] = [0, 1, 128, 129]

4. 各 area_id の XCom 取得:
   ```sql
   SELECT value FROM xcom
   WHERE task_id IN ('capture_0', 'capture_1', 'capture_128', 'capture_129')
   AND run_id = 'run_123';

   SELECT value FROM xcom
   WHERE task_id IN ('coords_0', 'coords_1', 'coords_128', 'coords_129')
   AND run_id = 'run_123';
   ```

5. データを結合して screenshots リスト作成:
   ```python
   screenshots = [
     {"id": "shot_abc123", "filepath": "/images/screenshots/shot_abc123.png", "x": 1024, "y": 2048},
     {"id": "shot_def456", "filepath": "/images/screenshots/shot_def456.png", "x": 2048, "y": 2048},
     {"id": "shot_ghi789", "filepath": "/images/screenshots/shot_ghi789.png", "x": 1024, "y": 66560},
     {"id": "shot_jkl012", "filepath": "/images/screenshots/shot_jkl012.png", "x": 2048, "y": 66560}
   ]
   ```

6. tiles サービス呼び出し:
   ```http
   POST http://tiles:8000/cut
   Content-Type: application/json

   {
     "tile_z": 1,
     "tile_x": 10,
     "tile_y": 20,
     "screenshots": [
       {"id": "shot_abc123", "filepath": "/images/screenshots/shot_abc123.png", "x": 1024, "y": 2048},
       {"id": "shot_def456", "filepath": "/images/screenshots/shot_def456.png", "x": 2048, "y": 2048},
       {"id": "shot_ghi789", "filepath": "/images/screenshots/shot_ghi789.png", "x": 1024, "y": 66560},
       {"id": "shot_jkl012", "filepath": "/images/screenshots/shot_jkl012.png", "x": 2048, "y": 66560}
     ]
   }
   ```

**tiles**

処理:
1. リクエスト受信

2. 各スクリーンショットを storage から取得:
   ```http
   GET http://storage:80/images/screenshots/shot_abc123.png
   GET http://storage:80/images/screenshots/shot_def456.png
   GET http://storage:80/images/screenshots/shot_ghi789.png
   GET http://storage:80/images/screenshots/shot_jkl012.png
   ```

3. 4枚の画像をメモリに展開

4. 座標情報を元に仮想キャンバス上に配置

5. タイル範囲（z:1, x:10, y:20）のピクセル座標計算:
   ```python
   tile_pixel_x = tile_x * 512
   tile_pixel_y = tile_y * 512
   tile_pixel_width = 512
   tile_pixel_height = 512
   ```

6. 該当領域を切り出し

7. 画像圧縮（WebP）

8. 境界をまたぐ場合、複数タイル生成（例: 2枚）

9. 各タイルを storage へ保存:
   ```http
   PUT http://storage:80/images/tiles/1/10/20.png
   Content-Type: image/png

   [タイル画像バイナリ]

   PUT http://storage:80/images/tiles/1/10/21.png
   Content-Type: image/png

   [タイル画像バイナリ]
   ```

10. メモリ解放

レスポンス:
```json
{
  "tiles_created": [
    {"z": 1, "x": 10, "y": 20, "filepath": "/images/tiles/1/10/20.png"},
    {"z": 1, "x": 10, "y": 21, "filepath": "/images/tiles/1/10/21.png"}
  ],
  "source_screenshot_ids": ["shot_abc123", "shot_def456", "shot_ghi789", "shot_jkl012"]
}
```

**airflow-worker-tiles**

処理（続き）:
7. レスポンス受信

8. DB接続（airflow）- XCom保存:
   ```sql
   INSERT INTO xcom (task_id, dag_id, run_id, key, value)
   VALUES ('tile_1_10_20', 'map_processing', 'run_123', 'return_value',
           '{"tiles_created": [...], "source_screenshot_ids": [...]}');
   ```

9. **DB接続（gamedb）- データ永続化**:
   ```sql
   BEGIN;

   -- タイル保存
   INSERT INTO tiles (job_id, z, x, y, filepath, created_at)
   VALUES
   (123, 1, 10, 20, '/images/tiles/1/10/20.png', NOW()),
   (123, 1, 10, 21, '/images/tiles/1/10/21.png', NOW());

   -- スクリーンショット使用カウント更新
   UPDATE screenshot_usage
   SET completed_tiles_count = completed_tiles_count + 1
   WHERE screenshot_id IN ('shot_abc123', 'shot_def456', 'shot_ghi789', 'shot_jkl012')
   AND job_id = 123;

   COMMIT;
   ```

10. DB接続（airflow）:
    ```sql
    UPDATE task_instance
    SET state = 'success', end_date = NOW()
    WHERE task_id = 'tile_1_10_20' AND run_id = 'run_123';
    ```

---

#### Step 6: スクリーンショット削除

**airflow-scheduler**

処理:
1. DB接続（airflow）と gamedb を確認:
   ```sql
   -- cleanup_0 が依存する全タイルタスクが完了したかチェック
   -- （area_0 を使用する全タイルタスク）
   SELECT state FROM task_instance
   WHERE task_id IN ('tile_1_10_20', 'tile_1_10_21', ...)
   AND run_id = 'run_123';
   ```

   または

   ```sql
   -- gamedb から完了状況チェック
   SELECT completed_tiles_count, required_by_tiles_count
   FROM screenshot_usage
   WHERE screenshot_id = 'shot_abc123' AND job_id = 123;
   ```
   → completed = required

2. cleanup_0 をスケジュール:
   ```sql
   UPDATE task_instance
   SET state = 'scheduled'
   WHERE task_id = 'cleanup_0' AND run_id = 'run_123';
   ```

3. Redis に投入:
   ```
   LPUSH default "cleanup_0"
   ```

**airflow-worker-tiles**

処理:
1. Redis からタスク取得:
   ```
   BLPOP default 0
   → "cleanup_0"
   ```

2. DB接続（airflow）:
   ```sql
   UPDATE task_instance
   SET state = 'running', start_date = NOW()
   WHERE task_id = 'cleanup_0' AND run_id = 'run_123';
   ```

3. XCom から screenshot 情報取得:
   ```sql
   SELECT value FROM xcom
   WHERE task_id = 'capture_0' AND run_id = 'run_123';
   ```
   → `{"screenshot_id": "shot_abc123", "filepath": "/images/screenshots/shot_abc123.png"}`

4. storage へ削除リクエスト:
   ```http
   DELETE http://storage:80/images/screenshots/shot_abc123.png
   ```

5. **DB接続（gamedb）- メタデータ削除**:
   ```sql
   BEGIN;
   DELETE FROM coordinates WHERE screenshot_id = 'shot_abc123';
   DELETE FROM screenshots WHERE id = 'shot_abc123';
   COMMIT;
   ```

6. DB接続（airflow）:
   ```sql
   UPDATE task_instance
   SET state = 'success', end_date = NOW()
   WHERE task_id = 'cleanup_0' AND run_id = 'run_123';
   ```

---

#### Step 7: 完了とステータス確認

**airflow-scheduler**

処理:
1. DB接続（airflow）- 全タスク完了チェック:
   ```sql
   SELECT COUNT(*)
   FROM task_instance
   WHERE dag_id = 'map_processing'
   AND run_id = 'run_123'
   AND state != 'success';
   ```
   → 0

2. dag_run を完了状態に:
   ```sql
   UPDATE dag_run
   SET state = 'success', end_date = NOW()
   WHERE run_id = 'run_123';
   ```

**Browser（3秒ごとのポーリング）**

リクエスト:
```http
GET http://backend:4567/api/jobs/123/status
```

**Backend**

処理:
1. DB接続（gamedb）:
   ```sql
   SELECT status, airflow_dag_run_id
   FROM jobs
   WHERE id = 123;
   ```
   → status='running', dag_run_id='run_123'

2. DB接続（airflow）:
   ```sql
   SELECT
     state,
     COUNT(*) FILTER (WHERE state = 'success') as completed,
     COUNT(*) as total
   FROM task_instance
   WHERE dag_id = 'map_processing' AND run_id = 'run_123'
   GROUP BY state;
   ```
   → state='success', completed=300000, total=300000

3. 完了していれば DB接続（gamedb）で更新:
   ```sql
   UPDATE jobs
   SET status = 'completed', completed_at = NOW()
   WHERE id = 123;
   ```

4. DB接続（gamedb）- タイル数取得:
   ```sql
   SELECT COUNT(*) FROM tiles WHERE job_id = 123;
   ```
   → 100000

レスポンス:
```json
{
  "job_id": 123,
  "status": "completed",
  "progress": 100.0,
  "total_tasks": 300000,
  "completed_tasks": 300000,
  "tiles_created": 100000
}
```

**Browser**
- status='completed' を検知
- ポーリング停止
- 完了メッセージ表示

---

## 4. UseCase 2: Webブラウザでマップ閲覧

### 4.1 全体フロー概要

```
1. ブラウザで Leaflet.js 初期化
   ↓
2. 表示範囲から必要なタイルを計算
   ↓
3. Backend へタイルリクエスト（並列）
   ↓
4. Backend が Storage へプロキシ（キャッシュ有効）
   ↓
5. ブラウザでタイル描画、マップ表示完了
```

---

### 4.2 詳細フロー

**Browser**

処理:
1. Leaflet.js 初期化:
   ```javascript
   const map = L.map('map').setView([35.6762, 139.6503], 13);

   L.tileLayer('http://backend:4567/tiles/{z}/{x}/{y}.png', {
     maxZoom: 18,
     attribution: 'Game Map'
   }).addTo(map);
   ```

2. 現在の表示範囲とズームレベルから必要なタイルを計算:
   - ズームレベル: z = 1
   - 表示範囲: x = 10〜15, y = 20〜25
   - 必要タイル数: 6 × 6 = 36枚

3. 各タイルを並列リクエスト（ブラウザが自動的に6-8並列）:
   ```http
   GET http://backend:4567/tiles/1/10/20.png
   GET http://backend:4567/tiles/1/10/21.png
   GET http://backend:4567/tiles/1/10/22.png
   ...
   GET http://backend:4567/tiles/1/15/25.png
   ```
   計36リクエスト

**Backend（nginx リバースプロキシ）**

nginx.conf:
```nginx
http {
  proxy_cache_path /var/cache/nginx/tiles
    levels=1:2
    keys_zone=tiles_cache:100m
    max_size=10g
    inactive=30d;

  server {
    listen 4567;

    location /tiles/ {
      proxy_pass http://storage:80/images/tiles/;
      proxy_cache tiles_cache;
      proxy_cache_valid 200 30d;
      proxy_cache_key "$scheme$proxy_host$request_uri";
      add_header X-Cache-Status $upstream_cache_status;
      add_header Cache-Control "public, max-age=2592000";
    }
  }
}
```

処理（各タイルリクエストごと）:
1. リクエスト受信: `GET /tiles/1/10/20.png`

2. キャッシュチェック:
   - キャッシュヒット → キャッシュから返却（高速）
   - キャッシュミス → storage へプロキシ

3. キャッシュミスの場合:
   ```http
   GET http://storage:80/images/tiles/1/10/20.png
   ```

**Storage**

処理:
1. リクエスト受信
2. ファイル読み込み:
   ```
   /data/images/tiles/1/10/20.png
   ```
3. レスポンス返却:
   ```http
   HTTP/1.1 200 OK
   Content-Type: image/png
   Content-Length: 45678

   [画像バイナリデータ]
   ```

**Backend（続き）**

処理:
4. storage からのレスポンス受信
5. キャッシュに保存: `/var/cache/nginx/tiles/...`
6. レスポンス返却:
   ```http
   HTTP/1.1 200 OK
   Content-Type: image/png
   Cache-Control: public, max-age=2592000
   X-Cache-Status: MISS

   [画像バイナリデータ]
   ```

**Browser**

処理（各タイルごと）:
4. タイル画像受信（5-100KB、圧縮済み）
5. ブラウザキャッシュに保存
6. Canvas に描画

全36枚受信後:
7. マップ表示完了

ユーザーがパン・ズーム操作:
- 新しい範囲のタイルを自動リクエスト
- ブラウザキャッシュにあれば即座に表示
- Backend のキャッシュにあれば高速取得
- いずれもなければ storage から取得

---

## 5. データフロー図

### 5.1 依存関係（一方向）

```
Browser
  ↓ HTTP Request
Backend
  ↓ Airflow REST API
Airflow Webserver
  ↓ DB Write
Airflow Scheduler
  ↓ Redis Publish
Redis
  ↓ Message Queue
Airflow Workers
  ↓ HTTP Request & DB Write
Services (capture/coords/tiles)
  ↓ HTTP Request
Storage
```

### 5.2 データ永続化の責任

| データ | 永続化担当 | DB | テーブル |
|--------|-----------|-----|----------|
| Job 情報 | Backend | gamedb | jobs |
| タイル依存関係 | Backend | gamedb | tile_dependencies |
| DAG Run | Airflow Webserver | airflow | dag_run |
| Task Instance | Airflow Scheduler | airflow | task_instance |
| スクリーンショット | airflow-worker-capture | gamedb | screenshots |
| 座標情報 | airflow-worker-coords | gamedb | coordinates |
| タイル情報 | airflow-worker-tiles | gamedb | tiles |
| XCom（タスク間データ） | 各 Airflow Worker | airflow | xcom |

### 5.3 ファイル操作の責任

| ファイル | 操作 | 担当コンテナ | storage API |
|---------|------|-------------|-------------|
| スクリーンショット | 保存 | capture | PUT |
| スクリーンショット | 取得 | coords | GET |
| スクリーンショット | 取得 | tiles | GET |
| スクリーンショット | 削除 | airflow-worker-tiles | DELETE |
| タイル | 保存 | tiles | PUT |
| タイル | 配信 | backend（nginx経由） | GET |

---

## 6. 重要な設計原則

### 6.1 依存関係の一方向性

**絶対に守るべきルール**:
- 下位層から上位層への呼び出しは一切行わない
- Services (capture/coords/tiles) は Backend を呼び出さない
- Airflow Workers のみが gamedb へ書き込む
- Backend は Airflow の起動と gamedb の読み書きのみ

**誤った設計例**:
```
❌ capture → backend → gamedb (循環依存)
❌ tiles → backend API → gamedb (不要な中間層)
```

**正しい設計**:
```
✅ airflow-worker-capture → capture → storage
✅ airflow-worker-capture → gamedb (直接書き込み)
```

### 6.2 責務の明確化

**各層の責務**:
- **Services**: 専門処理のみ、DB接続なし、他サービス呼び出しなし
- **Workers**: タスク実行、結果の永続化（DB書き込み）
- **Airflow**: ワークフロー管理、依存関係制御
- **Backend**: ビジネスロジック、API提供、Airflow制御

### 6.3 データ永続化のタイミング

**原則**:
- Airflow Workers が処理結果を受け取った時点で即座に DB へ永続化
- Services は結果を返すのみ、永続化は行わない
- Backend の内部 API は使用しない

**理由**:
- 依存関係の一方向性を保つ
- データロストのリスクを最小化
- デバッグとトレーサビリティの向上

---

## 7. スケーリングとパフォーマンス

### 7.1 並列度の設定

| コンテナ | レプリカ数 | キュー | 並列処理数 |
|---------|-----------|--------|-----------|
| airflow-worker-capture | 3 | capture | 3 |
| airflow-worker-coords | 2 | coords | 2 |
| airflow-worker-tiles | 2 | tiles | 2 |
| capture | 3 | - | 3 |
| coords | 2 | - | 2 |
| tiles | 2 | - | 2 |

### 7.2 ボトルネック対策

**想定されるボトルネック**:
1. スクリーンショット撮影（ゲーム起動に時間）
   - 対策: capture と airflow-worker-capture を最も多く配置

2. Storage I/O
   - 対策: SSD使用、nginx キャッシュ

3. タイル配信
   - 対策: nginx プロキシキャッシュ（30日間）

---

この設計書に従うことで、依存関係が一方向で、責務が明確に分離された、保守性の高いシステムを構築できます。
