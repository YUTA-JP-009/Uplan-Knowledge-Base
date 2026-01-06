# Uplan Batch Processor v3 - 並列処理版 デプロイガイド

## 概要

このガイドでは、Uplan Knowledge Baseのバッチプロセッサ（並列処理版）をGoogle Cloud Run Jobsにデプロイし、実行する手順を説明します。

## 新機能

### 並列処理による高速化
- **ProcessPoolExecutor**による真の並列処理（5-10並列対応）
- **処理時間を約1/5に短縮**（50件の案件を30-50分で処理）
- **メモリ効率の向上**（各プロセスが独立したメモリ空間を使用）

### 柔軟なターゲット指定
- コマンドライン引数で任意の階層を指定可能
- あ行、か行など、特定のグループ単位での一括処理が可能
- 木造全体、RC造全体など、大規模な一括処理も対応

### Cloud Run Jobs対応
- ローカルPCのメモリ不足問題を解決
- 8GB-16GBの大容量メモリで安定稼働
- Gemini APIのレート制限に強い（Dynamic Shared Quota）

## システム要件

### GCPプロジェクト設定
- プロジェクトID: `uplan-knowledge-base`
- リージョン: `us-central1`
- 必要なAPI:
  - Cloud Run API
  - Cloud Build API
  - Artifact Registry API
  - Vertex AI API
  - Secret Manager API
  - Firestore API

### Secret Managerに必要なシークレット
以下のシークレットが設定されている必要があります:
- `MS_CLIENT_ID`: Microsoft Graph APIのクライアントID
- `MS_TENANT_ID`: Microsoft 365のテナントID
- `MS_CLIENT_SECRET`: Microsoft Graph APIのクライアントシークレット

## デプロイ手順

### 1. 前提条件の確認

```bash
# GCP CLIがインストールされているか確認
gcloud --version

# Dockerがインストールされているか確認
docker --version

# 認証
gcloud auth login
gcloud auth configure-docker
```

### 2. デプロイスクリプトの実行

```bash
cd Uplan-Knowledge-Base/backend
./deploy.sh
```

このスクリプトは以下を自動実行します:
1. GCPプロジェクトの設定
2. 必要なAPIの有効化
3. Dockerイメージのビルド
4. Container Registryへのプッシュ
5. Cloud Run Jobsのデプロイ

### 3. デプロイ設定詳細

デフォルト設定:
- **メモリ**: 8GB
- **CPU**: 4コア
- **タイムアウト**: 3600秒（1時間）
- **最大リトライ**: 2回
- **並列処理数**: 5

## 実行方法

### パターン1: あ行配下の全案件を処理（推奨）

```bash
gcloud run jobs execute uplan-batch-processor --region us-central1 \
  --args='--target-path,001_Ｕ'\''plan_全社/01.構造設計/01.木造（在来軸組）/□あ行,--workers,5,--mode,full'
```

**処理時間の目安**:
- 案件数50件の場合: 30-50分
- 並列数5で効率的に処理

### パターン2: 特定の取引先配下の全案件を処理

```bash
gcloud run jobs execute uplan-batch-processor --region us-central1 \
  --args='--target-path,001_Ｕ'\''plan_全社/01.構造設計/01.木造（在来軸組）/□あ行/A00698アゼリアホーム,--workers,3,--mode,full'
```

### パターン3: 木造全体を処理（大規模処理）

**⚠️ 注意**: この処理には16GBのメモリが必要です。事前にジョブを更新してください。

```bash
# ステップ1: ジョブのメモリを16GBに変更
gcloud run jobs update uplan-batch-processor --region us-central1 \
  --memory 16Gi --cpu 8

# ステップ2: 実行
gcloud run jobs execute uplan-batch-processor --region us-central1 \
  --args='--target-path,001_Ｕ'\''plan_全社/01.構造設計/01.木造（在来軸組）,--workers,10,--mode,full'
```

**処理時間の目安**:
- 案件数200-300件の場合: 1.5-3時間
- 並列数10で高速処理

### パターン4: 差分更新モード（月次更新）

```bash
gcloud run jobs execute uplan-batch-processor --region us-central1 \
  --args='--mode,delta,--workers,5'
```

**動作**:
- 前回からの変更分のみを処理
- 初回実行後、2回目以降で使用可能
- 大幅な時間短縮が期待できる

## 実行状況の確認

### ジョブの実行一覧を確認

```bash
gcloud run jobs executions list \
  --job uplan-batch-processor \
  --region us-central1
```

### 特定の実行の詳細を確認

```bash
gcloud run jobs executions describe EXECUTION_NAME \
  --region us-central1
```

### リアルタイムログの確認

```bash
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=uplan-batch-processor" \
  --limit 50 \
  --format json
```

### ログのフィルタリング（エラーのみ）

```bash
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=uplan-batch-processor AND severity>=ERROR" \
  --limit 20 \
  --format json
```

## コマンドライン引数の詳細

### --target-path
- **説明**: 抽出対象のルートパス
- **デフォルト**: `001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）`
- **例**:
  - `001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□あ行`
  - `001_Ｕ'plan_全社/01.構造設計/02.RC造`

### --workers
- **説明**: 並列処理数
- **デフォルト**: 5
- **推奨値**:
  - 小規模（10-50件）: 3-5
  - 中規模（50-100件）: 5-8
  - 大規模（100件以上）: 8-10
- **注意**: 並列数を増やす場合はメモリも増やす必要があります
  - 5並列: 8GB
  - 10並列: 16GB

### --mode
- **説明**: 実行モード
- **値**:
  - `full`: 全件スキャンモード（デフォルト）
  - `delta`: 差分更新モード
- **使い分け**:
  - 初回実行: `full`
  - 月次更新: `delta`

## トラブルシューティング

### メモリ不足エラー

**症状**: `Memory limit exceeded` エラー

**解決方法**:
```bash
# メモリを増やす
gcloud run jobs update uplan-batch-processor --region us-central1 --memory 16Gi
```

### タイムアウトエラー

**症状**: `Execution timeout exceeded` エラー

**解決方法**:
```bash
# タイムアウトを延長
gcloud run jobs update uplan-batch-processor --region us-central1 --task-timeout 7200s
```

### Gemini API レート制限エラー

**症状**: `429 Resource Exhausted` エラー

**対策**:
1. 並列数を減らす（`--workers 3`）
2. スクリプトには自動リトライが実装済み（最大60秒バックオフ）
3. Vertex AIのクォータ増加をリクエスト

### 認証エラー

**症状**: `Authentication failed` エラー

**解決方法**:
1. Secret Managerのシークレットが正しく設定されているか確認
2. Cloud Run JobsのサービスアカウントにSecret Managerへのアクセス権限があるか確認

```bash
# サービスアカウントに権限を付与
gcloud projects add-iam-policy-binding uplan-knowledge-base \
  --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

## パフォーマンス最適化

### 並列数の最適化

| 案件数 | 推奨並列数 | メモリ | CPU | 予想処理時間 |
|--------|-----------|--------|-----|-------------|
| 10-30件 | 3 | 6GB | 2 | 10-20分 |
| 30-80件 | 5 | 8GB | 4 | 20-40分 |
| 80-150件 | 8 | 12GB | 6 | 40-80分 |
| 150件以上 | 10 | 16GB | 8 | 1-3時間 |

### コスト最適化

**Cloud Run Jobsの料金**:
- メモリ8GB x 1時間: 約$0.50-1.00
- CPU 4コア x 1時間: 約$0.20-0.40
- **合計**: 約$0.70-1.40/実行

**推奨事項**:
1. 小規模なテストは並列数3、メモリ6GBで実行
2. 本番実行は並列数5、メモリ8GBで実行
3. 大規模処理のみ並列数10、メモリ16GBを使用

## ローカルでのテスト

Cloud Runにデプロイする前に、ローカルでテストすることをお勧めします。

```bash
# 仮想環境の作成
cd Uplan-Knowledge-Base/backend
python3 -m venv venv
source venv/bin/activate

# 依存関係のインストール
pip install -r requirements.txt

# GCP認証
gcloud auth application-default login

# ローカルでテスト実行（少数の案件で）
python batch_processor_v3_parallel.py \
  --target-path "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□あ行/A00698アゼリアホーム" \
  --workers 2 \
  --mode full
```

## 次のステップ

1. ✅ デプロイスクリプトの実行
2. ✅ ローカルでの小規模テスト
3. ✅ Cloud Run Jobsでの小規模テスト（あ行の一部）
4. ✅ Cloud Run Jobsでの中規模テスト（あ行全体）
5. ✅ Cloud Run Jobsでの大規模テスト（木造全体）
6. ✅ 差分更新モードのテスト

## サポート

問題が発生した場合は、以下の情報を添えてお問い合わせください:
- エラーメッセージの全文
- 実行したコマンド
- ログの抜粋
- 処理対象の案件数

---

**最終更新日**: 2026-01-06
**バージョン**: v3.0 (並列処理版)
