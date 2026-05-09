"""旧ロジック vs 新ロジックの大量保有検索トリガー比較スクリプト。

キャッシュ済みの2024/2025年データを使い、APIコールなしで
どの企業が新たに検索対象に加わるかを表示する。

使い方:
    python compare_triggers.py              # コンソール表示のみ（前年 vs 今年）
    python compare_triggers.py --years 2024,2025,2026  # 3年比較
    python compare_triggers.py --csv        # CSV出力（output/trigger_comparison.csv）
    python compare_triggers.py --csv -o out.csv  # 出力先を指定

注意: キャッシュデータに approval_rate == 0.0 のパーサーバグが
存在するため、votes_for > 0 の 0.0% は除外して判定する。
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path

from src.models import MeetingResult, ProposalType, VoteResult
from src.trend_analyzer import TrendAnalyzer
from src.trend_cache import load_year_data


# ------------------------------------------------------------------
# データ構造
# ------------------------------------------------------------------

@dataclass
class CompanyTrigger:
    """1社分のトリガー判定結果。"""

    sec_code: str
    company_name: str
    cond_a: bool = False
    cond_b: bool = False
    cond_c: bool = False
    status: str = ""  # 新規追加 / 既存継続 / 旧のみ
    cond_a_details: list[str] = field(default_factory=list)
    cond_b_details: list[str] = field(default_factory=list)
    cond_c_details: list[str] = field(default_factory=list)


# ------------------------------------------------------------------
# 否決判定ヘルパー（0.0%パーサーバグ除外）
# ------------------------------------------------------------------

def _is_truly_rejected(meeting: MeetingResult) -> bool:
    """会社提案が本当に否決されたか（0.0%パーサーバグを除外）。"""
    for p in meeting.proposals:
        if p.proposal_type != ProposalType.COMPANY:
            continue
        if p.result == VoteResult.REJECTED:
            return True
        for c in p.candidates:
            if c.approval_rate is None:
                continue
            if c.approval_rate == 0.0:
                if c.votes_for is None or c.votes_for > 0:
                    continue
            if c.approval_rate < 50.0:
                return True
    return False


def _get_rejection_details(meeting: MeetingResult) -> list[str]:
    """否決の詳細情報を返す（0.0%バグ除外済み）。"""
    details: list[str] = []
    for p in meeting.proposals:
        if p.proposal_type != ProposalType.COMPANY:
            continue
        if p.result == VoteResult.REJECTED:
            title = p.title or "(タイトルなし)"
            rate = (
                f"{p.approval_rate:.1f}%"
                if p.approval_rate is not None
                else "N/A"
            )
            details.append(f"議案否決: {title} ({rate})")
        for c in p.candidates:
            if c.approval_rate is None:
                continue
            if c.approval_rate == 0.0 and (
                c.votes_for is None or c.votes_for > 0
            ):
                continue
            if c.approval_rate < 50.0:
                details.append(
                    f"候補者否決: {c.name} → {c.approval_rate:.1f}%"
                )
    return details


# ------------------------------------------------------------------
# 分析本体
# ------------------------------------------------------------------

def analyze_triggers(
    years: list[int],
    holding_threshold: float = -10.0,
    cache_dir: Path = Path("output/cache"),
) -> tuple[list[CompanyTrigger], dict[str, int]]:
    """トリガー比較分析を実行する。

    Args:
        years: 比較年度リスト。
        holding_threshold: 条件Aの閾値（pp）。
        cache_dir: キャッシュディレクトリ。

    Returns:
        (CompanyTriggerリスト, サマリー統計dict) のタプル。
    """
    # キャッシュ読み込み
    year_data: dict[int, list[MeetingResult]] = {}
    for y in years:
        data = load_year_data(y, cache_dir)
        if data is None:
            print(f"エラー: {y}年のキャッシュがありません")
            print(
                f"  先に python -m src.main --year {y} "
                "を実行してください"
            )
            sys.exit(1)
        year_data[y] = data

    # トレンド分析
    analyzer = TrendAnalyzer(threshold=-5.0)
    report = analyzer.analyze(year_data)

    latest_year = max(years)

    # sec_code → 企業名マップ
    name_map: dict[str, str] = {}
    for meetings in year_data.values():
        for m in meetings:
            name_map[m.sec_code[:4]] = m.company_name

    # 旧ロジック: 株主提案がある企業のみ
    old_codes: set[str] = set()
    for m in year_data[latest_year]:
        if m.has_shareholder_proposals:
            old_codes.add(m.sec_code[:4])

    # 条件A: 会社提案の賛成率が holding_threshold 以上低下
    cond_a_codes: set[str] = set()
    cond_a_details: dict[str, list[str]] = {}
    for t in report.declining_proposals:
        if (
            t.proposal_type == "会社提案"
            and t.delta <= holding_threshold
        ):
            cond_a_codes.add(t.sec_code)
            label = t.category
            if t.candidate_name:
                label += f"/{t.candidate_name}"
            label += f" {t.delta:+.1f}pp"
            cond_a_details.setdefault(t.sec_code, []).append(label)

    # 条件B: 新規株主提案（前年にはなかった）
    cond_b_codes: set[str] = set()
    cond_b_details: dict[str, list[str]] = {}
    for ns in report.new_shareholder_proposals:
        cond_b_codes.add(ns.sec_code)
        titles = [
            f"{t} ({r:.1f}%)" if r is not None else t
            for t, r in zip(ns.proposal_titles, ns.approval_rates)
        ]
        cond_b_details[ns.sec_code] = titles

    # 条件C: 会社提案が否決
    cond_c_codes: set[str] = set()
    cond_c_details: dict[str, list[str]] = {}
    for m in year_data[latest_year]:
        code4 = m.sec_code[:4]
        if _is_truly_rejected(m):
            cond_c_codes.add(code4)
            cond_c_details[code4] = _get_rejection_details(m)

    new_codes = cond_a_codes | cond_b_codes | cond_c_codes
    all_codes = old_codes | new_codes

    # CompanyTriggerリストを作成
    triggers: list[CompanyTrigger] = []
    for code4 in sorted(all_codes):
        in_old = code4 in old_codes
        in_new = code4 in new_codes

        if in_new and not in_old:
            status = "新規追加"
        elif in_new and in_old:
            status = "既存継続"
        else:
            status = "旧のみ"

        triggers.append(
            CompanyTrigger(
                sec_code=code4,
                company_name=name_map.get(code4, "不明"),
                cond_a=code4 in cond_a_codes,
                cond_b=code4 in cond_b_codes,
                cond_c=code4 in cond_c_codes,
                status=status,
                cond_a_details=cond_a_details.get(code4, []),
                cond_b_details=cond_b_details.get(code4, []),
                cond_c_details=cond_c_details.get(code4, []),
            )
        )

    year_counts = {
        y: len(year_data[y]) for y in years
    }

    stats = {
        "total_old": len(old_codes),
        "total_new": len(new_codes),
        "cond_a": len(cond_a_codes),
        "cond_b": len(cond_b_codes),
        "cond_c": len(cond_c_codes),
        "added": len(new_codes - old_codes),
        "common": len(old_codes & new_codes),
        "removed": len(old_codes - new_codes),
        "year_counts": year_counts,
    }

    return triggers, stats


# ------------------------------------------------------------------
# CSV出力
# ------------------------------------------------------------------

def export_csv(
    triggers: list[CompanyTrigger],
    path: Path,
) -> None:
    """トリガー比較結果をCSVに出力する。"""
    path.parent.mkdir(parents=True, exist_ok=True)

    headers = [
        "証券コード",
        "企業名",
        "ステータス",
        "条件A:賛成率低下",
        "条件B:新規株主提案",
        "条件C:会社提案否決",
        "条件A詳細",
        "条件B詳細",
        "条件C詳細",
    ]

    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for t in triggers:
            writer.writerow([
                t.sec_code,
                t.company_name,
                t.status,
                "○" if t.cond_a else "",
                "○" if t.cond_b else "",
                "○" if t.cond_c else "",
                " / ".join(t.cond_a_details),
                " / ".join(t.cond_b_details),
                " / ".join(t.cond_c_details),
            ])

    print(f"\nCSV出力: {path} ({len(triggers)}行)")


# ------------------------------------------------------------------
# コンソール出力
# ------------------------------------------------------------------

def print_report(
    triggers: list[CompanyTrigger],
    stats: dict,
    years: list[int],
    holding_threshold: float,
) -> None:
    """コンソールにレポートを表示する。"""
    year_counts: dict[int, int] = stats.get("year_counts", {})
    counts_str = ", ".join(
        f"{y}年={year_counts.get(y, 0)}社" for y in years
    )
    print(f"読み込み: {counts_str}")

    print(f"\n{'='*70}")
    print("  大量保有検索トリガー比較")
    years_str = " → ".join(str(y) for y in years)
    print(f"  比較年度: {years_str}")
    print(f"  賛成率低下閾値: {holding_threshold}pp")
    print(f"{'='*70}")

    print(
        f"\n  旧ロジック（株主提案ありのみ）:  "
        f"{stats['total_old']}社"
    )
    print(
        f"  新ロジック（3条件）:              "
        f"{stats['total_new']}社"
    )
    print(
        f"    条件A 賛成率{holding_threshold}pp以上低下: "
        f"{stats['cond_a']}社"
    )
    print(f"    条件B 新規株主提案:              {stats['cond_b']}社")
    print(f"    条件C 会社提案否決:              {stats['cond_c']}社")

    print(f"\n  共通（旧→新で継続）: {stats['common']}社")
    print(f"  新たに追加:          {stats['added']}社")
    print(f"  旧のみ（新に含まれない）: {stats['removed']}社")

    added = [t for t in triggers if t.status == "新規追加"]
    if added:
        print(f"\n{'─'*70}")
        print(f"  ✅ 新たに検索対象になった企業（{len(added)}社）")
        print(f"{'─'*70}")
        for t in added:
            conditions: list[str] = []
            if t.cond_a:
                conditions.append("A:賛成率低下")
            if t.cond_b:
                conditions.append("B:新規株主提案")
            if t.cond_c:
                conditions.append("C:会社提案否決")
            print(f"\n  {t.sec_code} {t.company_name}")
            print(f"    条件: {' + '.join(conditions)}")
            for d in t.cond_a_details:
                print(f"      A: {d}")
            for d in t.cond_c_details[:5]:
                print(f"      C: {d}")
            if len(t.cond_c_details) > 5:
                remaining = len(t.cond_c_details) - 5
                print(f"      C: ...他{remaining}件")

    upgraded = [
        t for t in triggers
        if t.status == "既存継続" and (t.cond_a or t.cond_c)
    ]
    if upgraded:
        print(f"\n{'─'*70}")
        print(f"  📋 既存対象 + 新条件でも該当（{len(upgraded)}社）")
        print(f"{'─'*70}")
        for t in upgraded:
            conds = []
            if t.cond_a:
                conds.append("A")
            if t.cond_b:
                conds.append("B")
            if t.cond_c:
                conds.append("C")
            print(
                f"  {t.sec_code} {t.company_name}  "
                f"[{'+'.join(conds)}]"
            )

    removed = [t for t in triggers if t.status == "旧のみ"]
    if removed:
        print(f"\n{'─'*70}")
        print(f"  ⚠️  旧ロジックのみの企業（{len(removed)}社）")
        print(
            "  ※旧: 株主提案あり → 新: 「新規」株主提案のみが"
            "条件Bの対象"
        )
        print(f"{'─'*70}")
        for t in removed:
            print(f"  {t.sec_code} {t.company_name}")

    print(f"\n{'='*70}")


# ------------------------------------------------------------------
# エントリーポイント
# ------------------------------------------------------------------

def _resolve_years(years_str: str | None) -> list[int]:
    """年度文字列をパースする。Noneなら[前年, 今年]を返す。"""
    if years_str:
        return sorted(int(y.strip()) for y in years_str.split(","))
    from datetime import date
    current = date.today().year
    return [current - 1, current]


def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする。"""
    parser = argparse.ArgumentParser(
        description="大量保有検索トリガーの旧→新ロジック比較"
    )
    parser.add_argument(
        "--years",
        type=str,
        default=None,
        help=(
            "比較年度（カンマ区切り、デフォルト: 前年,今年）"
            " 例: --years 2024,2025,2026"
        ),
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="CSV出力を有効化",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="output/trigger_comparison.csv",
        help="CSV出力先パス（デフォルト: output/trigger_comparison.csv）",
    )
    parser.add_argument(
        "--holding-threshold",
        type=float,
        default=-10.0,
        help="条件Aの賛成率低下閾値（pp、デフォルト: -10.0）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    years = _resolve_years(args.years)

    triggers, stats = analyze_triggers(
        years=years,
        holding_threshold=args.holding_threshold,
    )

    print_report(triggers, stats, years, args.holding_threshold)

    if args.csv:
        export_csv(triggers, Path(args.output))


if __name__ == "__main__":
    main()
