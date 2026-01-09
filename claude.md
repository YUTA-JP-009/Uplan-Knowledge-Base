# U'plan Knowledge Base - 開発ドキュメント

## 1. プロジェクト概要

構造設計事務所の過去案件データ（OneDrive上のPDF）をAIで解析・構造化し、SUUMOのように詳細な条件で検索できる社内ナレッジベースを構築するプロジェクト。

**目的**: 過去の設計ノウハウ（暗黙知）の形式知化、検索コストの削減、設計品質の向上

**現状**: バッチ処理プログラム（v3）の実装完了、メタデータ抽出機能・ルート判定ロジック実装済み

**データ保存先**: Google Cloud Firestore (データベース名: `uplan`, コレクション名: `2025_11_23`)

---

## 2. システムアーキテクチャ

```
OneDrive/SharePoint (データソース)
    ↓ Graph API
batch_processor_v3.py (Python)
    ├─ フォルダ探索・ファイル選定
    ├─ メタデータ抽出 (作成日・取引先・物件名)
    ├─ PDF解析 (Gemini 2.5 Pro)
    └─ データ保存
         ↓
Google Cloud Firestore
    ↓
Next.js フロントエンド (検索UI) ※今後実装予定
```

---

## 3. 技術スタック

### 言語・環境
- Python 3.11+
- GCP Project ID: `uplan-knowledge-base`
- Vertex AI Region: `us-central1`

### 主要ライブラリ
- `msal`: Microsoft認証
- `requests`: APIコール
- `google-cloud-secret-manager`: 機密情報管理
- `google-cloud-firestore`: DB保存
- `vertexai`: Gemini 2.5 Pro SDK

### 認証
- **Microsoft Graph API**: アプリケーション権限 (Files.Read.All, Sites.Read.All)
- **GCP**: Application Default Credentials
  ```bash
  gcloud auth application-default login
  ```

---

## 4. 実装済み機能

### 4.1. メタデータ自動抽出機能

フォルダパスから以下の情報を正規表現で自動抽出:

| 項目 | 抽出元 | 例 |
|------|--------|-----|
| 作成日 | `YYYYMMDD_` で始まるフォルダ名 | `20250312_...` → `2025-03-12` |
| 提出年・月 | 作成日から自動生成 | `2025`, `3` |
| 取引先名 | `T数字 会社名（...）` パターン | `T125 三栄建築設計（...）` → `三栄建築設計` |
| 物件名 | `7桁数字_物件名` パターン | `2025004_蕨市錦町002②1号棟` → `蕨市錦町002②1号棟` |

**実装ファイル**: [`batch_processor_v3.py`](batch_processor_v3.py:40-94) (`extract_project_metadata()`)

**テスト結果**: [METADATA_EXTRACTION_TEST_RESULTS.md](METADATA_EXTRACTION_TEST_RESULTS.md)

### 4.2. 構造計算ルート判定ロジック（ルート1優先版）

**重要な仕様変更（2025/12/6）**:
- 構造計算ソフトは、ルート1（壁量計算）でも参考値として「層間変形角」「偏心率」を出力することがある
- この参考値に惑わされず、**壁量計算や4分割法が1つでも確認できれば必ずルート1と判定**するロジックを実装

**判定優先順位**:
1. **ルート1の証拠を最優先で探す**: 壁量計算、4分割法、N値計算
2. ルート3の確認: 保有水平耐力（Qu, Qun）の計算
3. ルート2の確認: 層間変形角、剛性率・偏心率の判定表（かつ壁量計算が全くない場合のみ）

**実装ファイル**: [`batch_processor_v3.py`](batch_processor_v3.py:256-284)

**テスト済み物件**:
- ✅ 蕨市錦町002②1号棟: ルート1（正しく判定）
- ✅ 蕨市錦町002②2号棟: ルート1（正しく判定）
- ✅ 松下邸: ルート1（正しく判定）

**Firestoreフィールド**:
- `regulations.calcRoutes`: ルート判定結果の配列
- `regulations.calcRouteReasoning`: 判定理由（100文字程度）

### 4.3. ファイル選定ロジック

**構造設計図書フォルダの選定**:
- 成果物フォルダ内から「構造設計図書」または「構造計算書」を含むフォルダを探索
- 優先順位: 「【補正】」(スコア+100) > 「【修正】」(スコア+50) > 日付新しい順

**PDFファイルの選定**:
- 構造計算書: 「構造計算書」を含むPDF、優先順位同上
- 指摘回答書: 「指摘回答書」を含むPDF、最新のもの

**実装ファイル**: [`batch_processor_v3.py`](batch_processor_v3.py:96-180)

---

## 5. Firestoreデータスキーマ

### コレクション構造
- **データベース名**: `uplan`
- **コレクション名**: `2025_11_23`
- **ドキュメントID**: 構造計算書PDFのファイルID

### 保存データ
```json
{
  "file_id": "OneDriveファイルID",
  "file_name": "構造計算書.pdf",
  "onedrive_url": "https://...",
  "folder_full_path": "001_Ｕ'plan_全社/01.構造設計/...",

  // メタデータ（自動抽出）
  "submission_date": "2025-03-12",
  "submission_year": 2025,
  "submission_month": 3,
  "client_name": "三栄建築設計",
  "project_name": "蕨市錦町002②1号棟",

  // AI解析結果
  "analysis_result": {
    "basicSpecs": {
      "structureTypes": ["木造（在来軸組）"],
      "useTypes": ["戸建住宅"],
      "floorCategories": ["3階建て"],
      "totalArea": 112.61,
      "areaCategory": "101〜300㎡"
    },
    "regulations": {
      "calcRoutes": ["ルート1（許容応力度計算）"],
      "calcRouteReasoning": "構造計算方針(p7)に『ルート1』と明記...",
      "suitabilityJudgment": "不要",
      "fireResistance": ["その他（法22条区域・指定なし区域）"],
      "performanceLabels": []
    },
    "technology": { ... },
    "environment": { ... },
    "management": { ... },
    "summary": "..."
  },

  "model_version": "gemini-2.5-pro",
  "processed_at": "TIMESTAMP",
  "status": "completed"
}
```

---

## 6. 実行方法

### 6.1. 環境セットアップ

```bash
# 作業ディレクトリ
cd /Users/yuta.sakamoto/uplan-batch-v3/Uplan-Knowledge-Base/backend

# 仮想環境アクティベート
source venv/bin/activate

# GCP認証（初回のみ）
gcloud auth application-default login
```

### 6.2. バッチ処理実行

```bash
# TARGET_ROOT_PATH を編集してから実行
python batch_processor_v3.py
```

**TARGET_ROOT_PATH の設定例**:
```python
# 特定の1物件のみ（テスト用）
TARGET_ROOT_PATH = "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□さ行/T125 三栄建築設計（計算書・構造図ダブルチェック必要）/2025004_蕨市錦町002②1号棟"

# 特定の1社全体（推奨）
TARGET_ROOT_PATH = "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□さ行/T125 三栄建築設計（計算書・構造図ダブルチェック必要）"

# 特定の「行」全体
TARGET_ROOT_PATH = "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□さ行"
```

⚠️ **注意**: フォルダ名は必ずOneDriveから**コピペ**すること（全角・半角・特殊文字の違いに注意）

### 6.3. Firestoreデータ確認

```python
from google.cloud import firestore

db = firestore.Client(project='uplan-knowledge-base', database='uplan')

# 全ドキュメント取得
docs = db.collection('2025_11_23').stream()
for doc in docs:
    data = doc.to_dict()
    print(f"物件名: {data.get('project_name')}")
    print(f"ルート: {data.get('analysis_result', {}).get('regulations', {}).get('calcRoutes')}")

# 特定物件の検索
docs = db.collection('2025_11_23').where(
    filter=firestore.FieldFilter('project_name', '==', '蕨市錦町002②1号棟')
).stream()
```

---

## 7. 検索カテゴリ一覧

### 7.1. 建物基本スペック
- **構造種別**: 木造（在来軸組）、木造（限界耐力計算）、鉄骨造、RC造、混構造 等
- **用途**: 戸建住宅、共同住宅、長屋、店舗、事務所、倉庫 等
- **階数**: 平屋、2階建て、3階建て、4階建て以上、地下階あり
- **延床面積**: 〜100㎡、101〜300㎡、301〜500㎡、501〜1000㎡、1001㎡〜

### 7.2. 法規・計算ルート・性能
- **構造計算ルート**: 仕様規定のみ、ルート1、ルート2、ルート3、限界耐力計算
- **適合性判定**: 適判物件（要判定）、不要
- **耐火性能要件**: 耐火建築物、準耐火建築物、省令準耐火構造 等
- **性能表示・等級**: 長期優良住宅、耐震等級2、耐震等級3 等

### 7.3. 構造技術・工法
- **基礎形式**: べた基礎、布基礎、独立基礎、地盤改良あり、杭基礎
- **水平力抵抗要素**: 筋かい耐力壁、面材耐力壁、ラーメン構造、制震ダンパー
- **床・屋根構面**: 剛床（合板直張り）、火打ち構面、トラス構造
- **特徴的な設計・技術**: 大スパン、大開口、オーバーハング、スキップフロア、吹抜け、混構造 等

### 7.4. プロジェクト条件・環境
- **多雪地域**: 指定なし、垂直積雪量 1m未満、1m以上
- **風圧力・地表面粗度**: 基準風速 Vo=34m/s〜、地表面粗度区分 Ⅱ/Ⅲ
- **地盤条件**: 良好、軟弱（液状化検討あり）
- **防火地域指定**: 防火地域、準防火地域、法22条区域

### 7.5. 管理・ツール情報
- **使用ソフト**: KIZUKURI、HOUSE-ST1、SS7/SS3、BUILD.一貫、その他
- **取引先**: 工務店名、設計事務所名（キーワード検索）
- **審査機関**: ビューローベリタス、ERI、UDI、確認サービス 等

---

## 8. GCP Secret Manager設定

以下のシークレットが登録済み:
- `MS_CLIENT_ID`: Microsoft アプリケーションID
- `MS_TENANT_ID`: Microsoft テナントID
- `MS_CLIENT_SECRET`: Microsoft クライアントシークレット

---

## 9. 次のステップ（To-Do）

### 短期（現在のフェーズ）
- [ ] 複数の「行」フォルダをまとめて処理できるようにTARGET_ROOT_PATHを上位階層に設定
- [ ] エラーハンドリングの強化（APIレートリミット、ネットワークエラー等）
- [ ] ログ出力の改善（処理進捗の可視化）

### 中期（フロントエンド開発）
- [ ] Next.jsによる検索UIの実装
- [ ] Firestoreとの連携（検索クエリ、結果表示）
- [ ] フィルタリング機能（複数条件の組み合わせ）

### 長期（運用・スケール）
- [ ] Cloud Run Jobsへのデプロイ（定期実行）
- [ ] Cloud Schedulerによる自動実行設定
- [ ] 処理済みデータの差分更新ロジック
- [ ] Vercelへのフロントエンドデプロイ

---

## 10. 重要な注意事項

### 10.1. OneDriveパス指定の罠

**必ずコピペで入力すること！** 見た目は同じでもシステム上は別の文字として扱われるケースあり:

- 全角の「Ｕ」: `U'plan` ではなく `Ｕ'plan`
- 全角の「Ａ」: `A行` ではなく `Ａ行`
- 特殊記号「□」: フォルダ名にそのまま含まれる
- カッコ: `()` (半角) と `（）` (全角) の違い
- スペース: 半角スペース` `と全角スペース`　`の違い

### 10.2. Vercelホスティングについて

- **検索UI（フロントエンド）**: Vercelが最適
- **バッチ処理（Python）**: Vercelは不向き（実行時間制限あり）
  - 推奨: ローカル実行 or GCP Cloud Run Jobs
  - データ連携: Firestore経由

### 10.3. 重複処理の防止

- 構造計算書のファイルIDをドキュメントIDとして使用
- 処理前に `doc_ref.get().exists` で重複チェック
- すでに処理済みの場合はスキップ

---

## 11. テスト済み物件データ

| 物件名 | 取引先 | 作成日 | ルート判定 | 判定理由 |
|--------|--------|--------|------------|----------|
| 蕨市錦町002②1号棟 | 三栄建築設計 | 2025-03-12 | ルート1 | 構造計算方針にルート1明記、壁量計算実施 |
| 蕨市錦町002②2号棟 | 三栄建築設計 | 2025-03-12 | ルート1 | 令46条壁量計算確認、層間変形角は付加検討 |
| 松下邸 | （未抽出） | 2025-09-11 | ルート1 | プログラムチェックリストにルート1明記 |

---

## 12. トラブルシューティング

### エラー: 404 The database (default) does not exist

**原因**: Firestoreクライアント初期化時にデータベース名を指定していない

**解決策**:
```python
# ❌ 間違い
db = firestore.Client(project='uplan-knowledge-base')

# ✅ 正しい
db = firestore.Client(project='uplan-knowledge-base', database='uplan')
```

### エラー: 構造計算書PDFが見つかりませんでした

**原因**: フォルダ内に構造計算書PDFが存在しない、またはファイル名パターンが一致しない

**確認方法**:
1. バッチ処理のデバッグ出力で「📋 フォルダ内のアイテム数」を確認
2. ファイル名に「構造計算書」が含まれているか確認
3. 拡張子が `.pdf` になっているか確認

### 取引先名が「不明」になる

**原因**: フォルダパスに `T数字 会社名` または `A数字 会社名` のパターンが存在しない

**対処**:
- フォルダ構造を確認し、該当パターンがあるか確認
- 必要に応じて正規表現パターンを調整（`batch_processor_v3.py:61-67`）

---

## 付録: 主要ファイル一覧

| ファイル名 | 説明 |
|-----------|------|
| `batch_processor_v3.py` | メインバッチ処理プログラム |
| `test_metadata_extraction.py` | メタデータ抽出のテストスクリプト |
| `test_full_path_extraction.py` | 実パスでのメタデータ抽出テスト |
| `METADATA_EXTRACTION_TEST_RESULTS.md` | テスト結果レポート |
| `claude.md` | 本ドキュメント（開発履歴・仕様書） |

---

**最終更新日**: 2025-12-07
**バージョン**: v3.1（メタデータ抽出・ルート1優先判定実装完了）
