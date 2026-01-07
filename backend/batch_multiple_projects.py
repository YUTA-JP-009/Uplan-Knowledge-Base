"""
複数の個別案件を並列処理で抽出するスクリプト
新しいFirestoreコレクション「Parallel_Test_2026_01_06」に保存
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from batch_processor_v3 import *
from concurrent.futures import ProcessPoolExecutor, as_completed
import time

# 新しいコレクション名
NEW_COLLECTION_NAME = "Parallel_Test_2026_01_06"

# 処理対象の案件リスト（親フォルダまでのパスを指定 - スクリプトが構造設計図書フォルダを自動探索）
# folder_urlフィールドを追加するため全5件を再実行
TARGET_PROJECTS = [
    "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□た行/A00790_多田建築設計事務所/2025001_松下邸",
    "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□Ａ行/453 Luce建築設計事務所/2025003_フルイチ様オフィス新築工事",
    "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□Ａ行/329 PROCESS5 DESIGN/豊中の貸倉庫兼オフィス",
    "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□あ行/A00698アゼリアホーム/2024009_（仮称）三田2丁目AP／2024010_設計変更",
    "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□Ａ行/279 A1・ID設計/2025012_（仮称）小さなお葬式 名古屋昭和区ホール"
]

def process_single_project_path(project_path, access_token, user_email, collection_name):
    """
    個別の案件パスを処理

    Args:
        project_path: 案件フォルダのパス
        access_token: アクセストークン
        user_email: ユーザーメール
        collection_name: Firestoreコレクション名

    Returns:
        (success, project_path, message)
    """
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        print(f"\n📂 処理開始: {project_path}")

        # フォルダの存在確認とID取得
        folder_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/root:/{project_path}"
        response = requests.get(folder_url, headers=headers, timeout=30)

        if response.status_code != 200:
            return False, project_path, f"フォルダが見つかりません (Status: {response.status_code})"

        parent_folder = response.json()
        parent_folder_id = parent_folder.get('id')

        # 構造設計図書フォルダを探索
        children_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{parent_folder_id}/children"
        children_response = requests.get(children_url, headers=headers, timeout=30)
        children_response.raise_for_status()
        children = children_response.json().get('value', [])

        # 構造設計図書フォルダを検索
        target_folder = None
        for child in children:
            if 'folder' in child:
                child_name = child.get('name', '')
                if '構造設計図書' in child_name or '構造計算書' in child_name:
                    if '○' not in child_name:  # ダミーフォルダ除外
                        target_folder = child
                        break

        # 構造設計図書フォルダが見つからない場合、サブフォルダ（09.成果物など）も探索
        if not target_folder:
            for child in children:
                if 'folder' in child and ('成果物' in child.get('name', '') or '納品' in child.get('name', '')):
                    sub_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{child['id']}/children"
                    sub_response = requests.get(sub_url, headers=headers, timeout=30)
                    if sub_response.status_code == 200:
                        sub_children = sub_response.json().get('value', [])
                        for sub_child in sub_children:
                            if 'folder' in sub_child:
                                sub_name = sub_child.get('name', '')
                                if ('構造設計図書' in sub_name or '構造計算書' in sub_name) and '○' not in sub_name:
                                    target_folder = sub_child
                                    break
                                # 納品時などのさらにサブフォルダを探索
                                if '納品' in sub_name:
                                    subsub_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{sub_child['id']}/children"
                                    subsub_response = requests.get(subsub_url, headers=headers, timeout=30)
                                    if subsub_response.status_code == 200:
                                        subsub_children = subsub_response.json().get('value', [])
                                        for subsub_child in subsub_children:
                                            if 'folder' in subsub_child:
                                                subsub_name = subsub_child.get('name', '')
                                                if ('構造設計図書' in subsub_name or '構造計算書' in subsub_name) and '○' not in subsub_name:
                                                    target_folder = subsub_child
                                                    break
                        if target_folder:
                            break

        if not target_folder:
            return False, project_path, "構造設計図書フォルダが見つかりません"

        folder_id = target_folder.get('id')
        folder_name = target_folder.get('name', '')
        folder_web_url = target_folder.get('webUrl', '')

        # フォルダ名から作成年月を抽出（例：20240912 → 2024年9月）
        import re
        created_year_month = None
        date_match = re.match(r'^(\d{4})(\d{2})\d{2}', folder_name)
        if date_match:
            year = date_match.group(1)
            month = date_match.group(2).lstrip('0')  # 先頭の0を削除
            created_year_month = f"{year}年{month}月"

        # folder_pathから物件名を抽出
        # 例：001_Ｕ'plan_全社/.../豊中の貸倉庫兼オフィス → 豊中の貸倉庫兼オフィス
        project_name = None
        path_parts = project_path.split('/')
        # 最後の部分が物件名（取引先フォルダの次）
        if len(path_parts) >= 5:
            # パターン1: 取引先配下に直接物件名がある場合
            # 例: .../329 PROCESS5 DESIGN/豊中の貸倉庫兼オフィス
            last_part = path_parts[-1]
            # 数字で始まる場合（2024009_など）はスキップして次を使う
            if not re.match(r'^\d{4,7}_', last_part):
                project_name = last_part
            elif len(path_parts) >= 6:
                # 数字フォルダの場合、その前の部分から抽出
                # 例: .../2024009_（仮称）三田2丁目AP／2024010_設計変更
                number_folder = last_part
                # "2024009_物件名／2024010_変更" の形式から物件名を抽出
                name_match = re.match(r'^\d{4,7}_(.+?)(?:／|$)', number_folder)
                if name_match:
                    project_name = name_match.group(1)

        print(f"   📁 発見: {folder_name}")
        if created_year_month:
            print(f"   📅 作成年月: {created_year_month}")
        if project_name:
            print(f"   🏢 物件名: {project_name}")

        # フォルダ内のファイル一覧を取得
        files_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{folder_id}/children"
        files_response = requests.get(files_url, headers=headers, timeout=30)
        files_response.raise_for_status()
        items = files_response.json().get('value', [])

        # ファイルを選定
        calc_files, drawing_files, cert_file, review_file = select_project_files(items)

        if not calc_files:
            return False, project_path, "構造計算書PDFが見つかりません"

        print(f"   📄 構造計算書: {len(calc_files)}ファイル検出")

        # PDFをダウンロード（batch_processor_v3.pyの形式に合わせる）
        file_data_list = []
        file_name_hints = []

        for pdf_file in calc_files[:10]:  # 最大10ファイル
            download_url = pdf_file.get('@microsoft.graph.downloadUrl')
            if download_url:
                pdf_response = requests.get(download_url, timeout=120)
                if pdf_response.status_code == 200:
                    # (label, data)のタプル形式で追加
                    file_data_list.append((pdf_file['name'], pdf_response.content))
                    file_name_hints.append(pdf_file['name'])

        if not file_data_list:
            return False, project_path, "PDFダウンロード失敗"

        print(f"   ⬇️  ダウンロード完了: {len(file_data_list)}ファイル")

        # Gemini APIで解析
        print(f"   🤖 AI解析開始...")
        analysis_result = analyze_with_gemini(file_data_list, file_name_hints)

        # メモリ解放
        del file_data_list
        import gc
        gc.collect()

        if not analysis_result:
            return False, project_path, "AI解析失敗"

        print(f"   ✅ AI解析完了")

        # analysis_resultがリストの場合は最初の要素を取得
        if isinstance(analysis_result, list):
            if len(analysis_result) > 0:
                analysis_result = analysis_result[0]
            else:
                return False, project_path, "AI解析結果が空リスト"

        # フォルダパスからメタデータ抽出
        metadata = extract_project_metadata(project_path)

        # Firestoreに保存
        db = firestore.Client(project=GCP_PROJECT_ID, database="uplan")

        # ドキュメントIDを生成
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
            "created_year_month": created_year_month,  # 構造計算書の作成年月
            "project_name": project_name,  # 物件名
            "folder_name": folder_name,
            "folder_path": project_path,
            "folder_url": folder_web_url,  # フォルダのURL
            "file_count": {
                "calc": len(calc_files),
                "drawing": len(drawing_files),
                "cert": 1 if cert_file else 0,
                "review": 1 if review_file else 0
            }
        }

        # Firestoreに保存
        collection_ref = db.collection(collection_name)
        collection_ref.document(doc_id).set(save_data)

        print(f"   💾 Firestore保存完了: {collection_name}/{doc_id}")

        return True, project_path, f"成功 ({len(calc_files)}ファイル解析)"

    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"   ❌ エラー: {str(e)}")
        print(error_detail)
        return False, project_path, f"エラー: {str(e)[:100]}"

def main():
    print("=" * 80)
    print("🚀 複数案件の並列処理抽出")
    print("=" * 80)
    print(f"📊 処理対象: {len(TARGET_PROJECTS)}件")
    print(f"💾 保存先コレクション: {NEW_COLLECTION_NAME}")
    print("=" * 80)

    # 認証
    token = get_access_token()
    if not token:
        print("❌ 認証失敗")
        return

    print("✅ 認証成功\n")

    # シーケンシャル処理（レート制限対策）
    success_count = 0
    error_count = 0

    for i, path in enumerate(TARGET_PROJECTS):
        try:
            print(f"\n[{i+1}/{len(TARGET_PROJECTS)}] 処理中...")
            success, project_path, message = process_single_project_path(path, token, TARGET_USER_EMAIL, NEW_COLLECTION_NAME)

            if success:
                success_count += 1
                print(f"\n✅ [{i+1}/{len(TARGET_PROJECTS)}] 成功")
                print(f"   パス: {project_path}")
                print(f"   結果: {message}")
            else:
                error_count += 1
                print(f"\n❌ [{i+1}/{len(TARGET_PROJECTS)}] 失敗")
                print(f"   パス: {project_path}")
                print(f"   理由: {message}")

            # レート制限対策: 次の処理まで30秒待機
            if i < len(TARGET_PROJECTS) - 1:
                print(f"\n⏳ レート制限対策: 30秒待機中...")
                time.sleep(30)

        except Exception as e:
            error_count += 1
            print(f"\n❌ [{i+1}/{len(TARGET_PROJECTS)}] 例外発生")
            print(f"   パス: {path}")
            print(f"   エラー: {str(e)[:100]}")

    print("\n" + "=" * 80)
    print("📊 処理完了サマリー")
    print("=" * 80)
    print(f"✅ 成功: {success_count}件")
    print(f"❌ 失敗: {error_count}件")
    print(f"📝 合計: {len(TARGET_PROJECTS)}件")
    print(f"💾 保存先: Firestore > uplan > {NEW_COLLECTION_NAME}")
    print("=" * 80)

if __name__ == "__main__":
    main()
