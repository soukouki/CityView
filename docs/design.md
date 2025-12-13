# Simutrans CityView 設計書

## 1. システム概要

### 1.1 目的
街づくりシミュレーションゲームのマップ画面をスクリーンショット撮影し、座標推定・タイル切り出しを経て、WebGIS形式で閲覧可能にするシステム。

### 1.2 アーキテクチャの基本原則

#### 責務の明確化
- 各コンポーネントは特定の役割に特化し、責務を超えない。
- データ永続化はBackendが一元管理し、整合性を保つ。
- 処理サービス（`service-*`）はステートレスであり、外部状態に依存しない。

#### 変更耐性の確保
- 下位層の処理サービスは上位層の知識を持たない。
- Airflow DAGの変更がBackendやサービスに影響しないように設計する。

## 2. コンテナ構成

### 2.1 インフラストラクチャ層

#### db (PostgreSQL)
- **役割**: データベースサーバー
- **責務**:
  - アプリケーションデータの永続化（`gamedb`）
  - Airflowメタデータの永続化（`airflow`）
- **接続元**:
  - backend（`gamedb` への読み書き）
  - airflow-webserver, airflow-scheduler（`airflow` への読み書き）
  - airflow-worker-*（`airflow` への読み書き）
- **ポート**: `5432`
- **データベース**:
  - `gamedb`: アプリケーションデータ
    - `jobs`: ジョブ管理（`job_id`, `game_id`, `save_data_name`, `status`, `created_at` など）
    - `savedatas`: セーブデータ情報
    - `screenshots`: スクリーンショットと推定座標（`screenshot_id`, `job_id`, `x`, `y`, `estimated_x`, `estimated_y`, `filepath`, `status` など）
    - `tiles`: タイルメタデータ（`tile_id`, `job_id`, `z`, `x`, `y`, `filepath` など）
  - `airflow`: Airflowメタデータ
    - `dag_run`: DAG実行履歴
    - `task_instance`: タスク実行状態
    - `xcom`: タスク間データ受け渡し

#### redis
- **役割**: メッセージブローカー
- **責務**:
  - Celery（Airflow Worker）のタスクキュー管理
  - キュー: `capture`, `coords`, `tiles`, `cleanup`
- **接続元**:
  - airflow-scheduler（タスク投入）
  - airflow-worker-*（タスク取得）
- **ポート**: `6379`

#### storage
- **役割**: ファイルストレージサーバー（nginx + WebDAV）
- **責務**:
  - 画像ファイルの保存（PUT）
  - 画像ファイルの取得（GET）
  - 画像ファイルの削除（DELETE）
- **ストレージ構造**:
  ```text
  /data/
    images/
      screenshots/
        {screenshot_id}.png     # 一時データ
      tiles/
        {z}/
          {x}/
            {y}.avif            # 永続データ
  ```
- **エンドポイント**:

  | メソッド | パス | 説明 |
  |---|---|---|
  | PUT | `/images/screenshots/{screenshot_id}.png` | スクリーンショット保存 |
  | GET | `/images/screenshots/{screenshot_id}.png` | スクリーンショット取得 |
  | DELETE | `/images/screenshots/{screenshot_id}.png` | スクリーンショット削除 |
  | PUT | `/images/tiles/{z}/{x}/{y}.avif` | タイル保存 |
  | GET | `/images/tiles/{z}/{x}/{y}.avif` | タイル取得 |

- **接続元**:
  - service-capture（PUT）
  - service-coords（GET）
  - service-tiles（GET, PUT）
  - airflow-worker-cleanup（DELETE）
  - backend（GET - タイル配信）
- **ポート**: `80`
- **設定**: nginx WebDAV有効化、最大アップロードサイズ 50MB

### 2.2 アプリケーション層

#### backend
- **役割**: バックエンドAPIサーバー（Ruby + Sinatra）
- **責務**:
  - ビジネスロジック実行
  - `gamedb` への読み書き
  - Airflow DAG起動
  - 管理画面/マップ閲覧画面のHTML配信
  - 静的ファイル（CSS、JavaScript等）の配信
  - タイル配信（storage へのリバースプロキシ）
  - 管理画面 API および内部 API 提供
- **DB接続**:
  - `gamedb`: 読み書き
- **呼び出し先**:
  - airflow-webserver: DAG起動
  - storage: タイル取得（配信用）
- **ポート**:
  - メイン: `8000`
  - 管理画面: `8001`
  - Airflow Workers 内部 API: `8002`
- **エンドポイント**:

##### メイン画面
| メソッド | パス | 説明 |
|---|---|---|
| GET | `/` | メイン画面HTML配信 |
| GET | `/assets/*` | 静的ファイル配信 |

##### 管理画面
| メソッド | パス | 説明 |
|---|---|---|
| GET | `/` | 管理画面HTML配信 |
| GET | `/assets/*` | 静的ファイル配信 |

##### 管理画面 API
| メソッド | パス | 説明 | リクエスト | レスポンス |
|---|---|---|---|---|
| POST | `/api/tiles/create` | タイル生成ジョブ作成、DAG起動 | `{"game_id": "string", "save_data_name": "string"}` | `{"job_id": 0, "status": "string", "dag_run_id": "string"}` |
| GET | `/api/status` | 全ジョブのステータス一覧取得 | - | `[{"job_id": 0, "status": "string", "progress": 0.0, "total_tiles": 0, "created_tiles": 0}]` |

##### Airflow Workers 専用内部 API
| メソッド | パス | 説明 | リクエスト | レスポンス |
|---|---|---|---|---|
| POST | `/api/internal/screenshots` | スクリーンショットメタデータ保存 | `{"job_id": 0, "screenshot_id": "string", "x": 0, "y": 0, "filepath": "string"}` | `{"success": true}` |
| PUT | `/api/internal/screenshots/{screenshot_id}` | スクリーンショットの推定座標更新 | `{"estimated_x": 0, "estimated_y": 0}` | `{"success": true}` |
| POST | `/api/internal/tiles` | タイルメタデータ保存 | `{"job_id": 0, "tiles": []}` | `{"success": true}` |
| DELETE | `/api/internal/screenshots/{screenshot_id}` | スクリーンショット削除（ファイル＋DB） | - | `{"success": true}` |

##### タイル配信 API
| メソッド | パス | 説明 |
|---|---|---|
| GET | `/tiles/{z}/{x}/{y}.avif` | タイル画像配信（storage へプロキシ） |

### 2.3 Airflow層

#### airflow-webserver
- **役割**: Airflow Web UI および REST API サーバー
- **責務**:
  - Airflow Web UI 提供
  - DAG 実行トリガーAPI 提供
  - airflow DB への読み書き
- **DB接続**:
  - `airflow`: 読み書き
- **エンドポイント**:

  | メソッド | パス | 説明 |
  |---|---|---|
  | POST | `/api/v1/dags/{dag_id}/dagRuns` | DAG実行トリガー |

- **ポート**: `8003`

#### airflow-scheduler
- **役割**: Airflow スケジューラー
- **責務**:
  - DAG定義の読み込みとタスク生成
  - タスクの依存関係管理
  - 実行可能なタスクの検出
  - Redis へのタスク投入
  - タスク完了の監視と次タスクのスケジューリング
- **DB接続**:
  - `airflow`: 読み書き
- **呼び出し先**:
  - redis: タスク投入（LPUSH）

### 2.4 Airflow Worker層

#### airflow-worker-capture
- **役割**: スクリーンショット撮影タスク実行ワーカー
- **責務**:
  - `capture` キューからタスク取得
  - `service-capture` サービス呼び出し
  - Backend API を通じて結果を `gamedb` に永続化
  - タスク状態更新
- **DB接続**:
  - `airflow`: 読み書き（タスク状態、XCom）
- **呼び出し先**:
  - redis: タスク取得
  - service-capture: スクリーンショット撮影依頼
  - backend: 結果の永続化
- **レプリカ数**: `2`
- **処理フロー**:
  1. Redis からタスク取得
  2. airflow DB でタスクを `running` 状態に更新
  3. `service-capture` を呼び出し
  4. レスポンスを airflow DB の XCom に保存
  5. Backend の `/api/internal/screenshots` を呼び出して結果を永続化
  6. airflow DB でタスクを `success` 状態に更新

#### airflow-worker-coords
- **役割**: 座標推定タスク実行ワーカー
- **責務**:
  - `coords` キューからタスク取得
  - 前タスクの結果を XCom から取得
  - `service-coords` サービス呼び出し
  - Backend API を通じて結果を `gamedb` に永続化
  - タスク状態更新
- **DB接続**:
  - `airflow`: 読み書き（タスク状態、XCom）
- **呼び出し先**:
  - redis: タスク取得
  - service-coords: 座標推定依頼
  - backend: 結果の永続化
- **レプリカ数**: `2`
- **処理フロー**:
  1. Redis からタスク取得
  2. airflow DB でタスクを `running` 状態に更新
  3. airflow DB の XCom から前タスク結果取得
  4. `service-coords` を呼び出し
  5. レスポンスを airflow DB の XCom に保存
  6. Backend の `/api/internal/screenshots/{id}` を呼び出して推定座標を更新
  7. airflow DB でタスクを `success` 状態に更新

#### airflow-worker-tiles
- **役割**: タイル切り出しタスク実行ワーカー
- **責務**:
  - `tiles` キューからタスク取得
  - 前タスクの結果を XCom から取得
  - `service-tiles` サービス呼び出し
  - Backend API を通じて結果を `gamedb` に永続化
  - タスク状態更新
- **DB接続**:
  - `airflow`: 読み書き（タスク状態、XCom）
- **呼び出し先**:
  - redis: タスク取得
  - service-tiles: タイル切り出し依頼
  - backend: 結果の永続化
- **レプリカ数**: `2`
- **処理フロー**:
  1. Redis からタスク取得
  2. airflow DB でタスクを `running` 状態に更新
  3. airflow DB の XCom から複数の前タスク結果取得
  4. `service-tiles` を呼び出し
  5. レスポンスを airflow DB の XCom に保存
  6. Backend の `/api/internal/tiles` を呼び出してタイル情報を永続化
  7. airflow DB でタスクを `success` 状態に更新

#### airflow-worker-cleanup
- **役割**: スクリーンショット削除タスク実行ワーカー
- **責務**:
  - `cleanup` キューからタスク取得
  - スクリーンショットがもう使用されないことを確認
  - Backend API を通じてスクリーンショットを削除（ファイル + DBレコード）
  - タスク状態更新
- **DB接続**:
  - `airflow`: 読み書き（タスク状態、XCom）
- **呼び出し先**:
  - redis: タスク取得
  - backend: スクリーンショット削除指示
- **レプリカ数**: `2`
- **処理フロー**:
  1. Redis からタスク取得
  2. airflow DB でタスクを `running` 状態に更新
  3. XCom から対象スクリーンショットID取得
  4. Backend の `/api/internal/screenshots/{id}` DELETE を呼び出し
  5. airflow DB でタスクを `success` 状態に更新

### 2.5 処理サービス層

#### service-capture
- **役割**: スクリーンショット撮影サービス（Python + Flask）
- **責務**:
  - ゲームプロセス起動
  - 指定セーブデータと座標でスクリーンショット撮影
  - storage へ画像保存
  - 画像パスを返却
- **DB接続**: なし
- **呼び出し先**:
  - storage: 画像保存（PUT）
- **エンドポイント**:

  | メソッド | パス | 説明 | リクエスト | レスポンス |
  |---|---|---|---|---|
  | POST | `/capture` | スクリーンショット撮影 | `{"save_data_name": "string", "x": 0, "y": 0}` | `{"image_path": "string"}` |

- **レプリカ数**: `2`
- **処理フロー**:
  1. リクエスト受信
  2. ゲームプロセス起動、セーブデータ読み込み
  3. 座標へ移動してスクリーンショット撮影
  4. ファイル名を生成して storage へ PUT
  5. ゲーム終了、メモリ解放
  6. 画像パスを返却
- **ポート**: `5000`

#### service-coords
- **役割**: 座標推定サービス（Python + Flask + OpenCV）
- **責務**:
  - storage から画像取得
  - 画像解析による座標推定
  - 推定座標を返却
- **DB接続**: なし
- **呼び出し先**:
  - storage: 画像取得（GET）
- **エンドポイント**:

  | メソッド | パス | 説明 | リクエスト | レスポンス |
  |---|---|---|---|---|
  | POST | `/estimate` | 座標推定 | `{"image_path": "string", "adjacent_images": [], "hint_x": 0, "hint_y": 0}` | `{"estimated_x": 0, "estimated_y": 0}` |

- **レプリカ数**: `2`
- **処理フロー**:
  1. リクエスト受信
  2. storage から主画像と隣接画像を取得
  3. ヒント座標を用いて座標推定処理実行
  4. メモリ解放
  5. 推定座標を返却
- **ポート**: `5001`

#### service-tiles
- **役割**: タイル切り出しサービス（Python + Flask + Pillow）
- **責務**:
  - storage から複数の画像取得
  - 座標情報を元に画像を結合
  - 指定範囲を切り出し
  - AVIF形式（quality 30）で圧縮
  - storage へタイル保存
  - タイルパスを返却
- **DB接続**: なし
- **呼び出し先**:
  - storage: 画像取得（GET）、タイル保存（PUT）
- **エンドポイント**:

  | メソッド | パス | 説明 | リクエスト | レスポンス |
  |---|---|---|---|---|
  | POST | `/cut` | タイル切り出し | `{"images": [], "tile_x": 0, "tile_y": 0, "tile_size": 0}` | `{"tile_path": "string"}` |

- **レプリカ数**: `2`
- **処理フロー**:
  1. リクエスト受信
  2. 複数画像を storage から取得
  3. 仮想キャンバスに配置
  4. タイル範囲を切り出し
  5. AVIF（quality 30）に圧縮
  6. storage に保存
  7. メモリ解放
  8. タイルパスを返却
- **ポート**: `5002`

## 3. UseCase 1: マップタイル生成フロー

### 3.1 全体フロー概要
```text
1. 管理画面で「タイル生成」ボタンを押下
2. Backend が job を作成し、Airflow DAG を起動
3. Airflow Scheduler がタスクを生成・スケジューリング
4. スクリーンショット撮影タスク（並列実行）
5. 座標推定タスク（並列実行）
6. タイル切り出しタスク（並列実行）
7. スクリーンショット削除タスク（各スクショの使用完了後、個別に実行）
8. 完了、管理画面でステータスを確認
```

### 3.2 詳細フロー

#### Step 1: タイル生成ジョブ作成
ユーザーは管理画面からゲームID（例: `"city01"`）とセーブデータ名（例: `"save_001"`）を指定して「タイル生成」ボタンを押下します。Backendは `POST /api/tiles/create` リクエストを受け取ります。

Backendは以下を実行します:
- gamedbに新しいジョブレコードを作成（`status='preparing'`）
- 撮影対象エリアのリストを計算
- AirflowのDAG起動APIを呼び出し、`map_processing` DAGを起動
- 起動された `dag_run_id` を取得してDBに保存
- ジョブステータスを `running` に更新

Backendはクライアントに以下を返します:
```json
{"job_id": 123, "status": "running", "dag_run_id": "run_123"}
```

ブラウザは `/api/status` を3秒ごとにポーリング開始します。

#### Step 2: タスク生成とスケジューリング
Airflow Schedulerはdag_runを検知し、DAG定義ファイルを読み込みます。パラメータから撮影エリア数（例: 10,000）とタイル依存関係（各タイルが依存するスクリーンショットのエリアID）を取得し、以下のタスクを動的に生成します:

- `capture_0`, `capture_1`, ..., `capture_9999`（スクリーンショット撮影）
- `coords_0`, `coords_1`, ..., `coords_9999`（座標推定）
- `tile_1_10_20`, `tile_1_10_21`, ...（タイル切り出し、数十万個）
- `cleanup_0`, `cleanup_1`, ..., `cleanup_9999`（スクリーンショット削除）

タスク間の依存関係を設定します:
```text
capture_0 >> coords_0
coords_0 >> tile_1_10_20
coords_1 >> tile_1_10_20
... (タイルに必要なすべてのcoords完了まで)
tile_1_10_20 >> cleanup_0 (cleanup_0が使用するすべてのタイル完了)
tile_1_10_21 >> cleanup_0
... (タイル0に関連するすべてのタイル完了)
```

Schedulerは実行可能なタスク（`capture_*`）をRedisの `capture` キューに投入します。

#### Step 3: スクリーンショット撮影
`airflow-worker-capture` は `capture` キューからタスク（例: `"capture_0"`）を取得します。

Worker は以下を実行します:
- airflow DBでタスクを `running` に更新
- ジョブの設定パラメータからエリアID 0の座標を取得（例: `x=0`, `y=0`）
- `service-capture` を呼び出し: `POST http://service-capture:5000/capture`
  ```json
  {
    "save_data_name": "save_001",
    "x": 0,
    "y": 0
  }
  ```

`service-capture` は以下を実行します:
- ゲームプロセスを起動（仮想ディスプレイ）
- セーブデータ `"save_001"` をロード
- 座標 `(0, 0)` へゲーム内で移動
- スクリーンショット撮影
- `screenshot_id` を生成（例: `"shot_abc123"`）
- storageへ `PUT /images/screenshots/shot_abc123.png` でファイル保存
- `{"image_path": "/images/screenshots/shot_abc123.png"}` を返却
- ゲーム終了、メモリ解放

Worker は以下を実行します:
- レスポンスを受け取り、airflow DBのXComに保存
- Backend の `POST /api/internal/screenshots` を呼び出し:
  ```json
  {
    "job_id": 123,
    "screenshot_id": "shot_abc123",
    "x": 0,
    "y": 0,
    "filepath": "/images/screenshots/shot_abc123.png"
  }
  ```
- Backendは `screenshots` テーブルにレコード挿入
- airflow DBでタスクを `success` に更新

#### Step 4: 座標推定
`capture_0` タスクが完了すると `coords_0` が実行可能になります。

`airflow-worker-coords` は `coords` キューからタスク（`"coords_0"`）を取得します。

Worker は以下を実行します:
- airflow DBでタスクを `running` に更新
- XComから `capture_0` の結果を取得（`{"image_path": "/images/screenshots/shot_abc123.png"}`）
- DAGの設定から期待座標（ヒント）を取得（例: `hint_x=1024`, `hint_y=2048`）
- `service-coords` を呼び出し: `POST http://service-coords:5001/estimate`
  ```json
  {
    "image_path": "/images/screenshots/shot_abc123.png",
    "adjacent_images": ["/images/screenshots/shot_def456.png"],
    "hint_x": 1024,
    "hint_y": 2048
  }
  ```

`service-coords` は以下を実行します:
- storageから主画像と隣接画像を取得
- 画像解析（テンプレートマッチング、特徴点検出）を実行
- ヒント座標も考慮した座標推定
- `{"estimated_x": 1024, "estimated_y": 2048}` を返却

Worker は以下を実行します:
- レスポンスを受け取り、airflow DBのXComに保存
- Backend の `PUT /api/internal/screenshots/shot_abc123` を呼び出し:
  ```json
  {
    "estimated_x": 1024,
    "estimated_y": 2048
  }
  ```
- Backendは `screenshots` テーブルの該当レコードに推定座標を更新
- airflow DBでタスクを `success` に更新

#### Step 5: タイル切り出し
あるタイル（例: `tile_1_10_20`）に必要なすべてのcoords完了（例: `coords_0`, `coords_1`, `coords_128`, `coords_129`）後、`tile_1_10_20` が実行可能になります。

`airflow-worker-tiles` は `tiles` キューからタスク（`"tile_1_10_20"`）を取得します。

Worker は以下を実行します:
- airflow DBでタスクを `running` に更新
- DAGの設定からこのタイルが必要とするエリアID（例: `area_id: 0, 1, 128, 129`）を取得
- XComから各エリアのcapture・coords結果を取得し、以下のような `images` リストを構築:
  ```json
  [
    {
      "id": "shot_abc123",
      "path": "/images/screenshots/shot_abc123.png",
      "x": 1024,
      "y": 2048
    }
  ]
  ```
- `service-tiles` を呼び出し: `POST http://service-tiles:5002/cut`
  ```json
  {
    "images": [],
    "tile_x": 10,
    "tile_y": 20,
    "tile_size": 512
  }
  ```

`service-tiles` は以下を実行します:
- storageから複数の画像を取得
- 仮想キャンバス上に座標に基づいて配置
- タイル範囲（`x=10`, `y=20`, `size=512`）を切り出し
- AVIF（quality 30）に圧縮
- storageへ `PUT /images/tiles/1/10/20.avif` で保存
- `{"tile_path": "/images/tiles/1/10/20.avif"}` を返却

Worker は以下を実行します:
- レスポンスを受け取り、airflow DBのXComに保存
- Backend の `POST /api/internal/tiles` を呼び出し:
  ```json
  {
    "job_id": 123,
    "tiles": [
      {
        "z": 1,
        "x": 10,
        "y": 20,
        "filepath": "/images/tiles/1/10/20.avif"
      }
    ]
  }
  ```
- Backendは `tiles` テーブルにレコード挿入
- airflow DBでタスクを `success` に更新

#### Step 6: スクリーンショット削除
DAG設計では、各スクリーンショットを利用するすべてのタイル生成タスクが完了したとき、対応する削除タスク（`cleanup_0`）が実行可能になります。

例えば、スクリーンショットID `"shot_abc123"` が `tile_1_10_20` と `tile_1_10_21` の両方で使用される場合、両タイルが完了するまで `cleanup_0` は待機します。

`airflow-worker-cleanup` は `cleanup` キューからタスク（`"cleanup_0"`）を取得します。

Worker は以下を実行します:
- airflow DBでタスクを `running` に更新
- XComから対象スクリーンショットID（例: `"shot_abc123"`）を取得
- Backend の `DELETE /api/internal/screenshots/shot_abc123` を呼び出し

Backend は以下を実行します:
- storageへ `DELETE /images/screenshots/shot_abc123.png` でファイル削除
- gamedbの `screenshots` テーブルから該当レコード削除

Worker は以下を実行します:
- airflow DBでタスクを `success` に更新

この方式により、すべての必要なタイル生成が完了するまでスクリーンショットが削除されることはなく、また不要になると速やかに削除されます。

#### Step 7: 完了とステータス確認
Airflow DAGの全タスクが完了すると、dag_runは `success` 状態になります。

ブラウザはポーリングで定期的に `GET /api/status` を呼び出します。

Backend は以下を実行します:
- gamedbから全ジョブの情報を取得
- airflow DBからステータスを確認
- 各ジョブについて、生成されたタイル数を計算
- 全ジョブの情報を配列で返却:
  ```json
  [
    {
      "job_id": 123,
      "status": "completed",
      "progress": 100.0,
      "total_tiles": 100000,
      "created_tiles": 100000
    }
  ]
  ```

ブラウザは `status='completed'` を検知してポーリング停止、完了メッセージを表示します。

## 4. UseCase 2: Webブラウザでマップ閲覧

### 4.1 全体フロー概要
```text
1. ブラウザで MapLibre GL JS を初期化
2. 表示範囲から必要なタイルを計算
3. Backend へタイルリクエスト（並列）
4. Backend が Storage へプロキシ
5. ブラウザでタイル描画、マップ表示完了
```

### 4.2 詳細フロー

#### Browser
ユーザーがマップ閲覧ページ（`/view`）を開きます。Backendは `view.html` を返却します。

ブラウザ上で `MapLibre GL JS` が初期化されます。タイルレイヤーとして以下を指定します:
```javascript
L.tileLayer('http://backend:4567/tiles/{z}/{x}/{y}.avif', {
  maxZoom: 18,
  attribution: 'Game Map'
}).addTo(map);
```

ユーザーがマップを操作（表示、パン、ズーム）すると、MapLibreは現在の表示範囲に必要なタイルを計算します。例えば、ズームレベル `z=1`、表示範囲 `x=10-15`、`y=20-25` の場合、36枚のタイルが必要です。

ブラウザは並列（通常6-8並列）で以下のようなリクエストを送信します:
```text
GET http://backend:4567/tiles/1/10/20.avif
GET http://backend:4567/tiles/1/10/21.avif
... (計36リクエスト)
```

#### Backend
各タイルリクエストに対し、Backend は以下を実行します:
- リクエストを受け取る（例: `GET /tiles/1/10/20.avif`）
- storageにプロキシリクエスト: `GET http://storage:80/images/tiles/1/10/20.avif`
- storageからタイル画像バイナリを受け取る
- ブラウザに返却:
  ```text
  HTTP/1.1 200 OK
  Content-Type: image/avif
  Content-Length: 45678

  [バイナリデータ]
  ```

#### Browser
ブラウザはタイル画像を次々と受信し、キャッシュに保存します。各タイルはCanvasに描画されます。

全36枚のタイル受信により、マップ表示が完了します。

ユーザーがパン・ズームすると、新たに見える領域のタイルが自動的にリクエストされます。キャッシュに存在するタイルは即座に表示されます。

## 5. スケーリングとパフォーマンス

### 5.1 並列度の設定
システム全体の並列度は以下のとおりです。すべてのコンポーネントを統一した並列度（レプリカ数）で配置します。

| コンポーネント | レプリカ数 | キュー/役割 |
|---|---:|---|
| airflow-worker-capture | 2 | capture キュー処理 |
| airflow-worker-coords | 2 | coords キュー処理 |
| airflow-worker-tiles | 2 | tiles キュー処理 |
| airflow-worker-cleanup | 2 | cleanup キュー処理 |
| service-capture | 2 | スクリーンショット撮影 |
| service-coords | 2 | 座標推定 |
| service-tiles | 2 | タイル切り出し |

### 5.2 ボトルネック対策

#### スクリーンショット撮影
- ゲーム起動に時間がかかるため、撮影スループットがボトルネック。
- 対策: `service-capture` と `airflow-worker-capture` のレプリカ数を確保し、並列度を維持。

#### Storage I/O
- 大量の読み書きによるディスクI/Oがボトルネック。
- 対策: SSDを使用、ストレージネットワークの帯域確保。

#### タイル配信
- CDN導入を検討。複数のBackendインスタンスで負荷分散。

## 6. 重要な設計原則

### 6.1 責務の明確化
- **Backend**: ビジネスロジック、gamedb管理、Airflow制御、API提供、HTML配信。
- **Airflow**: DAG定義、タスク生成、依存関係管理、スケジューリング。
- **Airflow Workers**: タスク実行、Service呼び出し、Backend APIとの連携。
- **Services（service-capture/coords/tiles）**: 単一の専門処理のみを実行。ステートレス。他サービスやBackendの知識を持たない。
- **Storage**: ファイルのCRUD操作のみ。HTTPインターフェース。

### 6.2 変更耐性
- Service の処理ロジック変更は、Backend や Airflow に影響しない。
- Airflow DAGの構造変更は Service に影響しない。
- Backend の API設計により、データ永続化の詳細が Workers に漏えいしない。
