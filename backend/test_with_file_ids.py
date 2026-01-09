"""
既存Firestoreデータからfile_idを使用してテスト処理
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

# 新しいコレクション名（日時付き）
TEST_COLLECTION = f"Projects_Test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# テスト対象のキーワード（物件名で検索）
TEST_PROJECT_KEYWORDS = [
    "松下邸",
    "フルイチ様オフィス新築工事",
    "豊中の貸倉庫兼オフィス",
    "三田2丁目AP",
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
2. 構造種別（structureTypes）
3. 用途種別（useTypes）
4. 階数カテゴリ（floorCategories）
5. 延べ面積（totalArea）
6. 面積カテゴリ（areaCategory）
7. 性能表示（performanceLabels）
8. 計算ルート（calcRoutes）
9. 基礎形式（foundationTypes）
10. 設計特記（features）
11. 耐力要素（resistanceElements）
12. 積雪地域（snowRegion）
13. 防火地域（fireZone）
14. 地盤種別（groundCondition）
15. 計算ソフト（software）
16. 検査機関（inspectionAgency）
17. サマリー（summary）

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

def find_structure_docs_folder(access_token, user_email, parent_folder_id):
    """親フォルダ内から「構造設計図書」フォルダを探す"""
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{parent_folder_id}/children"
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        items = response.json().get('value', [])

        for item in items:
            if "folder" in item:
                folder_name = item['name']
                # 「構造設計図書」「構造計算書」などを含むフォルダを探す
                if ('構造設計図書' in folder_name or '構造計算書' in folder_name) and '○' not in folder_name:
                    # さらにサブフォルダがあるか確認
                    sub_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{item['id']}/children"
                    sub_response = requests.get(sub_url, headers=headers, timeout=30)
                    if sub_response.status_code == 200:
                        sub_items = sub_response.json().get('value', [])
                        # サブフォルダ内にも構造設計図書フォルダがあればそちらを返す
                        for sub_item in sub_items:
                            if "folder" in sub_item:
                                sub_name = sub_item['name']
                                if ('構造設計図書' in sub_name or '構造計算書' in sub_name) and '○' not in sub_name:
                                    return sub_item['id'], sub_item['name']

                    # サブフォルダがなければこのフォルダを返す
                    return item['id'], folder_name

        return None, None

    except Exception as e:
        print(f"⚠️ 構造設計図書フォルダ検索エラー: {e}")
        return None, None

def process_single_project_by_file_id(project_info: Dict, access_token: str, user_email: str) -> Tuple[bool, str, float]:
    """
    既存データのfile_idを使用して案件を処理
    Returns: (success: bool, message: str, elapsed_time: float)
    """
    start_time = time.time()

    headers = {"Authorization": f"Bearer {access_token}"}
    project_name = project_info.get('project_name', 'N/A')
    file_id = project_info.get('file_id')
    folder_path = project_info.get('folder_path', '')

    try:
        print(f"\n📂 処理開始: {project_name}")

        # 「構造設計図書」フォルダを探す
        docs_folder_id, docs_folder_name = find_structure_docs_folder(access_token, user_email, file_id)

        if not docs_folder_id:
            print(f"   ⚠️ 構造設計図書フォルダが見つかりません。親フォルダから直接取得します...")
            docs_folder_id = file_id
            docs_folder_name = project_info.get('folder_name', '')
        else:
            print(f"   ✅ 構造設計図書フォルダ見つかりました: {docs_folder_name}")

        # フォルダの詳細情報とwebUrlを取得
        folder_detail_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{docs_folder_id}"
        folder_detail_response = requests.get(folder_detail_url, headers=headers, timeout=30)
        folder_detail_response.raise_for_status()
        folder_detail = folder_detail_response.json()
        folder_web_url = folder_detail.get('webUrl', '')

        # フォルダ内のファイル一覧を取得
        folder_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{docs_folder_id}/children"
        response = requests.get(folder_url, headers=headers, timeout=60)
        response.raise_for_status()
        items = response.json().get('value', [])

        # ファイルを選定
        calc_files, drawing_files, cert_file, review_file = select_project_files(items)

        if not calc_files:
            elapsed = time.time() - start_time
            return False, "構造計算書PDFが見つかりません", elapsed

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

        # フォルダパスからメタデータ抽出
        metadata = extract_project_metadata(folder_path)

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
        date_match = re.match(r'^(\d{4})(\d{2})\d{2}', docs_folder_name)
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
            "file_id": docs_folder_id,
            "extracted_at": firestore.SERVER_TIMESTAMP,
            "created_year_month": created_year_month,
            "project_name": project_name,
            "folder_name": docs_folder_name,
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
    print("🧪 特定案件テスト実行（既存データベース）")
    print("=" * 80)
    print(f"📊 テストコレクション: {TEST_COLLECTION}")
    print("=" * 80)

    overall_start = time.time()

    # Firestoreから既存データを取得
    db = firestore.Client(project=GCP_PROJECT_ID, database="uplan")
    collection_ref = db.collection("Projects_2026_01_07")

    test_projects = []

    print("\n🔍 対象案件を検索中...")
    for keyword in TEST_PROJECT_KEYWORDS:
        # project_nameで部分一致検索（完全な検索はできないので、取得してからフィルタ）
        docs = collection_ref.order_by("extracted_at", direction=firestore.Query.DESCENDING).limit(100).stream()

        for doc in docs:
            data = doc.to_dict()
            project_name = data.get('project_name', '')
            if keyword in project_name:
                test_projects.append({
                    'doc_id': doc.id,
                    'project_name': project_name,
                    'file_id': data.get('file_id'),
                    'folder_path': data.get('folder_path', ''),
                    'folder_name': data.get('folder_name', ''),
                    'client_name': data.get('client_name', 'N/A')
                })
                print(f"   ✅ 見つかりました: {project_name}")
                break

    print(f"\n📂 対象案件数: {len(test_projects)}\n")

    if len(test_projects) == 0:
        print("❌ 対象案件が見つかりませんでした")
        return

    # 認証
    token = get_access_token()
    if not token:
        print("❌ 認証失敗のため終了します")
        return

    results = []

    # 各案件を順次処理
    for i, project_info in enumerate(test_projects, 1):
        print(f"\n[{i}/{len(test_projects)}] {project_info['project_name']}")
        print(f"   取引先: {project_info['client_name']}")
        success, message, elapsed = process_single_project_by_file_id(project_info, token, TARGET_USER_EMAIL)

        results.append({
            "project": project_info['project_name'],
            "success": success,
            "message": message,
            "elapsed": elapsed
        })

        if success:
            print(f"   ✅ {message} (処理時間: {elapsed:.1f}秒)")
        else:
            print(f"   ❌ {message} (処理時間: {elapsed:.1f}秒)")

        if i < len(test_projects):
            time.sleep(2)

    overall_elapsed = time.time() - overall_start

    # 結果サマリー
    print("\n" + "=" * 80)
    print("📊 テスト結果サマリー")
    print("=" * 80)

    success_count = sum(1 for r in results if r["success"])
    total_processing_time = sum(r["elapsed"] for r in results)
    avg_time = total_processing_time / len(results) if results else 0

    print(f"✅ 成功: {success_count}/{len(test_projects)}件")
    print(f"❌ 失敗: {len(test_projects) - success_count}/{len(test_projects)}件")
    print(f"⏱️  総実行時間: {overall_elapsed:.1f}秒 ({overall_elapsed/60:.1f}分)")
    print(f"⏱️  平均処理時間/件: {avg_time:.1f}秒")
    print(f"💾 保存先: Firestore > {TEST_COLLECTION}")
    print("=" * 80)

    # 詳細結果
    print("\n📋 詳細結果:")
    for i, result in enumerate(results, 1):
        status = "✅" if result["success"] else "❌"
        print(f"{i}. {status} {result['project']} - {result['message']} ({result['elapsed']:.1f}秒)")

if __name__ == "__main__":
    main()
