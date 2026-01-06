"""
Uplan Knowledge Base - Batch Processor v3 (Parallel Processing Edition)

並列処理対応版:
- ProcessPoolExecutor による5並列処理
- コマンドライン引数でターゲットパス指定
- 進捗管理とエラーハンドリング強化
- Cloud Run Jobs対応
"""

import msal
import requests
import json
import os
import gc
import argparse
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Dict, Tuple, Optional
import vertexai
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig
from google.cloud import secretmanager
from google.cloud import firestore
from google.api_core import retry, exceptions

# --- 設定 ---
GCP_PROJECT_ID = "uplan-knowledge-base"
LOCATION = "us-central1"
TARGET_USER_EMAIL = "info@uplan2018.onmicrosoft.com"

# デフォルト設定（コマンドライン引数で上書き可能）
DEFAULT_TARGET_PATH = "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）"
DEFAULT_MAX_WORKERS = 5
# ---------------------------------------------------------

# 1. 認証周り
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

# 1-2. システム設定管理（デルタクエリ用スタンプ）
def get_system_config():
    """Firestoreからシステム設定（前回の同期状態）を取得"""
    try:
        db = firestore.Client(project=GCP_PROJECT_ID, database="uplan")
        doc_ref = db.collection("system_config").document("onedrive_sync")
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        print(f"⚠️ システム設定取得エラー: {e}")
        return None

def save_system_config(delta_link):
    """Firestoreにシステム設定（同期状態）を保存"""
    try:
        db = firestore.Client(project=GCP_PROJECT_ID, database="uplan")
        doc_ref = db.collection("system_config").document("onedrive_sync")
        doc_ref.set({
            "deltaLink": delta_link,
            "last_run_at": firestore.SERVER_TIMESTAMP
        })
        print(f"✅ デルタリンクを保存しました")
    except Exception as e:
        print(f"❌ システム設定保存エラー: {e}")

# 2. パス情報抽出ロジック
def extract_project_metadata(folder_path):
    """
    フォルダパスから案件メタデータを抽出
    例: "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□あ行/A00698アゼリアホーム/..."
    """
    metadata = {
        "structureType": None,
        "clientName": None,
        "projectName": None
    }

    parts = folder_path.split('/')

    # 1. 取引先名の抽出
    # 基本構造: 木造（在来軸組）> □あ行 > 取引先名
    # 木造フォルダを起点に3階層目が取引先名
    for i, part in enumerate(parts):
        if '木造' in part:
            metadata["structureType"] = "木造"
            if i + 2 < len(parts):
                client_folder = parts[i + 2]
                # パターン1: "A数字_取引先名" または "A数字取引先名"（アンダーバーあり・なし対応）
                import re
                match = re.match(r'^[AT]\d+_?(.+?)(?:（.+?）)?$', client_folder)
                if match:
                    metadata["clientName"] = match.group(1).strip()
                    break
        elif 'RC' in part or '鉄筋コンクリート' in part:
            metadata["structureType"] = "RC造"
        elif '鉄骨' in part:
            metadata["structureType"] = "S造"

    # 2. 案件名の抽出
    # "2024009_（仮称）三田2丁目AP／2024010_設計変更" のようなフォルダ名から抽出
    for part in parts:
        if part.startswith(('2024', '2025', '2026')):
            # "／" で分割して最初の部分を案件名とする
            project_part = part.split('／')[0]
            # "2024009_" のような番号部分を除去
            import re
            match = re.match(r'^\d+_(.+)$', project_part)
            if match:
                metadata["projectName"] = match.group(1).strip()
                break

    return metadata

# 3. ファイル選定ロジック
def select_project_files(file_list):
    """
    フォルダ内のファイルから、構造計算書・図面・証明書・審査表を選定
    """
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

        # 構造計算書
        if "構造計算書" in name or "計算書" in name:
            all_calc_files.append(item)

        # 構造図
        elif "構造図" in name or "伏図" in name or "軸組図" in name:
            all_drawing_files.append(item)

        # 安全証明書
        elif "安全証明" in name or "適合証明" in name:
            safety_certs.append(item)

        # 構造審査表
        elif "審査表" in name or "チェックシート" in name:
            review_sheets.append(item)

    # 最新の証明書と審査表を選択
    best_cert = safety_certs[-1] if safety_certs else None
    best_review = review_sheets[-1] if review_sheets else None

    return all_calc_files, all_drawing_files, best_cert, best_review

# 4. デルタクエリによる差分取得
def fetch_drive_changes(access_token, user_email, delta_link=None):
    """Microsoft Graph APIのデルタクエリを使用して、前回からの変更を取得"""
    headers = {"Authorization": f"Bearer {access_token}"}
    changed_items = []

    if delta_link is None:
        url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/root:/delta"
        print(f"📍 初回デルタクエリ実行")
    else:
        url = delta_link
        print(f"📍 差分取得モード: 前回からの変更のみを取得")

    try:
        while url:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            items = data.get('value', [])
            for item in items:
                if 'deleted' in item:
                    continue
                if 'file' in item and item.get('name', '').lower().endswith('.pdf'):
                    changed_items.append(item)
                if 'folder' in item:
                    changed_items.append(item)

            url = data.get('@odata.nextLink')
            if not url:
                new_delta_link = data.get('@odata.deltaLink')
                break

        print(f"✅ デルタクエリ完了: {len(changed_items)}件の変更を検出")
        return changed_items, new_delta_link

    except Exception as e:
        print(f"❌ デルタクエリエラー: {e}")
        return [], None

# 5. フォルダ収集（並列処理用）
def collect_all_project_folders(access_token, user_email, root_path):
    """
    指定されたルートパス配下の全ての構造設計図書フォルダを収集
    Returns: List[Dict] - 案件フォルダ情報のリスト
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    project_folders = []

    print(f"📂 フォルダ収集開始: {root_path}")

    def scan_folder_recursive(folder_url, current_path=""):
        """再帰的にフォルダをスキャン"""
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

                # 構造設計図書フォルダを検出（ダミーフォルダ除外）
                if ('構造設計図書' in folder_name or '構造計算書' in folder_name) and '○' not in folder_name:
                    # サブフォルダ（納品時など）も探索
                    sub_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{folder_id}/children"
                    sub_response = requests.get(sub_url, headers=headers, timeout=30)
                    if sub_response.status_code == 200:
                        sub_items = sub_response.json().get('value', [])

                        # サブフォルダ内にも構造設計図書フォルダがあるかチェック
                        has_sub_folders = False
                        for sub_item in sub_items:
                            if "folder" in sub_item:
                                sub_name = sub_item['name']
                                if ('構造設計図書' in sub_name or '構造計算書' in sub_name) and '○' not in sub_name:
                                    project_folders.append({
                                        'id': sub_item['id'],
                                        'name': sub_item['name'],
                                        'path': new_path,
                                        'full_path': f"{new_path}/{sub_item['name']}"
                                    })
                                    has_sub_folders = True

                        # サブフォルダがなければ、このフォルダ自体を追加
                        if not has_sub_folders:
                            project_folders.append({
                                'id': folder_id,
                                'name': folder_name,
                                'path': current_path,
                                'full_path': new_path
                            })
                else:
                    # 構造設計図書フォルダでない場合は再帰的に探索
                    child_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{folder_id}/children"
                    scan_folder_recursive(child_url, new_path)

        except requests.exceptions.Timeout:
            print(f"⚠️ タイムアウト: {current_path}")
        except Exception as e:
            print(f"⚠️ フォルダスキャンエラー ({current_path}): {e}")

    # ルートパスから探索開始
    start_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/root:/{root_path}:/children"
    scan_folder_recursive(start_url, root_path)

    print(f"✅ フォルダ収集完了: {len(project_folders)}件の案件を検出")
    return project_folders

# 6. Gemini APIによる解析（リトライ付き）
@retry.Retry(
    predicate=retry.if_exception_type(exceptions.ResourceExhausted),
    initial=1.0,
    maximum=60.0,
    multiplier=2.0,
    timeout=300.0
)
def analyze_with_gemini_retry(file_data_list, file_name_hints=None):
    """Gemini APIを呼び出し（429エラー時は自動リトライ）"""
    return analyze_with_gemini(file_data_list, file_name_hints)

def analyze_with_gemini(file_data_list, file_name_hints=None):
    """
    Gemini 2.0 Flash (Vertex AI) でPDFを解析
    file_data_list: [{"data": bytes, "mime_type": str, "name": str}, ...]
    """
    vertexai.init(project=GCP_PROJECT_ID, location=LOCATION)
    model = GenerativeModel("gemini-2.0-flash-exp")

    parts = []

    # ファイル名ヒント
    if file_name_hints:
        hint_text = "【ファイル名ヒント】\n" + "\n".join([f"- {hint}" for hint in file_name_hints])
        parts.append(hint_text)

    # PDFファイルを追加
    for file_info in file_data_list:
        parts.append(Part.from_data(file_info["data"], mime_type=file_info["mime_type"]))
        parts.append(f"[ファイル名: {file_info['name']}]")

    # プロンプト（簡略版 - 実際のプロンプトは既存のものを使用）
    prompt = """
以下の構造計算書PDFを解析し、JSON形式で情報を抽出してください。

【抽出項目】
1. 都道府県名（prefecture）
2. 構造種別（structureTypes）: ["木造", "RC造", "S造", "混構造"]
3. 用途種別（useTypes）: ["共同住宅", "事務所", "店舗", "戸建住宅", etc.]
4. 階数カテゴリ（floorCategories）: ["平屋", "2階建て", "3階建て以上"]
5. 延べ面積（totalArea）: 数値
6. 面積カテゴリ（areaCategory）: "500㎡未満" | "500㎡以上"
7. 性能表示（performanceLabels）: ["耐震等級3", "制振構造", etc.]
8. 計算ルート（calcRoutes）: ["ルート1", "ルート2", "ルート3", "許容応力度計算", "限界耐力計算"]
9. 基礎形式（foundationTypes）: ["べた基礎", "布基礎", "杭基礎"]
10. 設計特記（features）: ["鉄骨造外部階段", "吹抜け", "オーバーハング", etc.]
11. 耐力要素（resistanceElements）: ["筋かい", "構造用合板", "耐力壁", etc.]
12. 積雪地域（snowRegion）: "一般地域" | "多雪地域"
13. 防火地域（fireZone）: "指定なし" | "準防火地域" | "防火地域"
14. 地盤種別（groundCondition）: "普通地盤" | "軟弱地盤"
15. 計算ソフト（software）
16. 検査機関（inspectionAgency）
17. サマリー（summary）: 案件の特徴を2-3文で要約

【出力形式】
```json
{
  "basic": {
    "prefecture": "神奈川県",
    "structureTypes": ["木造"],
    "useTypes": ["共同住宅"],
    "floorCategories": ["3階建て以上"],
    "totalArea": 850.5,
    "areaCategory": "500㎡以上"
  },
  "regulations": {
    "performanceLabels": ["耐震等級3"],
    "calcRoutes": ["許容応力度計算"],
    "calcRouteReasoning": "..."
  },
  "technology": {
    "foundationTypes": ["べた基礎"],
    "features": ["鉄骨造外部階段"],
    "resistanceElements": ["構造用合板"]
  },
  "environment": {
    "snowRegion": "一般地域",
    "fireZone": "準防火地域",
    "groundCondition": "普通地盤"
  },
  "management": {
    "software": "STRDESIGN Ver.17-03",
    "inspectionAgency": "日本ERI"
  },
  "analysis": {
    "summary": "..."
  }
}
```

【重要な検出ルール】
★★★最重要★★★ 鉄骨造外部階段の検出:
- 構造計算書の目次、本文、計算書内に「鉄骨階段」「外部階段」「屋外階段」などのキーワードがある
- 構造図面に鉄骨階段の図面がある
- 計算書のタイトルや章立てに「階段」「外部階段」などの記載がある
→ いずれかに該当すれば「鉄骨造外部階段」として抽出してください

それでは解析を開始してください。
"""

    parts.insert(0, prompt)

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

        # JSONを抽出
        if "```json" in text:
            json_str = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            json_str = text.split("```")[1].split("```")[0].strip()
        else:
            json_str = text.strip()

        result = json.loads(json_str)
        return result

    except Exception as e:
        print(f"❌ Gemini解析エラー: {e}")
        return None

# 7. 単一案件の処理（並列実行される関数）
def process_single_project(project_info: Dict, access_token: str, user_email: str) -> Tuple[bool, str]:
    """
    単一の案件フォルダを処理（並列実行される）

    Args:
        project_info: フォルダ情報
        access_token: アクセストークン
        user_email: ユーザーメールアドレス

    Returns:
        (success: bool, message: str)
    """
    folder_id = project_info['id']
    folder_name = project_info['name']
    full_path = project_info['full_path']

    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        # フォルダ内のファイル一覧を取得
        folder_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{folder_id}/children"
        response = requests.get(folder_url, headers=headers, timeout=60)
        response.raise_for_status()
        items = response.json().get('value', [])

        # ファイルを選定
        calc_files, drawing_files, cert_file, review_file = select_project_files(items)

        if not calc_files:
            return False, f"構造計算書PDFが見つかりません"

        # PDFをダウンロード
        file_data_list = []
        file_name_hints = []

        for pdf_file in calc_files[:5]:  # 最大5ファイル
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
            return False, "PDFダウンロード失敗"

        # Gemini APIで解析
        analysis_result = analyze_with_gemini_retry(file_data_list, file_name_hints)

        # メモリ解放
        del file_data_list
        gc.collect()

        if not analysis_result:
            return False, "AI解析失敗"

        # フォルダパスからメタデータ抽出
        metadata = extract_project_metadata(full_path)

        # Firestoreに保存
        db = firestore.Client(project=GCP_PROJECT_ID, database="uplan")

        # ドキュメントIDを生成（フォルダIDを使用）
        doc_id = f"project_{folder_id}"

        # 保存データを構築
        basic = analysis_result.get("basic", {})
        regulations = analysis_result.get("regulations", {})
        technology = analysis_result.get("technology", {})
        environment = analysis_result.get("environment", {})
        management = analysis_result.get("management", {})
        analysis = analysis_result.get("analysis", {})

        save_data = {
            # 建築物の特性
            "prefecture": basic.get("prefecture"),
            "structure_types": basic.get("structureTypes", []),
            "use_types": basic.get("useTypes", []),
            "floor_categories": basic.get("floorCategories", []),
            "total_area": basic.get("totalArea", 0.0),
            "area_category": basic.get("areaCategory", ""),

            # 法律・技術的要件
            "performance_requirements": regulations.get("performanceLabels", []),
            "calc_routes": regulations.get("calcRoutes", []),
            "calc_route_reasoning": regulations.get("calcRouteReasoning", ""),
            "foundation_types": technology.get("foundationTypes", []),
            "design_features": technology.get("features", []),
            "resistance_elements": technology.get("resistanceElements", []),

            # プロジェクトの条件
            "region_conditions": {
                "snow_region": environment.get("snowRegion", ""),
                "fire_zone": environment.get("fireZone", ""),
            },
            "ground_condition": environment.get("groundCondition", ""),
            "client_name": metadata['clientName'],
            "partners": [metadata['clientName']] if metadata['clientName'] else [],
            "inspection_agency": management.get("inspectionAgency"),

            # その他
            "summary": analysis.get("summary", ""),

            # システム管理用フィールド
            "analysis_result": analysis_result,
            "file_id": folder_id,
            "extracted_at": firestore.SERVER_TIMESTAMP,
            "folder_name": folder_name,
            "folder_path": full_path,
            "file_count": {
                "calc": len(calc_files),
                "drawing": len(drawing_files),
                "cert": 1 if cert_file else 0,
                "review": 1 if review_file else 0
            }
        }

        # Firestoreに保存
        collection_ref = db.collection("Beta_2025_12_24")
        collection_ref.document(doc_id).set(save_data)

        return True, f"成功: {len(calc_files)}ファイル解析"

    except Exception as e:
        return False, f"エラー: {str(e)[:100]}"

# 8. 並列処理実行
def process_projects_parallel(project_folders: List[Dict], max_workers: int = 5):
    """
    複数の案件フォルダを並列処理

    Args:
        project_folders: 案件フォルダ情報のリスト
        max_workers: 並列処理数
    """
    print(f"\n🚀 並列処理開始: {len(project_folders)}件を{max_workers}並列で処理")

    # 各プロセスで使用するアクセストークンを取得
    token = get_access_token()
    if not token:
        print("❌ 認証失敗")
        return

    success_count = 0
    error_count = 0

    # ProcessPoolExecutorで並列処理
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        # タスクを投入
        future_to_project = {
            executor.submit(process_single_project, project, token, TARGET_USER_EMAIL): project
            for project in project_folders
        }

        # 完了したタスクから順に処理
        for future in as_completed(future_to_project):
            project = future_to_project[future]
            try:
                success, message = future.result()
                if success:
                    success_count += 1
                    print(f"✅ [{success_count + error_count}/{len(project_folders)}] {project['name']}: {message}")
                else:
                    error_count += 1
                    print(f"❌ [{success_count + error_count}/{len(project_folders)}] {project['name']}: {message}")
            except Exception as e:
                error_count += 1
                print(f"❌ [{success_count + error_count}/{len(project_folders)}] {project['name']}: 例外 - {str(e)[:100]}")

            # 少し待機（レート制限対策）
            time.sleep(0.2)

    print(f"\n📊 処理完了: 成功 {success_count}件 / エラー {error_count}件 / 合計 {len(project_folders)}件")

# 9. メイン処理
def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(description='Uplan Knowledge Base - Batch Processor (並列処理版)')
    parser.add_argument('--target-path', type=str, default=DEFAULT_TARGET_PATH,
                       help=f'抽出対象のルートパス (デフォルト: {DEFAULT_TARGET_PATH})')
    parser.add_argument('--workers', type=int, default=DEFAULT_MAX_WORKERS,
                       help=f'並列処理数 (デフォルト: {DEFAULT_MAX_WORKERS})')
    parser.add_argument('--mode', choices=['full', 'delta'], default='full',
                       help='実行モード: full=全件スキャン, delta=差分更新')

    args = parser.parse_args()

    print("=" * 80)
    print("🚀 Uplan Knowledge Base - Batch Processor v3 (並列処理版)")
    print("=" * 80)
    print(f"📂 ターゲットパス: {args.target_path}")
    print(f"⚙️  並列処理数: {args.workers}")
    print(f"🔄 実行モード: {args.mode}")
    print("=" * 80)

    # 認証
    token = get_access_token()
    if not token:
        print("❌ 認証失敗のため終了します")
        return

    if args.mode == 'delta':
        # 差分更新モード
        print("\n📊 差分更新モード: 前回からの変更のみを処理します")
        system_config = get_system_config()
        delta_link = system_config.get('deltaLink') if system_config else None

        if not delta_link:
            print("⚠️ デルタリンクが見つかりません。全件スキャンモードで実行してください。")
            return

        changed_items, new_delta_link = fetch_drive_changes(token, TARGET_USER_EMAIL, delta_link)

        if not changed_items:
            print("✨ 変更はありませんでした")
            return

        # 変更されたフォルダを処理（ここでは簡略化のため省略）
        print(f"📝 {len(changed_items)}件の変更を検出しました")
        # TODO: 差分モードの詳細実装

    else:
        # 全件スキャンモード
        print("\n📊 全件スキャンモード: すべてのフォルダを探索します")

        # フォルダ収集
        project_folders = collect_all_project_folders(token, TARGET_USER_EMAIL, args.target_path)

        if not project_folders:
            print("⚠️ 案件フォルダが見つかりませんでした")
            return

        # 並列処理
        process_projects_parallel(project_folders, max_workers=args.workers)

        # デルタリンク取得と保存
        print("\n📍 初回デルタリンクを取得中...")
        _, new_delta_link = fetch_drive_changes(token, TARGET_USER_EMAIL, None)
        if new_delta_link:
            save_system_config(new_delta_link)

    print("\n🎉 全処理が完了しました")

if __name__ == "__main__":
    main()
