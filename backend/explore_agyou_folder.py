"""
□あ行フォルダを探索してアゼリアホームを探す
"""

import msal
import requests
from google.cloud import secretmanager

GCP_PROJECT_ID = 'uplan-knowledge-base'
TARGET_USER_EMAIL = 'info@uplan2018.onmicrosoft.com'

def get_secret(secret_id):
    client = secretmanager.SecretManagerServiceClient()
    name = f'projects/{GCP_PROJECT_ID}/secrets/{secret_id}/versions/latest'
    response = client.access_secret_version(request={'name': name})
    return response.payload.data.decode('UTF-8')

def get_access_token():
    client_id = get_secret('MS_CLIENT_ID')
    tenant_id = get_secret('MS_TENANT_ID')
    client_secret = get_secret('MS_CLIENT_SECRET')
    authority = f'https://login.microsoftonline.com/{tenant_id}'
    app = msal.ConfidentialClientApplication(client_id, authority=authority, client_credential=client_secret)
    result = app.acquire_token_for_client(scopes=['https://graph.microsoft.com/.default'])
    return result.get('access_token')

def explore_folder(access_token, folder_path):
    """指定パスのフォルダを探索"""
    headers = {'Authorization': f'Bearer {access_token}'}

    print(f'\n🔍 探索: {folder_path}')

    # パスからフォルダを取得
    url = f'https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/root:/{folder_path}'

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        folder = response.json()

        print(f'   ✅ フォルダ見つかりました')
        print(f'   ID: {folder["id"]}')

        # 子フォルダを取得
        children_url = f'https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{folder["id"]}/children'
        response = requests.get(children_url, headers=headers, timeout=30)
        response.raise_for_status()
        children = response.json().get('value', [])

        folders = [c for c in children if 'folder' in c]
        print(f'   📂 サブフォルダ数: {len(folders)}件')

        # A00698またはアゼリアを含むフォルダを探す
        for child in folders:
            name = child.get('name', '')
            if 'A00698' in name or 'アゼリア' in name:
                print(f'\n   🎯 ターゲットフォルダ見つかりました!')
                print(f'      名前: {name}')
                print(f'      ID: {child["id"]}')
                return child

        # 見つからなければ全フォルダをリスト表示
        print(f'\n   📋 サブフォルダ一覧（最初の20件）:')
        for child in folders[:20]:
            print(f'      - {child.get("name", "")}')

        return None

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f'   ⚠️ フォルダが見つかりません（404）')
        else:
            print(f'   ❌ エラー: {e}')
        return None
    except Exception as e:
        print(f'   ❌ エラー: {e}')
        return None

def main():
    print('=' * 80)
    print('📂 □あ行フォルダ探索')
    print('=' * 80)

    token = get_access_token()
    if not token:
        print('❌ 認証失敗')
        return

    # 木造（在来軸組）/□あ行 フォルダを探索
    paths_to_try = [
        "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□あ行",
        "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□Ａ行",
    ]

    for path in paths_to_try:
        result = explore_folder(token, path)
        if result:
            print(f'\n✅ アゼリアホームフォルダを特定しました')
            print(f'   次は、このフォルダ内の2024009案件を探索します')
            break

if __name__ == '__main__':
    main()
