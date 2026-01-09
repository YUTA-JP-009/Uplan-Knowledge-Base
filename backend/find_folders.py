"""
OneDrive上のフォルダを探索して正しいパスを見つける
"""

import msal
import requests
import json
from google.cloud import secretmanager

GCP_PROJECT_ID = "uplan-knowledge-base"
TARGET_USER_EMAIL = "info@uplan2018.onmicrosoft.com"

def get_secret(secret_id):
    """Secret Managerからシークレットを取得"""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{GCP_PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")

def get_access_token():
    """Microsoft Graph API用のアクセストークンを取得"""
    try:
        client_id = get_secret("MS_CLIENT_ID")
        tenant_id = get_secret("MS_TENANT_ID")
        client_secret = get_secret("MS_CLIENT_SECRET")

        authority = f"https://login.microsoftonline.com/{tenant_id}"
        app = msal.ConfidentialClientApplication(client_id, authority=authority, client_credential=client_secret)
        result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        return result.get("access_token")
    except Exception as e:
        print(f"❌ 認証エラー: {e}")
        return None

def search_folders(access_token, search_terms):
    """フォルダを検索"""
    headers = {"Authorization": f"Bearer {access_token}"}

    print(f"\n🔍 検索中: {search_terms}")

    # Microsoft Graph APIのsearch endpoint
    search_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/root/search(q='{search_terms}')"

    try:
        response = requests.get(search_url, headers=headers, timeout=30)
        response.raise_for_status()
        results = response.json().get('value', [])

        folders = [item for item in results if 'folder' in item]

        print(f"✅ {len(folders)}件のフォルダが見つかりました\n")

        for folder in folders[:10]:  # 最初の10件のみ表示
            path = folder.get('parentReference', {}).get('path', '')
            # /drive/root: を削除
            if path.startswith('/drive/root:'):
                path = path[12:]
            full_path = f"{path}/{folder['name']}" if path else folder['name']
            print(f"  📂 {full_path}")
            print(f"     ID: {folder['id']}")

    except Exception as e:
        print(f"❌ エラー: {e}")

def main():
    """メイン処理"""
    print("=" * 80)
    print("🔍 OneDriveフォルダ探索")
    print("=" * 80)

    token = get_access_token()
    if not token:
        print("❌ 認証失敗")
        return

    # 各案件を検索
    search_terms_list = [
        "松下邸",
        "フルイチ様オフィス",
        "豊中の貸倉庫",
        "三田2丁目AP",
        "小さなお葬式 名古屋昭和区"
    ]

    for search_term in search_terms_list:
        search_folders(token, search_term)

if __name__ == "__main__":
    main()
