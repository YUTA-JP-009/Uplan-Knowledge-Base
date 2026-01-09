"""
A1・ID設計フォルダから小さなお葬式案件を直接探索して処理
"""

import time
from search_and_process import *

def find_osousiki_project(access_token):
    """A1・ID設計フォルダから小さなお葬式案件を探す"""
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        # ステップ1: □Ａ行フォルダを取得
        print("\n🔍 ステップ1: □Ａ行フォルダを取得")
        a_gyou_path = "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□Ａ行"
        url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/root:/{a_gyou_path}"
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        a_gyou_folder = response.json()
        print(f"   ✅ □Ａ行フォルダ取得成功")

        # ステップ2: A1・ID設計フォルダを探す
        print("\n🔍 ステップ2: A1・ID設計フォルダを探索")
        children_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{a_gyou_folder['id']}/children"
        response = requests.get(children_url, headers=headers, timeout=30)
        response.raise_for_status()
        children = response.json().get('value', [])

        a1id_folder = None
        for child in children:
            if 'folder' in child and '279 A1' in child.get('name', ''):
                a1id_folder = child
                print(f"   ✅ A1・ID設計フォルダ見つかりました: {child.get('name', '')}")
                break

        if not a1id_folder:
            print("   ⚠️ A1・ID設計フォルダが見つかりません")
            return None

        # ステップ3: 2025012案件フォルダを探す
        print("\n🔍 ステップ3: 2025012案件フォルダを探索")
        project_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{a1id_folder['id']}/children"
        response = requests.get(project_url, headers=headers, timeout=30)
        response.raise_for_status()
        projects = response.json().get('value', [])

        osousiki_folder = None
        for proj in projects:
            if 'folder' in proj:
                proj_name = proj.get('name', '')
                if '2025012' in proj_name and '小さなお葬式' in proj_name:
                    osousiki_folder = proj
                    print(f"   ✅ 案件フォルダ見つかりました: {proj_name}")
                    break

        if not osousiki_folder:
            print("   ⚠️ 小さなお葬式案件フォルダが見つかりません")
            print("   📋 A1・ID設計配下のフォルダ:")
            for proj in projects[:10]:
                if 'folder' in proj:
                    print(f"      - {proj.get('name', '')}")
            return None

        # ステップ4: 09.成果物フォルダを探す
        print("\n🔍 ステップ4: 09.成果物フォルダを探索")
        seika_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{osousiki_folder['id']}/children"
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

        # ステップ5: 納品時フォルダを探す
        print("\n🔍 ステップ5: 納品時フォルダを探索")
        nouhin_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{seika_folder['id']}/children"
        response = requests.get(nouhin_url, headers=headers, timeout=30)
        response.raise_for_status()
        nouhin_items = response.json().get('value', [])

        nouhin_folder = None
        for item in nouhin_items:
            if 'folder' in item and '納品時' in item.get('name', ''):
                nouhin_folder = item
                print(f"   ✅ 納品時フォルダ見つかりました")
                break

        if not nouhin_folder:
            print("   ⚠️ 納品時フォルダが見つかりません")
            print("   📋 成果物フォルダ配下:")
            for item in nouhin_items:
                print(f"      - {item.get('name', '')}")
            return None

        # ステップ6: 構造設計図書一式フォルダを探す
        print("\n🔍 ステップ6: 構造設計図書一式フォルダを探索")
        docs_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{nouhin_folder['id']}/children"
        response = requests.get(docs_url, headers=headers, timeout=30)
        response.raise_for_status()
        docs_items = response.json().get('value', [])

        docs_folder = None
        for item in docs_items:
            if 'folder' in item:
                item_name = item.get('name', '')
                if '20251128' in item_name and '構造設計図書' in item_name:
                    docs_folder = item
                    print(f"   ✅ 構造設計図書フォルダ見つかりました: {item_name}")
                    break

        if not docs_folder:
            print("   ⚠️ 構造設計図書フォルダが見つかりません")
            print("   📋 納品時フォルダ配下:")
            for item in docs_items:
                print(f"      - {item.get('name', '')}")
            return None

        # パスを構築
        parent_path = docs_folder.get('parentReference', {}).get('path', '')
        if '/drive/root:' in parent_path:
            parent_path = parent_path.replace('/drive/root:', '')
        full_path = f"{parent_path}/{docs_folder['name']}".lstrip('/')

        return {
            'id': docs_folder['id'],
            'name': docs_folder['name'],
            'path': full_path,
            'webUrl': docs_folder.get('webUrl', '')
        }

    except Exception as e:
        print(f"❌ エラー: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    """メイン処理"""
    print("=" * 80)
    print("📂 小さなお葬式 名古屋昭和区ホール案件の抽出")
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
    folder_info = find_osousiki_project(token)

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
        print("\n📝 案件情報:")
        print(f"   物件名: （仮称）小さなお葬式 名古屋昭和区ホール")
        print(f"   取引先: A1・ID設計")
        print(f"   フォルダ: {folder_info['name']}")
    else:
        print(f"❌ 失敗: {message}")
        print(f"⏱️  処理時間: {elapsed:.1f}秒")

    print("=" * 80)

if __name__ == "__main__":
    main()
