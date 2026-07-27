# 株主総会議案分析 & アクティビスト保有調査

> **現状と定型オペレーションは [STATUS.md](STATUS.md) を先に読む。**

## 概要

3月決算企業の定時株主総会における **議案別の賛成・反対割合** を取得し、
**株主提案** や **会社提案の賛成率低下** をスクリーニングした上で、
該当企業の **アクティビスト保有状況**（大量保有報告書）を調査するツール。

ゆうとさんからの依頼に基づき作成。

## アプリ（Streamlit）

**`起動.command` をダブルクリック**すると起動し、ブラウザ（http://localhost:8501）が開く。
停止は開いたターミナルウィンドウで `Ctrl+C`。ターミナルから起動する場合は:

```bash
.venv/bin/streamlit run app.py    # → http://localhost:8501
```

- **実戦リスト / 全トリガー / 卒業・決着 / 銘柄検索** の4タブ。行クリックで銘柄詳細
  （議案別賛成率 2025 vs 2026・大量保有タイムライン＋チャート・トリガー該当理由）
- **株価・PER・PBR・配当利回り・ROE** を実戦リストの表と銘柄詳細に表示（warehouse `mart_latest` 由来）。
  銘柄詳細には **株探・IRBANK（大量保有／臨時報告書）への外部リンク**付き
- サイドバーのボタンで実行:
  **⚡高速再生成**（キャッシュから分析一式・数秒〜1分）／
  **🔄フル更新**（EDINET再スキャン・バックグラウンド40分〜2時間）／
  **📡充足チェック**（臨時報告書の日次件数）

## 技術スタック

- Python 3.11+
- EDINET API（臨時報告書・大量保有報告書）
- warehouse（`~/Claude/warehouse`）＝会社マスタ `wh_security`（社名補完）＋
  現在ファンダ `mart_latest`（株価・PER・PBR・配当利回り・ROE）。いずれも read_only・即クローズ
- httpx / duckdb / pandas / openpyxl / streamlit

## 分析フロー（3段階の漏斗型）

```
Step 1: 全企業トレンド分析（約2,300社）
  │  EDINET APIで臨時報告書（株主総会決議）を期間スキャン
  │  2年分の議案別賛成率を比較
  │
  │  → trend_YYYY_YYYY.csv
  │
  ▼ スクリーニング条件（自動）
Step 2: 注目企業の抽出 → 大量保有報告書の自動検索
  │  条件A: 会社提案の賛成率が10pp以上低下（--holding-threshold）
  │  条件B: 新たに株主提案が提出された（NEW_SHAREHOLDER）
  │  条件C: 会社提案が否決された（候補者の賛成率50%未満を含む）
  │  → 該当企業のEDINET大量保有報告書を自動検索
  │
  │  → activist_analysis.csv（手動詳細分析）
  │
  ▼ 深掘り調査
Step 3: アクティビスト保有推移の追跡
     EDINET大量保有報告書 / IRBANKから保有割合の時系列データを取得
     各アクティビストの買い増し・売却パターンを記録

     → activist_holdings_timeline.csv
```

### 2024→2025年の実績

| ステップ | 結果 |
|---------|------|
| Step 1 | 2024年=2,647社 / 2025年=2,625社をスキャン |
| 条件A | 233社（会社提案の賛成率が10pp以上低下） |
| 条件B | 36社（新規株主提案あり） |
| 条件C | 62社（会社提案が否決） |
| Step 2 | 288社がトリガー対象（3条件の和集合） |
| 大量保有報告書あり | 251社 / 288社 |
| Step 3 | 保有者別タイムライン 825行を出力 |

## セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 環境変数

`.env.example` をコピーして `.env` を作成し、APIキーを設定する。

```bash
cp .env.example .env
```

| 変数 | 用途 | 取得先 |
|------|------|--------|
| `EDINET_API_KEY` | EDINET API（必須） | https://disclosure.edinet-fsa.go.jp/ |
| `WAREHOUSE_DIR` | 会社マスタ(wh_security)の場所（任意・既定 `~/Claude/warehouse`） | ローカル |

> 会社名補完は warehouse の `wh_security`（read_only）を参照します。倉庫が無くても
> EDINETの提出者名で動作します（社名補完のみスキップ）。J-Quants は使いません。

## 使い方

### 単年度の議決結果取得

```bash
# 2025年度（デフォルト: 5/1〜8/31の臨時報告書をスキャン）
python -m src.main --year 2025

# 特定企業に絞り込み（太陽HD）
python -m src.main --year 2025 --code 4626

# コンソール表示のみ（ファイル出力なし）
python -m src.main --year 2025 --dry-run --verbose
```

### 年度間トレンド比較

```bash
# 2024年 vs 2025年の比較（キャッシュあり）
python -m src.main --trend --years 2024,2025

# 閾値を変更（3pp以上の低下をフラグ）
python -m src.main --trend --years 2024,2025 --threshold -3.0

# 大量保有検索トリガーの閾値を変更（15pp以上の低下で検索）
python -m src.main --trend --years 2024,2025 --holding-threshold -15.0

# キャッシュ無視で再取得
python -m src.main --trend --years 2024,2025 --no-cache
```

### コマンドライン引数一覧

| 引数 | 説明 | デフォルト |
|------|------|----------|
| `--year` | 対象年度 | 今年 |
| `--start-date` | スキャン開始日 (YYYY-MM-DD) | 対象年の5/1 |
| `--end-date` | スキャン終了日 (YYYY-MM-DD) | 対象年の8/31 |
| `--code` | 証券コード（4桁）で絞り込み | なし（全件） |
| `--output` | 出力ファイルパス | output/results_YYYY.csv |
| `--format` | 出力形式 (csv / excel) | csv |
| `--dry-run` | コンソール表示のみ | false |
| `--skip-holdings` | 大量保有報告書検索をスキップ | false |
| `--trend` | トレンド比較モード | false |
| `--years` | 比較年度（カンマ区切り） | 前年,今年 |
| `--threshold` | 賛成率低下アラート閾値（pp） | -5.0 |
| `--holding-threshold` | 大量保有検索トリガーの賛成率低下閾値（pp） | -10.0 |
| `--no-cache` | キャッシュ無視 | false |
| `--verbose` | デバッグログ | false |

### 補助スクリプト

```bash
# トリガー比較（旧ロジック vs 新ロジック）
python compare_triggers.py              # コンソール表示のみ
python compare_triggers.py --csv        # CSV出力（output/trigger_comparison.csv）
python compare_triggers.py --csv -o out.csv  # 出力先を指定
python compare_triggers.py --holding-threshold -15.0  # 閾値変更

# トリガー企業の大量保有報告書を一括検索
python search_trigger_holdings.py       # EDINET全量スキャン → CSV出力
python search_trigger_holdings.py --use-cache  # キャッシュ利用（API不要）

# 特定企業の大量保有報告書をスキャンしアクティビスト判定
python check_activists.py

# 大量保有報告書から保有割合の数値を抽出（時系列）
python fetch_holdings.py
```

## プロジェクト構造

```
.
├── src/
│   ├── main.py                 # エントリーポイント（単年度分析 & トレンド比較）
│   ├── edinet_client.py        # EDINET API クライアント
│   ├── resolution_parser.py    # 臨時報告書 iXBRL → 議案別賛成率のパーサー
│   ├── proposal_classifier.py  # 議案の分類（取締役選任/剰余金処分/その他）
│   ├── holding_searcher.py     # 大量保有報告書の検索
│   ├── xbrl_parser.py          # XBRL汎用パーサー
│   ├── warehouse_client.py     # 会社マスタ(wh_security)を read_only 参照
│   ├── trend_analyzer.py       # 年度間トレンド分析
│   ├── trend_cache.py          # トレンドデータのキャッシュ（JSON）
│   ├── trend_exporter.py       # トレンドレポートの出力
│   ├── csv_exporter.py         # CSV/Excel出力
│   ├── rate_limiter.py         # APIレート制限
│   └── models.py               # データモデル（Proposal, MeetingResult等）
├── tests/
│   ├── test_resolution_parser.py
│   ├── test_proposal_classifier.py
│   ├── test_trend_analyzer.py
│   └── test_trend_cache.py
├── compare_triggers.py         # トリガー比較（旧ロジック vs 新ロジック）
├── search_trigger_holdings.py  # トリガー企業の大量保有報告書一括検索
├── check_activists.py          # アクティビスト判定スクリプト（単体実行用）
├── fetch_holdings.py           # 保有割合抽出スクリプト（単体実行用）
├── inspect_doc.py              # EDINET文書の中身確認用
├── output/                     # 出力先（.gitignore対象）
│   ├── trend_2024_2025.csv     # Step 1: 全企業トレンド（約15,000行）
│   ├── trigger_comparison.csv  # トリガー比較結果（314行）
│   ├── trigger_holdings.csv    # トリガー企業の大量保有報告書・保有者別（825行）
│   ├── trigger_holdings_summary.csv  # トリガー企業の大量保有サマリー（288行）
│   ├── activist_holdings_timeline.csv  # アクティビスト保有推移（手動分析）
│   ├── activist_analysis.csv   # 注目企業リスト（手動分析）
│   ├── activist_check.csv      # check_activists.py の出力
│   ├── activist_holdings.csv   # fetch_holdings.py の出力
│   └── cache/                  # EDINET取得データのキャッシュ（JSON）
│       ├── 2024_meetings.json
│       ├── 2025_meetings.json
│       ├── tairyo_scan.json    # 大量保有報告書全量スキャン（35,950件）
│       └── tairyo_docs.json
├── .env                        # APIキー（.gitignore対象）
├── .env.example
├── requirements.txt
├── requirements-dev.txt
└── pyproject.toml
```

## 出力ファイルの説明

### trend_YYYY_YYYY.csv（Step 1）

全企業の議案別賛成率トレンド。主要カラム:

| カラム | 説明 |
|--------|------|
| 証券コード | 4桁コード |
| 企業名 | EDINET登録名 |
| 議案カテゴリ | 取締役選任 / 剰余金処分 / その他 |
| 提案区分 | 会社提案 / 株主提案 |
| 候補者 | 取締役選任の場合の個人名 |
| YYYY年賛成率(%) | 各年度の賛成率 |
| 変動(pp) | 前年比の変動幅 |
| アラート | DECLINING / NEW_SHAREHOLDER |

### trigger_comparison.csv

旧ロジック（株主提案ありのみ）と新ロジック（3条件）のトリガー比較。`compare_triggers.py --csv` で生成。

| カラム | 説明 |
|--------|------|
| 証券コード / 企業名 | 対象企業 |
| ステータス | 新規追加 / 既存継続 / 旧のみ |
| 条件A:賛成率低下 | 会社提案の賛成率が10pp以上低下 → ○ |
| 条件B:新規株主提案 | 前年になかった株主提案が出現 → ○ |
| 条件C:会社提案否決 | 会社提案が否決（候補者50%未満含む）→ ○ |
| 条件A〜C詳細 | 該当した議案/候補者の具体的内容 |

### trigger_holdings.csv

トリガー企業の大量保有報告書・保有者別タイムライン。`search_trigger_holdings.py` で生成。

| カラム | 説明 |
|--------|------|
| 証券コード / 企業名 | トリガー対象企業 |
| 保有者名 | 報告書の提出者名 |
| 最新保有割合(%) | 直近の保有比率 |
| 保有割合推移 | `24/03: 7.62% → 24/08: 4.44%` 形式の時系列 |
| 保有目的 | 純投資 / 重要提案行為 等 |
| トリガー条件 | A:賛成率低下 / B:新規株主提案 / C:会社提案否決 |
| 報告書件数 | その保有者の報告書数 |

### trigger_holdings_summary.csv

トリガー企業の大量保有報告書・企業単位サマリー。`search_trigger_holdings.py` で生成。

| カラム | 説明 |
|--------|------|
| 大量保有報告書 | あり / なし |
| 保有者数 | 報告書を出した保有者の数 |
| 保有者一覧 | `保有者名(保有割合%)` のサマリー |
| トリガー条件 | A / B / C のどれに該当したか |

### activist_analysis.csv（手動分析）

注目企業の詳細分析（手動まとめ）。条件列:
- **両方**: DECLINING + NEW_SHAREHOLDER 両方該当
- **新規株主提案**: NEW_SHAREHOLDER のみ該当

### activist_holdings_timeline.csv（手動分析）

アクティビストの保有割合推移。IRBANKの大量保有（5%ルール）ページから取得。
各投資家を個別行で管理し、共同保有の場合は備考に合計値を記載。

## データソース

| データ | ソース | 備考 |
|--------|--------|------|
| 臨時報告書（議決結果） | EDINET API | docTypeCode: 臨時報告書 |
| 大量保有報告書 | EDINET API / IRBANK | 5%ルール開示 |
| 企業マスタ | warehouse `wh_security` | 任意（社名補完用・read_only） |
| 株価・PER・PBR・利回り・ROE | warehouse `mart_latest` | 任意（read_only）。Mac側で derived JSON に焼き込み Cloud へ配布 |
| 株主総会一覧 | JPX | 参照用（APIアクセス不可） |

### 参考URL

- EDINET: https://disclosure.edinet-fsa.go.jp/
- IRBANK 大量保有: https://irbank.net/{EDINETコード}/share
- IRBANK 臨時報告書: https://irbank.net/{EDINETコード}/ext?f={書類ID}
- IRBANK 臨時報告書一覧（日別）: https://irbank.net/edi/adhoc?y=YYYY-MM-DD
- JPX 株主総会情報: https://www.jpx.co.jp/listing/event-schedules/shareholders-mtg/index.html

## 修正履歴

### approval_rate=0.0 パーサーバグ修正（2026-05-08）

| 問題 | 修正内容 |
|------|----------|
| `_parse_result_line` で賛成率抽出失敗時に `rate = 0.0` をフォールバック設定 | `rate = None` に変更（983件の偽0.0%を解消） |
| `_parse_grouped_candidates` で `pending_rate` が None のとき `0.0` を設定 | `r = pending_rate`（None のまま伝搬）に変更 |
| `has_rejected_company_proposals` が 0.0% を否決と誤判定 | `approval_rate == 0.0` かつ `votes_for > 0 or None` の場合はパーサーバグとしてスキップ |

### P0修正（2026-05-08）

| 問題 | 修正内容 |
|------|----------|
| 議案タイトルに「賛成」「128,451個」等が混入（中国電力等） | `_is_non_title_line` メソッド追加。投票ラベル・票数+単位・注記参照・パーセント表記をタイトル候補から除外 |
| `_is_vote_number` が「123,456個」形式を認識しない | 票数+単位「個」パターンに対応 |
| `httpx.Client` を毎リクエスト生成（パフォーマンス問題） | `EdinetClient` に永続 `httpx.Client` を保持。コンテキストマネージャ対応 |

## 既知の課題

- `fetch_holdings.py` の HTML 正規表現による保有割合抽出が一部失敗する
- 一部企業（ヤクルト本社・NTT等）で臨時報告書セクション(3)に議案タイトルが記載されておらず、タイトルが空になる（セクション(2)からの抽出が必要）
- 2023年分のキャッシュが空（`2023_meetings.json`）— 未取得
- JPX の株主総会一覧ページが 403 で直接取得不可

## 今後の予定

- [ ] 2023〜2025年の3期分トレンド比較（ゆうとさん要望の第2段階）
- [ ] セクション(2)からの議案タイトル抽出（空タイトル対策）
- [ ] EDINET APIリトライ機構の追加
- [ ] activist_holdings_timeline.csv の自動更新スクリプト化

---

## 公開版（GitHub Pages・現行）

**公開 URL: https://shell0423.github.io/sokai-agenda/**

boutetsuya-stocks と同じ「**完成済みHTMLを1枚だけ静的配信する**」方式。
`src/dashboard_gen.py` が生成した `output/dashboard_2026.html` を
`publish.py` が `docs/index.html` へ複製し、GitHub Pages（main ブランチの `/docs`）が配信する。
Python 実行環境は不要なので、Streamlit Cloud への登録も要らない。

- **公開リポジトリ**: https://github.com/shell0423/sokai-agenda （public）
- **更新**: launchd → `scripts/publish.py`（再生成 → docs/ 更新 → 秘密スキャン → push）
- **公開されるもの**: 実戦リスト（Tier別・株価/PER/PBR・株探リンク）／卒業・決着／注意点
- **公開されないもの**: Tier絞り込み・行クリック詳細・銘柄検索（＝Streamlit アプリ側の機能）

### ローカルアプリ版との違い

| | ローカル Streamlit | 公開ページ(GitHub Pages) |
|---|---|---|
| 実行 | Python が常駐 | 静的HTML（サーバー処理なし） |
| Tier絞り込み・行クリック詳細・銘柄検索 | ✅ | ❌ |
| 実戦リスト（Tier別・PER/PBR） | ✅ | ✅ |
| 株探リンク | ✅ | ✅（企業名がリンク） |
| 大量保有チャート・議案別賛成率 | ✅ | ❌ |

## Streamlit Cloud 公開版（未使用・いつでも再開できる状態）

対話機能ごと公開したくなった場合の選択肢。コード側の対応（`_is_cloud()` 判定・
`.streamlit/config.toml`・`runtime.txt`・Secrets 手順）は実装済みで、
https://share.streamlit.io/deploy でリポジトリを登録すれば動く。

- **公開 URL**: 未デプロイ（https://shell0423-sokai-agenda.streamlit.app 予定）

### ローカル版と Cloud 版の機能差分

| 機能 | ローカル | Cloud |
|---|---|---|
| 実戦リスト・全トリガー・卒業タブの閲覧 | ✅ | ✅ |
| 銘柄詳細（議案別賛成率 2025 vs 2026） | ✅ | ✅ |
| 大量保有タイムライン＋チャート | ✅ | ✅ |
| ⚡ 高速再生成ボタン（キャッシュから） | ✅ | ✅ |
| 🔄 フル更新ボタン（EDINET 再スキャン 40分〜2時間） | ✅ | ⚠️ 縮退（高速再生成に置換） |
| 📡 データ充足チェック | ✅ | ✅（EDINET_API_KEY 登録時のみ） |
| 🏭 倉庫レディネス判定 | ✅ | ❌ warehouse 未接続のため機能しません |
| 株価・PER・PBR の表示 | ✅ 最新（倉庫を直接参照） | ✅ 配布スナップショット（実戦リスト・除外の73社のみ） |
| 株探・IRBANK リンク | ✅ | ✅ |

### Cloud 用 Secrets の登録手順

1. https://share.streamlit.io で対象 app を開く
2. 右上 **⋯** → **Settings** → **Secrets** タブ
3. `.streamlit/secrets.toml.example` の中身をコピーし、
   `EDINET_API_KEY = "..."` を **自分の実キー** に置換して貼付
4. **Save** をクリック（自動再デプロイされる）

`.env`（ローカル）と `secrets.toml`（Cloud）の対応：

| 変数 | ローカル `.env` | Cloud Secrets |
|---|---|---|
| `EDINET_API_KEY` | 必須 | 必須（フル更新縮退版・充足チェック用） |
| `WAREHOUSE_DIR` | 任意 | 設定しない（Cloud には warehouse 無し） |

### 実行環境の判定ロジック

`app.py` の `_is_cloud()` が下記のどれかを満たせば Cloud と判定：
- 環境変数 `STREAMLIT_RUNTIME_ENV=cloud`
- `HOSTNAME` に `streamlit` を含む
- `~/Claude/warehouse/client.py` が存在しない

Cloud 判定時は：フル更新ボタンが高速再生成に置換、倉庫レディネスタブに警告バナー、
`st.secrets` の `EDINET_API_KEY` を `os.environ` に注入。

---

## 毎日更新の仕組み（launchd）

boutetsuya-stocks と同じ思想で、Mac ローカルの launchd が日次で全処理を回します。

```
06:00 JST
   │
   └─→ launchd (com.sokai.refresh)
         │
         └─→ .venv/bin/python scripts/publish.py --fast
               │
               ├─ [1/5] src.jobs fast（数秒〜1分・通信なし）
               │     compare_triggers×2 → 差分/実戦リスト
               │     → **株価/PER/PBR を倉庫から取り直し** → dashboard HTML
               │
               ├─ [2/5] docs/index.html を更新（GitHub Pages の配信元）
               │
               ├─ [3/5] 秘密情報スキャン（webhook URL/APIキー混入検査）
               │     公開対象ファイル群を正規表現で走査。ヒット時は push 中止。
               │
               ├─ [4/5] git add（.gitignore 白リスト分のみ）
               │     docs/, output/derived/, output/watchlist_*.csv,
               │     output/trigger_holdings_summary.csv,
               │     output/trigger_analysis_*.md, output/dashboard_*.html,
               │     output/diff_*.md, data/*.json
               │
               └─ [5/5] git commit -m "daily: YYYY-MM-DD refresh" && git push origin main
                     ↓
                GitHub Pages が push を検知して再ビルド（1〜2分で反映）
```

### 日次は「軽量」・EDINET再スキャンは季節作業

株主総会の議決結果は**年1回**しか増えないので、EDINET の全再スキャン（40分〜2時間）を
毎日回す意味はない。一方 **株価・PER・PBR は毎日動く**ので、日次は倉庫を読むだけの
`--fast`（数秒〜1分）で回す。

| モード | 中身 | 所要 | いつ |
|---|---|---|---|
| `publish.py --fast` | `src.jobs fast`（キャッシュ再計算＋倉庫からPER/PBR） | 数秒〜1分 | **毎日06:00・launchd** |
| `publish.py` | `full_update.sh`（EDINET全再スキャン） | 40分〜2時間 | **総会後に手動**（例: 7/30 アインHD総会後） |
| `publish.py --skip-full` | 再生成なし・現状ファイルを公開 | 数秒 | 疎通確認用 |

### launchd の on/off 手順

**インストール（初回のみ）:**

```bash
cp ~/Claude/株主総会議案分析/scripts/com.sokai.refresh.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.sokai.refresh.plist
launchctl list | grep sokai   # com.sokai.refresh が表示されればロード成功
```

**手動キック（テスト実行）:**

```bash
launchctl kickstart -k gui/$(id -u)/com.sokai.refresh
# → output/logs/publish.log と output/logs/launchd_stdout.log を tail で監視
```

**停止:**

```bash
launchctl unload ~/Library/LaunchAgents/com.sokai.refresh.plist
```

**再ロード（plist を編集したあと）:**

```bash
launchctl unload ~/Library/LaunchAgents/com.sokai.refresh.plist
cp ~/Claude/株主総会議案分析/scripts/com.sokai.refresh.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.sokai.refresh.plist
```

### publish.py の単体実行（launchd を通さない検証）

```bash
cd ~/Claude/株主総会議案分析
.venv/bin/python scripts/publish.py --fast --dry-run  # 日次と同じ再生成、push はしない
.venv/bin/python scripts/publish.py --skip-full       # 再生成せず現状ファイルだけ公開
.venv/bin/python scripts/publish.py --fast            # 日次運用と同じ挙動（launchd と同一）
.venv/bin/python scripts/publish.py                   # フル更新つき（総会後に手動で）
```

### ログの見方

- `output/logs/publish.log` — publish.py 自身のログ（各ステップの ✅ / ❌）
- `output/logs/full_update.log` — full_update.sh のログ
- `output/logs/launchd_stdout.log` / `launchd_stderr.log` — launchd 経由の生 stdout/stderr
