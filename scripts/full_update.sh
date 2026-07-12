#!/bin/bash
# フル更新: 2026年の総会データをEDINETから再取得し、大量保有→分析→HTMLまで再生成する。
# 所要: 40分〜2時間(EDINET APIレート制限律速)。アプリの「フル更新」ボタンから起動される。
#
# 手順(このセッションで実証済みの安全な経路):
#   1. 2026キャッシュを退避 → --trend --skip-holdings で2026のみ再スキャン(2025はキャッシュ)
#   2. search_trigger_holdings.py で大量保有を全量再スキャン(有界・トリガー社のみXBRL解析)
#      ※ main.py内蔵の大量保有検索(_search_alert_holdings)は O(社数×日数) で激遅のため使わない
#   3. fast_regen で差分・実戦リスト・ダッシュボード再生成
set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python
TODAY=$(date +%F)
CACHE=output/cache/2026_meetings.json
BAK=output/cache/2026_meetings.bak.json
echo "=== FULL UPDATE 開始: $(date '+%F %T') ==="

# 途中停止(⛔ボタン=SIGTERM)・クラッシュでも退避キャッシュを必ず復元する。
# 再スキャン成功時はBAKを消すので、このtrapは無害なno-opになる。
restore_cache() {
  if [ ! -f "$CACHE" ] && [ -f "$BAK" ]; then
    mv "$BAK" "$CACHE"
    echo "(trap) 2026キャッシュを復元しました"
  fi
}
trap restore_cache EXIT TERM INT

echo "--- [1/3] 2026総会データ再スキャン(40-50分) ---"
if [ -f "$CACHE" ]; then
  # キャッシュが存在すると--trendがスキャンをスキップするため退避(mv)が必要
  mv "$CACHE" "$BAK"
  echo "既存2026キャッシュを退避: 2026_meetings.bak.json"
fi
if $PY -m src.main --trend --years 2025,2026 --skip-holdings; then
  echo "[1/3] OK"
  rm -f "$BAK"
else
  echo "[1/3] 失敗 → キャッシュを復元して中断"
  restore_cache
  echo "FULL_UPDATE_DONE status=error step=1"
  exit 1
fi

echo "--- [2/3] 大量保有 全量再スキャン(〜60分) ---"
if $PY search_trigger_holdings.py --years 2025,2026 --start 2024-01-01 --end "$TODAY" --no-cache; then
  echo "[2/3] OK"
else
  echo "[2/3] 失敗(分析は旧trigger_holdings.csvで継続)"
fi

echo "--- [3/3] 分析・実戦リスト・HTML再生成 ---"
if $PY -m src.jobs fast; then
  echo "[3/3] OK"
else
  echo "[3/3] 失敗"
  echo "FULL_UPDATE_DONE status=error step=3"
  exit 1
fi

echo "=== FULL UPDATE 完了: $(date '+%F %T') ==="
echo "FULL_UPDATE_DONE status=ok"
