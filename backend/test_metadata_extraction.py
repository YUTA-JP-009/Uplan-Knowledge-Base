"""
メタデータ抽出機能のテストスクリプト
"""
import re
from datetime import datetime

def extract_project_metadata(folder_path):
    """
    フォルダパスから作成日、取引先名、物件名を抽出
    """
    metadata = {
        "submissionDate": None,      # 提出日（YYYY-MM-DD形式）
        "submissionYear": None,       # 提出年
        "submissionMonth": None,      # 提出月
        "clientName": None,           # 取引先名
        "projectName": None           # 物件名
    }

    # パスを '/' で分割
    parts = folder_path.split('/')

    # 1. 取引先名の抽出（例: "T125 三栄建築設計（計算書・構造図ダブルチェック必要）"）
    for part in parts:
        # "T数字 取引先名" または "数字 取引先名" のパターン
        match = re.match(r'^[T]?\d+\s+(.+?)(?:（.+?）)?$', part)
        if match:
            metadata["clientName"] = match.group(1).strip()
            break

    # 2. 物件名の抽出（例: "2025004_蕨市錦町002②1号棟"）
    for part in parts:
        # "数字_物件名" のパターン（7桁以上の数字で始まるものを物件コードとする）
        match = re.match(r'^(\d{7,})_(.+)$', part)
        if match:
            metadata["projectName"] = match.group(2).strip()
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


# テストケース
test_paths = [
    # ケース1: 完全なパス（要求されたテストケース）
    "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□さ行/T125 三栄建築設計（計算書・構造図ダブルチェック必要）/2025004_蕨市錦町002②1号棟/09.成果物/20250312_蕨市錦町002②1号棟_【補正】 構造設計図書",

    # ケース2: 簡略パス
    "□さ行/T125 三栄建築設計（計算書・構造図ダブルチェック必要）/2025004_蕨市錦町002②1号棟/09.成果物/20250312_蕨市錦町002②1号棟_【補正】 構造設計図書",

    # ケース3: 日付なしのケース
    "□さ行/T125 三栄建築設計（計算書・構造図ダブルチェック必要）/2025004_蕨市錦町002②1号棟/09.成果物/構造設計図書",
]

print("=" * 80)
print("メタデータ抽出テスト")
print("=" * 80)

for i, path in enumerate(test_paths, 1):
    print(f"\n【テストケース {i}】")
    print(f"入力パス: {path}")
    print("-" * 80)

    metadata = extract_project_metadata(path)

    print(f"📋 抽出結果:")
    print(f"   作成日      : {metadata['submissionDate'] or '不明'}")
    print(f"   提出年      : {metadata['submissionYear'] or '不明'}")
    print(f"   提出月      : {metadata['submissionMonth'] or '不明'}")
    print(f"   取引先名    : {metadata['clientName'] or '不明'}")
    print(f"   物件名      : {metadata['projectName'] or '不明'}")

    # 期待値チェック（ケース1のみ）
    if i == 1:
        print(f"\n✅ 期待値との比較:")
        expected = {
            "submissionDate": "2025-03-12",
            "submissionYear": 2025,
            "submissionMonth": 3,
            "clientName": "三栄建築設計",
            "projectName": "蕨市錦町002②1号棟"
        }

        all_match = True
        for key, expected_value in expected.items():
            actual_value = metadata[key]
            match = "✅ OK" if actual_value == expected_value else f"❌ NG (期待値: {expected_value})"
            print(f"   {key:20s}: {match}")
            if actual_value != expected_value:
                all_match = False

        if all_match:
            print(f"\n🎉 すべての抽出が正しく動作しています！")
        else:
            print(f"\n⚠️  一部の抽出に問題があります")

print("\n" + "=" * 80)
