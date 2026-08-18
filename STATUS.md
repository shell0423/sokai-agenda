# STATUS — 株主総会議案分析（旧「ゆうとさん関係」）

> このプロジェクトを触る前にまずここを読む。詳細な使い方は README.md。

## 今どうなっているか (2026-08-17)

- **✅ 大量保有の取得を倉庫参照へ切り替え、公開済み**（commit `c885199`）。
  `search_trigger_holdings.py`（自前EDINETスキャン＋壊れた `src/xbrl_parser.py`）に代えて
  **`scripts/build_trigger_holdings_wh.py`** が `wh_shareholders` から `trigger_holdings.csv` を作る。
  - **フル更新 40分〜2時間 → 数秒**（EDINETを叩かない・APIキー不要）
  - 行数 818 → **2,007**（共同保有1,639件が初めて見える）
  - 実戦リスト **61社 → 66社**（T1:28→**34** / T2:15→14 / T3:18→18）、**外れた銘柄は0＝退行なし**
  - 新規入りは村上系など「個別ほぼ0%・グループ合算が大きい」共同保有（例 4023クレハ レノ 個別0.0%→**グループ16.8%**）
  - CSVに **`グループ合算(%)` / `共同保有者数` / `グループ合算推移`** の3列を追加。
    `analysis_diff` は共同保有時に**グループ合算で** Tier/除外を判定する(`eff_ratio`/`eff_delta`)。
    個別値は `ratio` として表示用に残す。旧CSV(新列なし)でも個別値へフォールバックして動く。
  - 保有者の名寄せは **`html.unescape` → NFKC → 空白畳み込み**。倉庫の旧eraは
    `Dodge &amp; Cox` のようにエンティティ未デコード、新eraは NBSP(U+00A0) 混在で、
    どちらも素の文字列で束ねるとタイムラインが割れる。**法人格の違い(Inc./LLC)は寄せない**。
- **前提となる倉庫側の修復（2026-08-15〜17）**: 共同保有者の行展開を復活し、
  2024-01〜2026-06 の30ヶ月をバックフィル（32,029行→96,225行）。詳細は warehouse/STATUS.md。
- **`search_trigger_holdings.py` は当面残す**（比較用）が、**通常運用では使わない**。
  こちらは `contextRef` を見ないため共同保有で先頭しか拾えない既知の欠陥がある。

## 以前の状態 (2026-08-15 追記)

- **⚠ 公開中の `output/trigger_holdings.csv` は共同保有分が過小評価のまま**（2026-08-15 判明）。
  本アプリの `search_trigger_holdings.py` は自前の `src/xbrl_parser.py` を使うが、これは
  `大量報告書関係/src/xbrl_parser.py` と**md5一致の同一コピー**で、`contextRef` を見ないため
  共同保有書類で先頭の保有者しか拾えない（実例: ステラケミファ4109 NAVF は CSV上4.03% だが
  倉庫では個別4.24%・**グループ合算22.73%**）。倉庫側は 2026-08-15 に修復済みなので、
  **`search_trigger_holdings.py` を倉庫参照(`wh_shareholders`)へ切り替えるのが本筋**。
  切り替えるまでは公開CSVのアクティビスト保有割合を鵜呑みにしないこと。

## 今どうなっているか (2026-07-27)

- **公開ページに タブ／Tier絞り込み／行クリック銘柄詳細 を実装（2026-07-27）**。
  静的HTMLでもJSでここまでできる（topix-review-public と同方式）。詳細モーダルは
  議案別賛成率2025vs2026・大量保有チャート(lightweight-charts v4.2.3 を `assets/` に
  vendor しインライン)・トリガー理由・株探/IRBANKリンク。埋め込みは実戦61社＋除外12社ぶんで
  **ページ全体 約470KB**（全社ぶんだと総会キャッシュ13MBを抱えるため対象を絞っている）。
  データ生成は `src/detail_data.py`。
- **公開済み: https://shell0423.github.io/sokai-agenda/ （GitHub Pages）**。
  某哲也(boutetsuya-stocks)と同じ「完成HTML1枚を静的配信」方式を採用し、
  **Streamlit Cloud は使わない**（Python実行環境が要らないため）。
  配信元＝`docs/index.html`（`publish.py` が `output/dashboard_2026.html` から複製）。
  リポジトリ＝ https://github.com/shell0423/sokai-agenda （public・56ファイル/1MB）。
  ※ Cloud 対応コードは残してあるので、対話機能ごと公開したくなったら share.streamlit.io に登録するだけ。
- **日次自動更新 稼働中**: launchd `com.sokai.refresh`（毎日06:00 JST）→
  `publish.py --fast` → 倉庫から株価/PER/PBR取り直し → docs/更新 → 秘密スキャン → push。
  **EDINET再スキャン(40分〜2時間)は日次では回さない**（総会は年1回。株価だけ毎日動くため）。
  総会後は手動で `.venv/bin/python scripts/publish.py`（--fast なし＝フル更新）。
  ログ＝`output/logs/publish.log`。

## 以前の状態 (2026-07-12)

- **Streamlitアプリ完成**: `起動.command` ダブルクリック → http://localhost:8701
  （**8501は使わない。kabusokuの番号**。詳細は README の注記）
  - 実戦リスト(61社 A28/B15/C18) / 全トリガー(268社) / 卒業・決着 / 銘柄検索 の4タブ
  - 行クリック→下部に銘柄詳細（議案別賛成率2025vs2026・大量保有タイムライン＋チャート・トリガー理由）
  - サイドバーに実行ボタン3種（下記）
- **株価/PER/PBR を表示（2026-07-27 追加・某哲也アプリからの移植）**: 倉庫 `mart_latest` から
  株価・PER・PBR・配当利回り・ROE を取得し、実戦リストの表／銘柄詳細／dashboard HTML／
  watchlist CSV に表示。銘柄詳細に **株探・IRBANK** リンク（某哲也の `kabutanLink` と同じ導線）。
  **倉庫は Cloud に無いため `build_all()` が derived JSON に焼き込んで配布**する
  （倉庫に繋げない環境で再生成しても前回値を引き継ぎ、値が消えない）。
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

- [ ] **7/30 アインHD(9627)総会後にフル更新** — `.venv/bin/python scripts/publish.py`
      （`--fast` を付けない＝EDINET再スキャン込み・40分〜2時間。日次の軽量更新では総会データは増えない）。
      Oasis 17.7%買い増し中の抗争が2026トリガー入りする見込み
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
  - **「充填が進んだ頃」の判断＝機械判定（手動実行）**：アプリのサイドバー **「🏭 倉庫レディネス判定 → 判定を実行」** ボタン、
    または CLI `.venv/bin/python scripts/check_wh_readiness.py`（両者ともロジックは `src/wh_readiness.py::evaluate()`）。
    3ゲート(A鮮度/Bカバレッジ/C一致度)を測り 🔴まだ/🟡近い/🟢寄せてよい を返す(CLI終了コード 2/1/0)。月1くらいで押してAが✅になるのを待つ。
    判定結果は `output/derived/wh_readiness_last.json` に保存され、**サイドバー上部に前回結果のバッジが常時表示**(押さなくても🔴/🟡/🟢＋確認日＋A鮮度が見える)。🟢/🟡はst.success/warningで目立つ。
  - **✅解消(2026-08-15 実測)**: 鮮度は**A✅**になった（最新提出=2026-08-14＝1日遅れ／直近30日2,365件）。
    2026-07-21 時点の「2026-06-11で止まったまま」は解消済み＝下の記述は履歴として残す。
  - **⛏ 倉庫側で共同保有者の行展開を修復(2026-08-15)**: 倉庫の `fetch_edinet_tairyo.py` は
    2026-06-10以降 `holder_number=1` 固定で**1書類1行**しか作らず、共同保有の2人目以降が消えていた
    （例 太陽誘電6976: 野村證券0.26%だけが残り、実際に12.21%持つ野村アセットマネジメントが欠落）。
    さらに `JointHolder{N}Member` 書式は**提出者すら取りこぼしていた**（サツドラHD3544: テラ51.21%が消失）。
    3,291書類を再取得して修復済み（+3,822行／32,029→35,851）。
    **効果**: レディネス判定の主要アクティビスト検出が **60/61 → 61/61(全員検出)** に改善。
  - **残る不合格はC(一致度82%)のみ**だが、差1pt超10社のうち**8社は倉庫の方が新しい**
    （倉庫の最新提出 2026-07-23〜08-13 に対しアプリ側キャッシュは2026-07-11のスキャン）。
    ＝Cは倉庫の誤りでなく**アプリ側の鮮度落ち**を測っている可能性が高い。
    次にフル更新(`scripts/publish.py`)を回してから再判定すること。
    **見る順はA→C**。今の唯一の不合格は**Aの鮮度**（最新提出2026-06-11＝39日遅れ・直近30日0件。Bカバレッジは78%で✅）。
  - **再判定トリガー**：`check_wh_readiness.py` が **🟢(A鮮度が10日以内＋C一致90%超)** を出したら移行設計へ（そのとき sankei も一緒に）。
  - **注意**：鮮度は自然に進むとは限らない。06-11で止まったまま＝倉庫の株主EP取込が直近を拾えていない可能性。Aが数週間🔴のままなら「待つ」でなく**倉庫側の大量保有取込の鮮度改善が先**（[[unified-stock-db-capacity]]／warehouse STATUSの追加EP充填）。
  - **今すぐ寄せてよい消費者**：相互保有照合 holders.py（鮮度不要・on-demand・同源）。kabusokuは既利用（「倉庫取込済み分のみ」と自己注記）。
