"""
見つかった案件を処理
- 2025012_（仮称）小さなお葬式 名古屋昭和区ホール
- 279 A1・ID設計 フォルダ配下の案件
"""

import time
from search_and_process import *

# 特定のフォルダ名で検索
SPECIFIC_FOLDERS = [
    "2025012_（仮称）小さなお葬式 名古屋昭和区ホール",
    "279 A1・ID設計"
]

def find_specific_folder(access_token, folder_name):
    """特定のフォルダ名で検索"""
    headers = {"Authorization": f"Bearer {access_token}"}

    print(f"\n🔍 検索中: {folder_name}")

    search_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/root/search(q='{folder_name}')"

    try:
        response = requests.get(search_url, headers=headers, timeout=30)
        response.raise_for_status()
        results = response.json().get('value', [])

        folders = [item for item in results if 'folder' in item and item.get('name') == folder_name]

        if folders:
            print(f"✅ 見つかりました: {len(folders)}件")
            folder = folders[0]  # 最初の一致
            parent_path = folder.get('parentReference', {}).get('path', '')
            if '/drive/root:' in parent_path:
                parent_path = parent_path.replace('/drive/root:', '')
            full_path = f"{parent_path}/{folder['name']}".lstrip('/')

            return {
                'id': folder['id'],
                'name': folder['name'],
                'path': full_path,
                'webUrl': folder.get('webUrl', '')
            }
        else:
            print(f"⚠️ 見つかりませんでした")
            return None

    except Exception as e:
        print(f"❌ 検索エラー: {e}")
        return None

def find_structure_docs_in_folder(access_token, parent_folder_id):
    """親フォルダ内から構造設計図書フォルダを探す（再帰的）"""
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{parent_folder_id}/children"
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        items = response.json().get('value', [])

        structure_folders = []

        for item in items:
            if 'folder' in item:
                folder_name = item['name']

                # 構造設計図書フォルダを探す
                if ('構造設計図書' in folder_name or '構造計算書' in folder_name) and '○' not in folder_name:
                    parent_path = item.get('parentReference', {}).get('path', '')
                    if '/drive/root:' in parent_path:
                        parent_path = parent_path.replace('/drive/root:', '')
                    full_path = f"{parent_path}/{folder_name}".lstrip('/')

                    structure_folders.append({
                        'id': item['id'],
                        'name': folder_name,
                        'path': full_path,
                        'webUrl': item.get('webUrl', '')
                    })
                else:
                    # サブフォルダを再帰的に探索
                    sub_folders = find_structure_docs_in_folder(access_token, item['id'])
                    structure_folders.extend(sub_folders)

        return structure_folders

    except Exception as e:
        print(f"⚠️ サブフォルダ探索エラー: {e}")
        return []

def main():
    """メイン処理"""
    print("=" * 80)
    print("🔍 見つかった案件を処理")
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

    # 小さなお葬式のフォルダを探す
    osousiki_folder = find_specific_folder(token, SPECIFIC_FOLDERS[0])
    if osousiki_folder:
        print(f"   パス: {osousiki_folder['path']}")

        # このフォルダ内の構造設計図書フォルダを探す
        print(f"   🔍 構造設計図書フォルダを探索中...")
        structure_folders = find_structure_docs_in_folder(token, osousiki_folder['id'])

        if structure_folders:
            print(f"   ✅ {len(structure_folders)}件の構造設計図書フォルダが見つかりました")
            for sf in structure_folders:
                print(f"      📂 {sf['name']}")
                all_target_folders.append(sf)
        else:
            # 構造設計図書フォルダがない場合は親フォルダを使う
            print(f"   ⚠️ 構造設計図書フォルダが見つかりません。親フォルダを使用します。")
            all_target_folders.append(osousiki_folder)

    # A1・ID設計フォルダを探す
    a1id_folder = find_specific_folder(token, SPECIFIC_FOLDERS[1])
    if a1id_folder:
        print(f"   パス: {a1id_folder['path']}")

        # このフォルダ内の案件フォルダを探す
        print(f"   🔍 案件フォルダを探索中...")
        structure_folders = find_structure_docs_in_folder(token, a1id_folder['id'])

        if structure_folders:
            print(f"   ✅ {len(structure_folders)}件の構造設計図書フォルダが見つかりました")
            # 「小さなお葬式」を含むものだけを選択
            for sf in structure_folders:
                if '小さなお葬式' in sf['path'] or '名古屋昭和区' in sf['path']:
                    print(f"      📂 {sf['name']}")
                    all_target_folders.append(sf)

    if not all_target_folders:
        print("\n❌ 処理対象フォルダが見つかりませんでした")
        return

    print(f"\n📂 処理対象: {len(all_target_folders)}件")

    results = []

    # 各フォルダを処理
    for i, folder_info in enumerate(all_target_folders, 1):
        print(f"\n[{i}/{len(all_target_folders)}] {folder_info['name']}")

        # レート制限対策
        if i > 1:
            print("   ⏳ レート制限対策のため60秒待機...")
            time.sleep(60)
        else:
            print("   ⏳ 初回実行前に30秒待機...")
            time.sleep(30)

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
