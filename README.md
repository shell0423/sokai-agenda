# 株主総会議案分析 & アクティビスト保有調査

## 概要

3月決算企業の定時株主総会における **議案別の賛成・反対割合** を取得し、
**株主提案** や **会社提案の賛成率低下** をスクリーニングした上で、
該当企業の **アクティビスト保有状況**（大量保有報告書）を調査するツール。

ゆうとさんからの依頼に基づき作成。

## 技術スタック

- Python 3.11+
- EDINET API（臨時報告書・大量保有報告書）
- J-Quants API（企業マスタ補完）
- httpx / pandas / openpyxl

## 分析フロー（3段階の漏斗型）

```
Step 1: 全企業トレンド分析（約2,300社）
  │  EDINET APIで臨時報告書（株主総会決議）を期間スキャン
  │  2年分の議案別賛成率を比較
  │
  │  → trend_YYYY_YYYY.csv
  │
  ▼ スクリーニング条件
Step 2: 注目企業の抽出（数十社）
  │  条件A: 会社提案の賛成率が5pp以上低下（DECLINING）
  │  条件B: 新たに株主提案が提出された（NEW_SHAREHOLDER）
  │  → 「両方」該当 or 「新規株主提案のみ」で注目企業をリストアップ
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
| Step 1 | 約2,365社をスキャン |
| DECLINING | 483社（会社提案の賛成率が5pp以上低下） |
| NEW_SHAREHOLDER | 36社（新規株主提案あり） |
| 両方該当 | 14社 |
| Step 2 | 22社を詳細分析 |
| Step 3 | 各社のアクティビスト保有推移を追跡 |

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
| `JQUANTS_API_KEY` | J-Quants API（任意） | https://jpx-jquants.com/ |

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
| `--no-cache` | キャッシュ無視 | false |
| `--verbose` | デバッグログ | false |

### 補助スクリプト

```bash
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
│   ├── jquants_client.py       # J-Quants API クライアント
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
├── check_activists.py          # アクティビスト判定スクリプト（単体実行用）
├── fetch_holdings.py           # 保有割合抽出スクリプト（単体実行用）
├── inspect_doc.py              # EDINET文書の中身確認用
├── output/                     # 出力先（.gitignore対象）
│   ├── trend_2024_2025.csv     # Step 1: 全企業トレンド（約15,000行）
│   ├── activist_analysis.csv   # Step 2: 注目企業リスト（手動分析）
│   ├── activist_holdings_timeline.csv  # Step 3: アクティビスト保有推移
│   ├── activist_check.csv      # check_activists.py の出力
│   ├── activist_holdings.csv   # fetch_holdings.py の出力
│   └── cache/                  # EDINET取得データのキャッシュ（JSON）
│       ├── 2024_meetings.json
│       ├── 2025_meetings.json
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

### activist_analysis.csv（Step 2）

注目企業の詳細分析（手動まとめ）。条件列:
- **両方**: DECLINING + NEW_SHAREHOLDER 両方該当
- **新規株主提案**: NEW_SHAREHOLDER のみ該当

### activist_holdings_timeline.csv（Step 3）

アクティビストの保有割合推移。IRBANKの大量保有（5%ルール）ページから取得。
各投資家を個別行で管理し、共同保有の場合は備考に合計値を記載。

## データソース

| データ | ソース | 備考 |
|--------|--------|------|
| 臨時報告書（議決結果） | EDINET API | docTypeCode: 臨時報告書 |
| 大量保有報告書 | EDINET API / IRBANK | 5%ルール開示 |
| 企業マスタ | J-Quants API | 任意（企業名補完用） |
| 株主総会一覧 | JPX | 参照用（APIアクセス不可） |

### 参考URL

- EDINET: https://disclosure.edinet-fsa.go.jp/
- IRBANK 大量保有: https://irbank.net/{EDINETコード}/share
- IRBANK 臨時報告書: https://irbank.net/{EDINETコード}/ext?f={書類ID}
- IRBANK 臨時報告書一覧（日別）: https://irbank.net/edi/adhoc?y=YYYY-MM-DD
- JPX 株主総会情報: https://www.jpx.co.jp/listing/event-schedules/shareholders-mtg/index.html

## 既知の課題

- `fetch_holdings.py` の HTML 正規表現による保有割合抽出が一部失敗する
- `trend_2024_2025.csv` の末尾に一部パースエラーあり（議決権数が議案カテゴリに混入）
- 2023年分のキャッシュが空（`2023_meetings.json`）— 未取得
- JPX の株主総会一覧ページが 403 で直接取得不可

## 今後の予定

- [ ] 2023〜2025年の3期分トレンド比較（ゆうとさん要望の第2段階）
- [ ] 会社提案が否決された場合にも大量保有報告書を自動検索するロジック追加
- [ ] パースエラーの修正（中国電力等）
- [ ] activist_holdings_timeline.csv の自動更新スクリプト化
