"""トリガー該当企業の大量保有報告書を一括検索するスクリプト。

compare_triggers.py で抽出した条件該当企業に対し、
EDINET APIで大量保有報告書（docTypeCode 350/360）を一括スキャンし、
保有者・割合・保有目的をCSV出力する。

使い方:
    # 通常実行（キャッシュあり、スキャン結果を再利用）
    python search_trigger_holdings.py

    # キャッシュ無視で再スキャン
    python search_trigger_holdings.py --no-cache

    # スキャン期間を指定
    python search_trigger_holdings.py --start 2024-01-01 --end 2026-05-08

    # 出力先を指定
    python search_trigger_holdings.py -o output/my_holdings.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from compare_triggers import analyze_triggers
from src.edinet_client import EdinetClient
from src.xbrl_parser import XbrlParser

logger = logging.getLogger(__name__)

CACHE_PATH = Path("output/cache/tairyo_scan.json")


# ------------------------------------------------------------------
# データ構造
# ------------------------------------------------------------------

@dataclass
class HoldingRecord:
    """1件の大量保有報告書レコード。"""

    sec_code: str
    company_name: str
    holder_name: str
    ratio_held: float | None
    ratio_before: float | None
    purpose: str
    submit_date: str
    doc_type: str  # "新規" or "変更"
    trigger_conditions: str


@dataclass
class HolderTimeline:
    """1社・1保有者の保有割合推移。"""

    sec_code: str
    company_name: str
    holder_name: str
    purpose: str
    trigger_conditions: str
    entries: list[tuple[str, float | None]] = field(
        default_factory=list
    )  # [(submit_date, ratio), ...]


# ------------------------------------------------------------------
# キャッシュ
# ------------------------------------------------------------------

def _save_scan_cache(
    docs: list[dict], path: Path = CACHE_PATH
) -> None:
    """スキャン結果をJSONキャッシュに保存する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(docs, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("スキャンキャッシュ保存: %s (%d件)", path, len(docs))


def _load_scan_cache(
    path: Path = CACHE_PATH,
) -> list[dict] | None:
    """スキャンキャッシュを読み込む。"""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        logger.info(
            "スキャンキャッシュ読み込み: %s (%d件)", path, len(data)
        )
        return data
    except (json.JSONDecodeError, TypeError):
        return None


# ------------------------------------------------------------------
# 一括スキャン
# ------------------------------------------------------------------

def scan_all_holding_docs(
    edinet_client: EdinetClient,
    start_date: date,
    end_date: date,
    use_cache: bool = True,
) -> list[dict]:
    """全大量保有報告書のメタデータを一括取得する。

    Args:
        edinet_client: EDINETクライアント。
        start_date: スキャン開始日。
        end_date: スキャン終了日。
        use_cache: キャッシュを使用するか。

    Returns:
        大量保有報告書のメタデータリスト。
    """
    if use_cache:
        cached = _load_scan_cache()
        if cached is not None:
            return cached

    logger.info(
        "EDINET一括スキャン開始: %s 〜 %s", start_date, end_date
    )

    def is_holding(doc: dict) -> bool:
        return doc.get("docTypeCode", "") in ("350", "360")

    docs = edinet_client.scan_date_range(
        start_date=start_date,
        end_date=end_date,
        doc_filter=is_holding,
    )

    logger.info("大量保有報告書: %d件", len(docs))
    _save_scan_cache(docs)
    return docs


# ------------------------------------------------------------------
# マッチング＋XBRL解析
# ------------------------------------------------------------------

def match_and_parse(
    edinet_client: EdinetClient,
    holding_docs: list[dict],
    target_edinet_codes: dict[str, tuple[str, str, str]],
) -> list[HoldingRecord]:
    """大量保有報告書をターゲット企業とマッチングし、XBRLを解析する。

    Args:
        edinet_client: EDINETクライアント。
        holding_docs: 大量保有報告書メタデータリスト。
        target_edinet_codes: {edinet_code: (sec_code, company_name,
            trigger_conditions)} のマッピング。

    Returns:
        HoldingRecordリスト。
    """
    # issuerEdinetCodeでフィルタ
    matched_docs: list[tuple[dict, str, str, str]] = []
    for doc in holding_docs:
        issuer = doc.get("issuerEdinetCode", "") or ""
        if issuer in target_edinet_codes:
            sec_code, company_name, conditions = (
                target_edinet_codes[issuer]
            )
            matched_docs.append(
                (doc, sec_code, company_name, conditions)
            )

    if not matched_docs:
        logger.info("マッチする大量保有報告書なし")
        return []

    logger.info(
        "マッチした報告書: %d件（%d社）",
        len(matched_docs),
        len({d[1] for d in matched_docs}),
    )

    # XBRL解析
    parser = XbrlParser()
    records: list[HoldingRecord] = []
    total = len(matched_docs)

    for idx, (doc, sec_code, company_name, conditions) in enumerate(
        matched_docs, 1
    ):
        doc_id = doc.get("docID", "")
        filer_name = doc.get("filerName", "") or "不明"
        submit_date = (
            doc.get("submitDateTime", "") or ""
        )[:10]
        doc_type_code = doc.get("docTypeCode", "")
        doc_type = "新規" if doc_type_code == "350" else "変更"

        if idx % 20 == 0 or idx == total:
            logger.info("  解析中: %d/%d", idx, total)

        try:
            zip_bytes = edinet_client.download_document_zip(doc_id)
            info = parser.parse_zip(zip_bytes)
            holder_name = info.holder_name or filer_name
            records.append(
                HoldingRecord(
                    sec_code=sec_code,
                    company_name=company_name,
                    holder_name=holder_name,
                    ratio_held=info.ratio_held,
                    ratio_before=info.ratio_before,
                    purpose=info.purpose or "",
                    submit_date=submit_date,
                    doc_type=doc_type,
                    trigger_conditions=conditions,
                )
            )
        except Exception:
            logger.warning(
                "解析失敗: %s (%s)", doc_id, filer_name,
                exc_info=True,
            )

    return records


# ------------------------------------------------------------------
# タイムライン構築
# ------------------------------------------------------------------

def build_timelines(
    records: list[HoldingRecord],
) -> list[HolderTimeline]:
    """レコードを(企業,保有者)ごとにグループ化してタイムライン化。"""
    # key: (sec_code, holder_name) → list[HoldingRecord]
    groups: dict[tuple[str, str], list[HoldingRecord]] = {}
    for r in records:
        key = (r.sec_code, r.holder_name)
        groups.setdefault(key, []).append(r)

    timelines: list[HolderTimeline] = []
    for (sec_code, holder_name), recs in sorted(groups.items()):
        recs.sort(key=lambda r: r.submit_date)
        entries = [
            (r.submit_date, r.ratio_held) for r in recs
        ]
        # 最新レコードから情報を取得
        latest = recs[-1]
        timelines.append(
            HolderTimeline(
                sec_code=sec_code,
                company_name=latest.company_name,
                holder_name=holder_name,
                purpose=latest.purpose,
                trigger_conditions=latest.trigger_conditions,
                entries=entries,
            )
        )

    return timelines


# ------------------------------------------------------------------
# CSV出力
# ------------------------------------------------------------------

def export_timeline_csv(
    timelines: list[HolderTimeline],
    path: Path,
) -> None:
    """タイムラインをCSVに出力する。"""
    path.parent.mkdir(parents=True, exist_ok=True)

    headers = [
        "証券コード",
        "企業名",
        "保有者名",
        "最新保有割合(%)",
        "保有割合推移",
        "保有目的",
        "トリガー条件",
        "報告書件数",
    ]

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for tl in timelines:
            # 推移文字列: "24/06/01: 5.53% → 24/08/01: 6.22%"
            entries_str = " → ".join(
                f"{d[2:7].replace('-', '/')}: "
                + (f"{r:.2f}%" if r is not None else "N/A")
                for d, r in tl.entries
            )

            # 最新保有割合
            latest_ratio = None
            for _, r in reversed(tl.entries):
                if r is not None:
                    latest_ratio = r
                    break

            writer.writerow([
                tl.sec_code,
                tl.company_name,
                tl.holder_name,
                (
                    f"{latest_ratio:.2f}"
                    if latest_ratio is not None
                    else ""
                ),
                entries_str,
                tl.purpose,
                tl.trigger_conditions,
                len(tl.entries),
            ])

    print(f"\nCSV出力: {path} ({len(timelines)}行)")


def export_summary_csv(
    timelines: list[HolderTimeline],
    all_target_codes: set[str],
    name_map: dict[str, str],
    conditions_map: dict[str, str],
    path: Path,
) -> None:
    """企業単位のサマリーCSVを出力する。

    大量保有報告書の有無と保有者一覧を1社1行で表示。
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # sec_code → timelines
    by_company: dict[str, list[HolderTimeline]] = {}
    for tl in timelines:
        by_company.setdefault(tl.sec_code, []).append(tl)

    headers = [
        "証券コード",
        "企業名",
        "大量保有報告書",
        "保有者数",
        "保有者一覧",
        "トリガー条件",
    ]

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for code4 in sorted(all_target_codes):
            company_tls = by_company.get(code4, [])
            has_report = "あり" if company_tls else "なし"
            n_holders = len(company_tls)

            holder_list = " / ".join(
                f"{tl.holder_name}"
                + (
                    f"({tl.entries[-1][1]:.1f}%)"
                    if tl.entries and tl.entries[-1][1] is not None
                    else ""
                )
                for tl in company_tls
            )

            writer.writerow([
                code4,
                name_map.get(code4, "不明"),
                has_report,
                n_holders if n_holders > 0 else "",
                holder_list,
                conditions_map.get(code4, ""),
            ])

    print(f"サマリーCSV出力: {path} ({len(all_target_codes)}行)")


# ------------------------------------------------------------------
# エントリーポイント
# ------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする。"""
    parser = argparse.ArgumentParser(
        description="トリガー該当企業の大量保有報告書を一括検索"
    )
    parser.add_argument(
        "--start",
        type=str,
        default="2024-01-01",
        help="スキャン開始日（デフォルト: 2024-01-01）",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="スキャン終了日（デフォルト: 今日）",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="output/trigger_holdings.csv",
        help="タイムラインCSV出力先",
    )
    parser.add_argument(
        "--summary",
        type=str,
        default="output/trigger_holdings_summary.csv",
        help="サマリーCSV出力先",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="スキャンキャッシュを無視",
    )
    parser.add_argument(
        "--holding-threshold",
        type=float,
        default=-10.0,
        help="条件Aの閾値（pp、デフォルト: -10.0）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="デバッグログ",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    load_dotenv()
    edinet_key = os.getenv("EDINET_API_KEY", "")
    if not edinet_key:
        print("エラー: EDINET_API_KEY が設定されていません")
        sys.exit(1)

    # Step 1: トリガー分析（キャッシュ済みデータ使用、API不要）
    print("Step 1: トリガー分析...")
    triggers, stats = analyze_triggers(
        years=[2024, 2025],
        holding_threshold=args.holding_threshold,
    )

    # 新ロジックで該当する企業のみ対象
    target_triggers = [
        t for t in triggers if t.status in ("新規追加", "既存継続")
    ]
    print(
        f"  対象企業: {len(target_triggers)}社 "
        f"(新規追加: {stats['added']}社, "
        f"既存継続: {stats['common']}社)"
    )

    # sec_code → edinet_code マッピングの構築
    from src.trend_cache import load_year_data

    year_data = {}
    for y in [2024, 2025]:
        data = load_year_data(y, Path("output/cache"))
        if data:
            year_data[y] = data

    # edinet_code → (sec_code, company_name, conditions)
    edinet_map: dict[str, tuple[str, str, str]] = {}
    name_map: dict[str, str] = {}
    conditions_map: dict[str, str] = {}

    target_sec_codes = {t.sec_code for t in target_triggers}

    for t in target_triggers:
        conds: list[str] = []
        if t.cond_a:
            conds.append("A:賛成率低下")
        if t.cond_b:
            conds.append("B:新規株主提案")
        if t.cond_c:
            conds.append("C:会社提案否決")
        conditions_map[t.sec_code] = " + ".join(conds)
        name_map[t.sec_code] = t.company_name

    for meetings in year_data.values():
        for m in meetings:
            code4 = m.sec_code[:4]
            if code4 in target_sec_codes and m.edinet_code:
                conds_str = conditions_map.get(code4, "")
                edinet_map[m.edinet_code] = (
                    code4, m.company_name, conds_str
                )

    print(f"  EDINET コード解決: {len(edinet_map)}社")

    # Step 2: EDINET一括スキャン
    start_date = date.fromisoformat(args.start)
    end_date = (
        date.fromisoformat(args.end)
        if args.end
        else date.today()
    )

    print(f"\nStep 2: EDINET一括スキャン ({start_date} 〜 {end_date})...")

    with EdinetClient(api_key=edinet_key) as client:
        holding_docs = scan_all_holding_docs(
            client, start_date, end_date,
            use_cache=not args.no_cache,
        )
        print(f"  大量保有報告書: {len(holding_docs)}件")

        # Step 3: マッチング＋XBRL解析
        print("\nStep 3: マッチング＋XBRL解析...")
        records = match_and_parse(client, holding_docs, edinet_map)

    print(f"  解析完了: {len(records)}件")

    # Step 4: タイムライン構築＋CSV出力
    print("\nStep 4: CSV出力...")
    timelines = build_timelines(records)

    # 保有報告書がある企業数
    companies_with_holdings = {tl.sec_code for tl in timelines}
    print(
        f"  大量保有報告書あり: "
        f"{len(companies_with_holdings)}社 / "
        f"{len(target_sec_codes)}社"
    )

    export_timeline_csv(timelines, Path(args.output))
    export_summary_csv(
        timelines,
        target_sec_codes,
        name_map,
        conditions_map,
        Path(args.summary),
    )

    print("\n完了!")


if __name__ == "__main__":
    main()
