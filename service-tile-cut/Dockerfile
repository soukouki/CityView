FROM python:3.11-slim

WORKDIR /app

# 最小限のシステム依存関係のみインストール
RUN apt-get update && apt-get install -y \
    libpng-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Pythonパッケージのインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードのコピー
COPY app.py .

ENV PYTHONUNBUFFERED=1

# ヘルスチェック
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5002/health || exit 1

# ポート公開
EXPOSE 5002

# Gunicornで実行
CMD ["gunicorn", "--bind", "0.0.0.0:5002", "--workers", "2", "--threads", "4", "--timeout", "120", "app:app"]
