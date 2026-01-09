# Docker 使用ガイド

## 概要

このプロジェクトは、Google Cloud Run JobsでバッチPDF処理を実行するためのDocker環境を提供します。

## ファイル構成

```
backend/
├── Dockerfile                          # 本番用Dockerイメージ
├── docker-compose.yml                  # ローカル開発用Docker Compose設定
├── .dockerignore                       # Dockerビルドから除外するファイル
├── .env.template                       # 環境変数テンプレート
├── deploy.sh                           # Cloud Run Jobsデプロイスクリプト
├── batch_processor_v3_parallel.py      # メインアプリケーション
└── requirements.txt                    # Python依存関係
```

## 前提条件

### 必要なツール

- Docker Desktop (最新版)
- Google Cloud SDK (gcloud CLI)
- GCPプロジェクトへのアクセス権限

### GCP認証

```bash
# Application Default Credentials でログイン
gcloud auth application-default login

# プロジェクトを設定
gcloud config set project uplan-knowledge-base
```

## ローカル開発

### 1. Docker Composeで実行

```bash
# ビルドして実行
docker-compose up batch-processor

# バックグラウンドで実行
docker-compose up -d batch-processor

# ログを確認
docker-compose logs -f batch-processor
```

### 2. カスタムパラメータで実行

```bash
# docker-compose.ymlを編集するか、直接コマンドを指定
docker-compose run --rm batch-processor \
  --target-path "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□あ行" \
  --workers 5 \
  --mode full
```

### 3. デバッグモード

コンテナ内でシェルを開いて、手動でコマンドを実行できます。

```bash
# デバッグコンテナを起動
docker-compose run --rm debug

# コンテナ内で実行
python batch_processor_v3_parallel.py \
  --target-path "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□あ行" \
  --workers 2 \
  --mode full
```

### 4. ローカルでのDocker実行（Composeなし）

```bash
# イメージをビルド
docker build -t uplan-batch-processor:local --platform linux/amd64 .

# コンテナを実行
docker run --rm \
  -v ~/.config/gcloud:/root/.config/gcloud:ro \
  -e GOOGLE_CLOUD_PROJECT=uplan-knowledge-base \
  uplan-batch-processor:local \
  --target-path "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□あ行" \
  --workers 5 \
  --mode full
```

## Cloud Run Jobsへのデプロイ

### 1. デプロイスクリプトを使用（推奨）

```bash
# スクリプトに実行権限を付与
chmod +x deploy.sh

# デプロイ実行
./deploy.sh
```

このスクリプトは以下を自動的に実行します:
- GCP認証確認
- プロジェクト設定
- 必要なAPIの有効化
- Dockerイメージのビルド（AMD64プラットフォーム）
- Container Registryへのプッシュ
- Cloud Run Jobsの作成/更新

### 2. 手動デプロイ

```bash
# プロジェクト設定
export PROJECT_ID="uplan-knowledge-base"
export REGION="us-central1"
export JOB_NAME="uplan-batch-processor"
export IMAGE_NAME="gcr.io/${PROJECT_ID}/${JOB_NAME}"

# イメージをビルド
docker build --platform linux/amd64 -t ${IMAGE_NAME}:latest .

# Container Registryにプッシュ
docker push ${IMAGE_NAME}:latest

# Cloud Run Jobsを作成/更新
gcloud run jobs update ${JOB_NAME} \
  --image ${IMAGE_NAME}:latest \
  --region ${REGION} \
  --memory 8Gi \
  --cpu 4 \
  --max-retries 2 \
  --task-timeout 3600s \
  --set-env-vars GOOGLE_CLOUD_PROJECT=${PROJECT_ID}
```

## Cloud Run Jobsの実行

### 1. 基本的な実行

```bash
# デフォルトパラメータで実行
gcloud run jobs execute uplan-batch-processor --region us-central1

# 完了まで待機
gcloud run jobs execute uplan-batch-processor --region us-central1 --wait
```

### 2. カスタムパラメータで実行

```bash
# あ行配下の全案件を5並列で処理
gcloud run jobs execute uplan-batch-processor --region us-central1 \
  --args='--target-path,001_Ｕ'\''plan_全社/01.構造設計/01.木造（在来軸組）/□あ行,--workers,5,--mode,full'

# 木造全体を10並列で処理（まずメモリを16GBに変更）
gcloud run jobs update uplan-batch-processor --region us-central1 --memory 16Gi --cpu 8
gcloud run jobs execute uplan-batch-processor --region us-central1 \
  --args='--target-path,001_Ｕ'\''plan_全社/01.構造設計/01.木造（在来軸組）,--workers,10,--mode,full'

# 差分更新モードで実行
gcloud run jobs execute uplan-batch-processor --region us-central1 \
  --args='--mode,delta,--workers,5'
```

### 3. 実行状況の確認

```bash
# 実行履歴を確認
gcloud run jobs executions list --job uplan-batch-processor --region us-central1

# 特定の実行の詳細を確認
gcloud run jobs executions describe <EXECUTION_ID> --region us-central1

# ログを確認
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=uplan-batch-processor" \
  --limit 50 \
  --format json

# リアルタイムでログを監視
gcloud logging tail "resource.type=cloud_run_job AND resource.labels.job_name=uplan-batch-processor"
```

## トラブルシューティング

### 1. ビルドエラー

```bash
# Docker Desktopが起動しているか確認
docker info

# キャッシュをクリアして再ビルド
docker build --no-cache -t uplan-batch-processor:local .
```

### 2. 認証エラー

```bash
# 認証を更新
gcloud auth application-default login

# サービスアカウントの権限を確認
gcloud projects get-iam-policy uplan-knowledge-base
```

### 3. メモリ不足

```bash
# ジョブのメモリを増やす
gcloud run jobs update uplan-batch-processor \
  --region us-central1 \
  --memory 16Gi \
  --cpu 8

# 並列処理数を減らす
# --workers 5 → --workers 3
```

### 4. タイムアウト

```bash
# タイムアウト時間を延長（最大3600秒 = 1時間）
gcloud run jobs update uplan-batch-processor \
  --region us-central1 \
  --task-timeout 3600s
```

## パフォーマンスチューニング

### リソース設定の推奨値

| 処理規模 | メモリ | CPU | Workers | 対象フォルダ例 |
|---------|-------|-----|---------|--------------|
| 小規模 | 4Gi | 2 | 3 | □あ行（10-20案件） |
| 中規模 | 8Gi | 4 | 5 | □あ行～□か行（50-100案件） |
| 大規模 | 16Gi | 8 | 10 | 木造全体（200+案件） |

### コスト最適化

```bash
# 必要最小限のリソースで実行
gcloud run jobs update uplan-batch-processor \
  --region us-central1 \
  --memory 4Gi \
  --cpu 2

# 実行時のみ課金されるため、不要な実行を避ける
# 差分更新モードを活用
```

## セキュリティ

### Secret Manager

機密情報（Microsoft APIキーなど）はSecret Managerに保存されています:

- `MS_CLIENT_ID`
- `MS_TENANT_ID`
- `MS_CLIENT_SECRET`

これらはアプリケーションから自動的に取得されます。

### IAM権限

Cloud Run Jobsのサービスアカウントには以下の権限が必要です:

- Secret Manager Secret Accessor
- Firestore User
- Vertex AI User
- Cloud Storage Object Viewer

## 参考リンク

- [Cloud Run Jobs ドキュメント](https://cloud.google.com/run/docs/create-jobs)
- [Docker Compose ドキュメント](https://docs.docker.com/compose/)
- [gcloud CLI リファレンス](https://cloud.google.com/sdk/gcloud/reference/run/jobs)
