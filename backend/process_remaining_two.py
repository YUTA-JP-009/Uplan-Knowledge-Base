"""
残り2件の案件を個別処理
- 豊中の貸倉庫兼オフィス（斜め壁）
- 小さなお葬式（片持ち基礎）
"""

import time
from datetime import datetime
from batch_processor_v4_rate_optimized import *

# 既存のテストコレクション
TEST_COLLECTION = "Projects_V4_Test_20260108_214000"

def get_folder_by_exact_path(access_token, folder_path):
    """完全なパスでフォルダ情報を取得"""
    headers = {"Authorization": f"Bearer {access_token}"}

    url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/root:/{folder_path}"

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        folder = response.json()

        parent_path = folder.get('parentReference', {}).get('path', '')
        if '/drive/root:' in parent_path:
            parent_path = parent_path.replace('/drive/root:', '')
        full_path = f"{parent_path}/{folder['name']}".lstrip('/')

        return {
            'id': folder['id'],
            'name': folder['name'],
            'path': parent_path,
            'full_path': full_path
        }
    except Exception as e:
        print(f"❌ エラー: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    """メイン処理"""
    print("=" * 80)
    print("🔍 残り2件の案件処理")
    print("=" * 80)
    print(f"📊 保存先コレクション: {TEST_COLLECTION}")
    print("=" * 80)

    overall_start = time.time()

    # 認証
    token = get_access_token()
    if not token:
        print("❌ 認証失敗のため終了します")
        return

    # 正確なパスを指定
    projects = [
        {
            'name': '豊中の貸倉庫兼オフィス（斜め壁）',
            'path': "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□Ａ行/329 PROCESS5 DESIGN/豊中の貸倉庫兼オフィス/09.成果物/20251202_TOYONAKA_BASE_最終構造設計図書一式"
        },
        {
            'name': '小さなお葬式（片持ち基礎）',
            'path': "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□Ａ行/279 A1・ID設計/2025012_（仮称）小さなお葬式 名古屋昭和区ホール/09.成果物/納品時/20251128_【事前】（仮称）小さなお葬式 名古屋昭和区ホール_構造設計図書一式"
        }
    ]

    success_count = 0
    error_count = 0
    results = []

    for project in projects:
        print(f"\n📂 {project['name']}")
        print(f"   パス: {project['path']}")

        folder_info = get_folder_by_exact_path(token, project['path'])

        if not folder_info:
            print(f"   ❌ フォルダ取得失敗")
            error_count += 1
            continue

        print(f"   ✅ フォルダ特定成功")
        print(f"   🚀 処理開始...")

        # 30秒待機（レート制限対策）
        time.sleep(30)

        success, message, elapsed = process_single_project(
            folder_info, token, TARGET_USER_EMAIL, TEST_COLLECTION
        )

        results.append({
            'name': project['name'],
            'success': success,
            'message': message,
            'elapsed': elapsed
        })

        if success:
            success_count += 1
            print(f"   ✅ 成功: {message} ({elapsed:.1f}秒)")
        else:
            error_count += 1
            print(f"   ❌ 失敗: {message}")

    overall_elapsed = time.time() - overall_start
    avg_time = sum(r['elapsed'] for r in results if r['success']) / success_count if success_count > 0 else 0

    # 結果サマリー
    print("\n" + "=" * 80)
    print("📊 追加処理結果")
    print("=" * 80)

    print(f"\n✅ 成功: {success_count}/2件")
    print(f"❌ 失敗: {error_count}/2件")
    print(f"⏱️  総実行時間: {overall_elapsed:.1f}秒 ({overall_elapsed/60:.1f}分)")
    print(f"⏱️  平均処理時間: {avg_time:.1f}秒/件")
    print(f"💾 保存先: Firestore > {TEST_COLLECTION}")

    print("\n📋 詳細結果:")
    for i, result in enumerate(results, 1):
        status = "✅" if result['success'] else "❌"
        print(f"{i}. {status} {result['name']}")
        print(f"   結果: {result['message']}")
        print(f"   処理時間: {result['elapsed']:.1f}秒")

    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()
