"""
ローカルテスト用スクリプト（Phase 2）
並列数2で3件の案件をテスト

目的:
1. 新機能の動作確認（folder_url, created_year_month, project_name）
2. 重複チェックの動作確認
3. 改善されたドキュメントIDの確認
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from batch_processor_v3_parallel import *

# テスト用の案件リスト（3件のみ）
TEST_PROJECTS = [
    "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□た行/A00790_多田建築設計事務所/2025001_松下邸",
    "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□Ａ行/453 Luce建築設計事務所/2025003_フルイチ様オフィス新築工事",
    "001_Ｕ'plan_全社/01.構造設計/01.木造（在来軸組）/□Ａ行/329 PROCESS5 DESIGN/豊中の貸倉庫兼オフィス",
]

def test_local():
    """ローカルテストのメイン関数"""
    from datetime import datetime
    start_time = time.time()
    start_datetime = datetime.now()

    print("=" * 80)
    print("🧪 ローカルテスト（Phase 2）")
    print("=" * 80)
    print(f"📊 処理対象: {len(TEST_PROJECTS)}件")
    print(f"⚙️  並列処理数: 2")
    print(f"💾 保存先: Projects_2026_01_07")
    print(f"⏰ 開始時刻: {start_datetime.strftime('%Y/%m/%d %H:%M:%S')}")
    print("=" * 80)

    # 認証
    print("\n🔑 認証中...")
    token = get_access_token()
    if not token:
        print("❌ 認証失敗")
        return

    print("✅ 認証成功")

    # 各案件のフォルダ情報を収集
    print("\n📂 フォルダ情報を収集中...")
    project_folders = []

    for i, project_path in enumerate(TEST_PROJECTS):
        print(f"\n[{i+1}/{len(TEST_PROJECTS)}] {project_path}")

        # フォルダIDを取得するために、親フォルダをチェック
        headers = {"Authorization": f"Bearer {token}"}
        try:
            folder_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/root:/{project_path}"
            response = requests.get(folder_url, headers=headers, timeout=30)

            if response.status_code != 200:
                print(f"   ⚠️  スキップ: フォルダが見つかりません")
                continue

            parent_folder = response.json()
            parent_folder_id = parent_folder.get('id')

            # 構造設計図書フォルダを探索
            children_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{parent_folder_id}/children"
            children_response = requests.get(children_url, headers=headers, timeout=30)

            if children_response.status_code != 200:
                print(f"   ⚠️  スキップ: サブフォルダ取得失敗")
                continue

            children = children_response.json().get('value', [])

            # 構造設計図書フォルダを検索
            target_folder = None
            for child in children:
                if 'folder' in child:
                    child_name = child.get('name', '')
                    if ('構造設計図書' in child_name or '構造計算書' in child_name) and '○' not in child_name:
                        target_folder = child
                        break

            # サブフォルダ（成果物/納品時）も探索
            if not target_folder:
                for child in children:
                    if 'folder' in child and ('成果物' in child.get('name', '') or '納品' in child.get('name', '')):
                        sub_url = f"https://graph.microsoft.com/v1.0/users/{TARGET_USER_EMAIL}/drive/items/{child['id']}/children"
                        sub_response = requests.get(sub_url, headers=headers, timeout=30)
                        if sub_response.status_code == 200:
                            sub_children = sub_response.json().get('value', [])
                            for sub_child in sub_children:
                                if 'folder' in sub_child:
                                    sub_name = sub_child.get('name', '')
                                    if ('構造設計図書' in sub_name or '構造計算書' in sub_name) and '○' not in sub_name:
                                        target_folder = sub_child
                                        break
                            if target_folder:
                                break

            if target_folder:
                project_folders.append({
                    'id': target_folder['id'],
                    'name': target_folder['name'],
                    'path': project_path,
                    'full_path': project_path
                })
                print(f"   ✅ 発見: {target_folder['name']}")
            else:
                print(f"   ⚠️  スキップ: 構造設計図書フォルダが見つかりません")

        except Exception as e:
            print(f"   ❌ エラー: {str(e)[:100]}")

    if not project_folders:
        print("\n❌ 処理可能な案件が見つかりませんでした")
        return

    print(f"\n✅ {len(project_folders)}件の案件を検出しました")

    # 並列処理実行
    print("\n🚀 並列処理を開始します（並列数: 2）")
    print("=" * 80)

    success_count = 0
    error_count = 0

    # ProcessPoolExecutorで並列処理（並列数2）
    with ProcessPoolExecutor(max_workers=2) as executor:
        # タスクを投入
        future_to_project = {
            executor.submit(process_single_project, project, token, TARGET_USER_EMAIL): project
            for project in project_folders
        }

        # 完了したタスクから順に処理
        for future in as_completed(future_to_project):
            project = future_to_project[future]
            try:
                success, message = future.result()
                if success:
                    success_count += 1
                    print(f"✅ [{success_count + error_count}/{len(project_folders)}] {project['name']}")
                    print(f"   結果: {message}")
                else:
                    error_count += 1
                    print(f"❌ [{success_count + error_count}/{len(project_folders)}] {project['name']}")
                    print(f"   理由: {message}")
            except Exception as e:
                error_count += 1
                print(f"❌ [{success_count + error_count}/{len(project_folders)}] {project['name']}")
                print(f"   例外: {str(e)[:100]}")

            # 少し待機（レート制限対策）
            time.sleep(1)

    # 実行時間トラッキング終了
    end_time = time.time()
    end_datetime = datetime.now()
    elapsed_seconds = int(end_time - start_time)
    elapsed_minutes = elapsed_seconds // 60
    elapsed_seconds_remainder = elapsed_seconds % 60

    print("\n" + "=" * 80)
    print("📊 テスト完了サマリー")
    print("=" * 80)
    print(f"✅ 成功: {success_count}件")
    print(f"❌ 失敗: {error_count}件")
    print(f"📝 合計: {len(project_folders)}件")
    print(f"💾 保存先: Firestore > uplan > Projects_2026_01_07")
    print(f"⏰ 開始時刻: {start_datetime.strftime('%Y/%m/%d %H:%M:%S')}")
    print(f"⏰ 終了時刻: {end_datetime.strftime('%Y/%m/%d %H:%M:%S')}")
    print(f"⏱️  処理時間: {elapsed_minutes}分{elapsed_seconds_remainder}秒")
    print("=" * 80)

    print("\n📋 確認項目:")
    print("  1. Firestoreで新フィールド（folder_url, created_year_month, project_name）を確認")
    print("  2. ドキュメントIDが「物件名_タイムスタンプ」形式になっているか確認")
    print("  3. 重複チェックが動作しているか（再実行時にスキップされるか）")

if __name__ == "__main__":
    test_local()
