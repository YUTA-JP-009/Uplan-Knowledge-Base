"""
Uplan Knowledge Base - Batch Processor v4 (Rate Limit Optimized)

レート制限最適化版:
- ProcessPoolExecutorによる並列処理で各プロセスが独立したレート制限枠を持つ
- 指数バックオフリトライ戦略
- より積極的なリトライ設定
- タスクごとの適切な待機時間
- Cloud Run Jobsでの大規模処理に最適化
"""

import msal
import requests
import json
import os
import gc
import argparse
import time
import random
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Dict, Tuple, Optional
import vertexai
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig
from google.cloud import secretmanager
from google.cloud import firestore
from google.api_core import retry, exceptions
from datetime import datetime, timezone, timedelta
import re

# 日本時間のタイムゾーン
JST = timezone(timedelta(hours=9))

# --- 設定 ---
GCP_PROJECT_ID = "uplan-knowledge-base"
LOCATION = "us-central1"
TARGET_USER_EMAIL = "info@uplan2018.onmicrosoft.com"

# デフォルト設定
DEFAULT_TARGET_PATH = "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）"
DEFAULT_MAX_WORKERS = 10  # 並列数を増やしてレート制限を分散
# Firestoreルール: データ抽出のたびに新規コレクションを作成（形式: YYYY-MM-DD-HH:MM）
DEFAULT_COLLECTION = datetime.now().strftime("%Y-%m-%d-%H:%M")

# レート制限対策設定
INITIAL_RETRY_DELAY = 2.0  # 初回リトライ待機時間（秒）
MAX_RETRY_DELAY = 120.0     # 最大リトライ待機時間（秒）
MAX_RETRIES = 5             # 最大リトライ回数
JITTER_RANGE = 0.5          # ランダムジッター範囲（秒）

# ---------------------------------------------------------

def get_secret(secret_id):
    """Secret Managerからシークレットを取得"""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{GCP_PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")

def get_access_token():
    """Microsoft Graph API用のアクセストークンを取得"""
    try:
        client_id = get_secret("MS_CLIENT_ID")
        tenant_id = get_secret("MS_TENANT_ID")
        client_secret = get_secret("MS_CLIENT_SECRET")

        authority = f"https://login.microsoftonline.com/{tenant_id}"
        app = msal.ConfidentialClientApplication(client_id, authority=authority, client_credential=client_secret)
        result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        return result.get("access_token")
    except Exception as e:
        print(f"❌ 認証エラー: {e}")
        return None

def extract_project_metadata(folder_path):
    """フォルダパスから案件メタデータを抽出"""
    metadata = {
        "structureType": None,
        "clientName": None,
        "projectName": None
    }

    parts = folder_path.split('/')

    for i, part in enumerate(parts):
        if '木造' in part:
            metadata["structureType"] = "木造"
            if i + 2 < len(parts):
                client_folder = parts[i + 2]
                match = re.match(r'^[AT]\d+_?(.+?)(?:（.+?）)?$', client_folder)
                if match:
                    metadata["clientName"] = match.group(1).strip()
                    break
                match2 = re.match(r'^\d+\s+(.+)$', client_folder)
                if match2:
                    metadata["clientName"] = match2.group(1).strip()
                    break
        elif 'RC' in part or '鉄筋コンクリート' in part:
            metadata["structureType"] = "RC造"
        elif '鉄骨' in part:
            metadata["structureType"] = "S造"

    for part in parts:
        if part.startswith(('2024', '2025', '2026')):
            project_part = part.split('／')[0]
            match = re.match(r'^\d+_(.+)$', project_part)
            if match:
                metadata["projectName"] = match.group(1).strip()
                break

    return metadata

def select_project_files(file_list):
    """フォルダ内のファイルから、構造計算書・図面・証明書・審査表を選定"""
    all_calc_files = []
    all_drawing_files = []
    safety_certs = []
    review_sheets = []

    for item in file_list:
        if "folder" in item:
            continue

        name = item.get("name", "")
        name_lower = name.lower()

        if not name_lower.endswith(".pdf"):
            continue

        if "構造計算書" in name or "計算書" in name:
            all_calc_files.append(item)
        elif "構造図" in name or "伏図" in name or "軸組図" in name:
            all_drawing_files.append(item)
        elif "安全証明" in name or "適合証明" in name:
            safety_certs.append(item)
        elif "審査表" in name or "チェックシート" in name:
            review_sheets.append(item)

    best_cert = safety_certs[-1] if safety_certs else None
    best_review = review_sheets[-1] if review_sheets else None

    return all_calc_files, all_drawing_files, best_cert, best_review

def exponential_backoff_with_jitter(attempt: int) -> float:
    """指数バックオフ + ランダムジッター"""
    delay = min(INITIAL_RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)
    jitter = random.uniform(-JITTER_RANGE, JITTER_RANGE)
    return max(0.1, delay + jitter)

def analyze_with_gemini_with_retry(file_data_list, file_name_hints=None, max_attempts=MAX_RETRIES):
    """
    Gemini APIを呼び出し（積極的なリトライ戦略）
    指数バックオフ + ランダムジッターでレート制限を回避
    """
    vertexai.init(project=GCP_PROJECT_ID, location=LOCATION)
    model = GenerativeModel("gemini-2.0-flash-exp")

    parts = []

    if file_name_hints:
        hint_text = "【ファイル名ヒント】\n" + "\n".join([f"- {hint}" for hint in file_name_hints])
        parts.append(hint_text)

    for file_info in file_data_list:
        parts.append(Part.from_data(file_info["data"], mime_type=file_info["mime_type"]))
        parts.append(f"[ファイル名: {file_info['name']}]")

    prompt = """
以下の構造計算書PDFを解析し、JSON形式で情報を抽出してください。

【抽出項目と選択肢】

■ 基本情報
1. 構造種別（structureType）: 単一選択
   選択肢: "木造（在来軸組）", "木造（限界耐力計算）", "木造（枠組壁）", "鉄骨造", "RC造（壁式）", "RC造（ラーメン）"

2. 主要用途（primaryUse）: 単一選択
   選択肢: "戸建住宅", "共同住宅", "店舗", "事務所", "倉庫", "工場", "その他"

3. 階数（floors）: 単一選択
   選択肢: "平屋", "2階建て", "3階建て", "4階建て以上"

4. 延床面積（totalFloorArea）: 単一選択
   選択肢: "〜100㎡", "101〜300㎡", "301〜1000㎡", "1001㎡〜"

■ 法律・技術的要件
5. 性能要件（performanceRequirements）: 複数選択可
   選択肢: "準耐火建築物", "耐火建築物", "長期優良住宅", "適合性判定", "その他"

6. 構造計算ルート（structuralCalcRoute）: 単一選択
   選択肢: "ルート1（許容応力度計算）", "ルート2（許容応力度等計算）", "ルート3（保有水平耐力計算）"

7. ルート判定の根拠（routeReasoning）: 文字列（100文字程度）

8. 基礎形式（foundationType）: 単一選択
   選択肢: "直接基礎（べた基礎、布基礎など）", "杭基礎"

9. 特徴的な設計技術（designFeatures）: 複数選択可
   選択肢: "大スパン / 大開口", "スキップフロア", "木質ラーメン", "大屋根", "鉄骨造外部階段", "片持ち基礎（片持ちスラブ）", "ゾーニング", "塔屋", "片持ち基礎", "斜め壁"
   注意: 「大屋根」は構造計算書には記載がないため、構造図から視覚的に判定

10. 水平力抵抗要素（lateralResistance）: 複数選択可
    選択肢: "面材耐力壁（構造用合板、OSBなど）", "筋かい耐力壁"

■ プロジェクトの条件
11. 地域（regionalConditions）: 複数選択可
    選択肢: "多雪地域", "塩害地域", "防火・準防火地域"
    注意: 選択肢に該当しない場合は空配列

12. 地盤条件（groundCondition）: 単一選択
    選択肢: "良好", "軟弱"

13. 審査機関（inspectionAgency）: 文字列
    抽出ルール: 構造計算書には記載がないので質疑回答書があれば抽出、なければ空文字列
    質疑回答書の表記揺れ: 質疑解答書、質疑事項回答書、指摘回答書、指摘事項回答書など

■ その他
14. 物件特徴の要約（projectSummary）: 文字列（300文字程度で詳細に要約）

15. 物件名（projectName）: 文字列

16. 構造計算書の作成年月（calcBookDate）: 文字列（例: "2025年3月"）

17. 計算ソフト（software）: 文字列

【出力形式】
以下のJSON形式で出力してください：

```json
{
  "basic": {
    "structureType": "木造（在来軸組）",
    "primaryUse": "戸建住宅",
    "floors": "2階建て",
    "totalFloorArea": "101〜300㎡"
  },
  "legalTechnical": {
    "performanceRequirements": ["長期優良住宅"],
    "structuralCalcRoute": "ルート1（許容応力度計算）",
    "routeReasoning": "木造2階建て、延床面積500㎡未満のため、令第82条に基づきルート1を適用",
    "foundationType": "直接基礎（べた基礎、布基礎など）",
    "designFeatures": ["スキップフロア"],
    "lateralResistance": ["面材耐力壁（構造用合板、OSBなど）", "筋かい耐力壁"]
  },
  "projectConditions": {
    "regionalConditions": ["多雪地域"],
    "groundCondition": "良好",
    "inspectionAgency": "日本ERI"
  },
  "other": {
    "projectSummary": "木造2階建て住宅の構造設計。スキップフロアを採用し、空間の立体的な構成が特徴。多雪地域に対応した積雪荷重を考慮。耐力壁は構造用合板と筋かいを併用し、水平力に対する抵抗性能を確保。べた基礎により良好な地盤条件を活かした安定した基礎設計を実現。",
    "projectName": "○○邸新築工事",
    "calcBookDate": "2025年3月",
    "software": "STRDESIGN Ver.17-03"
  }
}
```

それでは解析を開始してください。
"""

    parts.insert(0, prompt)

    # リトライループ
    for attempt in range(max_attempts):
        try:
            response = model.generate_content(
                parts,
                generation_config=GenerationConfig(
                    temperature=0.1,
                    top_p=0.95,
                    max_output_tokens=8192,
                )
            )

            text = response.text

            if "```json" in text:
                json_str = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                json_str = text.split("```")[1].split("```")[0].strip()
            else:
                json_str = text.strip()

            result = json.loads(json_str)
            return result

        except exceptions.ResourceExhausted as e:
            # 429エラー: レート制限
            if attempt < max_attempts - 1:
                delay = exponential_backoff_with_jitter(attempt)
                print(f"   ⚠️ レート制限エラー (試行 {attempt + 1}/{max_attempts}): {delay:.1f}秒後にリトライ")
                time.sleep(delay)
            else:
                print(f"   ❌ Gemini解析失敗: 最大リトライ回数に達しました")
                return None

        except json.JSONDecodeError as e:
            print(f"   ❌ JSON解析エラー: {e}")
            return None

        except Exception as e:
            print(f"   ❌ Gemini解析エラー: {e}")
            if attempt < max_attempts - 1:
                delay = exponential_backoff_with_jitter(attempt)
                print(f"   ⏳ {delay:.1f}秒後にリトライ")
                time.sleep(delay)
            else:
                return None

    return None

def collect_all_project_folders(access_token, user_email, root_path):
    """指定されたルートパス配下の全ての構造設計図書フォルダを収集"""
    headers = {"Authorization": f"Bearer {access_token}"}
    project_folders = []

    print(f"📂 フォルダ収集開始: {root_path}")

    def scan_folder_recursive(folder_url, current_path="", depth=0):
        """再帰的にフォルダをスキャン（深さ制限付き）"""
        if depth > 10:  # 深さ制限
            return

        try:
            response = requests.get(folder_url, headers=headers, timeout=30)
            response.raise_for_status()
            items = response.json().get('value', [])

            for item in items:
                if "folder" not in item:
                    continue

                folder_name = item['name']
                folder_id = item['id']
                new_path = f"{current_path}/{folder_name}".lstrip('/')

                # 構造設計図書フォルダを検出
                if ('構造設計図書' in folder_name or '構造計算書' in folder_name) and '○' not in folder_name:
                    sub_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{folder_id}/children"
                    sub_response = requests.get(sub_url, headers=headers, timeout=30)
                    if sub_response.status_code == 200:
                        sub_items = sub_response.json().get('value', [])

                        has_sub_folders = False
                        for sub_item in sub_items:
                            if "folder" in sub_item:
                                sub_name = sub_item['name']
                                if ('構造設計図書' in sub_name or '構造計算書' in sub_name) and '○' not in sub_name:
                                    project_folders.append({
                                        'id': sub_item['id'],
                                        'name': sub_item['name'],
                                        'path': current_path,
                                        'full_path': f"{new_path}/{sub_item['name']}"
                                    })
                                    has_sub_folders = True

                        if not has_sub_folders:
                            project_folders.append({
                                'id': folder_id,
                                'name': folder_name,
                                'path': current_path,
                                'full_path': new_path
                            })
                else:
                    # 再帰的に探索
                    child_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{folder_id}/children"
                    scan_folder_recursive(child_url, new_path, depth + 1)

        except requests.exceptions.Timeout:
            print(f"⚠️ タイムアウト: {current_path}")
        except Exception as e:
            print(f"⚠️ フォルダスキャンエラー ({current_path}): {e}")

    start_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/root:/{root_path}:/children"
    scan_folder_recursive(start_url, root_path)

    print(f"✅ フォルダ収集完了: {len(project_folders)}件の案件を検出")
    return project_folders

def process_single_project(project_info: Dict, access_token: str, user_email: str, collection_name: str) -> Tuple[bool, str, float]:
    """
    単一の案件フォルダを処理（並列実行される）
    各プロセスが独立したレート制限枠を持つ
    """
    folder_id = project_info['id']
    folder_name = project_info['name']
    full_path = project_info['full_path']

    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        # 処理開始時にランダムな初期遅延を入れて、リクエストを分散
        initial_delay = random.uniform(0, 2.0)
        time.sleep(initial_delay)

        # フォルダの詳細情報とwebUrlを取得
        folder_detail_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{folder_id}"
        folder_detail_response = requests.get(folder_detail_url, headers=headers, timeout=30)
        folder_detail_response.raise_for_status()
        folder_detail = folder_detail_response.json()
        folder_web_url = folder_detail.get('webUrl', '')

        # フォルダ内のファイル一覧を取得
        folder_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{folder_id}/children"
        response = requests.get(folder_url, headers=headers, timeout=60)
        response.raise_for_status()
        items = response.json().get('value', [])

        # ファイルを選定
        calc_files, drawing_files, cert_file, review_file = select_project_files(items)

        if not calc_files:
            return False, f"構造計算書PDFが見つかりません", 0.0

        # 重複チェック
        db = firestore.Client(project=GCP_PROJECT_ID, database="uplan")
        existing_query = db.collection(collection_name).where("file_id", "==", folder_id).limit(1).stream()
        existing_docs = list(existing_query)

        if len(existing_docs) > 0:
            existing_doc = existing_docs[0]
            existing_data = existing_doc.to_dict()
            existing_project_name = existing_data.get('project_name', 'N/A')
            return False, f"スキップ（登録済み: {existing_project_name}）", 0.0

        # フォルダ名から作成年月を抽出
        created_year_month = None
        date_match = re.match(r'^(\d{4})(\d{2})\d{2}', folder_name)
        if date_match:
            year = date_match.group(1)
            month = date_match.group(2).lstrip('0')
            created_year_month = f"{year}年{month}月"

        # プロジェクト名を抽出
        project_name = None
        path_parts = full_path.split('/')
        if len(path_parts) >= 5:
            last_part = path_parts[-1]
            if not re.match(r'^\d{4,7}_', last_part):
                project_name = last_part
            elif len(path_parts) >= 6:
                number_folder = last_part
                name_match = re.match(r'^\d{4,7}_(.+?)(?:／|$)', number_folder)
                if name_match:
                    project_name = name_match.group(1)

        # PDFをダウンロード
        file_data_list = []
        file_name_hints = []

        for pdf_file in calc_files[:5]:
            download_url = pdf_file.get('@microsoft.graph.downloadUrl')
            if download_url:
                pdf_response = requests.get(download_url, timeout=120)
                if pdf_response.status_code == 200:
                    file_data_list.append({
                        "data": pdf_response.content,
                        "mime_type": "application/pdf",
                        "name": pdf_file['name']
                    })
                    file_name_hints.append(pdf_file['name'])

        if not file_data_list:
            return False, "PDFダウンロード失敗", 0.0

        # Gemini APIで解析（積極的なリトライ）
        start_time = time.time()
        analysis_result = analyze_with_gemini_with_retry(file_data_list, file_name_hints)
        elapsed = time.time() - start_time

        del file_data_list
        gc.collect()

        if not analysis_result:
            return False, "AI解析失敗", elapsed

        # フォルダパスからメタデータ抽出
        metadata = extract_project_metadata(full_path)

        # 解析結果を取得
        basic = analysis_result.get("basic", {})
        legal_technical = analysis_result.get("legalTechnical", {})
        project_conditions = analysis_result.get("projectConditions", {})
        other = analysis_result.get("other", {})

        # Firestoreに保存
        # Firestoreルール: ドキュメントIDは物件名をそのまま使用（特殊文字のみ置換）
        doc_id = (other.get("projectName", project_name) or "不明物件").replace("/", "-").replace(":", "-")

        # 取引先名をフォルダパスから抽出
        client_name = metadata['clientName'] or ""

        save_data = {
            # 基本情報
            "structure_type": basic.get("structureType", ""),
            "primary_use": basic.get("primaryUse", ""),
            "floors": basic.get("floors", ""),
            "total_floor_area": basic.get("totalFloorArea", ""),

            # 法律・技術的要件
            "performance_requirements": legal_technical.get("performanceRequirements", []),
            "structural_calc_route": legal_technical.get("structuralCalcRoute", ""),
            "route_reasoning": legal_technical.get("routeReasoning", ""),
            "foundation_type": legal_technical.get("foundationType", ""),
            "design_features": legal_technical.get("designFeatures", []),
            "lateral_resistance": legal_technical.get("lateralResistance", []),

            # プロジェクトの条件
            "regional_conditions": project_conditions.get("regionalConditions", []),
            "ground_condition": project_conditions.get("groundCondition", ""),
            "client_name": client_name,
            "inspection_agency": project_conditions.get("inspectionAgency", ""),

            # その他
            "project_summary": other.get("projectSummary", ""),
            "project_name": other.get("projectName", project_name or ""),
            "calc_book_date": other.get("calcBookDate", created_year_month or ""),
            "software": other.get("software", ""),

            # メタデータ
            "folder_url": folder_web_url,
            "extracted_at": datetime.now(JST).isoformat(),
            "file_id": folder_id,
            "folder_name": folder_name,
            "folder_path": full_path,
            "file_count": {
                "calc": len(calc_files),
                "drawing": len(drawing_files),
                "cert": 1 if cert_file else 0,
                "review": 1 if review_file else 0
            },

            # 生の解析結果を保存（デバッグ用）
            "raw_analysis_result": analysis_result
        }

        collection_ref = db.collection(collection_name)
        collection_ref.document(doc_id).set(save_data)

        return True, f"成功: {len(calc_files)}ファイル解析", elapsed

    except Exception as e:
        return False, f"エラー: {str(e)[:100]}", 0.0

def process_projects_parallel(project_folders: List[Dict], max_workers: int, collection_name: str):
    """
    複数の案件フォルダを並列処理
    各ワーカーが独立したプロセスで実行されるため、レート制限が分散される
    """
    print(f"\n🚀 並列処理開始: {len(project_folders)}件を{max_workers}並列で処理")
    print(f"💡 レート制限対策: 各ワーカーが独立したレート制限枠を持ちます")

    token = get_access_token()
    if not token:
        print("❌ 認証失敗")
        return

    success_count = 0
    error_count = 0
    skipped_count = 0
    total_elapsed = 0.0

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_project = {
            executor.submit(process_single_project, project, token, TARGET_USER_EMAIL, collection_name): project
            for project in project_folders
        }

        for future in as_completed(future_to_project):
            project = future_to_project[future]
            try:
                success, message, elapsed = future.result()
                total_elapsed += elapsed

                if success:
                    success_count += 1
                    print(f"✅ [{success_count + error_count + skipped_count}/{len(project_folders)}] {project['name']}: {message} ({elapsed:.1f}秒)")
                elif "スキップ" in message:
                    skipped_count += 1
                    print(f"⏭️  [{success_count + error_count + skipped_count}/{len(project_folders)}] {project['name']}: {message}")
                else:
                    error_count += 1
                    print(f"❌ [{success_count + error_count + skipped_count}/{len(project_folders)}] {project['name']}: {message}")

            except Exception as e:
                error_count += 1
                print(f"❌ [{success_count + error_count + skipped_count}/{len(project_folders)}] {project['name']}: 例外 - {str(e)[:100]}")

    avg_time = total_elapsed / success_count if success_count > 0 else 0

    print(f"\n📊 処理完了: 成功 {success_count}件 / スキップ {skipped_count}件 / エラー {error_count}件 / 合計 {len(project_folders)}件")
    print(f"⏱️  平均処理時間: {avg_time:.1f}秒/件")
    print(f"⏱️  総処理時間: {total_elapsed:.1f}秒 ({total_elapsed/60:.1f}分)")

def main():
    """メイン処理"""
    start_time = time.time()
    start_datetime = datetime.now()

    parser = argparse.ArgumentParser(description='Uplan Knowledge Base - Batch Processor v4 (Rate Limit Optimized)')
    parser.add_argument('--target-path', type=str, default=DEFAULT_TARGET_PATH,
                       help=f'抽出対象のルートパス (デフォルト: {DEFAULT_TARGET_PATH})')
    parser.add_argument('--workers', type=int, default=DEFAULT_MAX_WORKERS,
                       help=f'並列処理数 (デフォルト: {DEFAULT_MAX_WORKERS})')
    parser.add_argument('--collection', type=str, default=DEFAULT_COLLECTION,
                       help=f'保存先コレクション (デフォルト: {DEFAULT_COLLECTION})')

    args = parser.parse_args()

    print("=" * 80)
    print("🚀 Uplan Knowledge Base - Batch Processor v4 (Rate Limit Optimized)")
    print("=" * 80)
    print(f"📂 ターゲットパス: {args.target_path}")
    print(f"⚙️  並列処理数: {args.workers}")
    print(f"💾 保存先コレクション: {args.collection}")
    print(f"⏰ 開始時刻: {start_datetime.strftime('%Y/%m/%d %H:%M:%S')}")
    print(f"🔄 レート制限対策: 指数バックオフ + ランダムジッター + プロセス分散")
    print("=" * 80)

    # 認証
    token = get_access_token()
    if not token:
        print("❌ 認証失敗のため終了します")
        return

    # フォルダ収集
    project_folders = collect_all_project_folders(token, TARGET_USER_EMAIL, args.target_path)

    if not project_folders:
        print("⚠️ 案件フォルダが見つかりませんでした")
        return

    # 並列処理
    process_projects_parallel(project_folders, max_workers=args.workers, collection_name=args.collection)

    # 実行時間トラッキング終了
    end_time = time.time()
    end_datetime = datetime.now()
    elapsed_seconds = int(end_time - start_time)
    elapsed_minutes = elapsed_seconds // 60
    elapsed_seconds_remainder = elapsed_seconds % 60

    print("\n" + "=" * 80)
    print("🎉 全処理が完了しました")
    print("=" * 80)
    print(f"⏰ 開始時刻: {start_datetime.strftime('%Y/%m/%d %H:%M:%S')}")
    print(f"⏰ 終了時刻: {end_datetime.strftime('%Y/%m/%d %H:%M:%S')}")
    print(f"⏱️  処理時間: {elapsed_minutes}分{elapsed_seconds_remainder}秒")
    print("=" * 80)

if __name__ == "__main__":
    main()
