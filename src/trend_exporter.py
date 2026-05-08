from __future__ import annotations

import csv
import logging
from pathlib import Path

from src.models import ApprovalTrend, TrendReport

logger = logging.getLogger(__name__)


def print_trend_report(
    report: TrendReport,
    holdings_map: dict[str, list] | None = None,
) -> None:
    """トレンド分析結果をコンソールに表示する。

    Args:
        report: トレンド分析レポート。
        holdings_map: edinet_code → HoldingContextリスト。
    """
    # 賛成率低下アラート
    if report.declining_proposals:
        print(f"\n{'='*60}")
        print("  ⚠️  賛成率低下アラート")
        print(f"{'='*60}")
        for t in report.declining_proposals:
            cand = f"/{t.candidate_name}" if t.candidate_name else ""
            years = sorted(t.year_rates.keys())
            rates_str = " → ".join(
                f"{y}: {t.year_rates[y]:.2f}%"
                for y in years
            )
            print(
                f"  {t.sec_code} {t.company_name}"
                f" [{t.category}{cand}]"
            )
            print(
                f"    {rates_str}"
                f" (Δ{t.delta:+.2f}pp)"
            )
    else:
        print("\n  賛成率低下アラート: なし")

    # 新規株主提案
    if report.new_shareholder_proposals:
        print(f"\n{'='*60}")
        print("  📋 新規株主提案")
        print(f"{'='*60}")
        for ns in report.new_shareholder_proposals:
            print(
                f"  {ns.sec_code} {ns.company_name}"
                f" — {ns.first_year}年に株主提案が初出現"
            )
            for title, rate in zip(
                ns.proposal_titles, ns.approval_rates
            ):
                rate_str = (
                    f" ({rate:.2f}%)" if rate is not None else ""
                )
                print(f"    ・{title}{rate_str}")
    else:
        print("\n  新規株主提案: なし")

    # 大量保有報告書検索結果
    if holdings_map:
        print(f"\n{'='*60}")
        print("  🔍 大量保有報告書検索結果")
        print(f"{'='*60}")
        for edinet_code, holders in holdings_map.items():
            for h in holders:
                ratio_str = (
                    f"{h.ratio_held:.2f}%"
                    if h.ratio_held
                    else "不明"
                )
                print(
                    f"  {edinet_code}: {h.holder_name}"
                    f" ({ratio_str})"
                )

    # サマリー
    n_holdings = len(holdings_map) if holdings_map else 0
    print(f"\n{'='*60}")
    print(
        f"  トレンド合計: {len(report.all_trends)}件"
        f" / 低下アラート: {len(report.declining_proposals)}件"
        f" / 新規株主提案: {len(report.new_shareholder_proposals)}社"
        f" / 大量保有検索: {n_holdings}社"
    )
    print(f"{'='*60}")


def export_trend_csv(
    report: TrendReport,
    path: Path,
    years: list[int] | None = None,
) -> None:
    """トレンド分析結果をCSVに出力する。

    Args:
        report: トレンド分析レポート。
        path: 出力先パス。
        years: 比較対象年度リスト（ヘッダー用）。
    """
    if years is None:
        # all_trendsからyearsを推測
        all_years: set[int] = set()
        for t in report.all_trends:
            all_years.update(t.year_rates.keys())
        years = sorted(all_years)

    path.parent.mkdir(parents=True, exist_ok=True)

    headers = [
        "証券コード",
        "企業名",
        "議案カテゴリ",
        "提案区分",
        "候補者",
    ]
    for y in years:
        headers.append(f"{y}年賛成率(%)")
    headers.extend(["変動(pp)", "アラート"])

    rows = _build_trend_rows(report, years)

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    logger.info("トレンドCSV出力: %s (%d行)", path, len(rows))


def _build_trend_rows(
    report: TrendReport, years: list[int]
) -> list[list[str]]:
    """トレンドデータをCSV行に変換する。"""
    rows: list[list[str]] = []

    # 低下アラート付きのsec_code+category+candidateのセット
    declining_keys: set[tuple[str, str, str]] = set()
    for t in report.declining_proposals:
        declining_keys.add(
            (t.sec_code, t.category, t.candidate_name)
        )

    for t in report.all_trends:
        alert = ""
        key = (t.sec_code, t.category, t.candidate_name)
        if key in declining_keys:
            alert = "DECLINING"

        row = [
            t.sec_code,
            t.company_name,
            t.category,
            t.proposal_type,
            t.candidate_name,
        ]
        for y in years:
            rate = t.year_rates.get(y)
            row.append(f"{rate:.2f}" if rate is not None else "")
        row.extend([f"{t.delta:+.2f}", alert])
        rows.append(row)

    # 新規株主提案を追記
    for ns in report.new_shareholder_proposals:
        for title, rate in zip(
            ns.proposal_titles, ns.approval_rates
        ):
            row = [
                ns.sec_code,
                ns.company_name,
                title,
                "株主提案",
                "",
            ]
            for y in years:
                if y == ns.first_year and rate is not None:
                    row.append(f"{rate:.2f}")
                else:
                    row.append("")
            row.extend(["", "NEW_SHAREHOLDER"])
            rows.append(row)

    return rows
