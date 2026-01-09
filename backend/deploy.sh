#!/bin/bash

# Cloud Run Jobs デプロイスクリプト
# Uplan Knowledge Base - Batch Processor v3 (並列処理版)

set -e  # エラーが発生したら即座に終了

# 設定
PROJECT_ID="uplan-knowledge-base"
REGION="us-central1"
JOB_NAME="uplan-batch-processor"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${JOB_NAME}"

echo "=================================================="
echo "Cloud Run Jobs デプロイ開始"
echo "=================================================="
echo "プロジェクト: ${PROJECT_ID}"
echo "リージョン: ${REGION}"
echo "ジョブ名: ${JOB_NAME}"
echo "=================================================="

# 0. 認証確認
echo "📍 ステップ0: GCP認証確認"
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q "@"; then
    echo "⚠️  GCPに認証されていません。認証を開始します..."
    gcloud auth login
fi
echo "✅ 認証済み: $(gcloud auth list --filter=status:ACTIVE --format='value(account)')"

# 1. GCPプロジェクトを設定
echo "📍 ステップ1: GCPプロジェクトを設定"
gcloud config set project ${PROJECT_ID}

# 2. 必要なAPIを有効化
echo "📍 ステップ2: 必要なAPIを有効化"
gcloud services enable \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com \
  secretmanager.googleapis.com \
  firestore.googleapis.com

# 3. Dockerイメージをビルド（AMD64プラットフォーム指定）
echo "📍 ステップ3: Dockerイメージをビルド（AMD64）"
docker build --platform linux/amd64 -t ${IMAGE_NAME}:latest .

# 4. Container Registryにプッシュ
echo "📍 ステップ4: Container Registryにプッシュ"
docker push ${IMAGE_NAME}:latest

# 5. Cloud Run Jobsをデプロイ
echo "📍 ステップ5: Cloud Run Jobsをデプロイ"
# ジョブが存在するかチェック
if gcloud run jobs describe ${JOB_NAME} --region ${REGION} &> /dev/null; then
  echo "既存のジョブを更新します..."
  gcloud run jobs update ${JOB_NAME} \
    --image ${IMAGE_NAME}:latest \
    --region ${REGION} \
    --memory 8Gi \
    --cpu 4 \
    --max-retries 2 \
    --task-timeout 3600s \
    --set-env-vars GOOGLE_CLOUD_PROJECT=${PROJECT_ID}
else
  echo "新しいジョブを作成します..."
  gcloud run jobs create ${JOB_NAME} \
    --image ${IMAGE_NAME}:latest \
    --region ${REGION} \
    --memory 8Gi \
    --cpu 4 \
    --max-retries 2 \
    --task-timeout 3600s \
    --set-env-vars GOOGLE_CLOUD_PROJECT=${PROJECT_ID}
fi

echo "=================================================="
echo "✅ デプロイ完了！"
echo "=================================================="
echo ""
echo "【実行方法】"
echo ""
echo "1. あ行配下の全案件を5並列で処理:"
echo "   gcloud run jobs execute ${JOB_NAME} --region ${REGION} \\"
echo "     --args='--target-path,001_Ｕ'\''plan_全社/01.構造設計/01.木造（在来軸組）/□あ行,--workers,5,--mode,full'"
echo ""
echo "2. 木造全体を10並列で処理（メモリ16GB必要）:"
echo "   # まずジョブのメモリを16GBに変更"
echo "   gcloud run jobs update ${JOB_NAME} --region ${REGION} --memory 16Gi --cpu 8"
echo "   # 実行"
echo "   gcloud run jobs execute ${JOB_NAME} --region ${REGION} \\"
echo "     --args='--target-path,001_Ｕ'\''plan_全社/01.構造設計/01.木造（在来軸組）,--workers,10,--mode,full'"
echo ""
echo "3. 差分更新モードで実行:"
echo "   gcloud run jobs execute ${JOB_NAME} --region ${REGION} \\"
echo "     --args='--mode,delta,--workers,5'"
echo ""
echo "4. ジョブの実行状況を確認:"
echo "   gcloud run jobs executions list --job ${JOB_NAME} --region ${REGION}"
echo ""
echo "5. ログを確認:"
echo "   gcloud logging read \"resource.type=cloud_run_job AND resource.labels.job_name=${JOB_NAME}\" --limit 50 --format json"
echo ""
echo "=================================================="
