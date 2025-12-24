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
- オーケストレーション層の変更がBackendやサービスに影響しないように設計する。

## 2. コンテナ構成

### 2.1 インフラストラクチャ層

#### db (PostgreSQL)
- **役割**: データベースサーバー
- **責務**:
  - アプリケーションデータの永続化（`app`）
  - Prefectメタデータの永続化（`app`内の`prefect_*`テーブル）
- **接続元**:
  - backend（`app` への読み書き）
  - prefect-server（`app` 内の `prefect_*` テーブルへの読み書き）
  - prefect-agent（`app` への読み書き：Backend API経由）
- **ポート**: `5432`
- **データベース**:
  - `app`: アプリケーションデータおよびPrefectメタデータ
    - `jobs`: ジョブ管理（`job_id`, `game_id`, `save_data_name`, `status`, `flow_run_id`, `created_at` など）
    - `savedatas`: セーブデータ情報
    - `screenshots`: スクリーンショットと推定座標（`screenshot_id`, `job_id`, `x`, `y`, `estimated_x`, `estimated_y`, `filepath`, `status` など）
    - `tiles`: タイルメタデータ（`tile_id`, `job_id`, `z`, `x`, `y`, `filepath`, `compressed`, `source_type` など）
      - `compressed`: 圧縮済みかどうか（boolean）
      - `source_type`: タイルの生成元（`screenshot`, `merged`）
  - `prefect`: Prefect内部用データベース
    - `prefect_*`: Prefectメタデータ（Prefect Serverが自動作成・管理）

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
      tiles/
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
  - backend（GET - 圧縮タイル配信）
- **ポート**: `80`
- **設定**: nginx WebDAV有効化、最大アップロードサイズ 50MB

### 2.2 アプリケーション層

#### backend
- **役割**: バックエンドAPIサーバー（Ruby + Sinatra）
- **責務**:
  - ビジネスロジック実行
  - `app` への読み書き
  - Prefect Flow起動
  - 管理画面/マップ閲覧画面のHTML配信
  - 静的ファイル（CSS、JavaScript等）の配信
  - タイル配信（storage へのリバースプロキシ）
  - 管理画面 API および内部 API 提供
- **DB接続**:
  - `app`: 読み書き
- **呼び出し先**:
  - prefect-server: Flow起動
  - storage: タイル取得（配信用）
- **ポート**:
  - メイン: `8000`
  - 管理画面: `8001`
  - Prefect Agent 内部 API: `8002`
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
| POST | `/api/tiles/create` | タイル生成ジョブ作成、Flow起動 | `{"game_id": "string", "save_data_name": "string"}` | `{"job_id": 0, "status": "string", "flow_run_id": "string"}` |
| GET | `/api/status` | 全ジョブのステータス一覧取得 | - | `[{"job_id": 0, "status": "string", "progress": 0.0, "total_tiles": 0, "created_tiles": 0}]` |

##### Prefect Agent 専用内部 API
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

### 2.3 Prefect層

#### prefect-server
- **役割**: Prefect Server（オーケストレーション管理サーバー）
- **責務**:
  - Flow実行の管理
  - タスク状態の追跡
  - Web UIの提供
  - REST APIの提供
  - `app` 内の `prefect_*` テーブルへの読み書き
- **DB接続**:
  - `app`: 読み書き（`prefect_*` テーブル）
- **エンドポイント**:

  | メソッド | パス | 説明 |
  |---|---|---|
  | POST | `/api/deployments/{deployment_id}/create_flow_run` | Flow実行トリガー |
  | GET | `/api/flow_runs/{flow_run_id}` | Flow実行状態取得 |

- **ポート**: `8003`

#### prefect-agent
- **役割**: Prefect Agent（Flow実行ワーカー）
- **責務**:
  - Prefect Serverからフロー実行を取得
  - Flowの実行（動的タスク生成含む）
  - 各 `service-*` サービスの呼び出し
  - Backend API を通じた結果の永続化
  - タスク状態の報告
- **DB接続**: なし（Backend API経由でのみデータ操作）
- **呼び出し先**:
  - prefect-server: Flow取得、状態報告
  - service-capture: スクリーンショット撮影依頼
  - service-estimate: 座標推定依頼
  - service-tile-cut: タイル切り出し依頼
  - service-tile-merge: タイルマージ依頼
  - service-tile-compress: タイル圧縮依頼
  - backend: 結果の永続化（内部API）
- **レプリカ数**: `2`
- **環境変数**:
  - `PREFECT_API_URL`: `http://prefect-server:8003/api`
- **処理フロー**:
  1. Prefect Server からフロー実行指示を取得
  2. Flow関数を実行（動的にタスクを生成・実行）
  3. 各タスク内で `service-*` を呼び出し
  4. Backend の `/api/internal/*` を呼び出して結果を永続化
  5. タスク完了を Prefect Server に報告
  6. Flow完了を Prefect Server に報告

### 2.4 処理サービス層

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
  | POST | `/capture` | スクリーンショット撮影 | `{"save_data_name": "string", "x": 0, "y": 0, "output_path": "string", "zoom_level": "string"}` | `{"status": "ok"}` |
  - `zoom_level` : `"quarter"`, `"half"`, `"normal"`, `"double"`のいずれか

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
      "y": number              // 切り出し開始Y（スクショ座標）
    },
    "output_path": "string"    // 保存先パス（例: "/images/rawtiles/18/10/20.png"）
  }
  ```

- **レスポンス**:
  ```json
  {
    "output_path": "string"   // 保存されたパス
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
    "output_path": "string"   // 保存されたパス
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
  | POST | `/compress` | タイル圧縮 | `{"input_path": "str", "output_path": "str", "quality": str}` | `{}` |

  - `quality` : 0〜100 もしくは "lossless"

- **レプリカ数**: `2`
- **処理フロー**:
  1. リクエスト受信
  2. storage から未圧縮タイルを取得
  3. AVIFに圧縮
  4. storage の `/images/tiles/{z}/{x}/{y}.avif` に保存
  5. メモリ解放
  6. タイルパスを返却
- **ポート**: `5004`

## 3. UseCase 1: マップタイル生成フロー

### 3.1 全体フロー概要
```text
1. 管理画面で「タイル生成」ボタンを押下
2. Backend が job を作成し、Prefect Flow を起動
3. Prefect Agent がフローを実行（動的にタスクを生成）
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

ここでは未圧縮タイル削除タスクが2回書かれているが、実際にはFlowで適切に依存関係を設定することで、各タイルが使用されなくなったタイミングで1回だけ実行される。

### 3.2 タスク依存関係の詳細

最大ズームレベルを `z_max`、最小ズームレベルを `z_min` とします。

```text
capture_{i}
  >> estimate_{i}
  >> tile_cut_{z_max}_{x}_{y}  (最大ズームタイル切り出し)
  >> [
       tile_compress_{z_max}_{x}_{y}  (最大ズームタイル圧縮)
       ,
       tile_merge_{z_max-1}_{x/2}_{y/2}  (ズームアウト1段階目)
        >> [
          tile_compress_{z_max-1}_{x/2}_{y/2}
          ,
          tile_merge_{z_max-2}_{x/4}_{y/4}  (ズームアウト2段階目)
          >> ...
          >> tile_merge_{z_min}_{...}_{...}  (最小ズームまで)
          >> tile_compress_{z_min}_{...}_{...}
        ]
     ]
```

### 3.3 詳細フロー

#### Step 1: タイル生成ジョブ作成
ユーザーは管理画面からゲームID（例: `"city01"`）とセーブデータ名（例: `"save_001"`）を指定して「タイル生成」ボタンを押下します。Backendは `POST /api/tiles/create` リクエストを受け取ります。

Backendは以下を実行します:
- appに新しいジョブレコードを作成（`status='preparing'`）
- 撮影対象エリアのリストを計算
- タイル生成パラメータを計算（最大ズーム、最小ズーム、タイル依存関係）
- PrefectのFlow起動APIを呼び出し、`map_processing` Flowを起動
- 起動された `flow_run_id` を取得してDBに保存
- ジョブステータスを `running` に更新

Backendはクライアントに以下を返します:
```json
{"job_id": 123, "status": "running", "flow_run_id": "abc-123-def"}
```

ブラウザは `/api/status` を3秒ごとにポーリング開始します。

#### Step 2: Flow実行開始
Prefect Agentはprefect-serverからフロー実行指示を取得します。

Agentは以下を実行します:
- Flow関数 `map_processing` を実行開始
- パラメータから撮影エリア数、ズームレベル範囲、タイル依存関係を取得
- 実行時に動的にタスクを生成

#### Step 3: スクリーンショット撮影
Agentはスクリーンショット撮影タスクを並列実行します。

各タスクは以下を実行します:
- ジョブの設定パラメータからエリアID 0の座標を取得（例: `x=0`, `y=0`）
- `service-capture` を呼び出し: `POST http://service-capture:5000/capture`
  ```json
  {
    "save_data_name": "save_demo",
    "x": 0,
    "y": 0,
    "output_path": "/images/screenshots/shot_abc123.png",
    "zoom_level": "double"
  }
  ```

`service-capture` は以下を実行します:
- スクリーンショット撮影
- `screenshot_id` を生成（例: `"shot_abc123"`）
- storageへ `PUT /images/screenshots/shot_abc123.png` でファイル保存
- `{"image_path": "/images/screenshots/shot_abc123.png"}` を返却

タスクは以下を実行します:
- レスポンスを受け取り、タスクの戻り値として保持
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
- タスク完了を返す

#### Step 4: 座標推定
Agentは座標推定タスクを並列実行します。

各タスクは以下を実行します:
- 前タスク（スクリーンショット撮影）の戻り値を取得
- Flowの設定から期待座標（ヒント）と隣接画像を取得
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

タスクは以下を実行します:
- レスポンスを受け取り、タスクの戻り値として保持
- Backend の `PUT /api/internal/screenshots/shot_abc123` を呼び出し:
  ```json
  {
    "estimated_x": 1024,
    "estimated_y": 2048
  }
  ```
- Backendは `screenshots` テーブルの該当レコードに推定座標を更新
- タスク完了を返す

### Step 5: 最大ズームタイル切り出し
Agentは最大ズームタイル切り出しタスクを並列実行します。

各タスクは以下を実行します:
- Flowの設定からこのタイルが必要とするエリアIDを取得
- 前タスク（座標推定）の戻り値から各エリアの情報を取得し、`images` リストを構築
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

`service-tile-cut` は以下を実行します:
- 複数のスクリーンショットを storage から取得
- 仮想キャンバスに配置し、指定範囲を切り出し
- PNGで storage へ保存
- `{"output_path": "/images/rawtiles/18/10/20.png"}` を返却

タスクは以下を実行します:
- レスポンスを受け取り、タスクの戻り値として保持
- Backend の `POST /api/internal/tiles` を呼び出し:
  ```json
  {
    "job_id": 123,
    "tiles": [
      {
        "z": 18,
        "x": 10,
        "y": 20,
        "filepath": "/images/rawtiles/18/10/20.png",
        "source_type": "screenshot"
      }
    ]
  }
  ```
- Backendは `tiles` テーブルにレコード挿入
- タスク完了を返す

#### Step 6: 最大ズームタイル圧縮
Agentは最大ズームタイル圧縮タスクを並列実行します。

各タスクは以下を実行します:
- 前タスク（タイル切り出し）の戻り値を取得
- `service-tile-compress` を呼び出し: `POST http://service-tile-compress:5004/compress`
  ```json
  {
    "input_path": "/images/rawtiles/18/10/20.png",
    "output_path": "/images/tiles/18/10/20.avif",
    "quality": "30"
  }
  ```

`service-tile-compress` は以下を実行します:
- storageから未圧縮タイルを取得
- AVIF（quality 30）に圧縮
- storageへ `PUT /images/tiles/18/10/20.avif` で保存
- `{"compressed_tile_path": "/images/tiles/18/10/20.avif"}` を返却

タスクは以下を実行します:
- レスポンスを受け取り
- Backend の `PUT /api/internal/tiles/compress` を呼び出し:
  ```json
  {
    "tile_ids": [456],
    "compressed_filepath": "/images/tiles/18/10/20.avif"
  }
  ```
- Backendは `tiles` テーブルの該当レコードを更新（`compressed=true`, `filepath` を圧縮版に更新）
- タスク完了を返す

### Step 7: ズームアウトタイルマージ

Agentはズームアウトタイルマージタスクを並列実行します。

各タスクは以下を実行します:
- 前タスク（4枚の子タイル切り出し/マージ）の戻り値を取得
- **子タイルのパスを特定**: タイル座標 `(z=17, tx=10, ty=20)` の子タイルは以下
  ```python
  child_z = 18
  child_tiles = [
      (child_z, tx * 2, ty * 2),        # 左上
      (child_z, tx * 2 + 1, ty * 2),    # 右上
      (child_z, tx * 2, ty * 2 + 1),    # 左下
      (child_z, tx * 2 + 1, ty * 2 + 1) # 右下
  ]
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

`service-tile-merge` は以下を実行します:
- 4枚の画像を storage から取得
- 2x2で結合、リサイズ
- PNGで storage へ保存
- `{"output_path": "/images/rawtiles/17/10/20.png"}` を返却

タスクは以下を実行します:
- レスポンスを受け取り、タスクの戻り値として保持
- Backend の `POST /api/internal/tiles` を呼び出してマージタイル情報を永続化
- タスク完了を返す

#### Step 8: 完了とステータス確認
Prefect Agentの全タスクが完了すると、flow_runは `Completed` 状態になります。

ブラウザはポーリングで定期的に `GET /api/status` を呼び出します。

Backend は以下を実行します:
- appから全ジョブの情報を取得
- prefect-serverのAPIからflow_run状態を確認
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
- storageにプロキシリクエスト: `GET http://storage:80/images/tiles/5/10/20.avif`
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

### 5.1 ボトルネック対策

#### スクリーンショット撮影
- ゲーム起動に時間がかかるため、撮影スループットがボトルネック。
- 対策: スクリーンショットの撮影とクリップ、保存を非同期化し、限られたゲームプロセスでも高スループットを実現。

#### タイル処理
- 最大ズームレベルでは数十万〜数百万のタイルを処理するため、タイル切り出し・マージ・圧縮がボトルネック。
- 対策: 各処理を分離し、並列度を確保。未圧縮タイルの早期削除によりストレージ消費を抑制。

#### Storage I/O
- 大量の読み書きによるディスクI/Oがボトルネック。
- 対策: SSDを使用、ストレージネットワークの帯域確保。

#### タイル配信
- CDN導入を検討。複数のBackendインスタンスで負荷分散。

### 5.2 ストレージ最適化

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
- **Backend**: ビジネスロジック、app管理、Prefect制御、API提供、HTML配信。
- **Prefect Server**: Flow実行管理、タスク状態追跡、メタデータ管理。
- **Prefect Agent**: Flow実行、動的タスク生成、Service呼び出し、Backend APIとの連携。
- **Services（service-*）**: 単一の専門処理のみを実行。ステートレス。他サービスやBackendの知識を持たない。
- **Storage**: ファイルのCRUD操作のみ。HTTPインターフェース。

### 6.2 変更耐性
- Service の処理ロジック変更は、Backend や Prefect に影響しない。
- Prefect Flowの構造変更は Service に影響しない。
- Backend の API設計により、データ永続化の詳細が Prefect Agent に漏えいしない。

### 6.3 段階的処理の利点
- **メモリ効率**: 未圧縮タイルを早期削除することで、ストレージ使用量を抑制。
- **並列性**: 切り出し、マージ、圧縮を独立したタスクにすることで、高い並列度を実現。
- **失敗時の復旧**: 各段階が独立しているため、失敗したタスクのみ再実行可能。
- **柔軟性**: 圧縮品質やズームレベル範囲の変更が容易。
