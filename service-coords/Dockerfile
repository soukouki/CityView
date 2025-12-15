FROM python:3.12-slim

WORKDIR /app

# OpenCVの依存関係をインストール
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# テスト用
RUN apt-get update && apt-get install -y curl

# requirements.txtをコピーして依存関係をインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY app.py .

ENV IMAGE_WIDTH=5632 \
    IMAGE_HEIGHT=2816 \
    IMAGE_MARGIN_WIDTH=256 \
    IMAGE_MARGIN_HEIGHT=128

EXPOSE 5001

# gunicornで起動（2ワーカー、タイムアウト120秒）
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "2", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
