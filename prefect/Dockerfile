FROM prefecthq/prefect:3.6-python3.11

# curl追加（ヘルスチェック用）
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/prefect/flows

# 依存パッケージのインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Flowsのコピー
COPY . .

CMD ["prefect", "worker", "start", "--pool", "default-agent-pool"]
