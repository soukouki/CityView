FROM apache/airflow:2.7.3-python3.11

USER root
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl build-essential && \
    rm -rf /var/lib/apt/lists/*
USER airflow

# 追加のPythonパッケージをインストール
COPY --chown=airflow requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# DAGをコピー
COPY --chown=airflow dags/ /opt/airflow/dags/
