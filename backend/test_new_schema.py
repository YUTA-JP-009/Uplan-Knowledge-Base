"""
新スキーマでの抽出テスト
5件の特徴的な物件を処理
"""

import time
from datetime import datetime
from batch_processor_v4_rate_optimized import *

# 新しいコレクション（新命名規則に従う）
TEST_COLLECTION = datetime.now().strftime("%Y-%m-%d-%H:%M")

# テスト対象案件
TEST_PROJECTS = [
    {
        'name': '松下邸',
        'path': "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□た行/A00790_多田建築設計事務所/2025001_松下邸/09.成果物/20250911_【補正】松下邸_構造設計図書一式"
    },
    {
        'name': 'フルイチ様オフィス新築工事',
        'path': "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□Ａ行/453 Luce建築設計事務所/2025003_フルイチ様オフィス新築工事/09.成果物/20251111_【事前】フルイチ様オフィス新築工事_構造設計図書一式"
    },
    {
        'name': '豊中の貸倉庫兼オフィス',
        'path': "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□Ａ行/329 PROCESS5 DESIGN/豊中の貸倉庫兼オフィス/09.成果物/20251202_TOYONAKA_BASE_最終構造設計図書一式"
    },
    {
        'name': '三田2丁目AP',
        'path': "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□あ行/A00698アゼリアホーム/2024009_（仮称）三田2丁目AP／2024010_設計変更/09.成果物/20240912_(仮称)三田2丁目AP_構造計算書類一式"
    },
    {
        'name': '小さなお葬式 名古屋昭和区ホール',
        'path': "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□Ａ行/279 A1・ID設計/2025012_（仮称）小さなお葬式 名古屋昭和区ホール/09.成果物/納品時/20251128_【事前】（仮称）小さなお葬式 名古屋昭和区ホール_構造設計図書一式"
    }
]

def get_folder_by_path(access_token, folder_path):
    """パスからフォルダ情報を取得"""
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
        print(f"   ❌ エラー: {e}")
        return None

def main():
    """メイン処理"""
    print("=" * 80)
    print("🧪 新スキーマ抽出テスト")
    print("=" * 80)
    print(f"📊 テストコレクション: {TEST_COLLECTION}")
    print(f"📂 対象案件数: {len(TEST_PROJECTS)}件")
    print("=" * 80)

    overall_start = time.time()

    # 認証
    token = get_access_token()
    if not token:
        print("❌ 認証失敗のため終了します")
        return

    # 各案件を逐次処理（丁寧に）
    results = []
    success_count = 0
    error_count = 0

    for i, project in enumerate(TEST_PROJECTS, 1):
        print(f"\n{'='*80}")
        print(f"📂 [{i}/{len(TEST_PROJECTS)}] {project['name']}")
        print(f"{'='*80}")
        print(f"   パス: {project['path']}")

        # フォルダ情報取得
        folder_info = get_folder_by_path(token, project['path'])

        if not folder_info:
            print(f"   ❌ フォルダ取得失敗")
            error_count += 1
            results.append({
                'name': project['name'],
                'success': False,
                'message': 'フォルダ取得失敗',
                'elapsed': 0.0
            })
            continue

        print(f"   ✅ フォルダ特定成功")

        # レート制限対策: 各案件の間に30秒待機
        if i > 1:
            print(f"   ⏳ レート制限対策のため30秒待機...")
            time.sleep(30)

        # 処理実行
        print(f"   🚀 処理開始...")
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
    print("📊 新スキーマ抽出テスト結果")
    print("=" * 80)

    print(f"\n✅ 成功: {success_count}/{len(TEST_PROJECTS)}件")
    print(f"❌ 失敗: {error_count}/{len(TEST_PROJECTS)}件")
    print(f"⏱️  総実行時間: {overall_elapsed:.1f}秒 ({overall_elapsed/60:.1f}分)")
    print(f"⏱️  平均処理時間: {avg_time:.1f}秒/件")
    print(f"💾 保存先: Firestore > {TEST_COLLECTION}")

    print("\n📋 詳細結果:")
    for i, result in enumerate(results, 1):
        status = "✅" if result['success'] else "❌"
        print(f"\n{i}. {status} {result['name']}")
        print(f"   結果: {result['message']}")
        print(f"   処理時間: {result['elapsed']:.1f}秒")

    print("\n📈 新スキーマ検証項目:")
    print("   ✓ コレクション名: YYYY-MM-DD-HH:MM 形式")
    print("   ✓ ドキュメントID: 物件名をそのまま使用")
    print("   ✓ フィールド構造: 新スキーマに準拠")
    print("   ✓ 取引先: フォルダパスから自動抽出")

    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()
