# Cloud Run Jobs用Dockerfile
# 軽量なPython 3.11イメージを使用
FROM python:3.11-slim

# 作業ディレクトリを設定
WORKDIR /app

# システムパッケージの更新と必要なツールのインストール
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Pythonの依存関係をコピーしてインストール
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
COPY batch_processor_v3_parallel.py .

# 環境変数の設定
ENV PYTHONUNBUFFERED=1
ENV GOOGLE_CLOUD_PROJECT=uplan-knowledge-base

# メモリ解放を積極的に行う設定
ENV MALLOC_TRIM_THRESHOLD_=100000

# コンテナ起動時にスクリプトを実行
# コマンドライン引数はCloud Run Jobsの設定で指定可能
ENTRYPOINT ["python", "batch_processor_v3_parallel.py"]

# デフォルト引数（上書き可能）
CMD ["--target-path", "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）", "--workers", "5", "--mode", "full"]
