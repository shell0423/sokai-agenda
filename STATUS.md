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
- **会社マスタ= warehouse `wh_security`**（`src/warehouse_client.py`・read_only・**J-Quantsは廃止**）。
  倉庫の作法どおり「開いて即クローズ」で夜間ライターをブロックしない。倉庫が無ければ社名補完のみスキップ。
  ※データの本体（議決権結果・大量保有）は引き続きアプリの `output/` に持つ（倉庫に無い/季節データのため。統一の方針判断は下記）。
- 検証済みの事実データ: `data/graduations_2026.json`(卒業9社の決着理由) / `data/notes_2026.json`(補正・銘柄メモ)
- 派生データ: `output/derived/diff_watchlist.json`（高速再生成で更新）
- 昨年分析: output/trigger_analysis_2025.md（2024→2025）

## warehouse統一の方針（2026-07-15 判断 / 07-20 大量保有を追記）
- **①会社マスタ→ wh_security：実施済み**（J-Quants依存を撤去。`src/warehouse_client.py`）。
- **②議決権結果（臨時報告書・議案別賛成率）：アプリ側に据え置き**（倉庫に無い・年1回の季節データ）。
- **③大量保有を倉庫に寄せる：見送り（時期尚早）— 2026-07-20 実測判定**。
  - 訂正：倉庫には既に大量保有ソースがある＝**`wh_shareholders`**（edinetdb.jp由来・28,750行・kabusokuが既利用）。フィールドも完備（holder/ratio/ratio_previous/**total_holding_ratio(共同保有合算)**/purpose/submit_date/doc_id）。
  - **判定＝今は寄せない**。実戦61社で突き合わせた結果：主要アクティビスト検出60/61・保有割合±0.5pt一致は42/60(70%)だが、**1pt超の差が16社**。原因は名寄せミスでなく**倉庫の取りこぼし/鮮度落ち**（`wh_shareholders`の全体最新submit=**2026-06-11**＝直取得07-11より約1ヶ月遅れ。例:スルガ/インダスは2024-12の1件のみで買い増しを欠落）。
  - 背景：倉庫STATUSの「**EDINET追加EP（株主等）充填中・全社カバーまで数週間**」＝大量保有はまだ充填途中で直近が薄い。
  - このアプリは「直近の買い増し検出」が命で、総会シーズン(6末〜7月)の大量保有を倉庫がまだ持たない→寄せると核シグナルを取りこぼす。自前scanは既にトリガー社に有界(~30-60分・25hハングは別経路で解消済)。
  - **再判定トリガー**：`SELECT max(submit_date_time) FROM wh_shareholders` が**当年7月分まで入り**、`/tmp/wh_verdict.py`相当(61社突合)で±0.5pt一致が9割超になったら移行を再検討（そのとき sankei も一緒に）。
  - **今すぐ寄せてよい消費者**：相互保有照合 holders.py（鮮度不要・on-demand・同源）。kabusokuは既利用（「倉庫取込済み分のみ」と自己注記）。
  - 検証スクリプト: `/tmp/wh_verdict.py`（61社突合）/ `/tmp/wh_outlier.py`（アクティビスト別履歴）。
