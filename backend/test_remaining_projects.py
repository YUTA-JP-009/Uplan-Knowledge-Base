"""
残りの案件をテスト処理（三田2丁目AP、小さなお葬式、松下邸リトライ）
"""

import time
import sys

# 既存のスクリプトをインポート
from test_with_file_ids import *

# 残りの案件キーワード
REMAINING_KEYWORDS = [
    "三田2丁目AP",
    "小さなお葬式",
    "松下邸"  # リトライ
]

def main():
    """メイン処理"""
    print("=" * 80)
    print("🧪 残り案件テスト実行")
    print("=" * 80)

    # 前回のコレクション名を再利用
    global TEST_COLLECTION
    TEST_COLLECTION = "Projects_Test_20260108_182447"

    print(f"📊 テストコレクション: {TEST_COLLECTION}")
    print("=" * 80)

    overall_start = time.time()

    # Firestoreから既存データを取得
    db = firestore.Client(project=GCP_PROJECT_ID, database="uplan")
    collection_ref = db.collection("Projects_2026_01_07")

    test_projects = []

    print("\n🔍 対象案件を検索中...")
    for keyword in REMAINING_KEYWORDS:
        docs = collection_ref.order_by("extracted_at", direction=firestore.Query.DESCENDING).limit(100).stream()

        for doc in docs:
            data = doc.to_dict()
            project_name = data.get('project_name', '')
            if keyword in project_name:
                test_projects.append({
                    'doc_id': doc.id,
                    'project_name': project_name,
                    'file_id': data.get('file_id'),
                    'folder_path': data.get('folder_path', ''),
                    'folder_name': data.get('folder_name', ''),
                    'client_name': data.get('client_name', 'N/A')
                })
                print(f"   ✅ 見つかりました: {project_name}")
                break

    print(f"\n📂 対象案件数: {len(test_projects)}\n")

    if len(test_projects) == 0:
        print("❌ 対象案件が見つかりませんでした")
        return

    # 認証
    token = get_access_token()
    if not token:
        print("❌ 認証失敗のため終了します")
        return

    results = []

    # 各案件を順次処理（レート制限対策で待ち時間を長く）
    for i, project_info in enumerate(test_projects, 1):
        print(f"\n[{i}/{len(test_projects)}] {project_info['project_name']}")
        print(f"   取引先: {project_info['client_name']}")

        # レート制限対策: 最初の案件の前に少し待つ
        if i == 1:
            print("   ⏳ レート制限対策のため30秒待機...")
            time.sleep(30)

        success, message, elapsed = process_single_project_by_file_id(project_info, token, TARGET_USER_EMAIL)

        results.append({
            "project": project_info['project_name'],
            "success": success,
            "message": message,
            "elapsed": elapsed
        })

        if success:
            print(f"   ✅ {message} (処理時間: {elapsed:.1f}秒)")
        else:
            print(f"   ❌ {message} (処理時間: {elapsed:.1f}秒)")

        # 次の案件の前に待機（レート制限対策）
        if i < len(test_projects):
            print("   ⏳ 次の案件まで60秒待機...")
            time.sleep(60)

    overall_elapsed = time.time() - overall_start

    # 結果サマリー
    print("\n" + "=" * 80)
    print("📊 テスト結果サマリー")
    print("=" * 80)

    success_count = sum(1 for r in results if r["success"])
    total_processing_time = sum(r["elapsed"] for r in results)
    avg_time = total_processing_time / len(results) if results else 0

    print(f"✅ 成功: {success_count}/{len(test_projects)}件")
    print(f"❌ 失敗: {len(test_projects) - success_count}/{len(test_projects)}件")
    print(f"⏱️  総実行時間: {overall_elapsed:.1f}秒 ({overall_elapsed/60:.1f}分)")
    print(f"⏱️  平均処理時間/件: {avg_time:.1f}秒")
    print(f"💾 保存先: Firestore > {TEST_COLLECTION}")
    print("=" * 80)

    # 詳細結果
    print("\n📋 詳細結果:")
    for i, result in enumerate(results, 1):
        status = "✅" if result["success"] else "❌"
        print(f"{i}. {status} {result['project']} - {result['message']} ({result['elapsed']:.1f}秒)")

    # 全体の成功率
    print(f"\n🎯 今回の成功率: {success_count}/{len(test_projects)} ({success_count/len(test_projects)*100:.1f}%)")

if __name__ == "__main__":
    main()
