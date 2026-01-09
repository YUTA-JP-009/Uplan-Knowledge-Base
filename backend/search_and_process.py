"""
OneDrive検索で案件を見つけて直接処理する
"""

import msal
import requests
import json
import os
import gc
import time
from datetime import datetime
from typing import List, Dict, Tuple, Optional
import vertexai
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig
from google.cloud import secretmanager
from google.cloud import firestore
from google.api_core import retry, exceptions
import re

# --- 設定 ---
GCP_PROJECT_ID = "uplan-knowledge-base"
LOCATION = "us-central1"
TARGET_USER_EMAIL = "info@uplan2018.onmicrosoft.com"

# テストコレクション
TEST_COLLECTION = "Projects_Test_20260108_182447"

# 検索キーワード
SEARCH_KEYWORDS = [
    "三田2丁目",
    "小さなお葬式"
]

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

def search_folders_by_keyword(access_token, keyword):
    """Microsoft Graph APIでフォルダを検索"""
    headers = {"Authorization": f"Bearer {access_token}"}

    print(f"\n🔍 検索中: {keyword}")

    search_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/root/search(q='{keyword}')"

    try:
        response = requests.get(search_url, headers=headers, timeout=30)
        response.raise_for_status()
        results = response.json().get('value', [])

        # 構造設計図書フォルダを探す
        target_folders = []
        for item in results:
            if 'folder' in item:
                name = item.get('name', '')
                parent_path = item.get('parentReference', {}).get('path', '')

                # 構造設計図書フォルダを優先
                if ('構造設計図書' in name or '構造計算書' in name) and '○' not in name:
                    if '/drive/root:' in parent_path:
                        parent_path = parent_path.replace('/drive/root:', '')
                    full_path = f"{parent_path}/{name}".lstrip('/')
                    target_folders.append({
                        'id': item['id'],
                        'name': name,
                        'path': full_path,
                        'webUrl': item.get('webUrl', '')
                    })

        if target_folders:
            print(f"✅ {len(target_folders)}件のフォルダが見つかりました")
            for folder in target_folders[:3]:  # 最初の3件を表示
                print(f"   📂 {folder['path']}")
            return target_folders
        else:
            print(f"⚠️ フォルダが見つかりませんでした")
            return []

    except Exception as e:
        print(f"❌ 検索エラー: {e}")
        return []

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
    """Gemini 2.0 Flash (Vertex AI) でPDFを解析"""
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

def process_folder(folder_info: Dict, access_token: str, user_email: str) -> Tuple[bool, str, float]:
    """
    フォルダを処理
    """
    start_time = time.time()

    headers = {"Authorization": f"Bearer {access_token}"}
    folder_id = folder_info['id']
    folder_name = folder_info['name']
    folder_path = folder_info['path']
    folder_web_url = folder_info['webUrl']

    try:
        print(f"\n📂 処理開始: {folder_name}")
        print(f"   パス: {folder_path}")

        # フォルダ内のファイル一覧を取得
        folder_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{folder_id}/children"
        response = requests.get(folder_url, headers=headers, timeout=60)
        response.raise_for_status()
        items = response.json().get('value', [])

        # ファイルを選定
        calc_files, drawing_files, cert_file, review_file = select_project_files(items)

        if not calc_files:
            elapsed = time.time() - start_time
            return False, "構造計算書PDFが見つかりません", elapsed

        # プロジェクト名を抽出
        metadata = extract_project_metadata(folder_path)
        project_name = metadata.get('projectName') or folder_name

        # PDFをダウンロード
        file_data_list = []
        file_name_hints = []

        print(f"   📥 PDFダウンロード中: {len(calc_files)}ファイル")
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
            elapsed = time.time() - start_time
            return False, "PDFダウンロード失敗", elapsed

        # Gemini APIで解析
        print(f"   🤖 AI解析中...")
        analysis_result = analyze_with_gemini_retry(file_data_list, file_name_hints)

        del file_data_list
        gc.collect()

        if not analysis_result:
            elapsed = time.time() - start_time
            return False, "AI解析失敗", elapsed

        # Firestoreに保存
        db = firestore.Client(project=GCP_PROJECT_ID, database="uplan")

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_project_name = (project_name or "不明物件").replace("/", "-").replace(":", "-")
        doc_id = f"{safe_project_name}_{timestamp}"

        basic = analysis_result.get("basic", {})
        regulations = analysis_result.get("regulations", {})
        technology = analysis_result.get("technology", {})
        environment = analysis_result.get("environment", {})
        management = analysis_result.get("management", {})
        analysis = analysis_result.get("analysis", {})

        # 作成年月の抽出
        created_year_month = None
        date_match = re.match(r'^(\d{4})(\d{2})\d{2}', folder_name)
        if date_match:
            year = date_match.group(1)
            month = date_match.group(2).lstrip('0')
            created_year_month = f"{year}年{month}月"

        save_data = {
            "prefecture": basic.get("prefecture"),
            "structure_types": basic.get("structureTypes", []),
            "use_types": basic.get("useTypes", []),
            "floor_categories": basic.get("floorCategories", []),
            "total_area": basic.get("totalArea", 0.0),
            "area_category": basic.get("areaCategory", ""),
            "performance_requirements": regulations.get("performanceLabels", []),
            "calc_routes": regulations.get("calcRoutes", []),
            "calc_route_reasoning": regulations.get("calcRouteReasoning", ""),
            "foundation_types": technology.get("foundationTypes", []),
            "design_features": technology.get("features", []),
            "resistance_elements": technology.get("resistanceElements", []),
            "region_conditions": {
                "snow_region": environment.get("snowRegion", ""),
                "fire_zone": environment.get("fireZone", ""),
            },
            "ground_condition": environment.get("groundCondition", ""),
            "client_name": metadata['clientName'],
            "partners": [metadata['clientName']] if metadata['clientName'] else [],
            "inspection_agency": management.get("inspectionAgency"),
            "summary": analysis.get("summary", ""),
            "analysis_result": analysis_result,
            "file_id": folder_id,
            "extracted_at": firestore.SERVER_TIMESTAMP,
            "created_year_month": created_year_month,
            "project_name": project_name,
            "folder_name": folder_name,
            "folder_path": folder_path,
            "folder_url": folder_web_url,
            "file_count": {
                "calc": len(calc_files),
                "drawing": len(drawing_files),
                "cert": 1 if cert_file else 0,
                "review": 1 if review_file else 0
            }
        }

        print(f"   💾 Firestore保存中...")
        collection_ref = db.collection(TEST_COLLECTION)
        collection_ref.document(doc_id).set(save_data)

        elapsed = time.time() - start_time
        return True, f"成功: {len(calc_files)}ファイル解析", elapsed

    except Exception as e:
        elapsed = time.time() - start_time
        return False, f"エラー: {str(e)[:100]}", elapsed

def main():
    """メイン処理"""
    print("=" * 80)
    print("🔍 OneDrive検索 & 直接処理")
    print("=" * 80)
    print(f"📊 保存先コレクション: {TEST_COLLECTION}")
    print("=" * 80)

    overall_start = time.time()

    # 認証
    token = get_access_token()
    if not token:
        print("❌ 認証失敗のため終了します")
        return

    all_target_folders = []

    # 各キーワードで検索
    for keyword in SEARCH_KEYWORDS:
        folders = search_folders_by_keyword(token, keyword)
        if folders:
            # 最も関連性の高いものを選択（最初の1件）
            all_target_folders.append(folders[0])

    if not all_target_folders:
        print("\n❌ 対象フォルダが見つかりませんでした")
        return

    print(f"\n📂 処理対象: {len(all_target_folders)}件")

    results = []

    # 各フォルダを処理
    for i, folder_info in enumerate(all_target_folders, 1):
        print(f"\n[{i}/{len(all_target_folders)}] {folder_info['name']}")

        # レート制限対策
        if i > 1:
            print("   ⏳ レート制限対策のため60秒待機...")
            time.sleep(60)

        success, message, elapsed = process_folder(folder_info, token, TARGET_USER_EMAIL)

        results.append({
            "folder": folder_info['name'],
            "path": folder_info['path'],
            "success": success,
            "message": message,
            "elapsed": elapsed
        })

        if success:
            print(f"   ✅ {message} (処理時間: {elapsed:.1f}秒)")
        else:
            print(f"   ❌ {message} (処理時間: {elapsed:.1f}秒)")

    overall_elapsed = time.time() - overall_start

    # 結果サマリー
    print("\n" + "=" * 80)
    print("📊 処理結果サマリー")
    print("=" * 80)

    success_count = sum(1 for r in results if r["success"])
    total_processing_time = sum(r["elapsed"] for r in results)
    avg_time = total_processing_time / len(results) if results else 0

    print(f"✅ 成功: {success_count}/{len(results)}件")
    print(f"❌ 失敗: {len(results) - success_count}/{len(results)}件")
    print(f"⏱️  総実行時間: {overall_elapsed:.1f}秒 ({overall_elapsed/60:.1f}分)")
    print(f"⏱️  平均処理時間: {avg_time:.1f}秒/件")
    print(f"💾 保存先: Firestore > {TEST_COLLECTION}")
    print("=" * 80)

    # 詳細結果
    print("\n📋 詳細結果:")
    for i, result in enumerate(results, 1):
        status = "✅" if result["success"] else "❌"
        print(f"{i}. {status} {result['folder']}")
        print(f"   パス: {result['path']}")
        print(f"   結果: {result['message']} ({result['elapsed']:.1f}秒)")

if __name__ == "__main__":
    main()
