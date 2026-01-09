"""
v4性能テスト: 5件の特徴的案件を並列処理
- スキップフロア: 松下邸
- 大屋根+平面不整形: フルイチ様オフィス
- 斜め壁: 豊中の貸倉庫兼オフィス
- 鉄骨造外部階段: 三田2丁目AP
- 片持ち基礎: 小さなお葬式
"""

import time
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from batch_processor_v4_rate_optimized import *

# テスト用の新しいコレクション
TEST_COLLECTION = f"Projects_V4_Test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# テスト対象案件（探索情報）
TEST_PROJECTS = [
    {
        'name': '松下邸（スキップフロア）',
        'search_keywords': ['た行', '多田建築', '松下邸', '2025001']
    },
    {
        'name': 'フルイチ様オフィス（大屋根+平面不整形）',
        'search_keywords': ['Ａ行', 'Luce', 'フルイチ', '2025003']
    },
    {
        'name': '豊中の貸倉庫兼オフィス（斜め壁）',
        'search_keywords': ['Ａ行', 'PROCESS5', '豊中', '貸倉庫']
    },
    {
        'name': '三田2丁目AP（鉄骨造外部階段）',
        'search_keywords': ['あ行', 'アゼリア', '三田', '2024009']
    },
    {
        'name': '小さなお葬式（片持ち基礎）',
        'search_keywords': ['Ａ行', 'A1', '小さなお葬式', '2025012']
    }
]

def search_folder_by_keywords(access_token, project_name, keywords):
    """キーワードで案件フォルダを階層的に探索"""
    headers = {"Authorization": f"Bearer {access_token}"}

    try:
        # ベースパス
        base_path = "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）"

        # 行フォルダを特定
        gyou_keyword = keywords[0]  # た行, Ａ行, あ行
        gyou_path = f"{base_path}/□{gyou_keyword}"

        print(f"   🔍 {gyou_path} 配下を探索中...")
        url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/root:/{gyou_path}:/children"
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        gyou_children = response.json().get('value', [])

        # 設計事務所フォルダを探す
        sekkei_folder = None
        sekkei_keyword = keywords[1]  # 多田建築, Luce, PROCESS5, アゼリア, A1

        for child in gyou_children:
            if 'folder' in child and sekkei_keyword in child.get('name', ''):
                sekkei_folder = child
                print(f"   ✅ 設計事務所フォルダ: {child.get('name', '')}")
                break

        if not sekkei_folder:
            print(f"   ❌ 設計事務所フォルダが見つかりません（キーワード: {sekkei_keyword}）")
            return None

        # 案件フォルダを探す
        url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{sekkei_folder['id']}/children"
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        project_children = response.json().get('value', [])

        project_folder = None
        project_keywords = keywords[2:]  # 残りのキーワード

        for child in project_children:
            if 'folder' in child:
                child_name = child.get('name', '')
                # すべてのキーワードが含まれているかチェック
                if all(kw in child_name for kw in project_keywords):
                    project_folder = child
                    print(f"   ✅ 案件フォルダ: {child_name}")
                    break

        if not project_folder:
            print(f"   ❌ 案件フォルダが見つかりません（キーワード: {project_keywords}）")
            return None

        # 09.成果物フォルダを探す
        url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{project_folder['id']}/children"
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        seika_children = response.json().get('value', [])

        seika_folder = None
        for child in seika_children:
            if 'folder' in child and '09.成果物' in child.get('name', ''):
                seika_folder = child
                print(f"   ✅ 成果物フォルダ発見")
                break

        if not seika_folder:
            print(f"   ❌ 09.成果物フォルダが見つかりません")
            return None

        # 成果物配下から最終フォルダを探す（再帰的に）
        def find_final_folder(folder_id, depth=0):
            if depth > 3:  # 最大3階層まで
                return None

            url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{folder_id}/children"
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            children = response.json().get('value', [])

            # 構造設計図書一式フォルダを優先的に探す
            for child in children:
                if 'folder' in child:
                    child_name = child.get('name', '')
                    if '構造設計図書' in child_name or '構造計算書' in child_name:
                        return child

            # なければサブフォルダを再帰的に探索
            for child in children:
                if 'folder' in child:
                    result = find_final_folder(child['id'], depth + 1)
                    if result:
                        return result

            return None

        final_folder = find_final_folder(seika_folder['id'])

        if not final_folder:
            print(f"   ❌ 構造設計図書フォルダが見つかりません")
            return None

        print(f"   ✅ 最終フォルダ: {final_folder.get('name', '')}")

        # パス情報を構築
        parent_path = final_folder.get('parentReference', {}).get('path', '')
        if '/drive/root:' in parent_path:
            parent_path = parent_path.replace('/drive/root:', '')
        full_path = f"{parent_path}/{final_folder['name']}".lstrip('/')

        return {
            'id': final_folder['id'],
            'name': final_folder['name'],
            'path': parent_path,
            'full_path': full_path
        }

    except Exception as e:
        print(f"   ❌ 探索エラー: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    """メイン処理"""
    print("=" * 80)
    print("🧪 v4性能テスト: 並列処理 + レート制限対策")
    print("=" * 80)
    print(f"📊 テストコレクション: {TEST_COLLECTION}")
    print(f"📂 対象案件数: {len(TEST_PROJECTS)}件")
    print(f"⚙️  並列処理数: {len(TEST_PROJECTS)}（全件同時実行）")
    print("=" * 80)

    overall_start = time.time()

    # 認証
    token = get_access_token()
    if not token:
        print("❌ 認証失敗のため終了します")
        return

    # フォルダ情報を取得
    print("\n🔍 フォルダ情報取得中...")
    project_folders = []

    for project in TEST_PROJECTS:
        print(f"\n📂 {project['name']}")
        folder_info = search_folder_by_keywords(token, project['name'], project['search_keywords'])
        if folder_info:
            project_folders.append(folder_info)
        else:
            print(f"   ⚠️  スキップします")

    if not project_folders:
        print("\n❌ 対象フォルダが見つかりませんでした")
        return

    print(f"\n✅ {len(project_folders)}件のフォルダを特定")

    # 並列処理実行（全件同時）
    print(f"\n🚀 並列処理開始: {len(project_folders)}件を同時実行")
    print("💡 レート制限対策:")
    print("   - 各プロセスが独立したレート制限枠を持つ")
    print("   - 指数バックオフ + ランダムジッター")
    print("   - 最大5回の積極的リトライ")
    print("   - 初期遅延のランダム化")

    success_count = 0
    error_count = 0
    total_elapsed = 0.0
    results = []

    with ProcessPoolExecutor(max_workers=len(project_folders)) as executor:
        future_to_project = {
            executor.submit(process_single_project, project, token, TARGET_USER_EMAIL, TEST_COLLECTION): project
            for project in project_folders
        }

        for future in as_completed(future_to_project):
            project = future_to_project[future]
            try:
                success, message, elapsed = future.result()
                total_elapsed += elapsed

                results.append({
                    'name': project['name'],
                    'success': success,
                    'message': message,
                    'elapsed': elapsed
                })

                if success:
                    success_count += 1
                    print(f"✅ [{success_count + error_count}/{len(project_folders)}] {project['name']}: {message} ({elapsed:.1f}秒)")
                else:
                    error_count += 1
                    print(f"❌ [{success_count + error_count}/{len(project_folders)}] {project['name']}: {message}")

            except Exception as e:
                error_count += 1
                print(f"❌ [{success_count + error_count}/{len(project_folders)}] {project['name']}: 例外 - {str(e)[:100]}")

    overall_elapsed = time.time() - overall_start
    avg_time = total_elapsed / success_count if success_count > 0 else 0

    # 結果サマリー
    print("\n" + "=" * 80)
    print("📊 v4性能テスト結果")
    print("=" * 80)

    print(f"\n✅ 成功: {success_count}/{len(project_folders)}件")
    print(f"❌ 失敗: {error_count}/{len(project_folders)}件")
    print(f"⏱️  総実行時間: {overall_elapsed:.1f}秒 ({overall_elapsed/60:.1f}分)")
    print(f"⏱️  平均処理時間: {avg_time:.1f}秒/件")
    print(f"💾 保存先: Firestore > {TEST_COLLECTION}")

    # 詳細結果
    print("\n📋 詳細結果:")
    for i, result in enumerate(results, 1):
        status = "✅" if result['success'] else "❌"
        print(f"{i}. {status} {result['name']}")
        print(f"   結果: {result['message']}")
        print(f"   処理時間: {result['elapsed']:.1f}秒")

    # v3との比較
    print("\n📈 v3との比較:")
    print(f"   v3平均処理時間: 86.7秒/件")
    print(f"   v4平均処理時間: {avg_time:.1f}秒/件")
    if avg_time > 0:
        improvement = ((86.7 - avg_time) / 86.7) * 100
        print(f"   改善率: {improvement:+.1f}%")

    print("\n🎯 レート制限エラー:")
    rate_limit_errors = sum(1 for r in results if 'レート制限' in r['message'] or '429' in r['message'])
    print(f"   発生件数: {rate_limit_errors}/{len(results)}件")
    print(f"   エラー率: {(rate_limit_errors/len(results)*100):.1f}%")

    print("\n" + "=" * 80)

if __name__ == "__main__":
    main()
