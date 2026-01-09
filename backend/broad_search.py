"""
より広範囲な検索を実行
"""

import msal
import requests
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

def search_variations(access_token, base_keywords):
    """複数のバリエーションで検索"""
    headers = {"Authorization": f"Bearer {access_token}"}

    for keyword in base_keywords:
        print(f"\n🔍 検索キーワード: {keyword}")

        search_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/root/search(q='{keyword}')"

        try:
            response = requests.get(search_url, headers=headers, timeout=30)
            response.raise_for_status()
            results = response.json().get('value', [])

            print(f"   検索結果: {len(results)}件")

            # フォルダのみを表示
            folders = [item for item in results if 'folder' in item]
            print(f"   フォルダ: {len(folders)}件")

            if folders:
                print(f"   最初の5件:")
                for i, folder in enumerate(folders[:5], 1):
                    name = folder.get('name', '')
                    parent_path = folder.get('parentReference', {}).get('path', '')
                    if '/drive/root:' in parent_path:
                        parent_path = parent_path.replace('/drive/root:', '')
                    full_path = f"{parent_path}/{name}".lstrip('/')
                    print(f"      {i}. {name}")
                    print(f"         パス: {full_path}")

        except Exception as e:
            print(f"   ❌ エラー: {e}")

def main():
    """メイン処理"""
    print("=" * 80)
    print("🔍 広範囲検索")
    print("=" * 80)

    token = get_access_token()
    if not token:
        print("❌ 認証失敗")
        return

    # 様々なバリエーションで検索
    search_variations(token, [
        "三田",
        "2024009",
        "アゼリアホーム",
        "小さなお葬式",
        "名古屋",
        "昭和区",
        "2025012",
        "A1・ID",
        "A1",
        "ID設計"
    ])

if __name__ == "__main__":
    main()
