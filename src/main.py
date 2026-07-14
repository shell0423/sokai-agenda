from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

from src.csv_exporter import CsvExporter
from src.edinet_client import EXTRAORDINARY_REPORT_CODE, EdinetClient
from src.holding_searcher import HoldingSearcher
from src import warehouse_client
from src.models import AnalysisRecord, MeetingResult, TrendReport
from src.resolution_parser import ResolutionParser
from src.trend_analyzer import TrendAnalyzer
from src.trend_cache import load_year_data, save_year_data
from src.trend_exporter import export_trend_csv, print_trend_report

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする。"""
    parser = argparse.ArgumentParser(
        description="株主総会議案の賛否割合・アクティビスト保有状況を分析する"
    )
    parser.add_argument(
        "--year",
        type=int,
        default=date.today().year,
        help="対象年度（デフォルト: 今年）",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="スキャン開始日 (YYYY-MM-DD)。未指定時は対象年の5月1日",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="スキャン終了日 (YYYY-MM-DD)。未指定時は対象年の8月31日",
    )
    parser.add_argument(
        "--code",
        type=str,
        default=None,
        help="特定企業の証券コード（4桁）で絞り込み",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="出力ファイルパス。未指定時は output/results_YYYY.csv",
    )
    parser.add_argument(
        "--format",
        choices=["csv", "excel"],
        default="csv",
        help="出力形式（デフォルト: csv）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="結果をコンソールに表示のみ（ファイル出力しない）",
    )
    parser.add_argument(
        "--skip-holdings",
        action="store_true",
        help="大量保有報告書の検索をスキップ",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="デバッグログを有効化",
    )
    # トレンド分析オプション
    parser.add_argument(
        "--trend",
        action="store_true",
        help="年度間トレンド比較モードを有効化",
    )
    parser.add_argument(
        "--years",
        type=str,
        default=None,
        help="比較対象年度（カンマ区切り、例: 2024,2025）",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=-5.0,
        help="賛成率低下アラートの閾値（pp、デフォルト: -5.0）",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="キャッシュを無視してEDINETから再取得",
    )
    parser.add_argument(
        "--holding-threshold",
        type=float,
        default=-10.0,
        help=(
            "大量保有報告書検索トリガーの賛成率低下閾値（pp、"
            "デフォルト: -10.0）"
        ),
    )
    parser.add_argument(
        "--scan-start-month",
        type=int,
        default=5,
        help=(
            "スキャン開始月（デフォルト: 5）。"
            "3月決算=5, 12月決算=2, 6月決算=8"
        ),
    )
    parser.add_argument(
        "--scan-end-month",
        type=int,
        default=8,
        help=(
            "スキャン終了月（デフォルト: 8）。"
            "3月決算=8, 12月決算=5, 6月決算=11"
        ),
    )
    return parser.parse_args()


def _setup_logging(verbose: bool) -> None:
    """ロギングを設定する。"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _build_meeting_results(
    edinet_client: EdinetClient,
    resolution_parser: ResolutionParser,
    start_date: date,
    end_date: date,
    target_code: str | None,
) -> list[MeetingResult]:
    """EDINET APIから臨時報告書を取得し、議決結果を解析する。

    Args:
        edinet_client: EDINETクライアント。
        resolution_parser: 議決結果パーサー。
        start_date: スキャン開始日。
        end_date: スキャン終了日。
        target_code: 絞り込み証券コード（4桁）。Noneで全件。

    Returns:
        MeetingResultリスト。
    """

    def doc_filter(doc: dict) -> bool:
        if doc.get("docTypeCode") != EXTRAORDINARY_REPORT_CODE:
            return False
        sec_code = doc.get("secCode") or ""
        # 投資ファンド等（secCodeなし）を除外
        if not sec_code:
            return False
        if target_code:
            return sec_code.startswith(target_code)
        return True

    logger.info(
        "EDINET スキャン開始: %s 〜 %s", start_date, end_date
    )
    docs = edinet_client.scan_date_range(
        start_date=start_date,
        end_date=end_date,
        doc_filter=doc_filter,
    )
    logger.info("臨時報告書候補: %d件", len(docs))

    # 企業ごとに重複排除（同一企業で複数の臨時報告書がある場合）
    # secCode + ResolutionOfShareholdersMeeting タグで判定
    meeting_results: list[MeetingResult] = []
    seen_codes: set[str] = set()

    for doc in docs:
        sec_code = doc.get("secCode", "") or ""
        code4 = sec_code[:4]
        if code4 in seen_codes:
            continue

        doc_id = doc.get("docID", "")
        filer_name = doc.get("filerName", "") or ""

        logger.debug("処理中: %s (%s)", filer_name, doc_id)

        try:
            zip_bytes = edinet_client.download_document_zip(doc_id)
        except Exception:
            logger.warning("ZIP DL失敗: %s", doc_id, exc_info=True)
            continue

        # 株主総会決議の臨時報告書か判定
        if not resolution_parser.has_resolution_tag(zip_bytes):
            continue

        # パース
        proposals = resolution_parser.parse_zip(zip_bytes)
        if not proposals:
            continue

        meeting = MeetingResult(
            doc_id=doc_id,
            edinet_code=doc.get("edinetCode", "") or "",
            sec_code=sec_code,
            company_name=filer_name,
            submit_date=(
                doc.get("submitDateTime", "") or ""
            )[:10],
            proposals=proposals,
        )
        meeting_results.append(meeting)
        seen_codes.add(code4)

        logger.info(
            "✓ %s: %d議案 (株主提案: %s)",
            filer_name,
            len(proposals),
            "あり" if meeting.has_shareholder_proposals else "なし",
        )

    # 提出者名が空の行を warehouse の会社マスタ(wh_security)で補完
    filled = warehouse_client.apply_master_names(meeting_results)
    if filled:
        logger.info("warehouse社名で補完: %d件", filled)

    return meeting_results


def _flatten_to_records(
    meetings: list[MeetingResult],
    holdings_map: dict[str, list],
) -> list[AnalysisRecord]:
    """MeetingResultリストをフラットなAnalysisRecordリストに変換する。

    Args:
        meetings: 議決結果リスト。
        holdings_map: edinetCode → HoldingContextリストのマッピング。

    Returns:
        AnalysisRecordリスト。
    """
    records: list[AnalysisRecord] = []

    for meeting in meetings:
        code4 = meeting.sec_code[:4]
        holders = holdings_map.get(meeting.edinet_code, [])
        holder_summary = ", ".join(
            f"{h.holder_name}({h.ratio_held:.2f}%)"
            if h.ratio_held
            else h.holder_name
            for h in holders
        )

        for proposal in meeting.proposals:
            if proposal.candidates:
                # 候補者ごとにレコード生成
                for cand in proposal.candidates:
                    result_str = ""
                    if cand.approval_rate is not None:
                        is_approved = (
                            cand.approval_rate >= 50.0
                        )
                        result_str = (
                            "可決" if is_approved else "否決"
                        )

                    records.append(
                        AnalysisRecord(
                            sec_code=code4,
                            company_name=meeting.company_name,
                            proposal_number=proposal.number,
                            proposal_title=proposal.title,
                            proposal_type=proposal.proposal_type.value,
                            candidate_name=cand.name,
                            result=result_str,
                            approval_rate=cand.approval_rate,
                            votes_for=cand.votes_for,
                            votes_against=cand.votes_against,
                            votes_abstain=cand.votes_abstain,
                            major_holders=(
                                holder_summary
                                if proposal.proposal_type.value
                                == "株主提案"
                                else ""
                            ),
                            submit_date=meeting.submit_date,
                            doc_id=meeting.doc_id,
                        )
                    )
            else:
                # 候補者なし議案
                result_str = (
                    proposal.result.value if proposal.result else ""
                )

                records.append(
                    AnalysisRecord(
                        sec_code=code4,
                        company_name=meeting.company_name,
                        proposal_number=proposal.number,
                        proposal_title=proposal.title,
                        proposal_type=proposal.proposal_type.value,
                        candidate_name="",
                        result=result_str,
                        approval_rate=proposal.approval_rate,
                        votes_for=proposal.votes_for,
                        votes_against=proposal.votes_against,
                        votes_abstain=proposal.votes_abstain,
                        major_holders=(
                            holder_summary
                            if proposal.proposal_type.value
                            == "株主提案"
                            else ""
                        ),
                        submit_date=meeting.submit_date,
                        doc_id=meeting.doc_id,
                    )
                )

    return records


def run(args: argparse.Namespace) -> None:
    """メイン処理。"""
    load_dotenv()

    edinet_key = os.getenv("EDINET_API_KEY", "")
    if not edinet_key:
        logger.error("EDINET_API_KEY が設定されていません")
        sys.exit(1)

    # 日付範囲の決定
    year = args.year
    start_date = (
        date.fromisoformat(args.start_date)
        if args.start_date
        else date(year, args.scan_start_month, 1)
    )
    if args.end_date:
        end_date = date.fromisoformat(args.end_date)
    else:
        end_month = args.scan_end_month
        # 月末日を算出
        if end_month == 12:
            end_date = date(year, 12, 31)
        else:
            end_date = date(year, end_month + 1, 1) - timedelta(
                days=1
            )

    # クライアント初期化（コンテキストマネージャでコネクション再利用）
    with EdinetClient(api_key=edinet_key) as edinet_client:
        resolution_parser = ResolutionParser()

        # Step 1: 臨時報告書の取得とパース
        meetings = _build_meeting_results(
            edinet_client,
            resolution_parser,
            start_date,
            end_date,
            args.code,
        )

        if not meetings:
            logger.info("該当する株主総会決議が見つかりませんでした")
            return

        # Step 2: warehouse の会社マスタ(wh_security)で社名を補完（任意）
        filled = warehouse_client.apply_master_names(meetings)
        if filled:
            logger.info("warehouse社名で補完: %d件", filled)

        # Step 3: 株主提案がある企業の大量保有報告書検索
        holdings_map: dict[str, list] = {}
        if not args.skip_holdings:
            holding_searcher = HoldingSearcher(edinet_client)
            # 検索範囲: 対象年の1月1日〜スキャン終了日
            h_start = date(year, 1, 1)

            for meeting in meetings:
                if meeting.has_shareholder_proposals:
                    holders = holding_searcher.search_holders(
                        edinet_code=meeting.edinet_code,
                        search_start=h_start,
                        search_end=end_date,
                    )
                    if holders:
                        holdings_map[meeting.edinet_code] = holders

    # Step 4: フラットなレコードに変換
    records = _flatten_to_records(meetings, holdings_map)

    # Step 5: 出力
    if args.dry_run:
        _print_results(records)
    else:
        output_path = Path(
            args.output or f"output/results_{year}.csv"
        )
        exporter = CsvExporter()
        if args.format == "excel":
            output_path = output_path.with_suffix(".xlsx")
            exporter.export_excel(records, output_path)
        else:
            exporter.export_csv(records, output_path)

    logger.info(
        "完了: %d社, %dレコード",
        len(meetings),
        len(records),
    )


def _print_results(records: list[AnalysisRecord]) -> None:
    """結果をコンソールに表示する。"""
    current_company = ""
    for r in records:
        if r.company_name != current_company:
            current_company = r.company_name
            print(f"\n{'='*60}")
            print(f"  {r.sec_code} {r.company_name}")
            print(f"  提出日: {r.submit_date}")
            print(f"{'='*60}")

        candidate_str = f" [{r.candidate_name}]" if r.candidate_name else ""
        rate_str = (
            f"{r.approval_rate:.2f}%"
            if r.approval_rate is not None
            else "N/A"
        )
        holder_str = f"  保有者: {r.major_holders}" if r.major_holders else ""

        print(
            f"  第{r.proposal_number}号 "
            f"[{r.proposal_type}] "
            f"{r.proposal_title}"
            f"{candidate_str}"
            f" → {r.result} ({rate_str})"
        )
        if holder_str:
            print(holder_str)


def _search_alert_holdings(
    edinet_client: EdinetClient,
    report: TrendReport,
    year_data: dict[int, list[MeetingResult]],
    years: list[int],
    holding_threshold: float = -10.0,
    skip: bool = False,
) -> dict[str, list]:
    """アラート企業の大量保有報告書を検索する。

    以下の条件に該当する企業を検索対象とする:
    - 会社提案の賛成率が holding_threshold 以上低下
    - 新規株主提案あり
    - 会社提案が否決された

    Args:
        edinet_client: EDINETクライアント。
        report: トレンド分析レポート。
        year_data: 年度→MeetingResultリストの辞書。
        years: 比較対象年度リスト。
        holding_threshold: 賛成率低下トリガーの閾値（pp）。
        skip: Trueなら検索をスキップ。

    Returns:
        edinet_code → HoldingContextリストのマッピング。
    """
    if skip:
        return {}

    # sec_code → edinet_code の逆引きマップ
    code_map: dict[str, tuple[str, str]] = {}
    for meetings in year_data.values():
        for m in meetings:
            code4 = m.sec_code[:4]
            if code4 not in code_map:
                code_map[code4] = (m.edinet_code, m.company_name)

    # アラート企業の収集
    alert_codes: set[str] = set()

    # 条件A: トレンドレポートから（賛成率低下 + 新規株主提案）
    alert_codes |= report.get_alert_sec_codes(holding_threshold)

    # 条件B: 最新年で会社提案が否決された企業
    latest_year = max(years)
    for m in year_data.get(latest_year, []):
        if m.has_rejected_company_proposals:
            alert_codes.add(m.sec_code[:4])

    if not alert_codes:
        return {}

    logger.info(
        "大量保有検索対象: %d社 (%s)",
        len(alert_codes),
        ", ".join(sorted(alert_codes)),
    )

    # 大量保有報告書の検索（最古年の開始〜今日まで）
    holding_searcher = HoldingSearcher(edinet_client)
    h_start = date(min(years), 1, 1)
    h_end = date.today()

    holdings_map: dict[str, list] = {}
    for code4 in sorted(alert_codes):
        mapping = code_map.get(code4)
        if not mapping:
            continue
        edinet_code, company_name = mapping
        logger.info(
            "検索中: %s %s (%s)", code4, company_name, edinet_code
        )
        holders = holding_searcher.search_holders(
            edinet_code=edinet_code,
            search_start=h_start,
            search_end=h_end,
        )
        if holders:
            holdings_map[edinet_code] = holders

    return holdings_map


def run_trend(args: argparse.Namespace) -> None:
    """トレンド比較モードの処理。"""
    load_dotenv()

    edinet_key = os.getenv("EDINET_API_KEY", "")
    if not edinet_key:
        logger.error("EDINET_API_KEY が設定されていません")
        sys.exit(1)

    # 年度リストの決定
    if args.years:
        years = sorted(int(y) for y in args.years.split(","))
    else:
        current_year = args.year
        years = [current_year - 1, current_year]

    logger.info("トレンド比較: %s", " vs ".join(str(y) for y in years))

    resolution_parser = ResolutionParser()
    cache_dir = Path("output/cache")

    # 各年のデータを取得（キャッシュ利用）+ 大量保有検索
    year_data: dict[int, list[MeetingResult]] = {}
    with EdinetClient(api_key=edinet_key) as edinet_client:
        for year in years:
            cached = None
            if not args.no_cache:
                cached = load_year_data(year, cache_dir)

            if cached is not None:
                year_data[year] = cached
            else:
                start = (
                    date.fromisoformat(args.start_date)
                    if args.start_date
                    else date(year, args.scan_start_month, 1)
                )
                if args.end_date:
                    end = date.fromisoformat(args.end_date)
                else:
                    em = args.scan_end_month
                    if em == 12:
                        end = date(year, 12, 31)
                    else:
                        end = date(
                            year, em + 1, 1
                        ) - timedelta(days=1)
                meetings = _build_meeting_results(
                    edinet_client,
                    resolution_parser,
                    start,
                    end,
                    args.code,
                )
                year_data[year] = meetings
                save_year_data(year, meetings, cache_dir)

        # 分析
        analyzer = TrendAnalyzer(threshold=args.threshold)
        report = analyzer.analyze(year_data)

        # アラート企業の大量保有報告書を検索
        holdings_map = _search_alert_holdings(
            edinet_client,
            report,
            year_data,
            years,
            holding_threshold=args.holding_threshold,
            skip=args.skip_holdings,
        )

    # 出力
    print_trend_report(report, holdings_map)

    if not args.dry_run and args.format == "csv":
        output_path = Path(
            args.output
            or f"output/trend_{'_'.join(str(y) for y in years)}.csv"
        )
        export_trend_csv(report, output_path, years)

    logger.info(
        "トレンド分析完了: %d件のトレンド, "
        "%d件の低下アラート, %d社の新規株主提案, "
        "%d社の大量保有検索",
        len(report.all_trends),
        len(report.declining_proposals),
        len(report.new_shareholder_proposals),
        len(holdings_map),
    )


def main() -> None:
    """エントリーポイント。"""
    args = parse_args()
    _setup_logging(args.verbose)
    if args.trend:
        run_trend(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
