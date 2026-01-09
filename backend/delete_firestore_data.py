"""
Firestoreのコレクション内の全ドキュメントを削除するスクリプト
Parallel_Test_2026_01_06 コレクションの過去データを削除
"""

from google.cloud import firestore

GCP_PROJECT_ID = "uplan-knowledge-base"
COLLECTION_NAME = "Projects_2026_01_07"

def delete_collection():
    """指定されたコレクションの全ドキュメントを削除"""
    db = firestore.Client(project=GCP_PROJECT_ID, database="uplan")
    collection_ref = db.collection(COLLECTION_NAME)

    # 全ドキュメントを取得
    docs = collection_ref.stream()

    deleted_count = 0
    doc_list = []

    # まずドキュメント一覧を取得
    for doc in docs:
        doc_list.append(doc)

    print(f"📊 削除対象: {len(doc_list)}件のドキュメント")
    print(f"🗑️  コレクション: {COLLECTION_NAME}")
    print()

    if len(doc_list) == 0:
        print("✨ 削除対象のドキュメントはありません")
        return

    # 確認
    print("削除するドキュメント:")
    for doc in doc_list:
        data = doc.to_dict()
        project_name = data.get('project_name', 'N/A')
        folder_name = data.get('folder_name', 'N/A')
        print(f"  - {doc.id}: {project_name} ({folder_name})")

    print()
    print(f"⚠️  自動削除モード: {len(doc_list)}件を削除します")

    # 削除実行
    print("\n🗑️  削除を開始します...")
    for doc in doc_list:
        doc.reference.delete()
        deleted_count += 1
        print(f"  ✅ 削除: {doc.id} ({deleted_count}/{len(doc_list)})")

    print(f"\n✅ {deleted_count}件のドキュメントを削除しました")

if __name__ == "__main__":
    print("=" * 80)
    print("🗑️  Firestore データ削除スクリプト")
    print("=" * 80)
    delete_collection()
    print("=" * 80)
