"""
三田2丁目AP案件を処理
パス: 01.木造（在来軸組） > □あ行 > A00698アゼリアホーム > 2024009_（仮称）三田2丁目AP／2024010_設計変更 > 09.成果物 > 20240912_(仮称)三田2丁目AP_構造計算書類一式
"""

import time
from search_and_process import *

def find_azalea_home_project(access_token):
    """アゼリアホーム配下の三田2丁目AP案件を探す"""
    headers = {"Authorization": f"Bearer {access_token}"}

    print("\n🔍 ステップ1: アゼリアホームフォルダを検索")
    search_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/root/search(q='A00698アゼリアホーム')"

    try:
        response = requests.get(search_url, headers=headers, timeout=30)
        response.raise_for_status()
        results = response.json().get('value', [])

        azalea_folders = [item for item in results if 'folder' in item and 'A00698アゼリアホーム' in item.get('name', '')]

        if not azalea_folders:
            print("   ⚠️ アゼリアホームフォルダが見つかりません")
            return None

        azalea_folder = azalea_folders[0]
        print(f"   ✅ アゼリアホームフォルダ見つかりました")
        print(f"      ID: {azalea_folder['id']}")

        # ステップ2: 配下の2024009フォルダを探す
        print("\n🔍 ステップ2: 2024009フォルダを探索")
        children_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{azalea_folder['id']}/children"
        response = requests.get(children_url, headers=headers, timeout=30)
        response.raise_for_status()
        children = response.json().get('value', [])

        project_folder = None
        for child in children:
            if 'folder' in child:
                child_name = child.get('name', '')
                if '2024009' in child_name and '三田' in child_name:
                    project_folder = child
                    print(f"   ✅ 案件フォルダ見つかりました: {child_name}")
                    break

        if not project_folder:
            print("   ⚠️ 2024009案件フォルダが見つかりません")
            return None

        # ステップ3: 09.成果物フォルダを探す
        print("\n🔍 ステップ3: 09.成果物フォルダを探索")
        seika_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{project_folder['id']}/children"
        response = requests.get(seika_url, headers=headers, timeout=30)
        response.raise_for_status()
        seika_items = response.json().get('value', [])

        seika_folder = None
        for item in seika_items:
            if 'folder' in item and '09.成果物' in item.get('name', ''):
                seika_folder = item
                print(f"   ✅ 成果物フォルダ見つかりました")
                break

        if not seika_folder:
            print("   ⚠️ 09.成果物フォルダが見つかりません")
            return None

        # ステップ4: 構造計算書類一式フォルダを探す
        print("\n🔍 ステップ4: 構造計算書類一式フォルダを探索")
        calc_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{seika_folder['id']}/children"
        response = requests.get(calc_url, headers=headers, timeout=30)
        response.raise_for_status()
        calc_items = response.json().get('value', [])

        calc_folder = None
        for item in calc_items:
            if 'folder' in item:
                item_name = item.get('name', '')
                if '20240912' in item_name and '三田' in item_name and '構造計算書' in item_name:
                    calc_folder = item
                    print(f"   ✅ 構造計算書類フォルダ見つかりました: {item_name}")
                    break

        if not calc_folder:
            print("   ⚠️ 構造計算書類フォルダが見つかりません")
            print("   📋 成果物フォルダ内のアイテム:")
            for item in calc_items:
                print(f"      - {item.get('name', '')}")
            return None

        # パスを構築
        parent_path = calc_folder.get('parentReference', {}).get('path', '')
        if '/drive/root:' in parent_path:
            parent_path = parent_path.replace('/drive/root:', '')
        full_path = f"{parent_path}/{calc_folder['name']}".lstrip('/')

        return {
            'id': calc_folder['id'],
            'name': calc_folder['name'],
            'path': full_path,
            'webUrl': calc_folder.get('webUrl', '')
        }

    except Exception as e:
        print(f"❌ エラー: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    """メイン処理"""
    print("=" * 80)
    print("📂 三田2丁目AP案件の抽出")
    print("=" * 80)
    print(f"📊 保存先コレクション: {TEST_COLLECTION}")
    print("=" * 80)

    overall_start = time.time()

    # 認証
    token = get_access_token()
    if not token:
        print("❌ 認証失敗のため終了します")
        return

    # フォルダを探す
    folder_info = find_azalea_home_project(token)

    if not folder_info:
        print("\n❌ 対象フォルダが見つかりませんでした")
        return

    print(f"\n✅ 処理対象フォルダ特定完了")
    print(f"   名前: {folder_info['name']}")
    print(f"   パス: {folder_info['path']}")

    # 処理実行
    print(f"\n🚀 処理開始")
    print("   ⏳ レート制限対策のため30秒待機...")
    time.sleep(30)

    success, message, elapsed = process_folder(folder_info, token, TARGET_USER_EMAIL)

    overall_elapsed = time.time() - overall_start

    # 結果表示
    print("\n" + "=" * 80)
    print("📊 処理結果")
    print("=" * 80)

    if success:
        print(f"✅ 成功: {message}")
        print(f"⏱️  処理時間: {elapsed:.1f}秒")
        print(f"⏱️  総実行時間: {overall_elapsed:.1f}秒 ({overall_elapsed/60:.1f}分)")
        print(f"💾 保存先: Firestore > {TEST_COLLECTION}")
    else:
        print(f"❌ 失敗: {message}")
        print(f"⏱️  処理時間: {elapsed:.1f}秒")

    print("=" * 80)

if __name__ == "__main__":
    main()
