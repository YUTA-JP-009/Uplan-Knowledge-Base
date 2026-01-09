"""
テスト結果を確認するスクリプト
"""

from google.cloud import firestore
import json

GCP_PROJECT_ID = "uplan-knowledge-base"

def main():
    """テスト結果を確認"""
    print("=" * 80)
    print("📊 5物件テスト結果確認")
    print("=" * 80)

    db = firestore.Client(project=GCP_PROJECT_ID, database="uplan")

    # Test_5Projectsで始まるコレクションを探す
    collections = db.collections()

    test_collections = []
    for collection in collections:
        if collection.id.startswith("Test_5Projects_"):
            test_collections.append(collection.id)

    if not test_collections:
        print("\n❌ テストコレクションが見つかりません")
        return

    # 最新のテストコレクションを使用
    latest_collection = sorted(test_collections)[-1]
    print(f"\n📦 使用するコレクション: {latest_collection}\n")

    collection_ref = db.collection(latest_collection)
    docs = collection_ref.stream()

    project_count = 0
    for doc in docs:
        project_count += 1
        data = doc.to_dict()

        print("=" * 80)
        print(f"【物件 {project_count}】 {doc.id}")
        print("=" * 80)

        # 基本情報
        print("\n📋 基本情報:")
        print(f"   物件名: {data.get('project_name', 'N/A')}")
        print(f"   クライアント: {data.get('client_name', 'N/A')}")
        print(f"   作成日: {data.get('created_date', 'N/A')}")
        print(f"   抽出日時: {data.get('extracted_at', 'N/A')}")
        print(f"   ファイル数: {data.get('file_count', 'N/A')}")

        # パス情報
        print(f"\n📂 パス情報:")
        print(f"   フォルダパス: {data.get('folder_path', 'N/A')}")
        folder_url = data.get('folder_url', 'N/A')
        if len(folder_url) > 100:
            print(f"   URL: {folder_url[:100]}...")
        else:
            print(f"   URL: {folder_url}")

        # 抽出データ - 基本情報
        print(f"\n🏗️ 構造基本情報:")
        print(f"   構造種別: {data.get('structure_type', 'N/A')}")
        print(f"   主要用途: {data.get('primary_use', 'N/A')}")
        print(f"   階数: {data.get('floors', 'N/A')}")
        print(f"   延床面積: {data.get('total_floor_area', 'N/A')}")

        # 抽出データ - 法的・技術情報
        print(f"\n📜 法的・技術情報:")
        print(f"   性能要件: {data.get('performance_requirements', 'N/A')}")
        print(f"   計算ルート: {data.get('structural_calc_route', 'N/A')}")
        print(f"   ルート選定理由: {data.get('route_reasoning', 'N/A')}")
        print(f"   基礎形式: {data.get('foundation_type', 'N/A')}")
        print(f"   設計特徴: {data.get('design_features', 'N/A')}")
        print(f"   耐力要素: {data.get('lateral_resistance', 'N/A')}")

        # 抽出データ - プロジェクト条件
        print(f"\n🌍 プロジェクト条件:")
        print(f"   地域条件: {data.get('regional_conditions', 'N/A')}")
        print(f"   地盤状況: {data.get('ground_condition', 'N/A')}")
        print(f"   検査機関: {data.get('inspection_agency', 'N/A')}")

        # 抽出データ - その他
        print(f"\n📝 その他:")
        project_summary = data.get('project_summary', 'N/A')
        if len(project_summary) > 200:
            print(f"   プロジェクト概要: {project_summary[:200]}...")
        else:
            print(f"   プロジェクト概要: {project_summary}")
        print(f"   計算書日付: {data.get('calc_book_date', 'N/A')}")
        print(f"   使用ソフトウェア: {data.get('software', 'N/A')}")

        print("\n")

    print("=" * 80)
    print(f"✅ 合計 {project_count} 件のデータを確認しました")
    print("=" * 80)

    # サマリー統計
    print("\n📊 データ品質サマリー:")
    collection_ref = db.collection(latest_collection)
    docs = list(collection_ref.stream())

    if docs:
        # 各フィールドの入力率を計算
        fields_to_check = [
            'structure_type',
            'primary_use',
            'floors',
            'total_floor_area',
            'performance_requirements',
            'structural_calc_route',
            'foundation_type',
            'lateral_resistance',
            'ground_condition',
            'project_summary',
            'calc_book_date',
            'software'
        ]

        for field in fields_to_check:
            count = sum(1 for doc in docs if doc.to_dict().get(field) not in [None, '', 'N/A', [], {}])
            percentage = (count / len(docs)) * 100
            print(f"   {field}: {count}/{len(docs)} ({percentage:.0f}%)")

if __name__ == "__main__":
    main()
