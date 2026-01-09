"""
実際のフォルダパスでのメタデータ抽出テスト
"""
import re
from datetime import datetime

def extract_project_metadata(folder_path):
    """
    フォルダパスから作成日、取引先名、物件名を抽出
    """
    metadata = {
        "submissionDate": None,
        "submissionYear": None,
        "submissionMonth": None,
        "clientName": None,
        "projectName": None
    }

    parts = folder_path.split('/')

    # 1. 取引先名の抽出
    for part in parts:
        match = re.match(r'^[T]?\d+\s+(.+?)(?:（.+?）)?$', part)
        if match:
            metadata["clientName"] = match.group(1).strip()
            break

    # 2. 物件名の抽出（7桁以上の数字で始まるものを物件コードとする）
    for part in parts:
        match = re.match(r'^(\d{7,})_(.+)$', part)
        if match:
            metadata["projectName"] = match.group(2).strip()
            break

    # 3. 作成日の抽出
    for part in parts:
        match = re.match(r'^(\d{4})(\d{2})(\d{2})_', part)
        if match:
            year, month, day = match.groups()
            try:
                date_obj = datetime(int(year), int(month), int(day))
                metadata["submissionDate"] = f"{year}-{month}-{day}"
                metadata["submissionYear"] = int(year)
                metadata["submissionMonth"] = int(month)
            except ValueError:
                pass
            break

    return metadata


# 実際のフォルダパス（要求されたテストケース）
actual_path = "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□さ行/T125 三栄建築設計（計算書・構造図ダブルチェック必要）/2025004_蕨市錦町002②1号棟/09.成果物/20250312_蕨市錦町002②1号棟_【補正】 構造設計図書"

print("=" * 100)
print("📂 実際のフォルダパスでのメタデータ抽出テスト")
print("=" * 100)
print()
print("【入力パス】")
print(actual_path)
print()
print("-" * 100)

metadata = extract_project_metadata(actual_path)

print()
print("【抽出結果】")
print()
print(f"  📅 作成日        : {metadata['submissionDate'] or '不明'}")
print(f"  📆 提出年        : {metadata['submissionYear'] or '不明'}")
print(f"  📆 提出月        : {metadata['submissionMonth'] or '不明'}")
print(f"  🏢 取引先名      : {metadata['clientName'] or '不明'}")
print(f"  🏗️  物件名        : {metadata['projectName'] or '不明'}")
print()
print("-" * 100)
print()

# Firestore保存形式のシミュレーション
print("【Firestoreに保存される形式（JSON）】")
print()
import json

firestore_data = {
    "submission_date": metadata['submissionDate'],
    "submission_year": metadata['submissionYear'],
    "submission_month": metadata['submissionMonth'],
    "client_name": metadata['clientName'],
    "project_name": metadata['projectName'],
    "folder_full_path": actual_path,
    "onedrive_url": "https://example.sharepoint.com/...",  # 実際はGraph APIから取得
}

print(json.dumps(firestore_data, ensure_ascii=False, indent=2))
print()
print("-" * 100)
print()

# フロントエンド表示イメージ
print("【フロントエンドでの表示イメージ】")
print()
print(f"  物件名: {metadata['projectName']}")
print(f"  作成日: {metadata['submissionYear']}年{metadata['submissionMonth']}月{metadata['submissionDate'][-2:]}日")
print(f"  取引先: {metadata['clientName']}")
print(f"  リンク: [OneDriveで開く] → {firestore_data['onedrive_url']}")
print()
print("=" * 100)

# 検証
expected = {
    "submissionDate": "2025-03-12",
    "submissionYear": 2025,
    "submissionMonth": 3,
    "clientName": "三栄建築設計",
    "projectName": "蕨市錦町002②1号棟"
}

all_correct = all(metadata[k] == v for k, v in expected.items())

if all_correct:
    print()
    print("✅ テスト成功！すべての情報が正しく抽出されました。")
    print()
else:
    print()
    print("❌ テスト失敗：期待値と一致しない項目があります。")
    print()
    for key, expected_value in expected.items():
        actual_value = metadata[key]
        if actual_value != expected_value:
            print(f"   {key}: 期待値={expected_value}, 実際={actual_value}")
    print()
