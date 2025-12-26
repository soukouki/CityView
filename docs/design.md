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
  | HEAD | `/images/screenshots/{map_id}/{screenshot_id}.png` | スクリーンショット存在確認 |
  | PUT | `/images/screenshots/{map_id}/{screenshot_id}.png` | スクリーンショット保存 |
  | GET | `/images/screenshots/{map_id}/{screenshot_id}.png` | スクリーンショット取得 |
  | DELETE | `/images/screenshots/{map_id}/{screenshot_id}.png` | スクリーンショット削除 |
  | HEAD | `/images/rawtiles/{map_id}/{z}/{x}/{y}.png` | 未圧縮タイル存在確認 |
  | PUT | `/images/rawtiles/{map_id}/{z}/{x}/{y}.png` | 未圧縮タイル保存 |
  | GET | `/images/rawtiles/{map_id}/{z}/{x}/{y}.png` | 未圧縮タイル取得 |
  | DELETE | `/images/rawtiles/{map_id}/{z}/{x}/{y}.png` | 未圧縮タイル削除 |
  | HEAD | `/images/tiles/{map_id}/{z}/{x}/{y}.avif` | 圧縮タイル存在確認 |
  | PUT | `/images/tiles/{map_id}/{z}/{x}/{y}.avif` | 圧縮タイル保存 |
  | GET | `/images/tiles/{map_id}/{z}/{x}/{y}.avif` | 圧縮タイル取得 |
  | DELETE | `/images/tiles/{map_id}/{z}/{x}/{y}.avif` | 圧縮タイル削除 |
  | HEAD | `/images/panels/{map_id}/{filename}` | 一枚絵存在確認 |
  | PUT | `/images/panels/{map_id}/{filename}` | 一枚絵保存 |
  | GET | `/images/panels/{map_id}/{filename}` | 一枚絵取得 |
  | DELETE | `/images/panels/{map_id}/{filename}` | 一枚絵削除 |

- **接続元**:
  - service-capture（PUT - スクリーンショット）
  - service-estimate（GET - スクリーンショット）
  - service-tile-cut（GET - スクリーンショット, PUT - 未圧縮タイル）
  - service-tile-merge（GET - 未圧縮タイル, PUT - 未圧縮タイル）
  - service-tile-compress（GET - 未圧縮タイル, PUT - 圧縮タイル）
  - service-create-panel（PUT - 一枚絵）
  - backend（GET - 圧縮タイル配信, GET - 一枚絵配信）
  - prefect-worker (HEAD - 各種存在確認)
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
| GET | `/tiles/{map_id}/{z}/{x}/{y}.avif` | タイル画像配信（storage `/images/tiles/` へプロキシ） |

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

#### service-create-panel
- **役割**: 一枚絵保存サービス（Python + Flask + Pillow）
- **責務**:
  - storage から複数のタイルを取得
  - マップ全体を一枚絵として結合
  - 指定解像度にリサイズ
  - PNG形式で storage へ保存
  - 保存パスを返却
- **DB接続**: なし
- **呼び出し先**:
  - storage: タイル取得（GET）、一枚絵保存（PUT）
- **エンドポイント**:

  | メソッド | パス | 説明 | リクエスト | レスポンス |
  |---|---|---|---|---|
  | POST | `/create_panel` | 一枚絵生成 | 下記参照 | `{"output_path": "string"}` |

- **リクエストボディ**:
  ```json
  {
    "z": number,            // タイルのズームレベル
    "tiles": [
      {
        "path": "string",   // storage上のパス
        "x": number,        // タイルX座標
        "y": number         // タイルY座標
      }
    ],
    "map_size": {
      "width": number,      // 今回のzoomレベルでのマップ幅（px）
      "height": number      // 今回のzoomレベルでのマップ高さ（px）
    },
    "offsets": {
      "x": number,          // マップ左上のタイルX座標に対するピクセルオフセット
      "y": number           // マップ左上のタイルY座標に対するピクセルオフセット
    },
    "resolution": {
      "width": number,      // 出力画像幅（px）
      "height": number      // 出力画像高さ（px）
    },
    "output_path": "string" // 保存先パス（例: "/images/panels/1920x1080.png"）
  }
  ```

- **レプリカ数**: `1`
- **処理フロー**:
  1. リクエスト受信
  2. 複数タイルを storage から取得
  3. マップ全体を一枚絵として結合
  4. マップの大きさに合わせてクリッピング
  5. 指定解像度にリサイズ
  6. PNG形式で `output_path` に保存
  7. 保存パスを返却
- **ポート**: `5005`

## 3. スケーリングとパフォーマンス

### 3.1 ボトルネック対策

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

### 3.2 ストレージ最適化

#### 段階的な削除戦略
- **未圧縮タイル**: 圧縮完了後およびマージ完了後に即座に削除
- **スクリーンショット**: すべての依存タイル処理完了後に削除
- **圧縮タイル**: 永続保存

#### ストレージ使用量の推定
最大ズームタイル数を N とすると:
- **スクリーンショット**: 約 N/100 枚（重複撮影考慮）、各 5MB → 合計 N/20 MB
- **未圧縮タイル（最大同時）**: 最大ズームで N 枚、各 1MB → 最大 N MB（段階的削除により実際はより少ない）
- **圧縮タイル（永続）**: 全ズームレベル合計で約 1.33N 枚、各 50KB → 約 N/15 MB

## 4. 重要な設計原則

### 4.1 責務の明確化
- **Backend**: ビジネスロジック、app管理、Prefect制御、API提供、HTML配信。
- **Prefect Server**: Flow実行管理、タスク状態追跡、メタデータ管理。
- **Prefect Agent**: Flow実行、動的タスク生成、Service呼び出し、Backend APIとの連携。
- **Services（service-*）**: 単一の専門処理のみを実行。ステートレス。他サービスやBackendの知識を持たない。
- **Storage**: ファイルのCRUD操作のみ。HTTPインターフェース。

### 4.2 変更耐性
- Service の処理ロジック変更は、Backend や Prefect に影響しない。
- Prefect Flowの構造変更は Service に影響しない。
- Backend の API設計により、データ永続化の詳細が Prefect Agent に漏えいしない。

### 4.3 段階的処理の利点
- **メモリ効率**: 未圧縮タイルを早期削除することで、ストレージ使用量を抑制。
- **並列性**: 切り出し、マージ、圧縮を独立したタスクにすることで、高い並列度を実現。
- **失敗時の復旧**: 各段階が独立しているため、失敗したタスクのみ再実行可能。
- **柔軟性**: 圧縮品質やズームレベル範囲の変更が容易。
