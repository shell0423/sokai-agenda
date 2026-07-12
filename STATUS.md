# STATUS — 株主総会議案分析（旧「ゆうとさん関係」）

> このプロジェクトを触る前にまずここを読む。詳細な使い方は README.md。

## 今どうなっているか (2026-07-12)

- **Streamlitアプリ完成**: `⁠.venv/bin/streamlit run app.py` → http://localhost:8501
  - 実戦リスト(61社 A28/B15/C18) / 全トリガー(268社) / 卒業・決着 / 銘柄検索 の4タブ
  - 行クリック→下部に銘柄詳細（議案別賛成率2025vs2026・大量保有タイムライン＋チャート・トリガー理由）
  - サイドバーに実行ボタン3種（下記）
- **2026年分析済み**: トリガー268社・否決59社。成果物は `output/`
  （trigger_analysis_2026.md / diff_2025_2026.md / watchlist_2026.csv / dashboard_2026.html）

## アプリのボタン（=定型オペレーション）

| ボタン | 中身 | 所要 |
|---|---|---|
| ⚡ 高速再生成 | `python -m src.jobs fast`（compare_triggers×2→差分/実戦リスト→HTML。キャッシュのみ） | 数秒〜1分 |
| 🔄 フル更新 | `scripts/full_update.sh`（2026総会再スキャン→大量保有全量→再生成。バックグラウンド・ログ`output/logs/full_update.log`） | 40分〜2時間 |
| 📡 充足チェック | EDINETメタデータのみ日次件数（`src.jobs.check_coverage`） | 日数×0.5秒 |

## 絶対に踏まないこと（過去の事故）

0. **app.py冒頭の `ARROW_DEFAULT_MEMORY_POOL=system` を消さない**。
   pyarrow 25.0.0 のmimallocがrerun毎の新スレッドでSIGSEGVし、
   「行クリック→任意の操作」でStreamlitサーバごと落ちる実バグの対策（レビューWorkflowで実機再現・対策検証済み）。
1. **`--trend` を大量保有検索込みで実行しない**（`--skip-holdings` 必須）。
   内蔵の `_search_alert_holdings` は O(社数×日数) で実際に25時間ハングした。
   大量保有は必ず `search_trigger_holdings.py`（全量1回スキャン・有界）で。
2. **条件C(会社提案否決)は過検出あり**。空タイトル/文字化け行を否決と誤判定する
   （実例: コニカミノルタ4902。data/notes_2026.json の corrections で補正済み）。
   重要銘柄は kessanai `get_agm_vote_results` で一次照合。
3. **保有者名の照合は必ずNFKC正規化**（src/analysis_diff.py の `_norm`）。
   全角英字(`Ｏａｓｉｓ`)の取りこぼしで花王等20社を見逃した前科（2026-07-12修正済）。

## 次の一手

- [ ] **7/30 アインHD(9627)総会後にフル更新**（Oasis 17.7%買い増し中の抗争が2026トリガー入りする見込み）
- [ ] 2027年シーズン: compare_triggers等は `--years 2026,2027` で流用可
- [ ] （任意）実戦リストのDiscord/LINE通知連携

## 構成メモ

- 分析パイプライン: `src/main.py`(取得) → `compare_triggers.py`(3条件) → `search_trigger_holdings.py`(大量保有) → `src/analysis_diff.py`(差分/実戦リスト) → `src/dashboard_gen.py`(HTML)
- アプリ: `app.py` + `src/app_data.py`(ローダー) + `src/jobs.py`(ボタンジョブ)
- 検証済みの事実データ: `data/graduations_2026.json`(卒業9社の決着理由) / `data/notes_2026.json`(補正・銘柄メモ)
- 派生データ: `output/derived/diff_watchlist.json`（高速再生成で更新）
- 昨年分析: output/trigger_analysis_2025.md（2024→2025）
