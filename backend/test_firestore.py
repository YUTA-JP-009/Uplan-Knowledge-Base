from google.cloud import firestore

# Firestoreクライアント接続テスト
GCP_PROJECT_ID = "uplan-knowledge-base"

try:
    print("🔌 Firestoreに接続しています...")
    db = firestore.Client(project=GCP_PROJECT_ID, database="uplan")

    print("✅ 接続成功！")
    print(f"プロジェクトID: {GCP_PROJECT_ID}")
    print(f"データベース名: uplan")

    # コレクション一覧を取得
    print("\n📂 コレクション一覧:")
    collections = db.collections()

    collection_count = 0
    for collection in collections:
        collection_count += 1
        print(f"  - {collection.id}")

        # 各コレクションのドキュメント数を取得
        docs = collection.limit(5).stream()
        doc_count = sum(1 for _ in docs)
        if doc_count > 0:
            print(f"    (ドキュメント数: {doc_count}件以上)")

    if collection_count == 0:
        print("  (コレクションが見つかりませんでした)")
    else:
        print(f"\n合計 {collection_count} 個のコレクションが見つかりました")

except Exception as e:
    print(f"❌ エラーが発生しました: {e}")
    print("\n確認事項:")
    print("1. GCP認証が完了しているか: gcloud auth application-default login")
    print("2. プロジェクトIDが正しいか: uplan-knowledge-base")
    print("3. Firestoreデータベース 'uplan' が存在するか")
