"""
SharePoint URLから直接フォルダを取得して処理する
"""

import time
import re
from urllib.parse import unquote
from search_and_process import *

def extract_folder_path_from_url(sharepoint_url):
    """SharePoint URLからフォルダパスを抽出"""
    # URLデコード
    decoded_url = unquote(sharepoint_url)

    # "Documents/"以降のパスを抽出
    if '/Documents/' in decoded_url:
        path = decoded_url.split('/Documents/')[1]
        # クエリパラメータを除去
        if '?' in path:
            path = path.split('?')[0]
        return path

    return None

def get_folder_by_path(access_token, folder_path):
    """パスからフォルダ情報を取得"""
    headers = {"Authorization": f"Bearer {access_token}"}

    print(f"\n🔍 フォルダパス: {folder_path}")

    # Microsoft Graph APIでフォルダを取得
    # パス内のシングルクォートをエスケープ
    escaped_path = folder_path.replace("'", "''")
    url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/root:/{escaped_path}"

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        folder = response.json()

        print(f"   ✅ フォルダ見つかりました")
        print(f"   名前: {folder.get('name', '')}")
        print(f"   ID: {folder.get('id', '')}")

        # webUrlも取得
        web_url = folder.get('webUrl', '')

        return {
            'id': folder['id'],
            'name': folder['name'],
            'path': folder_path,
            'webUrl': web_url
        }

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f"   ❌ フォルダが見つかりません（404）")
        else:
            print(f"   ❌ HTTPエラー: {e}")
        return None
    except Exception as e:
        print(f"   ❌ エラー: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    """メイン処理"""
    print("=" * 80)
    print("📂 SharePoint URLから案件を処理")
    print("=" * 80)
    print(f"📊 保存先コレクション: {TEST_COLLECTION}")
    print("=" * 80)

    # テストURL（小さなお葬式 名古屋昭和区ホール）
    test_url = "https://uplan2018-my.sharepoint.com/personal/info_uplan2018_onmicrosoft_com/Documents/001_%EF%BC%B5%27plan_%E5%85%A8%E7%A4%BE/01.%E6%A7%8B%E9%80%A0%E8%A8%AD%E8%A8%88/01.%E6%9C%A8%E9%80%A0%EF%BC%88%E5%9C%A8%E6%9D%A5%E8%BB%B8%E7%B5%84%EF%BC%89/%E2%96%A1%EF%BC%A1%E8%A1%8C/279%20A1%E3%83%BBID%E8%A8%AD%E8%A8%88/2025012_%EF%BC%88%E4%BB%AE%E7%A7%B0%EF%BC%89%E5%B0%8F%E3%81%95%E3%81%AA%E3%81%8A%E8%91%AC%E5%BC%8F%20%E5%90%8D%E5%8F%A4%E5%B1%8B%E6%98%AD%E5%92%8C%E5%8C%BA%E3%83%9B%E3%83%BC%E3%83%AB/09.%E6%88%90%E6%9E%9C%E7%89%A9/%E7%B4%8D%E5%93%81%E6%99%82/20251128_%E3%80%90%E4%BA%8B%E5%89%8D%E3%80%91%EF%BC%88%E4%BB%AE%E7%A7%B0%EF%BC%89%E5%B0%8F%E3%81%95%E3%81%AA%E3%81%8A%E8%91%AC%E5%BC%8F%20%E5%90%8D%E5%8F%A4%E5%B1%8B%E6%98%AD%E5%92%8C%E5%8C%BA%E3%83%9B%E3%83%BC%E3%83%AB_%E6%A7%8B%E9%80%A0%E8%A8%AD%E8%A8%88%E5%9B%B3%E6%9B%B8%E4%B8%80%E5%BC%8F"

    overall_start = time.time()

    # 認証
    token = get_access_token()
    if not token:
        print("❌ 認証失敗のため終了します")
        return

    # URLからフォルダパスを抽出
    print("\n📋 URL解析中...")
    folder_path = extract_folder_path_from_url(test_url)

    if not folder_path:
        print("❌ URLからパスを抽出できませんでした")
        return

    print(f"✅ パス抽出成功")

    # フォルダ情報を取得
    folder_info = get_folder_by_path(token, folder_path)

    if not folder_info:
        print("\n❌ フォルダを取得できませんでした")
        return

    print(f"\n✅ フォルダ取得成功")

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
        print(f"   物件名: 小さなお葬式 名古屋昭和区ホール")
        print(f"   取引先: A1・ID設計")
        print(f"   フォルダ: {folder_info['name']}")
    else:
        print(f"❌ 失敗: {message}")
        print(f"⏱️  処理時間: {elapsed:.1f}秒")

    print("=" * 80)

if __name__ == "__main__":
    main()
