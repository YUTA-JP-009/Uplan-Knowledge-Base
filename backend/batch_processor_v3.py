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
TARGET_ROOT_PATH = "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□Ａ行/008 QHC"
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

# 2. ファイル選定ロジック
def select_project_files(file_list):
    """
    フォルダ内から「構造計算書」と「指摘回答書」のベストなものをそれぞれ選ぶ
    """
    candidates_calc = []   # 構造計算書用
    candidates_review = [] # 指摘回答書用

    for file in file_list:
        if "folder" in file: continue
        name = file['name']
        if not name.lower().endswith(".pdf"): continue

        # A. 構造計算書を探す
        if "構造計算書" in name:
            score = 0
            if "【補正】" in name: score += 100
            elif "【修正】" in name: score += 50
            candidates_calc.append({
                "file": file, "score": score, "updated": file['lastModifiedDateTime']
            })
        
        # B. 指摘回答書を探す
        if "指摘回答書" in name or "指摘事項回答" in name:
            score = 0
            candidates_review.append({
                "file": file, "score": score, "updated": file['lastModifiedDateTime']
            })

    # 選定処理
    best_calc = None
    best_review = None

    if candidates_calc:
        # スコア高い順 -> 日付新しい順
        best_calc = sorted(candidates_calc, key=lambda x: (x['score'], x['updated']), reverse=True)[0]['file']
    
    if candidates_review:
        # 日付新しい順
        best_review = sorted(candidates_review, key=lambda x: x['updated'], reverse=True)[0]['file']

    return best_calc, best_review

# 3. フォルダ探索
def process_folder_recursive(access_token, folder_url, user_email):
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        response = requests.get(folder_url, headers=headers)
        response.raise_for_status()
        items = response.json().get('value', [])

        for item in items:
            if "folder" in item:
                folder_name = item['name']
                child_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/items/{item['id']}/children"
                
                # 納品フォルダ判定
                if "納品" in folder_name or "成果物" in folder_name:
                    print(f"\n🎯 ターゲットフォルダ発見: {folder_name}")
                    # 中身を取得
                    res_child = requests.get(child_url, headers=headers)
                    child_items = res_child.json().get('value', [])
                    
                    # 計算書と回答書を選定
                    target_calc, target_review = select_project_files(child_items)
                    
                    if target_calc:
                        # プロジェクト処理へ
                        process_project_files(access_token, user_email, target_calc, target_review)
                    else:
                        print("   ⚠️ 構造計算書PDFが見つかりませんでした")
                else:
                    # 再帰探索
                    process_folder_recursive(access_token, child_url, user_email)
    except Exception as e:
        print(f"探索エラー: {e}")

# 4. プロジェクトファイルの処理
def process_project_files(access_token, user_email, calc_file, review_file):
    file_id = calc_file['id']
    file_name = calc_file['name']

    # 重複チェック (計算書のIDをキーにする)
    db = firestore.Client(project=GCP_PROJECT_ID, database="uplan")
    doc_ref = db.collection("2025_11_23").document(file_id)
    if doc_ref.get().exists:
        print(f"   ℹ️ 処理済みのためスキップ ({file_name})")
        return

    # ダウンロード処理
    files_to_analyze = [] # (ファイル名, バイナリデータ) のリスト

    # A. 計算書のダウンロード
    print(f"   ⬇️ 計算書DL: {file_name} ...")
    calc_data = download_content(access_token, user_email, file_id)
    if not calc_data: return
    files_to_analyze.append(("構造計算書", calc_data))

    # B. 回答書のダウンロード (あれば)
    if review_file:
        print(f"   ⬇️ 回答書DL: {review_file['name']} ...")
        review_data = download_content(access_token, user_email, review_file['id'])
        if review_data:
            files_to_analyze.append(("指摘回答書", review_data))
    else:
        print("   (指摘回答書なし)")

    # AI解析
    print("   🤖 AI解析中 (Gemini 2.5 Pro)...")
    result_json = analyze_with_gemini(files_to_analyze)
    
    if result_json:
        result_json["fileName"] = file_name
        if review_file:
            result_json["reviewFileName"] = review_file['name']
        
        # Firestoreへ保存
        save_data = {
            "analysis_result": result_json,
            "file_id": file_id,
            "file_name": file_name,
            "model_version": "gemini-2.5-pro",
            "processed_at": firestore.SERVER_TIMESTAMP,
            "status": "completed"
        }
        doc_ref.set(save_data)
        print("   ✅ 保存完了！")
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
def analyze_with_gemini(file_data_list):
    vertexai.init(project=GCP_PROJECT_ID, location=LOCATION)
    config = GenerationConfig(temperature=0.0, response_mime_type="application/json")
    model = GenerativeModel("gemini-2.5-pro", generation_config=config)

    parts = []
    for label, data in file_data_list:
        parts.append(Part.from_data(data, mime_type="application/pdf"))

    # プロンプト
    prompt_text = """
    あなたは熟練した構造一級建築士です。
    提供されたPDFファイル（構造計算書、あれば指摘回答書）を統合的に読み解き、事実に基づいて以下の情報を抽出してJSONで出力してください。

    【重要指示: 審査機関の特定】
    - 「指摘回答書」がある場合は、そのヘッダー、フッター、宛名、または「担当者のメールアドレス」を重点的に確認すること。
    - メールアドレスのドメインから審査機関を推測すること。
      (例: @udi-co.jp → UDI確認検査, @erijapan.co.jp → 日本ERI, @kakunin.co.jp → 確認サービス など)
    - 該当ファイルがない場合や特定できない場合は null とする。

    【分類リスト】
    1. 建物基本スペック
       - 構造種別: 木造（在来軸組）、木造（限界耐力計算）、木造（枠組壁）、鉄骨造、RC造（壁式）、RC造（ラーメン）、補強CB造、ボックスカルバート、混構造、テント、膜構造、擁壁、耐震診断、工作物、SRC造、その他
       - 用途: 戸建住宅、共同住宅、長屋、店舗、事務所、倉庫、工場、車庫
       - 階数区分: 平屋、2階建て、3階建て、4階建て以上、地下階あり
       - 延床面積区分: 〜100㎡、101〜300㎡、301〜500㎡、501〜1000㎡、1001㎡〜

    2. 法規・計算ルート・性能
       - 構造計算ルート: 仕様規定のみ、ルート1（許容応力度計算）、ルート2（許容応力度等計算）、ルート3（保有水平耐力計算）、限界耐力計算
       - 適合性判定: 適判物件（要判定）、不要
       - 耐火性能要件: 耐火建築物、準耐火建築物（ロ-1）、準耐火建築物（ロ-2）、準耐火建築物（イ準耐）、省令準耐火構造、その他
       - 性能表示・等級: 長期優良住宅、耐震等級2、耐震等級3、積雪荷重の割増

    3. 構造技術・工法
       - 基礎形式: 直接基礎（べた基礎）、直接基礎（布基礎）、直接基礎（独立基礎）、地盤改良あり、杭基礎
       - 水平力抵抗要素: 筋かい耐力壁、面材耐力壁、ラーメン構造、制震ダンパー
       - 床・屋根構面: 剛床（合板直張り）、火打ち構面、トラス構造
       - 特徴的な設計・技術: 大スパン・大空間、大開口、オーバーハング・片持ち、スキップフロア、吹抜け、伝統構法、混構造

    4. プロジェクト条件・環境
       - 積雪地域区分: 指定なし、多雪地域
       - 垂直積雪量区分: 1m未満、1m以上
       - 地表面粗度区分: 基準風速 Vo=34m/s〜、地表面粗度区分 Ⅱ、地表面粗度区分 Ⅲ
       - 地盤条件: 良好、軟弱
       - 防火地域指定: 防火地域、準防火地域、法22条区域

    5. 管理・ツール情報
       - 使用ソフト: KIZUKURI、HOUSE-ST1、SS7 / SS3、BUILD.一貫、STRDESIGN、その他
       - その他キーワード抽出: 取引先、審査機関名

    【JSON出力フォーマット】
    {
      "basicSpecs": { "structureTypes": [], "useTypes": [], "floorCount": 0, "floorCategory": "", "hasBasement": false, "totalArea": 0.0, "areaCategory": "" },
      "regulations": { "calcRoutes": [], "suitabilityJudgment": "", "fireResistance": [], "performanceLabels": [] },
      "technology": { "foundationTypes": [], "resistanceElements": [], "floorRoofTypes": [], "features": [] },
      "environment": { "snowRegion": "", "snowDepth": 0, "windRoughness": [], "groundCondition": "", "fireZone": "" },
      "management": { 
          "software": [], 
          "partners": [], 
          "inspectionAgency": null
      },
      "summary": "300文字程度の詳細な要約"
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
    if token:
        # パスに日本語が含まれるためURLエンコード等はrequestsに任せるが、
        # graph APIのパス指定形式に従い構築
        # 注: TARGET_ROOT_PATH の先頭に / は不要
        start_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/root:/{TARGET_ROOT_PATH}:/children"
        
        process_folder_recursive(token, start_url, TARGET_USER_EMAIL)
        print("\n🎉 全処理が完了しました")