"""
日本時間（JST）のタイムスタンプ動作確認テスト
"""

from datetime import datetime, timezone, timedelta

# 日本時間のタイムゾーン
JST = timezone(timedelta(hours=9))

# 現在時刻をJSTで取得
now_jst = datetime.now(JST)
print("=" * 80)
print("日本時間（JST）タイムスタンプ動作確認")
print("=" * 80)

print(f"\n現在のJST時刻: {now_jst}")
print(f"ISO 8601形式: {now_jst.isoformat()}")
print(f"タイムゾーン: {now_jst.tzname()}")
print(f"UTCオフセット: {now_jst.strftime('%z')}")

# UTCとの比較
now_utc = datetime.now(timezone.utc)
print(f"\n現在のUTC時刻: {now_utc}")
print(f"ISO 8601形式: {now_utc.isoformat()}")

# 時差確認
time_diff = (now_jst - now_utc).total_seconds() / 3600
print(f"\nJSTとUTCの時差: {time_diff}時間")

# 想定される出力例
print("\n" + "=" * 80)
print("Firestoreに保存されるextracted_atの形式例:")
print("=" * 80)
print(f"{now_jst.isoformat()}")
print("\n例: 2026-01-09T16:30:45.123456+09:00")
print("    ↑ +09:00 が日本時間（JST）を示しています")
print("=" * 80)
