import msal
import requests
import json
import os
import vertexai
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig
from google.cloud import secretmanager
from google.cloud import firestore

# --- 設定 ---
GCP_PROJECT_ID = "uplan-knowledge-base"
LOCATION = "us-central1"

# 探索ルート (ここから下の「納品」フォルダを探します)
TARGET_ROOT_PATH = "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□Ａ行/279 A1・ID設計/2025012_（仮称）小さなお葬式 名古屋昭和区ホール"
TARGET_USER_EMAIL = "info@uplan2018.onmicrosoft.com"
# ---------------------------------------------------------

# 1. 認証周り
def get_secret(secret_id):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{GCP_PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")

def get_access_token():
    try:
        client_id = get_secret("MS_CLIENT_ID")
        tenant_id = get_secret("MS_TENANT_ID")
        client_secret = get_secret("MS_CLIENT_SECRET")

        authority = f"https://login.microsoftonline.com/{tenant_id}"
        app = msal.ConfidentialClientApplication(client_id, authority=authority, client_credential=client_secret)
        result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        return result.get("access_token")
    except Exception as e:
        print(f"認証エラー: {e}")
        return None

# 1-2. システム設定管理（デルタクエリ用スタンプ）
def get_system_config():
    """
    Firestoreからシステム設定（前回の同期状態）を取得
    Returns:
        dict: {"deltaLink": str, "last_run_at": timestamp} or None
    """
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
    """
    Firestoreにシステム設定（同期状態）を保存
    Args:
        delta_link (str): 次回の差分取得に使用するURL
    """
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
    フォルダパスから作成日、取引先名、物件名を抽出
    例: "□さ行/T125 三栄建築設計（計算書・構造図ダブルチェック必要）/2025004_蕨市錦町002②1号棟/09.成果物/20250312_蕨市錦町002②1号棟_【補正】 構造設計図書"
    -> 作成日: 2025-03-12, 取引先: 三栄建築設計, 物件: 蕨市錦町002②1号棟
    """
    import re
    from datetime import datetime

    metadata = {
        "submissionDate": None,      # 提出日（YYYY-MM-DD形式）
        "submissionYear": None,       # 提出年
        "submissionMonth": None,      # 提出月
        "clientName": None,           # 取引先名
        "projectName": None           # 物件名
    }

    # パスを '/' で分割
    parts = folder_path.split('/')

    # 1. 取引先名の抽出
    # 基本構造: 木造（在来軸組）> □あ行 > 取引先名
    # 木造フォルダを起点に3階層目が取引先名
    for i, part in enumerate(parts):
        # 木造フォルダを見つける
        if '木造' in part:
            # 木造フォルダの2つ後（木造 > □あ行 > 取引先名）
            if i + 2 < len(parts):
                client_folder = parts[i + 2]

                # 取引先名から不要な部分を除去
                # パターン1: "A数字_取引先名" または "A数字取引先名"（アンダーバーあり・なし対応）
                match = re.match(r'^[AT]\d+_?(.+?)(?:（.+?）)?$', client_folder)
                if match:
                    metadata["clientName"] = match.group(1).strip()
                    break

                # パターン2: "T数字 取引先名" または "数字 取引先名"（スペース区切り）
                match = re.match(r'^[T]?\d+\s+(.+?)(?:（.+?）)?$', client_folder)
                if match:
                    metadata["clientName"] = match.group(1).strip()
                    break

                # パターン3: 数字が含まれない場合はそのまま取引先名として扱う
                if not re.match(r'^[AT]?\d+', client_folder):
                    metadata["clientName"] = client_folder.strip()
                    break
            break

    # 2. 物件名の抽出
    # 優先順位:
    # (1) "数字_物件名" のパターン（例: "2025004_蕨市錦町002②1号棟"）
    # (2) 取引先フォルダの次のフォルダ（例: "329 PROCESS5 DESIGN/豊中の貸倉庫兼オフィス"）

    # まず (1) のパターンをチェック
    for part in parts:
        # 7桁以上の数字で始まるものを物件コードとする（ただし8桁の場合は日付の可能性があるので除外）
        match = re.match(r'^(\d{7,})_(.+)$', part)
        if match:
            code = match.group(1)
            # 8桁かつ日付として妥当な場合はスキップ（YYYYMMDDフォーマット）
            if len(code) == 8:
                try:
                    year = int(code[:4])
                    month = int(code[4:6])
                    day = int(code[6:8])
                    datetime(year, month, day)  # 日付として妥当かチェック
                    continue  # 日付フォルダなのでスキップ
                except (ValueError, OverflowError):
                    pass  # 日付として無効なので物件コードとして扱う

            metadata["projectName"] = match.group(2).strip()
            break

    # (1) で見つからなかった場合、(2) 取引先フォルダの次を探す
    if not metadata["projectName"]:
        client_found = False
        for i, part in enumerate(parts):
            # 取引先フォルダを見つけたら
            if metadata["clientName"] and (metadata["clientName"] in part):
                # 次のフォルダが物件名（ただし「09.成果物」「08.納品前報告」などは除外）
                if i + 1 < len(parts):
                    next_part = parts[i + 1]
                    if not re.match(r'^\d{2}\.', next_part):  # "09.成果物" のような形式を除外
                        metadata["projectName"] = next_part.strip()
                        break

    # 3. 作成日の抽出（例: "20250312_蕨市錦町002②1号棟_【補正】 構造設計図書"）
    for part in parts:
        # "YYYYMMDD_" で始まるパターン
        match = re.match(r'^(\d{4})(\d{2})(\d{2})_', part)
        if match:
            year, month, day = match.groups()
            try:
                # 日付の妥当性チェック
                date_obj = datetime(int(year), int(month), int(day))
                metadata["submissionDate"] = f"{year}-{month}-{day}"
                metadata["submissionYear"] = int(year)
                metadata["submissionMonth"] = int(month)
            except ValueError:
                # 無効な日付の場合はスキップ
                pass
            break

    return metadata

# 3. ファイル選定ロジック
def select_project_files(file_list):
    """
    フォルダ内から「構造計算書（全て）」「構造図面（全て）」「安全証明書」と「指摘回答書（最新版）」を選ぶ
    """
    candidates_calc = []     # 構造計算書用
    candidates_drawing = []  # 構造図面用
    candidates_review = []   # 指摘回答書用
    candidates_cert = []     # 安全証明書用

    for file in file_list:
        if "folder" in file: continue
        name = file['name']
        if not name.lower().endswith(".pdf"): continue

        # A. 構造計算書を探す（STR計算書、個別計算書も含む）
        if "構造計算書" in name or "STR計算書" in name or "個別計算書" in name:
            score = 0
            if "【補正】" in name: score += 100
            elif "【修正】" in name: score += 50
            # 全体版を優先（南棟・北棟などの分割版より優先）
            if "全体" in name: score += 10
            candidates_calc.append({
                "file": file, "score": score, "updated": file['lastModifiedDateTime']
            })

        # B. 構造図面を探す（構造図、軸組図、伏図、断面図など）
        if any(keyword in name for keyword in ["構造図", "軸組図", "伏図", "断面図", "矩計図"]):
            score = 0
            if "【補正】" in name: score += 100
            elif "【修正】" in name: score += 50
            # 全体版を優先
            if "全体" in name: score += 10
            candidates_drawing.append({
                "file": file, "score": score, "updated": file['lastModifiedDateTime']
            })

        # C. 安全証明書を探す
        if "安全証明書" in name:
            score = 0
            if "【補正】" in name: score += 100
            elif "【修正】" in name: score += 50
            candidates_cert.append({
                "file": file, "score": score, "updated": file['lastModifiedDateTime']
            })

        # D. 指摘回答書・質疑回答書を探す
        if "指摘回答書" in name or "指摘事項回答" in name or "質疑回答書" in name or "質疑応答書" in name:
            score = 0
            candidates_review.append({
                "file": file, "score": score, "updated": file['lastModifiedDateTime']
            })

    # 選定処理
    all_calc_files = []
    all_drawing_files = []
    best_cert = None
    best_review = None

    if candidates_calc:
        # 全てのSTR計算書をスコア高い順 -> 日付新しい順でソート
        sorted_calc = sorted(candidates_calc, key=lambda x: (x['score'], x['updated']), reverse=True)
        all_calc_files = [c['file'] for c in sorted_calc]

    if candidates_drawing:
        # 全ての構造図面をスコア高い順 -> 日付新しい順でソート
        sorted_drawing = sorted(candidates_drawing, key=lambda x: (x['score'], x['updated']), reverse=True)
        all_drawing_files = [c['file'] for c in sorted_drawing]

    if candidates_cert:
        # 日付新しい順で最新版を選択
        best_cert = sorted(candidates_cert, key=lambda x: (x['score'], x['updated']), reverse=True)[0]['file']

    if candidates_review:
        # 日付新しい順
        best_review = sorted(candidates_review, key=lambda x: x['updated'], reverse=True)[0]['file']

    return all_calc_files, all_drawing_files, best_cert, best_review

# 3-2. デルタクエリによる差分取得
def fetch_drive_changes(access_token, user_email, delta_link=None):
    """
    Microsoft Graph APIのデルタクエリを使用して、前回からの変更を取得
    Args:
        access_token (str): アクセストークン
        user_email (str): ユーザーメールアドレス
        delta_link (str): 前回の同期で取得したデルタリンク（初回はNone）
    Returns:
        tuple: (changed_items, new_delta_link)
            changed_items: 変更されたファイル・フォルダのリスト
            new_delta_link: 次回使用するデルタリンク
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    changed_items = []

    # 初回実行時はルートフォルダに対してdeltaクエリを実行
    if delta_link is None:
        # TARGET_ROOT_PATHに対してdeltaクエリを実行
        url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/root:/{TARGET_ROOT_PATH}:/delta"
        print(f"📍 初回デルタクエリ実行: {TARGET_ROOT_PATH}")
    else:
        # 前回のデルタリンクを使用
        url = delta_link
        print(f"📍 差分取得モード: 前回からの変更のみを取得")

    try:
        while url:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()

            # 変更されたアイテムを追加
            items = data.get('value', [])
            for item in items:
                # 削除されたファイルはスキップ
                if 'deleted' in item:
                    continue

                # PDFファイルのみを対象
                if 'file' in item and item.get('name', '').lower().endswith('.pdf'):
                    changed_items.append(item)

                # フォルダも保持（パス構築に必要）
                if 'folder' in item:
                    changed_items.append(item)

            # 次のページまたはデルタリンクを取得
            url = data.get('@odata.nextLink')  # ページネーション
            if not url:
                # 最終的なデルタリンクを取得
                new_delta_link = data.get('@odata.deltaLink')
                break

        print(f"✅ デルタクエリ完了: {len(changed_items)}件の変更を検出")
        return changed_items, new_delta_link

    except Exception as e:
        print(f"❌ デルタクエリエラー: {e}")
        return [], None

# 3-3. 差分モードで変更されたフォルダを処理
def process_changed_folders(access_token, user_email, changed_items):
    """
    デルタクエリで検出された変更を処理
    - 新規追加された構造設計図書フォルダ
    - PDFが追加された構造設計図書フォルダ
    を検出して処理する
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    processed_folders = set()  # 重複処理を防ぐ

    # 変更されたPDFファイルの親フォルダを特定
    folders_with_changes = {}

    for item in changed_items:
        if 'file' in item and item.get('name', '').lower().endswith('.pdf'):
            # PDFファイルの親フォルダIDを取得
            parent_ref = item.get('parentReference', {})
            parent_id = parent_ref.get('id')
            parent_path = parent_ref.get('path', '')

            if parent_id:
                if parent_id not in folders_with_changes:
                    folders_with_changes[parent_id] = {
                        'id': parent_id,
                        'path': parent_path,
                        'pdf_files': []
                    }
                folders_with_changes[parent_id]['pdf_files'].append(item['name'])

        # 新規追加されたフォルダ（構造設計図書フォルダの可能性）
        if 'folder' in item:
            folder_name = item.get('name', '')
            folder_id = item.get('id')
            # 構造設計図書フォルダか確認
            if ('構造設計図書' in folder_name or '構造計算書' in folder_name) and '○' not in folder_name:
                if folder_id not in folders_with_changes:
                    parent_ref = item.get('parentReference', {})
                    folders_with_changes[folder_id] = {
                        'id': folder_id,
                        'name': folder_name,
                        'path': parent_ref.get('path', ''),
                        'pdf_files': [],
                        'is_new_folder': True
                    }

    print(f"\n📁 変更があったフォルダ: {len(folders_with_changes)}件")

    # 各フォルダを処理
    for folder_id, folder_info in folders_with_changes.items():
        if folder_id in processed_folders:
            continue

        print(f"\n🔍 フォルダを処理中: {folder_info.get('name', folder_id)}")
        if folder_info.get('pdf_files'):
            print(f"   追加されたPDF: {', '.join(folder_info['pdf_files'][:3])}{'...' if len(folder_info['pdf_files']) > 3 else ''}")

        try:
            # フォルダ内の全ファイルを取得
            folder_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{folder_id}/children"
            response = requests.get(folder_url, headers=headers)
            response.raise_for_status()
            folder_items = response.json().get('value', [])

            # フォルダ情報も取得
            folder_detail_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{folder_id}"
            folder_response = requests.get(folder_detail_url, headers=headers)
            folder_detail = folder_response.json() if folder_response.status_code == 200 else {}

            # 構造計算書・図面・証明書を選定
            all_calc_files, all_drawing_files, target_cert, target_review = select_project_files(folder_items)

            if all_calc_files:
                # フォルダパスを構築
                parent_ref = folder_detail.get('parentReference', {})
                folder_path = parent_ref.get('path', '').replace('/drive/root:', '')
                folder_name = folder_detail.get('name', '')
                full_path = f"{folder_path}/{folder_name}".lstrip('/')

                print(f"   ✅ 構造計算書を検出: {len(all_calc_files)}ファイル")

                # フォルダ情報を構築
                project_folder_info = {
                    "id": folder_id,
                    "name": folder_name,
                    "webUrl": folder_detail.get('webUrl', ''),
                    "fullPath": full_path,
                    "allFiles": folder_items
                }

                # 既存の処理関数を呼び出し
                process_project_files(access_token, user_email, all_calc_files, all_drawing_files,
                                     target_cert, target_review, project_folder_info)
                processed_folders.add(folder_id)
            else:
                print(f"   ⚠️ 構造計算書PDFが見つかりませんでした")

        except Exception as e:
            print(f"   ❌ フォルダ処理エラー: {e}")
            continue

    print(f"\n✅ 差分モードで {len(processed_folders)}件のフォルダを処理しました")

# 4. フォルダ探索
def process_folder_recursive(access_token, folder_url, user_email, current_path=""):
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(folder_url, headers=headers)
        response.raise_for_status()
        items = response.json().get('value', [])

        for item in items:
            if "folder" in item:
                folder_name = item['name']
                # パス構築（現在のパスに追加）
                full_path = f"{current_path}/{folder_name}" if current_path else folder_name
                child_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{item['id']}/children"

                # 納品フォルダ判定
                if "納品" in folder_name or "成果物" in folder_name:
                    print(f"\n🎯 ターゲットフォルダ発見: {folder_name}")
                    # 中身を取得
                    res_child = requests.get(child_url, headers=headers)
                    child_items = res_child.json().get('value', [])

                    # デバッグ: フォルダ内の全アイテムを表示
                    print(f"   📋 フォルダ内のアイテム数: {len(child_items)}")
                    for child_item in child_items:
                        item_type = "📁" if "folder" in child_item else "📄"
                        print(f"   {item_type} {child_item['name']}")

                    # まず構造設計図書フォルダを探す（複数ある場合は優先順位で選択）
                    # ダミーフォルダ（○で伏せ字になっているもの）は除外
                    import re
                    kouzo_sekkei_candidates = []
                    for child_item in child_items:
                        name = child_item['name']
                        # ダミーフォルダを除外（○が含まれるフォルダ）
                        if '○' in name:
                            continue
                        if "folder" in child_item and ("構造設計図書" in name or "構造計算書" in name):
                            kouzo_sekkei_candidates.append(child_item)
                            print(f"   📁 構造設計図書フォルダ候補: {name}")

                    # サブフォルダ（納品時など）も探索
                    for child_item in child_items:
                        if "folder" in child_item:
                            sub_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{child_item['id']}/children"
                            res_sub = requests.get(sub_url, headers=headers)
                            sub_items = res_sub.json().get('value', [])
                            for sub_item in sub_items:
                                sub_name = sub_item['name']
                                # ダミーフォルダを除外
                                if '○' in sub_name:
                                    continue
                                if "folder" in sub_item and ("構造設計図書" in sub_name or "構造計算書" in sub_name):
                                    kouzo_sekkei_candidates.append(sub_item)
                                    print(f"   📁 構造設計図書フォルダ候補 (サブフォルダ内): {child_item['name']}/{sub_name}")

                    # 優先順位で選定（日付新しい順 > 最終 > 補正 > 修正 > 事前）
                    kouzo_sekkei_folder = None
                    if kouzo_sekkei_candidates:
                        # スコアリング
                        import re
                        scored_folders = []
                        for folder in kouzo_sekkei_candidates:
                            score = 0
                            name = folder['name']

                            # 日付を抽出（YYYYMMDDフォーマット）
                            date_match = re.match(r'^(\d{8})', name)
                            date_value = int(date_match.group(1)) if date_match else 0

                            # 状態によるスコア
                            if "最終" in name: score += 200
                            elif "【補正】" in name or "補正" in name: score += 100
                            elif "【修正】" in name or "修正" in name: score += 50
                            elif "【事前】" in name or "事前" in name: score += 10

                            scored_folders.append({"folder": folder, "score": score, "name": name, "date": date_value})

                        # 日付が新しい順、同じなら状態スコアが高い順
                        kouzo_sekkei_folder = sorted(scored_folders, key=lambda x: (x['date'], x['score']), reverse=True)[0]['folder']
                        print(f"   ✅ 選定された構造設計図書フォルダ: {kouzo_sekkei_folder['name']}")

                    # 構造設計図書フォルダが見つかった場合、その中のファイルを取得
                    if kouzo_sekkei_folder:
                        kouzo_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{kouzo_sekkei_folder['id']}/children"
                        res_kouzo = requests.get(kouzo_url, headers=headers)
                        kouzo_items = res_kouzo.json().get('value', [])
                        all_calc_files, all_drawing_files, target_cert, target_review = select_project_files(kouzo_items)

                        if all_calc_files:
                            # 構造設計図書フォルダの完全なパスを構築
                            kouzo_full_path = f"{full_path}/{kouzo_sekkei_folder['name']}"

                            # 構造設計図書フォルダの情報を渡す（全ファイルリストも追加）
                            project_folder_info = {
                                "id": kouzo_sekkei_folder['id'],
                                "name": kouzo_sekkei_folder['name'],
                                "webUrl": kouzo_sekkei_folder.get('webUrl', ''),
                                "fullPath": kouzo_full_path,
                                "allFiles": kouzo_items  # 全ファイル情報を追加
                            }
                            process_project_files(access_token, user_email, all_calc_files, all_drawing_files, target_cert, target_review, project_folder_info)
                        else:
                            print("   ⚠️ 構造設計図書フォルダ内に構造計算書PDFが見つかりませんでした")
                    else:
                        # 構造設計図書フォルダがない場合は、成果物フォルダ直下から探す
                        all_calc_files, all_drawing_files, target_cert, target_review = select_project_files(child_items)
                        if all_calc_files:
                            # 成果物フォルダの情報を渡す（全ファイルリストも追加）
                            project_folder_info = {
                                "id": item['id'],
                                "name": folder_name,
                                "webUrl": item.get('webUrl', ''),
                                "fullPath": full_path,
                                "allFiles": child_items  # 全ファイル情報を追加
                            }
                            process_project_files(access_token, user_email, all_calc_files, all_drawing_files, target_cert, target_review, project_folder_info)
                        else:
                            print("   ⚠️ 構造計算書PDFが見つかりませんでした")
                else:
                    # 再帰探索（パスを引き継ぐ）
                    process_folder_recursive(access_token, child_url, user_email, full_path)
    except Exception as e:
        print(f"探索エラー: {e}")

# 5. プロジェクトファイルの処理
def process_project_files(access_token, user_email, calc_files, drawing_files, cert_file, review_file, project_folder_info):
    """
    calc_files: 構造計算書ファイルのリスト（全てのSTR計算書）
    drawing_files: 構造図面ファイルのリスト（全ての構造図面）
    cert_file: 安全証明書ファイル（最新版1つ）
    review_file: 指摘回答書ファイル（最新版1つ）
    """
    if not calc_files:
        print("   ⚠️ 構造計算書がありません")
        return

    # 最初のファイルのIDをドキュメントキーとして使用
    primary_file = calc_files[0]
    file_id = primary_file['id']
    file_name = primary_file['name']

    # 重複チェック (最初の計算書のIDをキーにする)
    db = firestore.Client(project=GCP_PROJECT_ID, database="uplan")
    doc_ref = db.collection("Beta_2025_12_24").document(file_id)
    if doc_ref.get().exists:
        print(f"   ℹ️ 処理済みのためスキップ ({file_name})")
        return

    # フォルダパスからメタデータを抽出
    full_path = project_folder_info.get('fullPath', '')
    metadata = extract_project_metadata(full_path)

    print(f"   📋 抽出されたメタデータ:")
    print(f"      作成日: {metadata['submissionDate'] or '不明'}")
    print(f"      取引先: {metadata['clientName'] or '不明'}")
    print(f"      物件名: {metadata['projectName'] or '不明'}")

    # ダウンロード処理
    files_to_analyze = [] # (ファイル名, バイナリデータ) のリスト

    # A. 全ての構造計算書をダウンロード
    print(f"   ⬇️ 構造計算書DL: {len(calc_files)}ファイル")
    for calc_file in calc_files:
        calc_name = calc_file['name']
        calc_id = calc_file['id']
        print(f"      - {calc_name}")
        calc_data = download_content(access_token, user_email, calc_id)
        if not calc_data:
            print(f"      ⚠️ ダウンロード失敗: {calc_name}")
            continue
        files_to_analyze.append((f"構造計算書_{calc_name}", calc_data))

    # B. 全ての構造図面をダウンロード（大屋根判定などに使用）
    if drawing_files:
        print(f"   ⬇️ 構造図面DL: {len(drawing_files)}ファイル")
        for drawing_file in drawing_files:
            drawing_name = drawing_file['name']
            drawing_id = drawing_file['id']
            print(f"      - {drawing_name}")
            drawing_data = download_content(access_token, user_email, drawing_id)
            if not drawing_data:
                print(f"      ⚠️ ダウンロード失敗: {drawing_name}")
                continue
            files_to_analyze.append((f"構造図面_{drawing_name}", drawing_data))
    else:
        print("   (構造図面なし)")

    # C. 安全証明書のダウンロード (あれば)
    if cert_file:
        print(f"   ⬇️ 安全証明書DL: {cert_file['name']} ...")
        cert_data = download_content(access_token, user_email, cert_file['id'])
        if cert_data:
            files_to_analyze.append(("安全証明書", cert_data))
    else:
        print("   (安全証明書なし)")

    # D. 回答書のダウンロード (あれば)
    if review_file:
        print(f"   ⬇️ 回答書DL: {review_file['name']} ...")
        review_data = download_content(access_token, user_email, review_file['id'])
        if review_data:
            files_to_analyze.append(("指摘回答書", review_data))
    else:
        print("   (指摘回答書なし)")

    # ファイル名パターン分析（ゾーニング・大屋根・鉄骨階段などの検出）
    file_name_hints = []
    all_files = project_folder_info.get('allFiles', [])
    for f in all_files:
        fname = f.get('name', '')
        # ゾーニングのパターン検出
        if any(pattern in fname for pattern in ['南棟', '北棟', '左棟', '右棟', 'A棟', 'B棟', 'C棟']):
            file_name_hints.append(f"・構造計算書が複数棟に分割されています（ファイル名: {fname}）→ ゾーニング設計の可能性が高い")
        # 大屋根のパターン検出
        if any(pattern in fname for pattern in ['大屋根', '屋根', 'roof', 'Roof']):
            file_name_hints.append(f"・「{fname}」というファイルがあります → 大屋根の可能性")
        # 鉄骨階段のパターン検出
        if any(pattern in fname for pattern in ['鉄骨階段', '鉄骨外部階段', 'S階段', 'S造階段', '外部階段']):
            file_name_hints.append(f"・「{fname}」というファイルがあります → 鉄骨造外部階段が存在します")

    # AI解析
    print("   🤖 AI解析中 (Gemini 2.5 Pro)...")
    result_json = analyze_with_gemini(files_to_analyze, file_name_hints)

    if result_json:
        result_json["fileName"] = file_name
        if review_file:
            result_json["reviewFileName"] = review_file['name']

        # フォルダパスから抽出した取引先名をmanagementに追加
        if "management" not in result_json:
            result_json["management"] = {}
        if metadata['clientName']:
            result_json["management"]["partners"] = [metadata['clientName']]
        else:
            result_json["management"]["partners"] = []

        # Firestoreへ保存（フィールド順序を整理）
        # analysis_resultの構造を再構築して順序を整理
        analysis = result_json
        basic = analysis.get("basicSpecs", {})
        regulations = analysis.get("regulations", {})
        technology = analysis.get("technology", {})
        environment = analysis.get("environment", {})
        management = analysis.get("management", {})

        save_data = {
            # ■ 建築物の特性
            "prefecture": basic.get("prefecture"),
            "structure_types": basic.get("structureTypes", []),
            "use_types": basic.get("useTypes", []),
            "floor_categories": basic.get("floorCategories", []),
            "total_area": basic.get("totalArea", 0.0),
            "area_category": basic.get("areaCategory", ""),

            # ■ 法律・技術的要件
            "performance_requirements": regulations.get("performanceLabels", []),
            "calc_routes": regulations.get("calcRoutes", []),
            "calc_route_reasoning": regulations.get("calcRouteReasoning", ""),
            "foundation_types": technology.get("foundationTypes", []),
            "design_features": technology.get("features", []),
            "resistance_elements": technology.get("resistanceElements", []),

            # ■ プロジェクトの条件
            "region_conditions": {
                "snow_region": environment.get("snowRegion", ""),
                "fire_zone": environment.get("fireZone", ""),
            },
            "ground_condition": environment.get("groundCondition", ""),
            "client_name": metadata['clientName'],
            "partners": management.get("partners", []),
            "inspection_agency": management.get("inspectionAgency"),

            # ■ その他
            "summary": analysis.get("summary", ""),

            # システム管理用フィールド
            "analysis_result": result_json,  # 元のJSON全体を保持
            "file_id": file_id,
            "file_name": file_name,
            "onedrive_url": project_folder_info.get('webUrl', ''),
            "project_folder_name": project_folder_info.get('name', ''),
            "project_folder_id": project_folder_info.get('id', ''),
            "folder_full_path": full_path,
            "submission_date": metadata['submissionDate'],
            "submission_year": metadata['submissionYear'],
            "submission_month": metadata['submissionMonth'],
            "project_name": metadata['projectName'],
            "model_version": "gemini-2.5-pro",
            "processed_at": firestore.SERVER_TIMESTAMP,
            "extracted_at": firestore.SERVER_TIMESTAMP,
            "status": "completed"
        }
        doc_ref.set(save_data)
        print("   ✅ 保存完了！")
        print(f"   📁 OneDrive URL: {project_folder_info.get('webUrl', 'N/A')}")
        print(f"   📂 フォルダパス: {full_path}")
    else:
        print("   ❌ AI解析失敗")

def download_content(access_token, user_email, file_id):
    url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{file_id}/content"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        res = requests.get(url, headers=headers)
        if res.status_code == 200: return res.content
    except: pass
    return None

# 5. AI解析ロジック (高精度プロンプト実装済み)
def analyze_with_gemini(file_data_list, file_name_hints=None):
    vertexai.init(project=GCP_PROJECT_ID, location=LOCATION)
    config = GenerationConfig(temperature=0.0, response_mime_type="application/json")
    model = GenerativeModel("gemini-2.5-pro", generation_config=config)

    parts = []
    for label, data in file_data_list:
        parts.append(Part.from_data(data, mime_type="application/pdf"))

    # ファイル名からのヒント情報を追加
    hints_section = ""
    if file_name_hints and len(file_name_hints) > 0:
        hints_section = "\n【重要: 同じフォルダ内の関連ファイル情報】\n"
        hints_section += "以下のファイル名パターンから、建物の特徴を推測してください：\n"
        for hint in file_name_hints:
            hints_section += hint + "\n"
        hints_section += "\n"

    # プロンプト
    prompt_text = """
    あなたは熟練した構造一級建築士です。
    提供されたPDFファイル（構造計算書、構造図面、安全証明書、あれば指摘回答書）を統合的に読み解き、事実に基づいて以下の情報を抽出してJSONで出力してください。

    【最重要: 「大屋根」の検出】
    ★★★ 以下の優先順位で「大屋根」を検出してください ★★★

    **検出方法の優先順位:**

    1. **構造図面（断面図）による視覚的検出【最優先】**
       - 構造図面PDFの中から、建物の断面を示す図面を見つける
       - 断面図で以下をチェック:
         * 屋根の勾配線（斜め線）が1階床レベルから2階（またはそれ以上）の高さまで連続しているか？
         * 屋根が複数階を「またいで」いるか？（1つの階で完結していないか？）
       - 視覚的証拠: 1階から2階以上へ連続する斜めの屋根線、屋根の下に吹抜け空間、2階床レベルで屋根が貫通している様子
       - 構造図面に上記の視覚的証拠があれば「大屋根」と判定

    2. **個別計算書による検出【次点】**
       - 個別計算書には「耐風梁の検討」「吹抜け部の検討」「大屋根の検討」などの計算が含まれる場合がある
       - 以下のキーワードや計算項目があれば「大屋根」と判定:
         * 「耐風梁」「耐風梁の検討」
         * 「吹抜け」「吹き抜け」「吹抜け部の風圧力」
         * 「大屋根」「連続勾配屋根」
         * 複数階にまたがる屋根構造の計算

    3. **構造計算書のテキストによる検出【補助的】**
       - 構造計算書本文に「大屋根」「吹抜け」等のキーワードがあれば参考にする

    ※ 構造図面の視覚情報 > 個別計算書の計算項目 > 構造計算書のテキスト の順で優先してください。
    """ + hints_section + """

    【重要: 構造計算ソフトの抽出】
    - 「安全証明書」が提供されている場合は、そこに記載されている構造計算ソフトの名称とバージョンを優先的に抽出してください。
    - 安全証明書には「当該構造計算に用いたプログラム」という欄があり、そこにソフト名が記載されています。
    - 抽出例:
      * STRDESIGN Ver.17-03 → 「STRDESIGN」（その他カテゴリに該当）
      * KIZUKURI Ver.10.0 → 「KIZUKURI」
      * HOUSE-ST1 Ver.9.0 → 「HOUSE-ST1」
      * SS7 → 「SS7 / SS3」
      * BUILD.一貫 Ver.X.X → 「BUILD.一貫」
    - 安全証明書がない場合は、構造計算書の表紙やヘッダー、フッターから抽出してください。
    - 該当するカテゴリがない場合は「その他（任意解析ソフト等）」を選択し、ソフト名を記録してください。

    【重要指示: 審査機関の特定】
    - 「指摘回答書」がある場合は、そのヘッダー、フッター、宛名、または「担当者のメールアドレス」を重点的に確認すること。
    - メールアドレスのドメインから審査機関を推測すること。
      (例: @udi-co.jp → UDI確認検査, @erijapan.co.jp → 日本ERI, @kakunin.co.jp → 確認サービス など)
    - 該当ファイルがない場合や特定できない場合は null とする。

    【最重要：構造計算ルートの判定ロジック（ルート1優先版）】
    あなたは熟練した木造建築の構造設計者です。

    **重要な注意事項**：
    構造計算書ソフトは、簡易な「ルート1（壁量計算）」であっても、参考値として「層間変形角」などの詳細データを出力することがあります。
    参考データに惑わされず、**「この建物のメインの設計手法は何か」**を以下の優先順位で判定してください。

    **ステップ1：ルート1（壁量計算）の強力な証拠を探す【最優先】**
    - 「壁量計算書」「壁量充足率」「4分割法（側端部分の壁量比）」「N値計算」の表や図面が含まれているか？
    - **【判定】**：これらが確認できた場合は、たとえ後半に「層間変形角」や「偏心率」の表があっても、それは参考値とみなし、**「ルート1（許容応力度計算）」**と判定して終了する。

    **ステップ2：ルート3（保有水平耐力）の確認**
    - ステップ1に該当せず、「保有水平耐力」「Qu」「Qun」の計算があるか？
    - 【YES】 → 「ルート3（保有水平耐力計算）」

    **ステップ3：ルート2（許容応力度等計算）の確認**
    - ステップ1（壁量計算）の要素が**全くなく**、かつ「許容応力度計算」および「層間変形角」「剛性率・偏心率」の判定表があるか？
    - 【YES】 → 「ルート2（許容応力度等計算）」

    **ステップ4：最終確認**
    - 判定根拠には、「壁量計算の表が確認できたためルート1」のように、優先した要素を明記すること。
    - **壁量計算や4分割法が1つでも確認できれば、層間変形角の有無に関わらず必ずルート1と判定すること。**

    **【重要】判定理由の記録**
    - ルート判定を行った後、regulations.calcRouteReasoning フィールドに判定理由を100文字程度で記載すること。
    - 記載例：
      - ルート1の場合: 「壁量計算書と4分割法の表が確認できたためルート1と判定。層間変形角や偏心率の表は参考値として出力されたもの。」
      - ルート2の場合: 「壁量計算や4分割法の要素が全くなく、層間変形角・偏心率による詳細な検討のみが行われているためルート2と判定。」
      - ルート3の場合: 「保有水平耐力Qu=450kNの計算結果が確認できたためルート3と判定。」

    【分類リスト】※以下のカテゴリから該当するものを全て配列で返してください

    1. 建物基本スペック
       都道府県:
         - 【重要】構造計算書の表紙、建築概要、建築地などから都道府県名を抽出してください
         - 例: 「東京都」「大阪府」「北海道」「沖縄県」
         - 「○○県○○市」のような記載から都道府県名のみを抽出してください
         - 見つからない場合は null を返してください

       構造種別（該当するものを全て選択）:
         - 木造（在来軸組）
         - 木造（限界耐力計算）
         - 木造（枠組壁）
         - 鉄骨造
         - RC造（壁式）
         - RC造（ラーメン）
         - 補強CB造
         - ボックスカルバート
         - 混構造
         - テント
         - 膜構造
         - 擁壁
         - 耐震診断
         - 工作物
         - SRC造
         - その他構造

       用途（該当するものを全て選択）:
         - 戸建住宅
         - 共同住宅
         - 長屋
         - 店舗
         - 事務所
         - 倉庫
         - 工場
         - 車庫・カーポート

       階数（該当するものを全て選択）:
         - 平屋
         - 2階建て
         - 3階建て
         - 4階建て以上
         - 地下階あり

       延床面積（該当する区分を1つ選択）:
         - 〜100㎡
         - 101〜300㎡
         - 301〜500㎡
         - 501〜1000㎡
         - 1001㎡〜

    2. 法規・計算ルート・性能
       構造計算ルート（該当するものを全て選択）:
         - 仕様規定のみ（壁量計算・N値計算など）
         - ルート1（許容応力度計算）
         - ルート2（許容応力度等計算）
         - ルート3（保有水平耐力計算）
         - 限界耐力計算

       適合性判定（該当するものを選択）:
         - 適判物件（要判定）
         - 不要

       耐火性能要件（該当するものを全て選択）:
         - 耐火建築物
         - 準耐火建築物（ロ-1：燃えしろ設計・現し）
         - 準耐火建築物（ロ-2：被覆・ボード張り）
         - 準耐火建築物（イ準耐：1時間準耐火など）
         - 省令準耐火構造
         - その他（法22条区域・指定なし区域）

       性能表示・等級（該当するものを全て選択）:
         - 長期優良住宅
         - 耐震等級2
         - 耐震等級3
         - 積雪荷重の割増（多雪区域の等級取得）

    3. 構造技術・工法
       基礎形式（該当するものを全て選択）:
         - 直接基礎（べた基礎）
         - 直接基礎（布基礎）
         - 直接基礎（独立基礎）
         - 地盤改良あり（柱状・表層・鋼管）
         - 杭基礎（既製杭・場所打ち杭）

       水平力抵抗要素（該当するものを全て選択）:
         - 筋かい耐力壁
         - 面材耐力壁（構造用合板・OSB・モイス・ダイライト等）
         - ラーメン構造（S造・RC造・門型フレーム等）
         - 制震ダンパー

       床・屋根構面（該当するものを全て選択）:
         - 剛床（合板直張り）
         - 火打ち構面
         - トラス構造

       特徴的な設計・技術（該当するものを全て選択）:
         - 大スパン/大開口
           （定義: 柱間隔が大きい構造、または大きな開口部がある設計。柱のない大空間を実現する構造設計手法）
           （判定基準: 木造で一般住宅は最大6m程度、非住宅で10m超、鉄骨造で20～50m、RC造で10m程度のスパンが目安）
           （特徴: 無柱空間の実現、デザイン自由度が高い、体育館・倉庫・事務所の大空間などで採用）
           （表記揺れ: 「大スパン」「大空間」「長スパン」「ロングスパン」「大開口」「大開口部」「無柱空間」「柱のない空間」「梁せいが大きい」「大梁」）

         - スキップフロア
           （定義: 中間階層がある設計。半階ずつずらした多層構造で、建築物の床の高さをずらして各階の中間に空間を設置）
           （特徴: 1.5階、2.5階などの中間階、床の高さが異なる複数の建物を階段でつなぐ構造、構造計算が必要）
           （表記揺れ: 「スキップフロア」「スキップフロアー」「中間階」「中2階」「1.5階」「2.5階」「半階ずらし」「レベル差のある床」）
           （構造計算上の記述: 「左右でゾーン分割」「建物を分割して検討」なども該当）

         - 木質ラーメン
           （定義: 木造の柱と梁を剛接合したラーメン構造。筋かいを使わず、柱と梁の接合部を強固にすることで水平力に抵抗）
           （特徴: 耐力壁や筋かいの配置にとらわれない自由な空間設計、全方位に大開口が可能、特殊金物で接合部を強化）
           （表記揺れ: 「木質ラーメン」「木造ラーメン」「木ラーメン」「ラーメン構造」「門型フレーム」「ポータルフレーム」「剛接合」「モーメント接合」「ラグスクリューボルト」「鋼板挿入」「グルードインロッド」）

         - 大屋根
           （定義: 複数階を覆う連続した勾配を持つ屋根構造。1つの階で完結せず、2つ以上の階にまたがって連続する大きな屋根面）
           （判定基準1【形状】: 屋根の勾配が1階から2階以上へ連続して架かっていること。外観上、下層階から上層階までを一筆書きで覆うような大きな屋根面）
           （判定基準2【構造】: 屋根が通過する各階の床レベル位置に横架材（梁など水平部材）が入っており、下側が耐力壁、上側が妻壁として構成が分かれていること）
           （判定基準3【空間】: 屋根の下に吹抜け（階をまたぐ高い天井の空間）が存在し、耐風梁の検討が必要な規模であること）
           （【重要】検出方法: 構造図面（特に断面図、軸組図、矩計図）を優先的に確認すること。断面図で1階から2階以上にまたがる連続した勾配屋根が確認できれば「大屋根」と判定。構造計算書にキーワードがなくても、図面で視覚的に確認できれば該当。）
           （表記揺れ: 「大屋根」「大型屋根」「連続勾配屋根」「通し屋根」「吹抜け屋根」「勾配屋根（複数階）」「横架材」「妻壁」「耐風梁」「屋根トラス」「長尺屋根」「広幅屋根」）

         - 鉄骨造外部階段
           （定義: 建物外部に設置された鉄骨製の階段。主に避難経路として、建物の屋外に鉄骨で構築された階段）
           （特徴: 5階以上または地下2階以下に通じる避難階段、火災時に煙が充満しない）
           （★★★最重要★★★ 検出方法: 以下のいずれかに該当すれば「鉄骨造外部階段」として抽出してください）
             * 構造計算書の目次、本文、計算書内に「鉄骨階段」「外部階段」「屋外階段」などのキーワードがある
             * 構造図面に鉄骨階段の図面がある
             * 計算書のタイトルや章立てに「階段」「外部階段」などの記載がある
           （表記揺れ: 「鉄骨造外部階段」「S造外部階段」「鉄骨階段」「屋外階段」「外階段」「外付け階段」「避難階段」「非常階段」「鉄骨製階段」「屋外避難階段」「S階段」）

         - 片持ち基礎（片持ちスラブ）
           （定義: 一端のみで支持され、他端が自由端となっている基礎やスラブ。片側だけが固定されて空中に張り出す構造形式、キャンチレバー）
           （判定基準: 持ち出し長さ2m以下は片持ちスラブのみ可能、2m以上は荷重割り増しが必要）
           （特徴: ベランダ、共用廊下、バルコニーなどに採用、応力を1.5倍して検討）
           （表記揺れ: 「片持ち基礎」「片持基礎」「片持ち梁基礎」「片持ちスラブ」「片持スラブ」「キャンチスラブ」「キャンチレバースラブ」「オーバーハング基礎」「張り出し基礎」「cantilever」「片持ち床」「CG」「CB」「CS」）

         - ゾーニング
           （定義: 建物を複数の構造ゾーンに分割して設計・検討する手法。建物を構造的に独立した複数の部分に分け、それぞれを別々に構造計算）
           （特徴: エキスパンションジョイント（構造継目）を設置、規模が大きい建物やL字形などの変形プラン、クリアランス20～100mm）
           （表記揺れ: 「ゾーニング」「ゾーン分割」「ゾーン分け」「建物を分割」「左右に分割」「棟別に検討」「独立した架構」「別棟扱い」「左棟・右棟」「南棟・北棟」「A棟・B棟」「エキスパンションジョイント」「Exp.J」「構造分割」）

         - 塔屋
           （定義: 屋上に設置された小規模な建築物。建物の屋上から突き出た部分で、階段室、昇降機塔、機械室などに使用）
           （判定基準: 水平投影面積が建築面積の1/8以内、かつ高さ5m以下の場合、建築物の高さおよび階数に不算入）
           （特徴: 階段室、昇降機塔、装飾塔、物見塔、屋窓、昇降機の乗降ロビーなど）
           （表記揺れ: 「塔屋」「PH」「ペントハウス」「penthouse」「屋上突出部」「屋上構造物」「階段室（屋上）」「機械室（屋上）」「R階」「昇降機塔」）

         - 斜め壁
           （定義: 平面または立面で斜めに配置された耐力壁。敷地形状や意匠デザインの制約により、直交しない角度で配置される構造耐力壁）
           （特徴: 低減係数を適用して安全性確保、45度の場合は両方向に低減、それ以上は長辺側のみ考慮）
           （表記揺れ: 「斜め壁」「斜壁」「傾斜壁」「斜行壁」「斜交壁」「非直交壁」「振れ壁」「角度のある壁」「台形の壁」）

    4. プロジェクト条件・環境
       多雪地域（該当するものを選択）:
         - 指定なし
         - 垂直積雪量 1m未満
         - 垂直積雪量 1m以上（多雪補正あり）

       風圧力・地表面粗度（該当するものを全て選択）:
         - 基準風速 Vo=34m/s〜
         - 地表面粗度区分 Ⅱ（海岸・平野部）
         - 地表面粗度区分 Ⅲ（市街地）

       地盤条件（該当するものを選択）:
         - 良好
         - 軟弱（液状化検討あり）

       防火地域指定（該当するものを選択）:
         - 防火地域
         - 準防火地域
         - 法22条区域

    5. 管理・ツール情報
       使用ソフト（該当するものを全て選択し、具体的なソフト名も記載）:
         - KIZUKURI
         - HOUSE-ST1
         - SS7 / SS3
         - BUILD.一貫

         ※重要:
         - 【優先順位1】安全証明書がある場合は、安全証明書に記載されているソフト名を優先的に抽出してください。
         - 【優先順位2】安全証明書がない場合は、構造計算書の表紙、目次、計算結果のヘッダー・フッターからソフト名を抽出してください。
           * 表紙に「○○○ Ver.X.X による構造計算」などの記載がある場合
           * 計算書の各ページヘッダー・フッターにソフト名やバージョンが記載されている場合
           * 計算プログラム名として明記されている場合
         - 上記のリストに該当しない場合は、ソフト名をそのまま記載してください（「その他（...）」という形式は不要）。
         - 例: 「STRDESIGN Ver.17-03」「Wics FRAME Ver.2.0」「SEIN Ver.5.0」
         - バージョン番号も含めて記載してください。
         - リストにあるソフトでも、バージョンが記載されている場合はバージョンも含めてください。
           例: 「KIZUKURI Ver.10.0」「HOUSE-ST1 Ver.9.2」

       審査機関:
         - 【重要】構造計算書、指摘回答書、質疑回答書のいずれかに記載されている審査機関名を抽出してください
         - 抽出例: ビューローベリタス、ERI、UDI、確認サービス、日本ERI、ビューローベリタスジャパン、
                   株式会社確認検査機構アネックス、株式会社住宅性能評価センター、
                   一般財団法人日本建築設備・昇降機センター 等
         - 指摘回答書・質疑回答書がある場合は、そのヘッダー、フッター、宛先欄から審査機関名を優先的に抽出してください
         - 会社の正式名称（株式会社〜、一般財団法人〜等）を含めて抽出してください
         - 見つからない場合は null を返してください

    【JSON出力フォーマット】
    {
      "basicSpecs": {
        "prefecture": null,          // 都道府県（例: "東京都"）
        "structureTypes": [],        // 構造種別の配列（例: ["木造（在来軸組）"]）
        "useTypes": [],              // 用途の配列（例: ["戸建住宅"]）
        "floorCategories": [],       // 階数の配列（例: ["2階建て"]）
        "hasBasement": false,        // 地下階ありの場合はtrue
        "totalArea": 0.0,            // 延床面積（数値）
        "areaCategory": ""           // 延床面積区分（例: "101〜300㎡"）
      },
      "regulations": {
        "calcRoutes": [],            // 構造計算ルートの配列（例: ["ルート2（許容応力度等計算）"]）
        "calcRouteReasoning": "",    // ルート判定理由（例: "壁量計算と4分割法が主体。層間変形角の表は参考値のみ。"）
        "suitabilityJudgment": "",   // 適合性判定（例: "不要"）
        "fireResistance": [],        // 耐火性能要件の配列（例: ["省令準耐火構造"]）
        "performanceLabels": []      // 性能表示・等級の配列（例: ["耐震等級3", "長期優良住宅"]）
      },
      "technology": {
        "foundationTypes": [],       // 基礎形式の配列（例: ["直接基礎（べた基礎）"]）
        "resistanceElements": [],    // 水平力抵抗要素の配列（例: ["筋かい耐力壁", "面材耐力壁（構造用合板・OSB・モイス・ダイライト等）"]）
        "floorRoofTypes": [],        // 床・屋根構面の配列（例: ["剛床（合板直張り）"]）
        "features": []               // 特徴的な設計・技術の配列（例: ["吹抜け", "大開口（耐力壁が少ない）"]）
      },
      "environment": {
        "snowRegion": "",            // 多雪地域（例: "指定なし"）
        "windRoughness": [],         // 風圧力・地表面粗度の配列（例: ["地表面粗度区分 Ⅲ（市街地）"]）
        "groundCondition": "",       // 地盤条件（例: "良好"）
        "fireZone": ""               // 防火地域指定（例: "準防火地域"）
      },
      "management": {
        "software": [],              // 使用ソフトの配列（例: ["KIZUKURI"]）
        "inspectionAgency": null     // 審査機関（例: "UDI確認検査"）
      },
      "summary": "300文字程度の詳細な要約（建物の特徴、構造計算ルート、性能、特記事項などを含む）"
    }
    """
    parts.append(prompt_text)

    try:
        responses = model.generate_content(parts)
        return json.loads(responses.text)
    except Exception as e:
        print(f"   AIエラー: {e}")
        return None

# --- 実行 ---
if __name__ == "__main__":
    print("🚀 バッチ処理 v3 を開始します...")
    token = get_access_token()
    if not token:
        print("❌ 認証失敗のため終了します")
        exit(1)

    # システム設定から前回の同期状態を取得
    system_config = get_system_config()
    delta_link = system_config.get('deltaLink') if system_config else None

    new_delta_link = None

    if delta_link:
        # 【差分モード】前回からの変更のみを処理
        print("\n📊 差分更新モード: 前回からの変更のみを処理します")
        changed_items, new_delta_link = fetch_drive_changes(token, TARGET_USER_EMAIL, delta_link)

        if changed_items:
            print(f"📝 {len(changed_items)}件の変更を検出しました")
            process_changed_folders(token, TARGET_USER_EMAIL, changed_items)
        else:
            print("✨ 変更はありませんでした")

    else:
        # 【全件スキャンモード】初回実行または強制全件スキャン
        print("\n📊 全件スキャンモード: すべてのフォルダを探索します")
        start_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/root:/{TARGET_ROOT_PATH}:/children"

        # TARGET_ROOT_PATHを初期パスとして設定
        process_folder_recursive(token, start_url, TARGET_USER_EMAIL, TARGET_ROOT_PATH)

        # 全件スキャン完了後、デルタリンクを取得して保存
        print("\n📍 初回デルタリンクを取得中...")
        _, new_delta_link = fetch_drive_changes(token, TARGET_USER_EMAIL, None)

    # デルタリンクを保存（次回の差分取得用）
    if new_delta_link:
        save_system_config(new_delta_link)
        print(f"💾 次回は差分更新モードで実行されます")

    print("\n🎉 全処理が完了しました")