FROM python:3.11-slim

WORKDIR /app

# システム依存関係のインストール（PNG読み込みとcurl用）
RUN apt-get update && apt-get install -y \
    libpng-dev \
    libjpeg-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Pythonパッケージのインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードのコピー
COPY app.py .

# ログ出力のための環境変数のみ設定
ENV PYTHONUNBUFFERED=1

# ヘルスチェック
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5005/health || exit 1

# ポート公開
EXPOSE 5005

# Gunicornで実行
CMD ["gunicorn", "--bind", "0.0.0.0:5005", "--threads", "4", "--timeout", "300", "app:app"]
