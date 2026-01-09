"""
最終試行: 検索結果から直接IDを取得して処理
"""

import time
from search_and_process import *

def get_all_search_results(access_token, keyword):
    """検索結果をすべて取得"""
    headers = {"Authorization": f"Bearer {access_token}"}

    search_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/root/search(q='{keyword}')"

    try:
        response = requests.get(search_url, headers=headers, timeout=30)
        response.raise_for_status()
        results = response.json().get('value', [])
        return results
    except Exception as e:
        print(f"❌ 検索エラー: {e}")
        return []

def main():
    """メイン処理"""
    print("=" * 80)
    print("🔍 最終試行: 検索結果から直接処理")
    print("=" * 80)
    print(f"📊 保存先コレクション: {TEST_COLLECTION}")
    print("=" * 80)

    overall_start = time.time()

    # 認証
    token = get_access_token()
    if not token:
        print("❌ 認証失敗のため終了します")
        return

    all_target_folders = []

    # 1. 小さなお葬式を検索
    print("\n🔍 検索中: 2025012")
    results = get_all_search_results(token, "2025012")

    for item in results:
        if 'folder' in item:
            name = item.get('name', '')
            if '小さなお葬式' in name and '名古屋' in name:
                parent_path = item.get('parentReference', {}).get('path', '')
                if '/drive/root:' in parent_path:
                    parent_path = parent_path.replace('/drive/root:', '')
                full_path = f"{parent_path}/{name}".lstrip('/')

                print(f"   ✅ 見つかりました: {name}")
                print(f"      パス: {full_path}")

                all_target_folders.append({
                    'id': item['id'],
                    'name': name,
                    'path': full_path,
                    'webUrl': item.get('webUrl', '')
                })
                break

    # 2. A1・ID設計配下の小さなお葬式を探す
    print("\n🔍 検索中: A1・ID + 小さなお葬式")
    results = get_all_search_results(token, "ID設計")

    # まずA1・ID設計フォルダを見つける
    a1id_folders = [item for item in results if 'folder' in item and '279 A1・ID設計' in item.get('name', '')]

    if a1id_folders:
        a1id_folder = a1id_folders[0]
        print(f"   ✅ A1・ID設計フォルダ見つかりました")

        # その配下を探索
        try:
            headers = {"Authorization": f"Bearer {token}"}
            children_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{a1id_folder['id']}/children"
            response = requests.get(children_url, headers=headers, timeout=30)
            response.raise_for_status()
            children = response.json().get('value', [])

            for child in children:
                if 'folder' in child:
                    child_name = child.get('name', '')
                    if '2025012' in child_name or '小さなお葬式' in child_name:
                        print(f"   ✅ 案件フォルダ見つかりました: {child_name}")

                        # さらにその配下の構造設計図書フォルダを探す
                        sub_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{child['id']}/children"
                        sub_response = requests.get(sub_url, headers=headers, timeout=30)
                        if sub_response.status_code == 200:
                            sub_items = sub_response.json().get('value', [])

                            # 09.成果物フォルダを探す
                            for sub_item in sub_items:
                                if 'folder' in sub_item and '09.成果物' in sub_item.get('name', ''):
                                    print(f"      📂 成果物フォルダ見つかりました")

                                    # さらにその配下の構造設計図書フォルダ
                                    成果物_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{sub_item['id']}/children"
                                    成果物_response = requests.get(成果物_url, headers=headers, timeout=30)
                                    if 成果物_response.status_code == 200:
                                        成果物_items = 成果物_response.json().get('value', [])

                                        for 成果物_item in 成果物_items:
                                            if 'folder' in 成果物_item:
                                                成果物_name = 成果物_item.get('name', '')
                                                if '納品時' in 成果物_name:
                                                    print(f"         📂 納品時フォルダ見つかりました")

                                                    # 納品時フォルダの中の構造設計図書
                                                    納品時_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{成果物_item['id']}/children"
                                                    納品時_response = requests.get(納品時_url, headers=headers, timeout=30)
                                                    if 納品時_response.status_code == 200:
                                                        納品時_items = 納品時_response.json().get('value', [])

                                                        for 納品時_item in 納品時_items:
                                                            if 'folder' in 納品時_item:
                                                                if '構造設計図書' in 納品時_item.get('name', ''):
                                                                    parent_path = 納品時_item.get('parentReference', {}).get('path', '')
                                                                    if '/drive/root:' in parent_path:
                                                                        parent_path = parent_path.replace('/drive/root:', '')
                                                                    full_path = f"{parent_path}/{納品時_item['name']}".lstrip('/')

                                                                    print(f"            ✅ 構造設計図書フォルダ見つかりました")

                                                                    all_target_folders.append({
                                                                        'id': 納品時_item['id'],
                                                                        'name': 納品時_item['name'],
                                                                        'path': full_path,
                                                                        'webUrl': 納品時_item.get('webUrl', '')
                                                                    })

        except Exception as e:
            print(f"   ⚠️ エラー: {e}")

    if not all_target_folders:
        print("\n❌ 処理対象フォルダが見つかりませんでした")
        return

    print(f"\n📂 処理対象: {len(all_target_folders)}件")

    results = []

    # 各フォルダを処理
    for i, folder_info in enumerate(all_target_folders, 1):
        print(f"\n[{i}/{len(all_target_folders)}] {folder_info['name']}")
        print(f"   パス: {folder_info['path']}")

        # レート制限対策
        if i == 1:
            print("   ⏳ 初回実行前に30秒待機...")
            time.sleep(30)
        else:
            print("   ⏳ 次の案件まで60秒待機...")
            time.sleep(60)

        success, message, elapsed = process_folder(folder_info, token, TARGET_USER_EMAIL)

        results.append({
            "folder": folder_info['name'],
            "path": folder_info['path'],
            "success": success,
            "message": message,
            "elapsed": elapsed
        })

        if success:
            print(f"   ✅ {message} (処理時間: {elapsed:.1f}秒)")
        else:
            print(f"   ❌ {message} (処理時間: {elapsed:.1f}秒)")

    overall_elapsed = time.time() - overall_start

    # 結果サマリー
    print("\n" + "=" * 80)
    print("📊 処理結果サマリー")
    print("=" * 80)

    success_count = sum(1 for r in results if r["success"])
    total_processing_time = sum(r["elapsed"] for r in results)
    avg_time = total_processing_time / len(results) if results else 0

    print(f"✅ 成功: {success_count}/{len(results)}件")
    print(f"❌ 失敗: {len(results) - success_count}/{len(results)}件")
    print(f"⏱️  総実行時間: {overall_elapsed:.1f}秒 ({overall_elapsed/60:.1f}分)")
    print(f"⏱️  平均処理時間: {avg_time:.1f}秒/件")
    print(f"💾 保存先: Firestore > {TEST_COLLECTION}")
    print("=" * 80)

    # 詳細結果
    print("\n📋 詳細結果:")
    for i, result in enumerate(results, 1):
        status = "✅" if result["success"] else "❌"
        print(f"{i}. {status} {result['folder']}")
        print(f"   パス: {result['path']}")
        print(f"   結果: {result['message']} ({result['elapsed']:.1f}秒)")

if __name__ == "__main__":
    main()
