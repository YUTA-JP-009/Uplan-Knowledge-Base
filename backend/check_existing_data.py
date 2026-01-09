"""
Firestoreに保存されている既存データを確認してパスを調べる
"""

from google.cloud import firestore

GCP_PROJECT_ID = "uplan-knowledge-base"

def main():
    """既存データを確認"""
    print("=" * 80)
    print("📊 Firestore既存データ確認")
    print("=" * 80)

    db = firestore.Client(project=GCP_PROJECT_ID, database="uplan")

    # Projects_2026_01_07コレクションからサンプルデータを取得
    collection_ref = db.collection("Projects_2026_01_07")

    # 最新の10件を取得
    docs = collection_ref.order_by("extracted_at", direction=firestore.Query.DESCENDING).limit(10).stream()

    print("\n📋 最新10件のデータ:\n")

    for i, doc in enumerate(docs, 1):
        data = doc.to_dict()
        print(f"{i}. {doc.id}")
        print(f"   物件名: {data.get('project_name', 'N/A')}")
        print(f"   取引先: {data.get('client_name', 'N/A')}")
        print(f"   フォルダ名: {data.get('folder_name', 'N/A')}")
        print(f"   フォルダパス: {data.get('folder_path', 'N/A')}")
        print(f"   ファイルID: {data.get('file_id', 'N/A')}")
        print(f"   URL: {data.get('folder_url', 'N/A')[:80]}..." if data.get('folder_url') else "")
        print()

    # 特定の取引先でフィルタして探す
    print("\n🔍 特定の取引先を検索:\n")

    search_clients = [
        "多田建築設計事務所",
        "Luce建築設計事務所",
        "PROCESS5 DESIGN",
        "アゼリアホーム",
        "A1・ID設計"
    ]

    for client in search_clients:
        print(f"📂 {client}:")
        client_docs = collection_ref.where("client_name", "==", client).limit(3).stream()

        found = False
        for doc in client_docs:
            found = True
            data = doc.to_dict()
            print(f"   ✅ {data.get('project_name', 'N/A')}")
            print(f"      パス: {data.get('folder_path', 'N/A')}")

        if not found:
            print(f"   ⚠️ データが見つかりません")
        print()

if __name__ == "__main__":
    main()
