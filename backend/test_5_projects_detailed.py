"""
5物件の詳細抽出テスト
丁寧に時間をかけてテストを実行する
"""

import msal
import requests
import json
import os
import time
import random
from typing import List, Dict, Tuple, Optional
import vertexai
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig
from google.cloud import secretmanager
from google.cloud import firestore
from datetime import datetime, timezone, timedelta
import re

# 日本時間のタイムゾーン
JST = timezone(timedelta(hours=9))

# --- 設定 ---
GCP_PROJECT_ID = "uplan-knowledge-base"
LOCATION = "us-central1"
TARGET_USER_EMAIL = "info@uplan2018.onmicrosoft.com"

# テスト対象の5物件
TEST_PROJECTS = [
    {
        "name": "松下邸",
        "folder_path": "01.木造（在来軸組）/□た行/A00790_多田建築設計事務所/2025001_松下邸/09.成果物/20250911_【補正】松下邸_構造設計図書一式",
        "url": "https://uplan2018-my.sharepoint.com/personal/info_uplan2018_onmicrosoft_com/Documents/001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□た行/A00790_多田建築設計事務所/2025001_松下邸/09.成果物/20250911_【補正】松下邸_構造設計図書一式"
    },
    {
        "name": "フルイチ様オフィス新築工事",
        "folder_path": "01.木造（在来軸組）/□Ａ行/453 Luce建築設計事務所/2025003_フルイチ様オフィス新築工事/09.成果物/20251111_【事前】フルイチ様オフィス新築工事_構造設計図書一式",
        "url": "https://uplan2018-my.sharepoint.com/personal/info_uplan2018_onmicrosoft_com/Documents/001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□Ａ行/453 Luce建築設計事務所/2025003_フルイチ様オフィス新築工事/09.成果物/20251111_【事前】フルイチ様オフィス新築工事_構造設計図書一式"
    },
    {
        "name": "豊中の貸倉庫兼オフィス",
        "folder_path": "01.木造（在来軸組）/□Ａ行/329 PROCESS5 DESIGN/豊中の貸倉庫兼オフィス/09.成果物/20251202_TOYONAKA_BASE_最終構造設計図書一式",
        "url": "https://uplan2018-my.sharepoint.com/personal/info_uplan2018_onmicrosoft_com/Documents/001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□Ａ行/329 PROCESS5 DESIGN/豊中の貸倉庫兼オフィス/09.成果物/20251202_TOYONAKA_BASE_最終構造設計図書一式"
    },
    {
        "name": "（仮称）三田2丁目AP",
        "folder_path": "01.木造（在来軸組）/□あ行/A00698アゼリアホーム/2024009_（仮称）三田2丁目AP／2024010_設計変更/09.成果物/20240912_(仮称)三田2丁目AP_構造計算書類一式",
        "url": "https://uplan2018-my.sharepoint.com/personal/info_uplan2018_onmicrosoft_com/Documents/001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□あ行/A00698アゼリアホーム/2024009_（仮称）三田2丁目AP／2024010_設計変更/09.成果物/20240912_(仮称)三田2丁目AP_構造計算書類一式"
    },
    {
        "name": "（仮称）小さなお葬式 名古屋昭和区ホール",
        "folder_path": "01.木造（在来軸組）/□Ａ行/279 A1・ID設計/2025012_（仮称）小さなお葬式 名古屋昭和区ホール/09.成果物/納品時/20251128_【事前】（仮称）小さなお葬式 名古屋昭和区ホール_構造設計図書一式",
        "url": "https://uplan2018-my.sharepoint.com/personal/info_uplan2018_onmicrosoft_com/Documents/001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□Ａ行/279 A1・ID設計/2025012_（仮称）小さなお葬式 名古屋昭和区ホール/09.成果物/納品時/20251128_【事前】（仮称）小さなお葬式 名古屋昭和区ホール_構造設計図書一式"
    }
]

# レート制限対策設定
INITIAL_RETRY_DELAY = 3.0  # テスト用に少し長めに設定
MAX_RETRY_DELAY = 120.0
MAX_RETRIES = 5
JITTER_RANGE = 1.0

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
        "projectName": None,
        "createdDate": None
    }

    parts = folder_path.split('/')

    # 構造種別とクライアント名の抽出
    for i, part in enumerate(parts):
        if '木造' in part:
            metadata["structureType"] = "木造"
            if i + 2 < len(parts):
                client_folder = parts[i + 2]
                match = re.match(r'^[AT]\d+_?(.+?)(?:（.+?）)?$', client_folder)
                if match:
                    metadata["clientName"] = match.group(1).strip()
                    continue
                match2 = re.match(r'^\d+\s+(.+)$', client_folder)
                if match2:
                    metadata["clientName"] = match2.group(1).strip()
                    continue
        elif 'RC' in part or '鉄筋コンクリート' in part:
            metadata["structureType"] = "RC造"
        elif '鉄骨' in part:
            metadata["structureType"] = "S造"

    # プロジェクト名と作成日の抽出
    for part in parts:
        if part.startswith(('2024', '2025', '2026')):
            match = re.match(r'^(\d{7})_(.+)$', part)
            if match:
                metadata["projectName"] = match.group(2).strip()
                continue

        # 作成日の抽出（YYYYMMDDパターン）
        date_match = re.match(r'^(\d{8})_', part)
        if date_match:
            metadata["createdDate"] = date_match.group(1)

    return metadata

def get_folder_id_from_url(access_token, folder_url):
    """SharePointフォルダURLからフォルダIDを取得"""
    try:
        # URLをデコード
        import urllib.parse
        decoded_url = urllib.parse.unquote(folder_url)

        # パスを抽出
        if "/Documents/" in decoded_url:
            path_part = decoded_url.split("/Documents/")[1]
            # クエリパラメータを除去
            if "?" in path_part:
                path_part = path_part.split("?")[0]

            # パスをエンコード
            encoded_path = urllib.parse.quote(path_part)

            # Graph API エンドポイント
            drive_id_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive"
            headers = {"Authorization": f"Bearer {access_token}"}

            drive_response = requests.get(drive_id_url, headers=headers)
            if drive_response.status_code != 200:
                print(f"❌ ドライブ情報取得エラー: {drive_response.status_code}")
                return None

            drive_id = drive_response.json()["id"]

            # フォルダ情報を取得
            folder_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{encoded_path}"
            folder_response = requests.get(folder_url, headers=headers)

            if folder_response.status_code == 200:
                return folder_response.json()["id"]
            else:
                print(f"❌ フォルダ取得エラー: {folder_response.status_code}")
                return None

    except Exception as e:
        print(f"❌ URL解析エラー: {e}")
        return None

def get_pdf_files_from_folder(access_token, folder_id):
    """フォルダ内のPDFファイル一覧を取得"""
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{folder_id}/children"

        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"❌ ファイル一覧取得エラー: {response.status_code}")
            print(f"   レスポンス: {response.text}")
            return []

        items = response.json().get("value", [])
        pdf_files = [item for item in items if item["name"].lower().endswith(".pdf")]

        return pdf_files

    except Exception as e:
        print(f"❌ ファイル一覧取得エラー: {e}")
        return []

def select_project_files(pdf_files: List[Dict], max_files: int = 5) -> List[Dict]:
    """
    プロジェクトファイルを選択（優先順位付き）
    1. 【補正】がついているファイル（最優先）
    2. 【修正】がついているファイル（次優先）
    3. その他のファイル（作成日時が新しい順）
    """
    if not pdf_files:
        return []

    # 優先度スコアを計算
    def get_priority_score(file_item):
        name = file_item.get("name", "")
        created = file_item.get("createdDateTime", "")

        # 基本スコア（新しいファイルほど高い）
        score = 0
        if created:
            try:
                dt = datetime.fromisoformat(created.replace('Z', '+00:00'))
                score = dt.timestamp()
            except:
                score = 0

        # 【補正】ファイルに最高優先度
        if "【補正】" in name or "補正" in name:
            score += 10000000000
        # 【修正】ファイルに次の優先度
        elif "【修正】" in name or "修正" in name:
            score += 5000000000

        return score

    # スコアでソート
    sorted_files = sorted(pdf_files, key=get_priority_score, reverse=True)

    # 上位max_files件を返す
    return sorted_files[:max_files]

def download_pdf(access_token, file_id):
    """PDFファイルをダウンロード"""
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        download_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{file_id}/content"

        response = requests.get(download_url, headers=headers)
        if response.status_code == 200:
            return response.content
        else:
            print(f"❌ ダウンロードエラー: {response.status_code}")
            return None

    except Exception as e:
        print(f"❌ ダウンロードエラー: {e}")
        return None

def analyze_with_gemini_with_retry(pdf_contents: List[bytes], metadata: Dict) -> Dict:
    """
    Gemini 2.0 FlashでPDFを解析（リトライ機能付き）
    """
    vertexai.init(project=GCP_PROJECT_ID, location=LOCATION)
    model = GenerativeModel("gemini-2.0-flash-exp")

    # プロンプト
    prompt = """
あなたは構造設計の専門家です。提供された構造計算書PDFから、以下の情報を抽出してください。

【抽出項目】
1. 基本情報
   - structure_type: 構造種別（木造/RC造/S造/SRC造など）
   - primary_use: 主要用途（戸建住宅/共同住宅/事務所/店舗など）
   - floors: 階数（地上○階、地下○階の形式）
   - total_floor_area: 延床面積（数値 + 単位）

2. 法的・技術情報
   - performance_requirements: 性能要件（耐震等級、省令準耐火など）
   - structural_calc_route: 構造計算ルート（許容応力度計算/性能表示計算/限界耐力計算など）
   - route_reasoning: ルート選定理由
   - foundation_type: 基礎形式（べた基礎/布基礎/杭基礎など）
   - design_features: 設計上の特徴や工夫
   - lateral_resistance: 耐力要素（耐力壁/ブレース/ラーメンなど）

3. プロジェクト条件
   - regional_conditions: 地域条件（積雪/凍結深度/風速など）
   - ground_condition: 地盤状況（N値、地盤改良の有無など）
   - inspection_agency: 検査機関・確認検査機関

4. その他
   - project_summary: プロジェクト概要（100文字程度）
   - project_name: プロジェクト名称
   - calc_book_date: 計算書日付
   - software: 使用ソフトウェア

【出力形式】
必ずJSON形式で出力してください。情報が見つからない場合はnullとしてください。

{
  "structure_type": "...",
  "primary_use": "...",
  "floors": "...",
  "total_floor_area": "...",
  "performance_requirements": "...",
  "structural_calc_route": "...",
  "route_reasoning": "...",
  "foundation_type": "...",
  "design_features": "...",
  "lateral_resistance": "...",
  "regional_conditions": "...",
  "ground_condition": "...",
  "inspection_agency": "...",
  "project_summary": "...",
  "project_name": "...",
  "calc_book_date": "...",
  "software": "..."
}
"""

    # PDFをPartオブジェクトに変換
    parts = [Part.from_data(pdf_content, mime_type="application/pdf") for pdf_content in pdf_contents]
    parts.insert(0, prompt)

    # リトライロジック
    for attempt in range(MAX_RETRIES):
        try:
            # ランダムな初期遅延（負荷分散）
            if attempt == 0:
                initial_delay = random.uniform(0, 2)
                time.sleep(initial_delay)

            # Gemini API呼び出し
            response = model.generate_content(
                parts,
                generation_config=GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=8192,
                )
            )

            # レスポンステキストを取得
            result_text = response.text.strip()

            # JSONブロックを抽出
            if "```json" in result_text:
                json_start = result_text.find("```json") + 7
                json_end = result_text.find("```", json_start)
                result_text = result_text[json_start:json_end].strip()
            elif "```" in result_text:
                json_start = result_text.find("```") + 3
                json_end = result_text.find("```", json_start)
                result_text = result_text[json_start:json_end].strip()

            # JSONパース
            extracted_data = json.loads(result_text)

            # メタデータから検査機関を補完
            if not extracted_data.get("inspection_agency") and metadata.get("clientName"):
                extracted_data["inspection_agency"] = metadata["clientName"]

            print(f"✅ Gemini解析成功（試行回数: {attempt + 1}）")
            return extracted_data

        except Exception as e:
            error_msg = str(e)
            print(f"⚠️ Gemini API エラー（試行 {attempt + 1}/{MAX_RETRIES}）: {error_msg}")

            # 429エラー（レート制限）の場合
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "quota" in error_msg.lower():
                if attempt < MAX_RETRIES - 1:
                    # 指数バックオフ + ジッター
                    delay = min(INITIAL_RETRY_DELAY * (2 ** attempt), MAX_RETRY_DELAY)
                    jitter = random.uniform(-JITTER_RANGE, JITTER_RANGE)
                    wait_time = delay + jitter
                    print(f"⏳ レート制限により {wait_time:.1f}秒待機します...")
                    time.sleep(wait_time)
                    continue

            # その他のエラーの場合は短い待機
            if attempt < MAX_RETRIES - 1:
                wait_time = 5.0
                print(f"⏳ {wait_time}秒待機して再試行します...")
                time.sleep(wait_time)

    print(f"❌ {MAX_RETRIES}回の試行後も失敗しました")
    return {}

def save_to_firestore(project_data: Dict, collection_name: str):
    """Firestoreにデータを保存"""
    try:
        db = firestore.Client(project=GCP_PROJECT_ID, database="uplan")

        # ドキュメントID: プロジェクト名から生成（特殊文字を除去）
        project_name = project_data.get("project_name", "unknown")
        doc_id = re.sub(r'[^\w\s-]', '', project_name).strip().replace(' ', '_')

        # タイムスタンプを追加（日本時間）
        project_data["extracted_at"] = datetime.now(JST).isoformat()

        # Firestoreに保存
        doc_ref = db.collection(collection_name).document(doc_id)
        doc_ref.set(project_data)

        print(f"✅ Firestoreに保存しました: {collection_name}/{doc_id}")
        return True

    except Exception as e:
        print(f"❌ Firestore保存エラー: {e}")
        return False

def process_single_project(project_info: Dict, access_token: str, collection_name: str) -> Dict:
    """1つのプロジェクトを処理"""
    project_name = project_info["name"]
    folder_url = project_info["url"]
    folder_path = project_info["folder_path"]

    print(f"\n{'='*80}")
    print(f"📁 処理開始: {project_name}")
    print(f"{'='*80}")

    start_time = time.time()
    result = {
        "project_name": project_name,
        "success": False,
        "error": None,
        "processing_time": 0,
        "extracted_data": {}
    }

    try:
        # 1. メタデータ抽出
        print(f"📊 メタデータ抽出中...")
        metadata = extract_project_metadata(folder_path)
        print(f"   構造種別: {metadata.get('structureType')}")
        print(f"   クライアント: {metadata.get('clientName')}")
        print(f"   プロジェクト名: {metadata.get('projectName')}")
        print(f"   作成日: {metadata.get('createdDate')}")

        # 2. フォルダIDを取得
        print(f"\n🔍 フォルダID取得中...")
        folder_id = get_folder_id_from_url(access_token, folder_url)
        if not folder_id:
            raise Exception("フォルダIDの取得に失敗しました")
        print(f"   フォルダID: {folder_id}")

        # 3. PDFファイル一覧を取得
        print(f"\n📄 PDFファイル検索中...")
        pdf_files = get_pdf_files_from_folder(access_token, folder_id)
        print(f"   見つかったPDFファイル: {len(pdf_files)}件")

        if not pdf_files:
            raise Exception("PDFファイルが見つかりませんでした")

        # 4. ファイルを選択
        print(f"\n🎯 ファイル選択中...")
        selected_files = select_project_files(pdf_files, max_files=5)
        print(f"   選択されたファイル: {len(selected_files)}件")
        for i, file in enumerate(selected_files):
            print(f"   {i+1}. {file['name']}")

        # 5. PDFダウンロード
        print(f"\n⬇️ PDFダウンロード中...")
        pdf_contents = []
        for i, file in enumerate(selected_files):
            print(f"   {i+1}/{len(selected_files)}: {file['name']}")
            content = download_pdf(access_token, file["id"])
            if content:
                pdf_contents.append(content)
                print(f"      ✅ ダウンロード完了 ({len(content) / 1024 / 1024:.2f} MB)")
            else:
                print(f"      ⚠️ ダウンロード失敗")

        if not pdf_contents:
            raise Exception("PDFのダウンロードに失敗しました")

        # 6. Gemini解析
        print(f"\n🤖 Gemini AI解析中...")
        print(f"   解析するPDFファイル数: {len(pdf_contents)}")
        extracted_data = analyze_with_gemini_with_retry(pdf_contents, metadata)

        if not extracted_data:
            raise Exception("Gemini解析に失敗しました")

        # 7. データ整形
        project_data = {
            # メタデータ
            "folder_path": folder_path,
            "folder_url": folder_url,
            "folder_id": folder_id,
            "file_count": len(selected_files),
            "client_name": metadata.get("clientName"),
            "created_date": metadata.get("createdDate"),

            # 抽出データ
            **extracted_data
        }

        # 8. Firestoreに保存
        print(f"\n💾 Firestoreに保存中...")
        save_success = save_to_firestore(project_data, collection_name)

        if not save_success:
            raise Exception("Firestore保存に失敗しました")

        # 成功
        result["success"] = True
        result["extracted_data"] = project_data

        elapsed_time = time.time() - start_time
        result["processing_time"] = elapsed_time

        print(f"\n✅ 処理完了: {project_name} ({elapsed_time:.1f}秒)")

    except Exception as e:
        result["error"] = str(e)
        elapsed_time = time.time() - start_time
        result["processing_time"] = elapsed_time
        print(f"\n❌ 処理失敗: {project_name} - {e} ({elapsed_time:.1f}秒)")

    return result

def main():
    """メイン処理"""
    print("="*80)
    print("5物件 詳細抽出テスト")
    print("="*80)

    # コレクション名（テスト用）
    collection_name = f"Test_5Projects_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f"\n📦 保存先コレクション: {collection_name}")

    # アクセストークン取得
    print(f"\n🔐 認証中...")
    access_token = get_access_token()
    if not access_token:
        print("❌ 認証に失敗しました")
        return
    print("✅ 認証成功")

    # 各プロジェクトを処理
    results = []
    total_start_time = time.time()

    for i, project_info in enumerate(TEST_PROJECTS):
        print(f"\n\n{'#'*80}")
        print(f"プロジェクト {i+1}/{len(TEST_PROJECTS)}")
        print(f"{'#'*80}")

        result = process_single_project(project_info, access_token, collection_name)
        results.append(result)

        # プロジェクト間の待機（レート制限対策）
        if i < len(TEST_PROJECTS) - 1:
            wait_time = 10.0
            print(f"\n⏳ 次のプロジェクトまで{wait_time}秒待機...")
            time.sleep(wait_time)

    # 結果サマリー
    total_elapsed_time = time.time() - total_start_time

    print(f"\n\n{'='*80}")
    print("テスト結果サマリー")
    print(f"{'='*80}")
    print(f"総処理時間: {total_elapsed_time:.1f}秒")
    print(f"処理件数: {len(results)}件")

    success_count = sum(1 for r in results if r["success"])
    print(f"成功: {success_count}件")
    print(f"失敗: {len(results) - success_count}件")

    print(f"\n{'='*80}")
    print("詳細結果")
    print(f"{'='*80}")

    for i, result in enumerate(results):
        print(f"\n【{i+1}】 {result['project_name']}")
        print(f"   ステータス: {'✅ 成功' if result['success'] else '❌ 失敗'}")
        print(f"   処理時間: {result['processing_time']:.1f}秒")

        if result['success']:
            data = result['extracted_data']
            print(f"   構造種別: {data.get('structure_type', 'N/A')}")
            print(f"   主要用途: {data.get('primary_use', 'N/A')}")
            print(f"   階数: {data.get('floors', 'N/A')}")
            print(f"   延床面積: {data.get('total_floor_area', 'N/A')}")
            print(f"   計算ルート: {data.get('structural_calc_route', 'N/A')}")
            print(f"   基礎形式: {data.get('foundation_type', 'N/A')}")
        else:
            print(f"   エラー: {result['error']}")

    print(f"\n{'='*80}")
    print(f"✅ テスト完了")
    print(f"{'='*80}")

if __name__ == "__main__":
    main()
