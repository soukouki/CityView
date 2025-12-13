# ベースイメージ
FROM debian:trixie-slim

# Simutrans用パッケージのインストール
RUN apt-get update && \
    apt-get install -y autoconf build-essential curl libbz2-dev libpng-dev libz-dev subversion unzip sed wget miniupnpc libsdl2-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# libminiupnpc.17が必要なので、誤魔化す
RUN ln -s /usr/lib/x86_64-linux-gnu/libminiupnpc.so.18 /usr/lib/x86_64-linux-gnu/libminiupnpc.so.17 && \
    ldconfig

# 作業ディレクトリの設定
WORKDIR /app

