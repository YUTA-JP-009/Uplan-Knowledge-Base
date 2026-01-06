# Batch Processor v3 - 並列処理版

## クイックスタート

### デプロイ
```bash
cd Uplan-Knowledge-Base/backend
./deploy.sh
```

### 実行（あ行全体を5並列で処理）
```bash
gcloud run jobs execute uplan-batch-processor --region us-central1 \
  --args='--target-path,001_Ｕ'\''plan_全社/01.構造設計/01.木造（在来軸組）/□あ行,--workers,5,--mode,full'
```

## 主な機能

✅ **5-10並列処理**で処理時間を1/5に短縮
✅ **柔軟なターゲット指定**（あ行、木造全体など）
✅ **Cloud Run Jobs対応**でメモリ不足を解決
✅ **自動リトライ**でGemini APIレート制限に対応
✅ **差分更新モード**で月次更新を効率化

## ファイル構成

```
backend/
├── batch_processor_v3_parallel.py  # メインスクリプト（並列処理版）
├── Dockerfile                       # Cloud Run Jobs用
├── requirements.txt                 # Python依存関係
├── deploy.sh                        # デプロイスクリプト
├── DEPLOYMENT_GUIDE.md              # 詳細ガイド
└── README_PARALLEL.md               # このファイル
```

## コマンド例

### あ行全体を処理
```bash
gcloud run jobs execute uplan-batch-processor --region us-central1 \
  --args='--target-path,001_Ｕ'\''plan_全社/01.構造設計/01.木造（在来軸組）/□あ行,--workers,5,--mode,full'
```

### 木造全体を処理（メモリ16GB必要）
```bash
# メモリを16GBに変更
gcloud run jobs update uplan-batch-processor --region us-central1 --memory 16Gi --cpu 8

# 実行
gcloud run jobs execute uplan-batch-processor --region us-central1 \
  --args='--target-path,001_Ｕ'\''plan_全社/01.構造設計/01.木造（在来軸組）,--workers,10,--mode,full'
```

### 差分更新（月次更新）
```bash
gcloud run jobs execute uplan-batch-processor --region us-central1 \
  --args='--mode,delta,--workers,5'
```

## 処理時間の目安

| 案件数 | 並列数 | 処理時間 |
|--------|--------|----------|
| 50件 | 5 | 30-50分 |
| 100件 | 8 | 50-80分 |
| 200件 | 10 | 1.5-3時間 |

## 詳細情報

詳細なデプロイ手順、トラブルシューティング、最適化のヒントについては、[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)を参照してください。

## 変更履歴

### v3.0 (2026-01-06) - 並列処理版
- ProcessPoolExecutorによる並列処理実装
- コマンドライン引数対応
- Cloud Run Jobs対応
- 自動リトライ機能
- メモリ管理の最適化

### v2.0 (2025-12-XX) - デルタクエリ対応
- スタンプ機能（差分更新）実装

### v1.0 (2025-12-XX) - 初回リリース
- 基本的なPDF解析機能
