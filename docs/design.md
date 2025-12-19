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
    - `tiles`: タイルメタデータ（`tile_id`, `job_id`, `z`, `x`, `y`, `filepath`, `compressed`, `source_type` など）
      - `compressed`: 圧縮済みかどうか（boolean）
      - `source_type`: タイルの生成元（`screenshot`, `merged`）
  - `airflow`: Airflowメタデータ
    - `dag_run`: DAG実行履歴
    - `task_instance`: タスク実行状態
    - `xcom`: タスク間データ受け渡し

#### redis
- **役割**: メッセージブローカー
- **責務**:
  - Celery（Airflow Worker）のタスクキュー管理
  - キュー: `capture`, `estimate`, `tile_cut`, `tile_merge`, `tile_compress`, `tile_cleanup`, `screenshot_cleanup`
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
        {screenshot_id}.png # 一時データ
      rawtiles/
        {z}/
          {x}/
            {y}.png # 未圧縮タイル（一時データ）
      tiles
        {z}/
          {x}/
            {y}.avif # 圧縮タイル（永続データ）
  ```
- **エンドポイント**:

  | メソッド | パス | 説明 |
  |---|---|---|
  | PUT | `/images/screenshots/{screenshot_id}.png` | スクリーンショット保存 |
  | GET | `/images/screenshots/{screenshot_id}.png` | スクリーンショット取得 |
  | DELETE | `/images/screenshots/{screenshot_id}.png` | スクリーンショット削除 |
  | PUT | `/images/rawtiles/{z}/{x}/{y}.png` | 未圧縮タイル保存 |
  | GET | `/images/rawtiles/{z}/{x}/{y}.png` | 未圧縮タイル取得 |
  | DELETE | `/images/rawtiles/{z}/{x}/{y}.png` | 未圧縮タイル削除 |
  | PUT | `/images/tiles/{z}/{x}/{y}.avif` | 圧縮タイル保存 |
  | GET | `/images/tiles/{z}/{x}/{y}.avif` | 圧縮タイル取得 |

- **接続元**:
  - service-capture（PUT - スクリーンショット）
  - service-estimate（GET - スクリーンショット）
  - service-tile-cut（GET - スクリーンショット, PUT - 未圧縮タイル）
  - service-tile-merge（GET - 未圧縮タイル, PUT - 未圧縮タイル）
  - service-tile-compress（GET - 未圧縮タイル, PUT - 圧縮タイル）
  - airflow-worker-capture-cleanup（DELETE - スクリーンショット）
  - airflow-worker-tile-cleanup（DELETE - 未圧縮タイル）
  - backend（GET - 圧縮タイル配信）
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
| DELETE | `/api/internal/screenshots/{screenshot_id}` | スクリーンショット削除（DB） | - | `{"success": true}` |
| POST | `/api/internal/tiles` | タイルメタデータ保存（未圧縮） | `{"job_id": 0, "tiles": [{"z": 0, "x": 0, "y": 0, "filepath": "string", "source_type": "string"}]}` | `{"success": true}` |
| PUT | `/api/internal/tiles/compress` | タイル圧縮完了を記録 | `{"tile_ids": [0, 1, 2], "compressed_filepath": "string"}` | `{"success": true}` |
| DELETE | `/api/internal/tiles/{tile_id}` | タイル削除（DB） | - | `{"success": true}` |

##### タイル配信 API
| メソッド | パス | 説明 |
|---|---|---|
| GET | `/tiles/{z}/{x}/{y}.avif` | タイル画像配信（storage `/images/tiles/` へプロキシ） |

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

#### airflow-worker-estimate
- **役割**: 座標推定タスク実行ワーカー
- **責務**:
  - `estimate` キューからタスク取得
  - 前タスクの結果を XCom から取得
  - `service-estimate` サービス呼び出し
  - Backend API を通じて結果を `gamedb` に永続化
  - タスク状態更新
- **DB接続**:
  - `airflow`: 読み書き（タスク状態、XCom）
- **呼び出し先**:
  - redis: タスク取得
  - service-estimate: 座標推定依頼
  - backend: 結果の永続化
- **レプリカ数**: `2`
- **処理フロー**:
  1. Redis からタスク取得
  2. airflow DB でタスクを `running` 状態に更新
  3. airflow DB の XCom から前タスク結果取得
  4. `service-estimate` を呼び出し
  5. レスポンスを airflow DB の XCom に保存
  6. Backend の `/api/internal/screenshots/{id}` を呼び出して推定座標を更新
  7. airflow DB でタスクを `success` 状態に更新

#### airflow-worker-tile-cut
- **役割**: 最大ズームタイル切り出しタスク実行ワーカー（未圧縮）
- **責務**:
  - `tile_cut` キューからタスク取得
  - 前タスクの結果を XCom から取得
  - `service-tile-cut` サービス呼び出し
  - Backend API を通じて結果を `gamedb` に永続化
  - タスク状態更新
- **DB接続**:
  - `airflow`: 読み書き（タスク状態、XCom）
- **呼び出し先**:
  - redis: タスク取得
  - service-tile-cut: タイル切り出し依頼
  - backend: 結果の永続化
- **レプリカ数**: `2`
- **処理フロー**:
  1. Redis からタスク取得
  2. airflow DB でタスクを `running` 状態に更新
  3. airflow DB の XCom から複数の前タスク結果取得
  4. `service-tile-cut` を呼び出し
  5. レスポンスを airflow DB の XCom に保存
  6. Backend の `/api/internal/tiles` を呼び出してタイル情報を永続化
  7. airflow DB でタスクを `success` 状態に更新

#### airflow-worker-tile-merge
- **役割**: タイルマージタスク実行ワーカー（ズームアウト画像生成）
- **責務**:
  - `tile_merge` キューからタスク取得
  - 前タスクの結果を XCom から取得
  - `service-tile-merge` サービス呼び出し
  - Backend API を通じて結果を `gamedb` に永続化
  - タスク状態更新
- **DB接続**:
  - `airflow`: 読み書き（タスク状態、XCom）
- **呼び出し先**:
  - redis: タスク取得
  - service-tile-merge: タイルマージ依頼
  - backend: 結果の永続化
- **レプリカ数**: `2`
- **処理フロー**:
  1. Redis からタスク取得
  2. airflow DB でタスクを `running` 状態に更新
  3. airflow DB の XCom から子タイル（4枚）の情報取得
  4. `service-tile-merge` を呼び出し
  5. レスポンスを airflow DB の XCom に保存
  6. Backend の `/api/internal/tiles` を呼び出してマージタイル情報を永続化
  7. airflow DB でタスクを `success` 状態に更新

#### airflow-worker-tile-compress
- **役割**: タイル圧縮タスク実行ワーカー
- **責務**:
  - `tile_compress` キューからタスク取得
  - 前タスクの結果を XCom から取得
  - `service-tile-compress` サービス呼び出し
  - Backend API を通じて結果を `gamedb` に永続化
  - タスク状態更新
- **DB接続**:
  - `airflow`: 読み書き（タスク状態、XCom）
- **呼び出し先**:
  - redis: タスク取得
  - service-tile-compress: タイル圧縮依頼
  - backend: 結果の永続化
- **レプリカ数**: `2`
- **処理フロー**:
  1. Redis からタスク取得
  2. airflow DB でタスクを `running` 状態に更新
  3. airflow DB の XCom から未圧縮タイル情報取得
  4. `service-tile-compress` を呼び出し
  5. レスポンスを airflow DB の XCom に保存
  6. Backend の `/api/internal/tiles/compress` を呼び出して圧縮完了を記録
  7. airflow DB でタスクを `success` 状態に更新

#### airflow-worker-tile-cleanup
- **役割**: 未圧縮タイル削除タスク実行ワーカー
- **責務**:
  - `tile_cleanup` キューからタスク取得
  - 未圧縮タイルがもう使用されないことを確認
  - Backend API とストレージを通じて未圧縮タイルを削除（ファイル + DBレコード）
  - タスク状態更新
- **DB接続**:
  - `airflow`: 読み書き（タスク状態、XCom）
- **呼び出し先**:
  - redis: タスク取得
  - storage: 未圧縮タイル削除
  - backend: タイル削除指示
- **レプリカ数**: `2`
- **処理フロー**:
  1. Redis からタスク取得
  2. airflow DB でタスクを `running` 状態に更新
  3. XCom から対象タイルID取得
  4. Storage の `/images/rawtiles/{z}/{x}/{y}.png` DELETE を呼び出し
  5. Backend の `/api/internal/tiles/{tile_id}` DELETE を呼び出し
  6. airflow DB でタスクを `success` 状態に更新

#### airflow-worker-capture-cleanup
- **役割**: スクリーンショット削除タスク実行ワーカー
- **責務**:
  - `screenshot_cleanup` キューからタスク取得
  - スクリーンショットがもう使用されないことを確認
  - ストレージと Backend API を通じてスクリーンショットを削除（ファイル + DBレコード）
  - タスク状態更新
- **DB接続**:
  - `airflow`: 読み書き（タスク状態、XCom）
- **呼び出し先**:
  - redis: タスク取得
  - storage: スクリーンショット削除
  - backend: スクリーンショット削除指示
- **レプリカ数**: `2`
- **処理フロー**:
  1. Redis からタスク取得
  2. airflow DB でタスクを `running` 状態に更新
  3. XCom から対象スクリーンショットID取得
  4. Storage の `/images/screenshots/{screenshot_id}.png` DELETE を呼び出し
  5. Backend の `/api/internal/screenshots/{id}` DELETE を呼び出し
  6. airflow DB でタスクを `success` 状態に更新

### 2.5 処理サービス層

#### service-capture
- **役割**: スクリーンショット撮影サービス（Ruby + Sinatra）
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
  | POST | `/capture` | スクリーンショット撮影 | `{"save_data_name": "string", "x": 0, "y": 0, "output_path": "string"}` | `{"status": "ok"}` |

- **レプリカ数**: `2`
- **処理フロー**:
  1. リクエスト受信
  2. ゲームプロセス起動、セーブデータ読み込み
  3. 座標へ移動してスクリーンショット撮影(Shift+J, 数字キーの打ち込み、Enter打ち込み、Esc、カーソル退避、描画待ち、撮影)
  4. メニュー画面やフッター、カーソルがある部分をクリッピング
  5. ファイル名を生成して storage へ PUT
  6. 画像パスを返却
- **ゲームの起動について**
  - ゲームを起動するのには1分程度かかるので、ゲームプロセスは再利用する。
  - TTLは10分。
- **ポート**: `5000`

#### service-estimate
- **役割**: 座標推定サービス（Python + Flask + OpenCV）
- **責務**:
  - storage から画像取得
  - 既存画像（座標既知）と新画像（座標未知）を比較し、平行移動のみを仮定して新画像の絶対座標を推定する
  - 画像は ピクセル単位で RGB が完全一致する重複領域を持つ
  - 回転・スケール・歪みは一切存在しない
  - 新座標の仮定値をヒントとして受け取り、海上などの推定困難な場合に使用する
- **DB接続**: なし
- **呼び出し先**:
  - storage: 画像取得（GET）
- **エンドポイント**:

  | メソッド | パス | 説明 | リクエスト | レスポンス |
  |---|---|---|---|---|
  | POST | `/estimate` | 座標推定 | `{"image_path": "string", "adjacent_images": [{"image_path": "string", "x": number, "y": number}], "hint_x": number, "hint_y": number}` | `{"estimated_x": 0, "estimated_y": 0}` |

- **レプリカ数**: `2`
- **処理フロー**:
  1. リクエスト受信
  2. storage から主画像と隣接画像を取得
  3. ヒント座標を用いて座標推定処理実行
  4. メモリ解放
  5. 推定座標を返却
- **ポート**: `5001`
- **環境変数**:
  - `IMAGE_WIDTH`: 画像の横サイズ（px）、左右マージンを含んだ最終画像サイズ
  - `IMAGE_HEIGHT`: 画像の縦サイズ（px）、上下マージンを含んだ最終画像サイズ
  - `IMAGE_MARGIN_WIDTH`: 左右それぞれの未描画マージン幅（px）
  - `IMAGE_MARGIN_HEIGHT`: 上下それぞれの未描画マージン高さ（px）
  - `STORAGE_URL`: 画像取得元の base URL

#### service-tile-cut
- **役割**: 画像切り出しサービス（Python + Flask + Pillow）
- **責務**:
  - storage から複数のスクリーンショットを取得
  - 座標情報を元に仮想キャンバス上に配置
  - 指定ピクセル範囲を切り出し
  - 未圧縮PNG形式で storage へ保存
  - 保存パスを返却
- **DB接続**: なし
- **呼び出し先**:
  - storage: 画像取得（GET）、タイル保存（PUT）
- **エンドポイント**:

  | メソッド | パス | 説明 | リクエスト | レスポンス |
  |---|---|---|---|---|
  | POST | `/cut` | 画像切り出し | 下記参照 | `{"output_path": "string"}` |

- **リクエストボディ**:
  ```json
  {
    "images": [
      {
        "path": "string",      // storage上のパス
        "x": number,           // スクショ座標X
        "y": number            // スクショ座標Y
      }
    ],
    "cut_area": {
      "x": number,             // 切り出し開始X（スクショ座標）
      "y": number,             // 切り出し開始Y（スクショ座標）
    },
    "output_path": "string"    // 保存先パス（例: "/images/rawtiles/18/10/20.png"）
  }
  ```

- **レスポンス**:
  ```json
  {
    "output_path": "string",   // 保存されたパス
  }
  ```

- **レプリカ数**: `2`
- **処理フロー**:
  1. リクエスト受信
  2. 複数画像を storage から取得
  3. 仮想キャンバスに配置（各画像を指定座標に配置）
  4. `cut_area` で指定された範囲を切り出し
  5. 未圧縮PNG形式で `output_path` に保存
  6. メモリ解放
  7. 保存パスと実際のサイズを返却
- **ポート**: `5002`

#### service-tile-merge
- **役割**: 画像マージ・リサイズサービス（Python + Flask + Pillow）
- **責務**:
  - storage から4枚の画像を取得
  - 指定レイアウトで結合
  - 指定サイズにリサイズ
  - 未圧縮PNG形式で storage へ保存
  - 保存パスを返却
- **DB接続**: なし
- **呼び出し先**:
  - storage: 画像取得（GET）、画像保存（PUT）
- **エンドポイント**:

  | メソッド | パス | 説明 | リクエスト | レスポンス |
  |---|---|---|---|---|
  | POST | `/merge` | 画像マージ | 下記参照 | `{"output_path": "string"}` |

- **リクエストボディ**:
  ```json
  {
    "tiles": [
      {
        "path": "string",      // storage上のパス
        "position": "string"   // "top-left" | "top-right" | "bottom-left" | "bottom-right"
      }
    ],
    "output_path": "string"    // 保存先パス（例: "/images/rawtiles/17/10/20.png"）
  }
  ```

- **レスポンス**:
  ```json
  {
    "output_path": "string",   // 保存されたパス
  }
  ```

- **レプリカ数**: `2`
- **処理フロー**:
  1. リクエスト受信
  2. 4枚の画像を storage から取得
  3. 2x2の配置で結合（各タイルを指定位置に配置）
  4. `output_size` にリサイズ
  5. 未圧縮PNG形式で `output_path` に保存
  6. メモリ解放
  7. 保存パスと実際のサイズを返却
- **ポート**: `5003`

#### service-tile-compress
- **役割**: タイル圧縮サービス（Python + Flask + pillow-avif-plugin）
- **責務**:
  - storage から未圧縮タイルを取得
  - AVIF形式（qualityは環境変数で設定）で圧縮
  - storage へ圧縮タイルを保存
  - タイルパスを返却
- **DB接続**: なし
- **呼び出し先**:
  - storage: タイル取得（GET）、タイル保存（PUT）
- **エンドポイント**:

  | メソッド | パス | 説明 | リクエスト | レスポンス |
  |---|---|---|---|---|
  | POST | `/compress` | タイル圧縮 | `{"input_path": "str", "outpput_path": "str"}` | `{}` |

- **レプリカ数**: `2`
- **処理フロー**:
  1. リクエスト受信
  2. storage から未圧縮タイルを取得
  3. AVIFに圧縮
  4. storage の `/images/tiles/compressed/{z}/{x}/{y}.avif` に保存
  5. メモリ解放
  6. タイルパスを返却
- **ポート**: `5004`

## 3. UseCase 1: マップタイル生成フロー

### 3.1 全体フロー概要
```text
1. 管理画面で「タイル生成」ボタンを押下
2. Backend が job を作成し、Airflow DAG を起動
3. Airflow Scheduler がタスクを生成・スケジューリング
4. スクリーンショット撮影タスク（並列実行）
5. 座標推定タスク（並列実行）
6. 最大ズームタイル切り出しタスク（並列実行、未圧縮PNG）
7. 分岐A: 最大ズームタイル圧縮タスク（並列実行）
   → 未圧縮タイル削除タスク
8. 分岐B: ズームアウトタイルマージタスク（複数段階、並列実行、未圧縮PNG）
   → 各段階で圧縮タスク（並列実行）
   → 未圧縮タイル削除タスク
9. スクリーンショット削除タスク（各スクショの使用完了後、個別に実行）
10. 完了、管理画面でステータスを確認
```

ここでは未圧縮タイル削除タスクが2回書かれているが、実際にはDAGで適切に依存関係を設定することで、各タイルが使用されなくなったタイミングで1回だけ実行される。

### 3.2 タスク依存関係の詳細

最大ズームレベルを `z_max`、最小ズームレベルを `z_min` とします。

```text
capture_{i}
  >> estimate_{i}
  >> tile_cut_{z_max}_{x}_{y}  (最大ズームタイル切り出し)
  >> [
       tile_compress_{z_max}_{x}_{y}  (最大ズームタイル圧縮)
         >> tile_cleanup_{z_max}_{x}_{y}  (未圧縮タイル削除)
       ,
       tile_merge_{z_max-1}_{x/2}_{y/2}  (ズームアウト1段階目)
         >> tile_compress_{z_max-1}_{x/2}_{y/2}
         >> tile_cleanup_{z_max-1}_{x/2}_{y/2}
         >> tile_merge_{z_max-2}_{x/4}_{y/4}  (ズームアウト2段階目)
         >> ...
         >> tile_merge_{z_min}_{...}_{...}  (最小ズームまで)
         >> tile_compress_{z_min}_{...}_{...}
         >> tile_cleanup_{z_min}_{...}_{...}
     ]
  >> screenshot_cleanup_{i}  (全タイル完了後にスクショ削除)
```

**依存関係の詳細**:
- `tile_merge_{z}_{x}_{y}` は4枚の子タイル（`tile_cut_{z+1}_{2x}_{2y}`, `tile_cut_{z+1}_{2x+1}_{2y}`, `tile_cut_{z+1}_{2x}_{2y+1}`, `tile_cut_{z+1}_{2x+1}_{2y+1}`）または4枚のマージタイルの**圧縮完了**を待つ
- `tile_cleanup_{z}_{x}_{y}` は該当タイルを使用するすべてのタスク（圧縮タスク、またはマージタスク）の完了を待つ
- `screenshot_cleanup_{i}` は該当スクリーンショットを使用するすべての `tile_cut` タスクの子孫タスク（圧縮、マージ、削除すべて）の完了を待つ

### 3.3 詳細フロー

#### Step 1: タイル生成ジョブ作成
ユーザーは管理画面からゲームID（例: `"city01"`）とセーブデータ名（例: `"save_001"`）を指定して「タイル生成」ボタンを押下します。Backendは `POST /api/tiles/create` リクエストを受け取ります。

Backendは以下を実行します:
- gamedbに新しいジョブレコードを作成（`status='preparing'`）
- 撮影対象エリアのリストを計算
- タイル生成パラメータを計算（最大ズーム、最小ズーム、タイル依存関係）
- AirflowのDAG起動APIを呼び出し、`map_processing` DAGを起動
- 起動された `dag_run_id` を取得してDBに保存
- ジョブステータスを `running` に更新

Backendはクライアントに以下を返します:
```json
{"job_id": 123, "status": "running", "dag_run_id": "run_123"}
```

ブラウザは `/api/status` を3秒ごとにポーリング開始します。

#### Step 2: タスク生成とスケジューリング
Airflow Schedulerはdag_runを検知し、DAG定義ファイルを読み込みます。パラメータから撮影エリア数（例: 10,000）、ズームレベル範囲（例: z_max=18, z_min=0）、タイル依存関係を取得し、以下のタスクを動的に生成します:

- `capture_*_*`（スクリーンショット撮影）
- `estimate_*_*`（座標推定）
- `tile_cut_18_*_*`（最大ズームタイル切り出し、数十万個）
- `tile_compress_18_*_*`（最大ズームタイル圧縮）
- `tile_cleanup_18_*_*`（未圧縮タイル削除）
- `tile_merge_17_*_*`, `tile_compress_17_*_*`, `tile_cleanup_17_*_*`（ズームレベル17）
- `tile_merge_16_*_*`, `tile_compress_16_*_*`, `tile_cleanup_16_*_*`（ズームレベル16）
- ...（ズームレベル0まで）
- `screenshot_cleanup_0`, `screenshot_cleanup_1`, ...（スクリーンショット削除）

Schedulerは実行可能なタスク（`capture_*`）をRedisの `capture` キューに投入します。

ズームレベル範囲はpaksetのサイズとマップのサイズに基づいて決定される。

#### Step 3: スクリーンショット撮影
`airflow-worker-capture` は `capture` キューからタスク（例: `"capture_0_0"`）を取得します。

Worker は以下を実行します:
- airflow DBでタスクを `running` に更新
- ジョブの設定パラメータからエリアID 0の座標を取得（例: `x=0`, `y=0`）
- `service-capture` を呼び出し: `POST http://service-capture:5000/capture`
  ```json
  {
    "save_data_name": "save_demo",
    "x": 0,
    "y": 0,
    "output_path": "/images/screenshots/shot_abc123.png"
  }
  ```

`service-capture` は以下を実行します:
- スクリーンショット撮影
- `screenshot_id` を生成（例: `"shot_abc123"`）
- storageへ `PUT /images/screenshots/shot_abc123.png` でファイル保存
- `{"image_path": "/images/screenshots/shot_abc123.png"}` を返却

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
`airflow-worker-estimate` は `estimate` キューからタスク（`"estimate_0"`）を取得します。

Worker は以下を実行します:
- airflow DBでタスクを `running` に更新
- XComから、該当スクリーンショットの情報と、隣接エリアのスクリーンショット情報を取得
- DAGの設定から期待座標（ヒント）と隣接画像を取得
- `service-estimate` を呼び出し: `POST http://service-estimate:5001/estimate`
  ```json
  {
    "image_path": "/images/screenshots/shot_abc123.png",
    "adjacent_images": [
      {"image_path": "/images/screenshots/shot_def456.png", "x": 0, "y": 1024}
    ],
    "hint_x": 1024,
    "hint_y": 1024
  }
  ```

`service-estimate` は以下を実行します:
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

### Step 5: 最大ズームタイル切り出し
Worker は以下を実行します:
- airflow DBでタスクを `running` に更新
- DAGの設定からこのタイルが必要とするエリアID（例: `area_id: 0, 1, 128, 129`）を取得
- XComから各エリアのcapture・estimate結果を取得し、`images` リストを構築
- **座標変換を実施**: タイル座標 `(z=18, tx=10, ty=20)` からスクショ座標の切り出し範囲を計算
- `service-tile-cut` を呼び出し: `POST http://service-tile-cut:5002/cut`
  ```json
  {
    "images": [
      {
        "path": "/images/screenshots/shot_abc123.png",
        "x": 1024,
        "y": 2048
      }
    ],
    "cut_area": {
      "x": -5120,
      "y": 10240
    },
    "output_path": "/images/rawtiles/18/10/20.png"
  }
  ```

#### Step 6: 最大ズームタイル圧縮
`tile_cut_18_10_20` タスクが完了すると `tile_compress_18_10_20` が実行可能になります。

`airflow-worker-tile-compress` は `tile_compress` キューからタスク（`"tile_compress_18_10_20"`）を取得します。

Worker は以下を実行します:
- airflow DBでタスクを `running` に更新
- XComから `tile_cut_18_10_20` の結果を取得（`{"tile_path": "/images/rawtiles/18/10/20.png"}`）
- `service-tile-compress` を呼び出し: `POST http://service-tile-compress:5004/compress`
  ```json
  {
    "input_path": "/images/rawtiles/demo/18/10/20.png",
    "output_path": "/images/tiles/demo/18/10/20.avif"
  }
  ```

`service-tile-compress` は以下を実行します:
- storageから未圧縮タイルを取得
- AVIF（quality 30）に圧縮
- storageへ `PUT /images/tiles/18/10/20.avif` で保存
- `{"compressed_tile_path": "/images/tiles/18/10/20.avif"}` を返却

Worker は以下を実行します:
- レスポンスを受け取り、airflow DBのXComに保存
- Backend の `PUT /api/internal/tiles/compress` を呼び出し:
  ```json
  {
    "tile_ids": [456],
    "compressed_filepath": "/images/tiles/18/10/20.avif"
  }
  ```
- Backendは `tiles` テーブルの該当レコードを更新（`compressed=true`, `filepath` を圧縮版に更新）
- airflow DBでタスクを `success` に更新

### Step 7: ズームアウトタイルマージ（修正版）

Worker は以下を実行します:
- airflow DBでタスクを `running` に更新
- XComから4枚の子タイルの情報を取得
- **子タイルのパスを特定**: タイル座標 `(z=17, tx=10, ty=20)` の子タイルは以下
  ```python
  child_z = 18
  child_tiles = [
      (child_z, tx * 2, ty * 2),        # 左上
      (child_z, tx * 2 + 1, ty * 2),    # 右上
      (child_z, tx * 2, ty * 2 + 1),    # 左下
      (child_z, tx * 2 + 1, ty * 2 + 1) # 右下
  ]
  # 各子タイルのパスを構築
  # "/images/rawtiles/18/20/40.png" など
  ```
- `service-tile-merge` を呼び出し: `POST http://service-tile-merge:5003/merge`
  ```json
  {
    "tiles": [
      {
        "path": "/images/rawtiles/18/20/40.png",
        "position": "top-left"
      },
      {
        "path": "/images/rawtiles/18/21/40.png",
        "position": "top-right"
      },
      {
        "path": "/images/rawtiles/18/20/41.png",
        "position": "bottom-left"
      },
      {
        "path": "/images/rawtiles/18/21/41.png",
        "position": "bottom-right"
      }
    ],
    "output_path": "/images/rawtiles/17/10/20.png"
  }
  ```

#### Step 8: 未圧縮タイル削除
`tile_compress_18_10_20` タスクが完了し、このタイルを必要とする他のタスク（この場合は `tile_merge_17_5_10`）も完了すると、`tile_cleanup_18_10_20` が実行可能になります。

`airflow-worker-tile-cleanup` は `tile_cleanup` キューからタスク（`"tile_cleanup_18_10_20"`）を取得します。

Worker は以下を実行します:
- airflow DBでタスクを `running` に更新
- XComから対象タイルの情報を取得
- storageへ `DELETE /images/rawtiles/18/10/20.png` を呼び出し
- Backend の `DELETE /api/internal/tiles/{tile_id}` を呼び出し
- Backendは `tiles` テーブルから該当レコード削除（圧縮版レコードは残る）
- airflow DBでタスクを `success` に更新

#### Step 9: スクリーンショット削除
DAG設計では、各スクリーンショットを利用するすべてのタイル生成タスクとその子孫タスク（マージ、圧縮、削除すべて）が完了したとき、対応する削除タスク（`screenshot_cleanup_0`）が実行可能になります。

`airflow-worker-capture-cleanup` は `screenshot_cleanup` キューからタスク（`"screenshot_cleanup_0"`）を取得します。

Worker は以下を実行します:
- airflow DBでタスクを `running` に更新
- XComから対象スクリーンショットID（例: `"shot_abc123"`）を取得
- storageへ `DELETE /images/screenshots/shot_abc123.png` でファイル削除
- Backend の `DELETE /api/internal/screenshots/shot_abc123` を呼び出し
- Backendは `screenshots` テーブルから該当レコード削除
- airflow DBでタスクを `success` に更新

#### Step 10: 完了とステータス確認
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
L.tileLayer('http://backend:8000/tiles/{z}/{x}/{y}.avif', {
  maxZoom: 18,
  minZoom: 0,
  attribution: 'Game Map'
}).addTo(map);
```

ユーザーがマップを操作（表示、パン、ズーム）すると、MapLibreは現在の表示範囲に必要なタイルを計算します。例えば、ズームレベル `z=1`、表示範囲 `x=10-15`、`y=20-25` の場合、36枚のタイルが必要です。

ブラウザは並列（通常6-8並列）で以下のようなリクエストを送信します:
```text
GET http://backend:8000/tiles/1/10/20.avif
GET http://backend:8000/tiles/1/10/21.avif
... (計36リクエスト)
```

#### Backend
各タイルリクエストに対し、Backend は以下を実行します:
- リクエストを受け取る（例: `GET /tiles/1/10/20.avif`）
- storageにプロキシリクエスト: `GET http://storage:80/images/tiles/compressed/1/10/20.avif`
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
| airflow-worker-estimate | 2 | estimate キュー処理 |
| airflow-worker-tile-cut | 2 | tile_cut キュー処理 |
| airflow-worker-tile-merge | 2 | tile_merge キュー処理 |
| airflow-worker-tile-compress | 2 | tile_compress キュー処理 |
| airflow-worker-tile-cleanup | 2 | tile_cleanup キュー処理 |
| airflow-worker-capture-cleanup | 2 | screenshot_cleanup キュー処理 |
| service-capture | 2 | スクリーンショット撮影 |
| service-estimate | 2 | 座標推定 |
| service-tile-cut | 2 | タイル切り出し |
| service-tile-merge | 2 | タイルマージ |
| service-tile-compress | 2 | タイル圧縮 |

### 5.2 ボトルネック対策

#### スクリーンショット撮影
- ゲーム起動に時間がかかるため、撮影スループットがボトルネック。
- 対策: `service-capture` と `airflow-worker-capture` のレプリカ数を確保し、並列度を維持。

#### タイル処理
- 最大ズームレベルでは数十万〜数百万のタイルを処理するため、タイル切り出し・マージ・圧縮がボトルネック。
- 対策: 各処理を分離し、並列度を確保。未圧縮タイルの早期削除によりストレージ消費を抑制。

#### Storage I/O
- 大量の読み書きによるディスクI/Oがボトルネック。
- 対策: SSDを使用、ストレージネットワークの帯域確保。

#### タイル配信
- CDN導入を検討。複数のBackendインスタンスで負荷分散。

### 5.3 ストレージ最適化

#### 段階的な削除戦略
- **未圧縮タイル**: 圧縮完了後およびマージ完了後に即座に削除
- **スクリーンショット**: すべての依存タイル処理完了後に削除
- **圧縮タイル**: 永続保存

#### ストレージ使用量の推定
最大ズームタイル数を N とすると:
- **スクリーンショット**: 約 N/100 枚（重複撮影考慮）、各 5MB → 合計 N/20 MB
- **未圧縮タイル（最大同時）**: 最大ズームで N 枚、各 1MB → 最大 N MB（段階的削除により実際はより少ない）
- **圧縮タイル（永続）**: 全ズームレベル合計で約 1.33N 枚、各 50KB → 約 N/15 MB

## 6. 重要な設計原則

### 6.1 責務の明確化
- **Backend**: ビジネスロジック、gamedb管理、Airflow制御、API提供、HTML配信。
- **Airflow**: DAG定義、タスク生成、依存関係管理、スケジューリング。
- **Airflow Workers**: タスク実行、Service呼び出し、Backend APIとの連携。
- **Services（service-*）**: 単一の専門処理のみを実行。ステートレス。他サービスやBackendの知識を持たない。
- **Storage**: ファイルのCRUD操作のみ。HTTPインターフェース。

### 6.2 変更耐性
- Service の処理ロジック変更は、Backend や Airflow に影響しない。
- Airflow DAGの構造変更は Service に影響しない。
- Backend の API設計により、データ永続化の詳細が Workers に漏えいしない。

### 6.3 段階的処理の利点
- **メモリ効率**: 未圧縮タイルを早期削除することで、ストレージ使用量を抑制。
- **並列性**: 切り出し、マージ、圧縮を独立したタスクにすることで、高い並列度を実現。
- **失敗時の復旧**: 各段階が独立しているため、失敗したタスクのみ再実行可能。
- **柔軟性**: 圧縮品質やズームレベル範囲の変更が容易。

