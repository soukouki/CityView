# Simutrans CityView 設計書

## 1. システム概要

### 1.1 目的
街づくりシミュレーションゲームのマップ画面をスクリーンショット撮影し、座標推定・タイル切り出しを経て、WebGIS形式で閲覧可能にするシステム。

### 1.2 アーキテクチャの基本原則

**依存関係の一方向性**
```
Browser → Backend → Airflow → Workers → Services → Storage
```
- すべての依存関係は一方向です。
- 下位層から上位層への呼び出しは一切行いません。
- データの永続化は、原則として Backend API を通じて行われます。

**責務の分離**
- **Backend**: ビジネスロジック、DB管理、Airflow制御、データ永続化APIの提供。
- **Airflow**: ワークフロー管理、タスクオーケストレーション。
- **Workers**: タスク実行、サービス呼び出し、Backend API経由での結果永続化。
- **Services**: 専門処理のみ（DB接続なし、他コンテナ呼び出しなし）。
- **Storage**: ファイル操作のみ。

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
- airflow-worker-*（airflow への読み書き）

**ポート**: 5432

**データベース**:
- `gamedb`: アプリケーションデータ
  - `jobs`: ジョブ管理
  - `savedatas`: ゲームのセーブデータ情報
  - `screenshots`: スクリーンショットメタデータ
  - `coordinates`: 座標推定結果
  - `tiles`: タイルメタデータ
  - `tile_dependencies`: タイル依存関係
  - `screenshot_usage`: スクリーンショット使用状況
- `airflow`: Airflowメタデータ
  - `dag_run`: DAG実行履歴
  - `task_instance`: タスク実行状態
  - `xcom`: タスク間データ受け渡し

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
          {y}.avif            # 永続データ
```

**エンドポイント**:
| メソッド | パス | 説明 |
|---------|------|------|
| PUT | `/images/screenshots/{screenshot_id}.png` | スクリーンショット保存 |
| GET | `/images/screenshots/{screenshot_id}.png` | スクリーンショット取得 |
| DELETE | `/images/screenshots/{screenshot_id}.png` | スクリーンショット削除 |
| PUT | `/images/tiles/{z}/{x}/{y}.avif` | タイル保存 |
| GET | `/images/tiles/{z}/{x}/{y}.avif` | タイル取得 |

**接続元**:
- service-capture（PUT）
- service-coords（GET）
- service-tiles（GET, PUT）
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
- タイル配信（storage へのリバースプロキシ）
- 管理画面 API および内部 API 提供

**DB接続**:
- gamedb: 読み書き

**呼び出し先**:
- airflow-webserver: DAG起動
- storage: タイル取得（配信用）

**エンドポイント**:

##### 管理画面 API
| メソッド | パス | 説明 | リクエスト | レスポンス (配列) |
|---------|------|------|-----------|-----------|
| POST | `/api/jobs` | ジョブ作成、Airflow DAG起動 | `{"game_id": string, "save_data_name": string}` | `{"job_id": integer, "status": string, "dag_run_id": string}` |
| GET | `/api/jobs/status` | 全ジョブのステータス一覧取得 | - | `[{"job_id": integer, "status": string, "progress": float, ...}]` |

##### Airflow Workers 専用内部 API
このAPI群は、Airflow Workerから呼び出されることを想定した内部APIであり、データ永続化の責任をBackendに集約するための**推奨されるアーキテクチャパターン**です。

| メソッド | パス | 説明 |
|---------|------|------|
| POST | `/api/internal/screenshots` | スクリーンショットメタデータ保存 |
| POST | `/api/internal/coordinates` | 座標情報保存 |
| POST | `/api/internal/tiles` | タイルメタデータ保存 |
| POST | `/api/internal/jobs/{job_id}/cleanup` | ジョブ完了後のクリーンアップ実行 |

##### タイル配信 API
| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/tiles/{z}/{x}/{y}.avif` | タイル画像配信（storage へプロキシ） |

**ポート**: 4567

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

---

#### airflow-scheduler
**役割**: Airflow スケジューラー

**責務**:
- DAG定義の読み込みとタスク生成
- タスクの依存関係管理
- 実行可能なタスクの検出
- Redis へのタスク投入
- タスク完了の監視と次タスクのスケジューling

**DB接続**:
- airflow: 読み書き

**呼び出し先**:
- redis: タスク投入（LPUSH）

---

### 2.4 Airflow Worker層

#### airflow-worker-capture
**役割**: スクリーンショット撮影タスク実行ワーカー

**責務**:
- `capture` キューからタスク取得
- `service-capture` サービス呼び出し
- 結果を airflow DB（XCom）に保存
- **Backend API を通じて結果を gamedb に永続化**
- タスク状態更新

**DB接続**:
- airflow: 読み書き（タスク状態、XCom）

**呼び出し先**:
- redis: タスク取得（BLPOP capture）
- backend: 結果の永続化
- service-capture: スクリーンショット撮影依頼

**レプリカ数**: 3

**処理フロー**:
1. Redis からタスク取得
2. airflow DB でタスクを 'running' 状態に更新
3. `service-capture` サービスを呼び出し
4. レスポンスを airflow DB の XCom に保存
5. **Backend の内部APIを呼び出し、スクリーンショットメタデータを永続化**
6. airflow DB でタスクを 'success' 状態に更新

---

#### airflow-worker-coords
**役割**: 座標推定タスク実行ワーカー

**責務**:
- `coords` キューからタスク取得
- 前タスクの結果を XCom から取得
- `service-coords` サービス呼び出し
- 結果を airflow DB（XCom）に保存
- **Backend API を通じて結果を gamedb に永続化**
- タスク状態更新

**DB接続**:
- airflow: 読み書き（タスク状態、XCom）

**呼び出し先**:
- redis: タスク取得（BLPOP coords）
- backend: 結果の永続化
- service-coords: 座標推定依頼

**レプリカ数**: 2

**処理フロー**:
1. Redis からタスク取得
2. airflow DB でタスクを 'running' 状態に更新
3. airflow DB の XCom から前タスク結果取得
4. `service-coords` サービスを呼び出し
5. レスポンスを airflow DB の XCom に保存
6. **Backend の内部APIを呼び出し、座標情報を永続化**
7. airflow DB でタスクを 'success' 状態に更新

---

#### airflow-worker-tiles
**役割**: タイル切り出しタスク実行ワーカー

**責務**:
- `tiles` キューからタスク取得
- 前タスクの結果を XCom から取得
- `service-tiles` サービス呼び出し
- 結果を airflow DB（XCom）に保存
- **Backend API を通じて結果を gamedb に永続化**
- タスク状態更新
- （`default`キューで）ジョブ完了後のクリーンアップタスクを実行

**DB接続**:
- airflow: 読み書き（タスク状態、XCom）

**呼び出し先**:
- redis: タスク取得（BLPOP tiles, BLPOP default）
- backend: 結果の永続化、クリーンアップ指示
- service-tiles: タイル切り出し依頼
- storage: スクリーンショット削除（DELETE）

**レプリカ数**: 2

**処理フロー（タイル切り出し）**:
1. Redis からタスク取得
2. airflow DB でタスクを 'running' 状態に更新
3. airflow DB の XCom から複数の前タスク結果取得
4. `service-tiles` サービスを呼び出し
5. レスポンスを airflow DB の XCom に保存
6. **Backend の内部APIを呼び出し、タイル情報とスクリーンショット使用状況を永続化**
7. airflow DB でタスクを 'success' 状態に更新

**処理フロー（クリーンアップ）**:
1. DAGの最終タスクとしてトリガーされる
2. BackendのクリーンアップAPIを呼び出し、ジョブIDを渡す
3. Backendは対象ジョブの一時スクリーンショットファイルと関連DBレコードを削除する
4. airflow DB でタスクを 'success' 状態に更新

---

### 2.5 処理サービス層

#### service-capture
**役割**: スクリーンショット撮影サービス（Python + Flask）

**責務**:
- ゲームプロセス起動（仮想ディスプレイ上）
- 指定セーブデータと座標でスクリーンショット撮影
- storage へ画像保存
- 結果返却（画像パス）

**DB接続**: なし

**呼び出し先**:
- storage: 画像保存（PUT）

**エンドポイント**:
| メソッド | パス | 説明 | リクエスト | レスポンス |
|---------|------|------|-----------|-----------|
| POST | `/capture` | スクリーンショット撮影 | `{"save_data_name": string, "x": integer, "y": integer}` | `{"image_path": string}` |

**レプリカ数**: 3

**処理フロー**:
1. リクエスト受信
2. ゲームプロセス起動、指定セーブデータ読み込み
3. 指定座標へ移動しスクリーンショット撮影
4. 一意なファイル名を生成し、storage へ PUT リクエスト
5. ゲームプロセス終了、メモリ解放
6. レスポンス（画像パス）を返却

**注意事項**: DB接続や他サービス呼び出しは行わず、撮影処理のみに責務を限定。

---

#### service-coords
**役割**: 座標推定サービス（Python + Flask + OpenCV）

**責務**:
- storage から画像取得
- 画像解析による座標推定
- 結果返却（推定座標）

**DB接続**: なし

**呼び出し先**:
- storage: 画像取得（GET）

**エンドポイント**:
| メソッド | パス | 説明 | リクエスト | レスポンス |
|---------|------|------|-----------|-----------|
| POST | `/estimate` | 座標推定 | `{"image_path": string, "adjacent_images": array, "hint_x": integer, "hint_y": integer}` | `{"estimated_x": integer, "estimated_y": integer}` |

**レプリカ数**: 2

**処理フロー**:
1. リクエスト受信
2. `image_path` と `adjacent_images` の画像を storage から取得
3. `hint_x`, `hint_y` をヒントに座標推定処理を実行
4. メモリ解放
5. レスポンス（推定座標）を返却

**注意事項**: DB接続や他サービス呼び出しは行わず、座標推定処理のみに責務を限定。

---

#### service-tiles
**役割**: タイル切り出しサービス（Python + Flask + Pillow）

**責務**:
- storage から複数の画像取得
- 座標情報を元に画像を結合
- 指定範囲を切り出し、タイル画像を1枚生成
- AVIF形式 (quality 30) で圧縮
- storage へタイル保存
- 結果返却（タイルパス）

**DB接続**: なし

**呼び出し先**:
- storage: 画像取得（GET）、タイル保存（PUT）

**エンドポイント**:
| メソッド | パス | 説明 | リクエスト | レスポンス |
|---------|------|------|-----------|-----------|
| POST | `/cut` | タイル切り出し | `{"images": array, "tile_x": integer, "tile_y": integer, "tile_size": integer}` | `{"tile_path": string}` |

**レプリカ数**: 2

**処理フロー**:
1. リクエスト受信
2. リクエスト内の複数画像を storage から取得
3. 仮想キャンバス上に画像を配置
4. 指定されたタイル座標とサイズに基づき領域を切り出し
5. 画像を AVIF (quality 30) 形式に圧縮
6. storage へタイルを保存
7. メモリ解放
8. レスポンス（生成されたタイルパス）を返却

**注意事項**: DB接続や他サービス呼び出しは行わず、タイル切り出し処理のみに責務を限定。

---

## 3. UseCase 1: マップタイル生成フロー

### 3.1 全体フロー概要

```
1. 管理画面でジョブ作成ボタンを押下
   ↓
2. Backend が job を作成し、Airflow DAG を起動
   ↓
3. Airflow Scheduler がタスクを生成・スケジューリング
   ↓
4. スクリーンショット撮影タスク（並列実行）
   ↓
5. 座標推定タスク（並列実行）
   ↓
6. タイル切り出しタスク（並列実行）
   ↓
7. 全タイル生成完了後、スクリーンショットを一括削除
   ↓
8. 完了、管理画面でステータスを確認
```

---

### 3.2 詳細フロー

#### Step 1: ジョブ作成とDAG起動

ユーザーがブラウザの管理画面からゲームIDとセーブデータ名を指定してジョブ作成をリクエストします。
Backendはリクエストを受け、gamedbに新しいジョブレコードを作成します。その後、撮影対象エリアのリストやタイル依存関係を計算し、それらをパラメータとしてAirflow REST APIを呼び出し、`map_processing` DAGを起動します。
BackendはクライアントにジョブIDと"running"ステータスを返します。ブラウザは定期的にステータスAPI (`/api/jobs/status`) をポーリングして進捗を確認します。

#### Step 2: タスクスケジューリング

Airflow Schedulerは起動されたDAGを検知し、パラメータに基づいて動的にタスク（撮影、座標推定、タイル生成、クリーンアップ）を生成します。タスク間の依存関係を設定し、実行可能な最初のタスク群（スクリーンショット撮影タスク）をRedisのキューに投入します。

#### Step 3: スクリーンショット撮影

`airflow-worker-capture` が `capture` キューからタスクを取得します。Workerはタスクパラメータ（撮影座標、セーブデータ名など）を元に `service-capture` を呼び出します。`service-capture` はゲームを起動してスクリーンショットを撮影し、Storageに保存後、画像パスを返します。Workerは受け取った画像パスをBackendの内部APIに送り、メタデータをgamedbに永続化させます。

#### Step 4: 座標推定

スクリーンショット撮影タスクが完了すると、依存する座標推定タスクが実行可能になります。`airflow-worker-coords` は `coords` キューからタスクを取得し、前タスクのXComから画像パスなどの情報を取得します。また、期待される座標をヒント座標として `service-coords` を呼び出します。`service-coords` は画像を解析し、より正確な推定座標を返します。Workerはこの結果をBackendの内部API経由でgamedbに永続化させます。

#### Step 5: タイル切り出し

あるタイルを生成するのに必要な全てのスクリーンショットの座標推定が完了すると、タイル切り出しタスクが実行可能になります。`airflow-worker-tiles` は `tiles` キューからタスクを取得し、依存する複数のスクリーンショット情報（画像パス、推定座標）をXComから集約します。
Workerはこれらの情報を `service-tiles` に渡してタイル生成を依頼します。`service-tiles` は複数の画像を合成し、指定された範囲を切り出して1枚のタイル画像を生成します。画像はAVIF形式（quality 30）に圧縮され、Storageに保存されます。Workerは生成されたタイルパスを受け取り、Backendの内部API経由でgamedbに永続化させます。

#### Step 6: スクリーンショットの一括削除

DAG内の全てのタイル生成タスクが完了した後、最終タスクとしてクリーンアップタスクがトリガーされます。このタスクは、ジョブで使用されたすべての一時スクリーンショットファイルと、それに関連するDB上のメタデータ（screenshots, coordinatesテーブルなど）を削除する責務を持ちます。WorkerはBackendのクリーンアップAPIを呼び出すことで、この処理を実行します。これにより、ストレージ容量とDBをクリーンな状態に保ちます。

#### Step 7: 完了とステータス確認

ブラウザは定期的に `GET /api/jobs/status` をポーリングしています。Backendはこのリクエストに対し、gamedbとairflow DBから情報を集約し、全ジョブの最新ステータス（進捗率、完了タスク数など）を配列で返します。
Airflow DAGの実行が完了すると、Backendは該当ジョブのステータスを "completed" に更新します。ブラウザはこれ検知してポーリングを停止し、ユーザーに完了を通知します。

---

## 4. UseCase 2: Webブラウザでマップ閲覧

### 4.1 全体フロー概要

```
1. ブラウザで MapLibre GL JS を初期化
   ↓
2. 表示範囲から必要なタイルを計算
   ↓
3. Backend へタイルリクエスト（並列）
   ↓
4. Backend が Storage へプロキシ
   ↓
5. ブラウザでタイル描画、マップ表示完了
```

---

### 4.2 詳細フロー

**Browser**
ユーザーがマップ閲覧ページを開くと、クライアントサイドのJavaScriptが `MapLibre GL JS` ライブラリを初期化します。タイルレイヤーとして、Backendが提供するタイル配信APIのエンドポイント (`/tiles/{z}/{x}/{y}.avif`) を指定します。

MapLibre GL JSは、現在のマップの表示範囲（緯度経度）とズームレベルに基づき、描画に必要なタイルURLを自動的に計算し、Backendに対して複数のHTTP GETリクエストを並列で送信します。

**Backend**
Backendは、`/tiles/{z}/{x}/{y}.avif` へのリクエストを受け取ると、内部でリクエストをStorageサーバーにプロキシします。Storageサーバーは該当パスのタイル画像ファイル（AVIF形式）を読み込み、Backendに返します。

BackendはStorageから受け取った画像データをそのままクライアント（ブラウザ）に返します。

**Browser**
ブラウザはタイル画像を次々と受信し、マップ上の正しい位置に描画していきます。すべてのタイルが揃うと、マップ表示が完了します。ユーザーがマップをパン（移動）したりズームしたりすると、MapLibre GL JSは新たに見えるようになった領域のタイルを再度リクエストし、シームレスな地図体験を提供します。

---

## 5. データフロー図

### 5.1 依存関係（一方向）

```
Browser
  ↓ HTTP Request
Backend
  ↓ Airflow REST API / Internal API Call
Airflow Webserver / Airflow Workers
  ↓ (Scheduler -> Redis -> Worker)
Airflow Scheduler
  ↓ Redis Publish
Redis
  ↓ Message Queue
Airflow Workers
  ↓ HTTP Request
Services (service-capture/service-coords/service-tiles)
  ↓ HTTP Request
Storage
```

### 5.2 データ永続化の責任

| データ | 永続化担当 | DB | テーブル（例） |
|--------|-----------|-----|----------|
| Job 情報 | Backend | gamedb | jobs |
| タイル依存関係 | Backend | gamedb | tile_dependencies |
| DAG Run | Airflow Webserver | airflow | dag_run |
| Task Instance | Airflow Scheduler | airflow | task_instance |
| スクリーンショット | Backend (Worker経由) | gamedb | screenshots |
| 座標情報 | Backend (Worker経由) | gamedb | coordinates |
| タイル情報 | Backend (Worker経由) | gamedb | tiles |
| XCom（タスク間データ） | 各 Airflow Worker | airflow | xcom |

### 5.3 ファイル操作の責任

| ファイル | 操作 | 担当コンテナ | storage API |
|---------|------|-------------|-------------|
| スクリーンショット | 保存 | service-capture | PUT |
| スクリーンショット | 取得 | service-coords, service-tiles | GET |
| スクリーンショット | 削除 | airflow-worker-tiles (Backend経由) | DELETE |
| タイル | 保存 | service-tiles | PUT |
| タイル | 配信 | backend（nginx経由） | GET |

---

## 6. 重要な設計原則

### 6.1 依存関係の一方向性

**絶対に守るべきルール**:
- 下位層から上位層への呼び出しは一切行いません。
- Services (service-capture/coords/tiles) は Backend を呼び出しません。
- データ永続化は、Airflow WorkersからBackendの内部APIを呼び出すことで行います。

**避けるべき設計**:
```
❌ service-tiles → backend API → gamedb (責務違反、循環依存のリスク)
❌ airflow-worker-capture → gamedb (直接書き込み、責務違反)
```

**推奨される設計**:
```
✅ airflow-worker-capture → service-capture → storage
✅ airflow-worker-capture → backend (内部API) → gamedb
```

### 6.2 責務の明確化

**各層の責務**:
- **Services**: 専門処理のみ。ステートレスであり、DB接続や他サービス呼び出しは行いません。
- **Workers**: タスクの実行とオーケストレーション。Servicesを呼び出し、その結果をBackend API経由で永続化します。
- **Airflow**: ワークフロー全体の管理と依存関係制御。
- **Backend**: ビジネスロジック、API提供、データ永続化の一元管理。

### 6.3 データ永続化のタイミング

**原則**:
- Airflow WorkersがServicesから処理結果を受け取った後、Backendの内部APIを呼び出して即座にDBへ永続化します。
- Servicesは結果を返すのみで、永続化には関与しません。
- このパターンにより、データ永続化のロジックがBackendに集約され、システム全体の整合性と保守性が向上します。

---

## 7. スケーリングとパフォーマンス

### 7.1 並列度の設定

| コンテナ | レプリカ数 | キュー | 並列処理数 |
|------------------|-----------|--------|-----------|
| airflow-worker-capture | 3 | capture | 3 |
| airflow-worker-coords | 2 | coords | 2 |
| airflow-worker-tiles | 2 | tiles | 2 |
| service-capture | 3 | - | 3 |
| service-coords | 2 | - | 2 |
| service-tiles | 2 | - | 2 |

### 7.2 ボトルネック対策

**想定されるボトルネック**:
1. スクリーンショット撮影（ゲーム起動に時間がかかる）
   - **対策**: `service-capture` と `airflow-worker-capture` のレプリカ数を他のコンポーネントより多く配置し、並列度を高めます。

2. Storage I/O
   - **対策**: 高速なストレージ（SSDなど）を使用します。一時ファイル（スクリーンショット）は処理完了後に速やかに削除し、ストレージ使用量を抑制します。

3. タイル配信
   - **対策**: CDNの導入を検討します。また、BackendとStorage間のネットワーク帯域を確保します。

---

この設計書に従うことで、依存関係が一方向で、責務が明确に分離された、保守性と拡張性の高いシステムを構築できます。