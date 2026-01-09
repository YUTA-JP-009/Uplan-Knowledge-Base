"""
テスト結果を確認して処理時間を集計
"""

from google.cloud import firestore
from datetime import datetime

GCP_PROJECT_ID = "uplan-knowledge-base"
TEST_COLLECTION = "Projects_Test_20260108_182447"

def main():
    """テスト結果を確認"""
    print("=" * 80)
    print("📊 テスト結果最終確認")
    print("=" * 80)
    print(f"📂 コレクション: {TEST_COLLECTION}")
    print("=" * 80)

    db = firestore.Client(project=GCP_PROJECT_ID, database="uplan")
    collection_ref = db.collection(TEST_COLLECTION)

    # すべてのドキュメントを取得
    docs = collection_ref.order_by("extracted_at", direction=firestore.Query.DESCENDING).stream()

    print("\n✅ テスト処理完了した案件:\n")

    projects = []
    for i, doc in enumerate(docs, 1):
        data = doc.to_dict()
        projects.append(data)

        project_name = data.get('project_name', 'N/A')
        client_name = data.get('client_name', 'N/A')
        prefecture = data.get('prefecture', 'N/A')
        structure_types = data.get('structure_types', [])
        use_types = data.get('use_types', [])
        total_area = data.get('total_area', 0)
        calc_routes = data.get('calc_routes', [])
        design_features = data.get('design_features', [])
        summary = data.get('summary', '')

        print(f"{i}. 【{project_name}】")
        print(f"   📍 場所: {prefecture}")
        print(f"   🏢 取引先: {client_name}")
        print(f"   🏗️  構造種別: {', '.join(structure_types)}")
        print(f"   🏠 用途: {', '.join(use_types)}")
        print(f"   📐 延べ面積: {total_area}㎡")
        print(f"   📊 計算ルート: {', '.join(calc_routes)}")
        print(f"   ⭐ 設計特記: {', '.join(design_features) if design_features else 'なし'}")
        print(f"   📝 サマリー: {summary[:100]}..." if len(summary) > 100 else f"   📝 サマリー: {summary}")
        print()

    print("=" * 80)
    print(f"✅ 総処理件数: {len(projects)}件")
    print("=" * 80)

    # 統計情報
    if projects:
        print("\n📈 統計情報:")
        print(f"   都道府県:")
        prefectures = {}
        for p in projects:
            pref = p.get('prefecture', '不明')
            prefectures[pref] = prefectures.get(pref, 0) + 1
        for pref, count in sorted(prefectures.items()):
            print(f"      {pref}: {count}件")

        print(f"\n   構造種別:")
        structures = {}
        for p in projects:
            for s in p.get('structure_types', []):
                structures[s] = structures.get(s, 0) + 1
        for s, count in sorted(structures.items()):
            print(f"      {s}: {count}件")

        print(f"\n   用途種別:")
        uses = {}
        for p in projects:
            for u in p.get('use_types', []):
                uses[u] = uses.get(u, 0) + 1
        for u, count in sorted(uses.items()):
            print(f"      {u}: {count}件")

        # 平均処理時間の推定
        # 実際の処理: 松下邸(85.8秒)、フルイチ様(70.9秒)、豊中(103.5秒)
        print(f"\n⏱️  処理時間:")
        print(f"      松下邸: 85.8秒")
        print(f"      フルイチ様オフィス新築工事: 70.9秒")
        print(f"      豊中の貸倉庫兼オフィス: 103.5秒")
        print(f"      平均: 86.7秒/件")

    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()
