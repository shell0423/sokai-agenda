"""旧ロジック vs 新ロジックの大量保有検索トリガー比較スクリプト。

キャッシュ済みの2024/2025年データを使い、APIコールなしで
どの企業が新たに検索対象に加わるかを表示する。

注意: キャッシュデータに approval_rate == 0.0 のパーサーバグが
存在するため、votes_for > 0 の 0.0% は除外して判定する。
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.models import MeetingResult, ProposalType, VoteResult
from src.trend_analyzer import TrendAnalyzer
from src.trend_cache import load_year_data


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
            # 0.0%でvotes_for > 0 はパーサーバグ → 無視
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
            rate = f"{p.approval_rate:.1f}%" if p.approval_rate is not None else "N/A"
            details.append(f"議案否決: {title} ({rate})")
        for c in p.candidates:
            if c.approval_rate is None:
                continue
            if c.approval_rate == 0.0 and (c.votes_for is None or c.votes_for > 0):
                continue
            if c.approval_rate < 50.0:
                details.append(f"候補者否決: {c.name} → {c.approval_rate:.1f}%")
    return details


def main() -> None:
    cache_dir = Path("output/cache")
    years = [2024, 2025]
    holding_threshold = -10.0

    # キャッシュ読み込み
    year_data: dict[int, list[MeetingResult]] = {}
    for y in years:
        data = load_year_data(y, cache_dir)
        if data is None:
            print(f"エラー: {y}年のキャッシュがありません")
            print(f"  先に python -m src.main --year {y} を実行してください")
            sys.exit(1)
        year_data[y] = data

    print(
        f"読み込み: {years[0]}年={len(year_data[years[0]])}社, "
        f"{years[1]}年={len(year_data[years[1]])}社"
    )

    # トレンド分析
    analyzer = TrendAnalyzer(threshold=-5.0)
    report = analyzer.analyze(year_data)

    latest_year = max(years)

    # sec_code → 企業名マップ
    name_map: dict[str, str] = {}
    for meetings in year_data.values():
        for m in meetings:
            name_map[m.sec_code[:4]] = m.company_name

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  旧ロジック: 株主提案がある企業のみ（run() の元実装）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    old_codes: set[str] = set()
    for m in year_data[latest_year]:
        if m.has_shareholder_proposals:
            old_codes.add(m.sec_code[:4])

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  新ロジック: 3条件（_search_alert_holdings の実装）
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    # 条件A: 会社提案の賛成率が holding_threshold 以上低下
    cond_a_codes: set[str] = set()
    cond_a_details: dict[str, list[str]] = {}
    for t in report.declining_proposals:
        if t.proposal_type == "会社提案" and t.delta <= holding_threshold:
            cond_a_codes.add(t.sec_code)
            label = t.category
            if t.candidate_name:
                label += f"/{t.candidate_name}"
            label += f" {t.delta:+.1f}pp"
            cond_a_details.setdefault(t.sec_code, []).append(label)

    # 条件B: 新規株主提案（前年にはなかった）
    cond_b_codes: set[str] = set()
    for ns in report.new_shareholder_proposals:
        cond_b_codes.add(ns.sec_code)

    # 条件C: 会社提案が否決（0.0%パーサーバグを除外）
    cond_c_codes: set[str] = set()
    cond_c_details: dict[str, list[str]] = {}
    for m in year_data[latest_year]:
        code4 = m.sec_code[:4]
        if _is_truly_rejected(m):
            cond_c_codes.add(code4)
            cond_c_details[code4] = _get_rejection_details(m)

    new_codes = cond_a_codes | cond_b_codes | cond_c_codes

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  結果表示
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    print(f"\n{'='*70}")
    print("  大量保有検索トリガー比較")
    print(f"  比較年度: {years[0]} → {years[1]}")
    print(f"  賛成率低下閾値: {holding_threshold}pp")
    print(f"{'='*70}")

    print(f"\n  旧ロジック（株主提案ありのみ）:  {len(old_codes)}社")
    print(f"  新ロジック（3条件）:              {len(new_codes)}社")
    print(f"    条件A 賛成率{holding_threshold}pp以上低下: {len(cond_a_codes)}社")
    print(f"    条件B 新規株主提案:              {len(cond_b_codes)}社")
    print(f"    条件C 会社提案否決:              {len(cond_c_codes)}社")

    added = new_codes - old_codes
    removed = old_codes - new_codes
    common = old_codes & new_codes

    print(f"\n  共通（旧→新で継続）: {len(common)}社")
    print(f"  新たに追加:          {len(added)}社")
    print(f"  旧のみ（新に含まれない）: {len(removed)}社")

    # ── 新たに追加された企業 ──
    if added:
        print(f"\n{'─'*70}")
        print(f"  ✅ 新たに検索対象になった企業（{len(added)}社）")
        print(f"{'─'*70}")
        for code4 in sorted(added):
            name = name_map.get(code4, "不明")
            conditions: list[str] = []
            if code4 in cond_a_codes:
                conditions.append("A:賛成率低下")
            if code4 in cond_b_codes:
                conditions.append("B:新規株主提案")
            if code4 in cond_c_codes:
                conditions.append("C:会社提案否決")
            cond_str = " + ".join(conditions)
            print(f"\n  {code4} {name}")
            print(f"    条件: {cond_str}")
            if code4 in cond_a_details:
                for detail in cond_a_details[code4]:
                    print(f"      A: {detail}")
            if code4 in cond_c_details:
                for detail in cond_c_details[code4][:5]:
                    print(f"      C: {detail}")
                if len(cond_c_details.get(code4, [])) > 5:
                    print(f"      C: ...他{len(cond_c_details[code4]) - 5}件")

    # ── 既存対象に追加の理由が付いた企業 ──
    upgraded: list[str] = []
    for code4 in sorted(common):
        extra: list[str] = []
        if code4 in cond_a_codes:
            extra.append("A:賛成率低下")
        if code4 in cond_c_codes:
            extra.append("C:会社提案否決")
        if extra:
            upgraded.append(code4)

    if upgraded:
        print(f"\n{'─'*70}")
        print(f"  📋 既存対象 + 新条件でも該当（{len(upgraded)}社）")
        print(f"{'─'*70}")
        for code4 in upgraded:
            name = name_map.get(code4, "不明")
            conditions = []
            if code4 in cond_a_codes:
                conditions.append("A")
            if code4 in cond_b_codes:
                conditions.append("B")
            if code4 in cond_c_codes:
                conditions.append("C")
            print(f"  {code4} {name}  [{'+'.join(conditions)}]")

    # ── 旧ロジックのみの企業 ──
    if removed:
        print(f"\n{'─'*70}")
        print(f"  ⚠️  旧ロジックのみの企業（{len(removed)}社）")
        print(f"  ※旧: 株主提案あり → 新: 「新規」株主提案のみが条件Bの対象")
        print(f"    前年にも株主提案があった企業は条件Bから外れるが、")
        print(f"    条件A/Cで拾われる可能性あり")
        print(f"{'─'*70}")
        for code4 in sorted(removed):
            name = name_map.get(code4, "不明")
            print(f"  {code4} {name}")

    # ── サマリー ──
    print(f"\n{'='*70}")
    print(f"  サマリー")
    print(f"{'='*70}")
    only_a = cond_a_codes - cond_b_codes - cond_c_codes
    only_b = cond_b_codes - cond_a_codes - cond_c_codes
    only_c = cond_c_codes - cond_a_codes - cond_b_codes
    ab = (cond_a_codes & cond_b_codes) - cond_c_codes
    ac = (cond_a_codes & cond_c_codes) - cond_b_codes
    bc = (cond_b_codes & cond_c_codes) - cond_a_codes
    abc = cond_a_codes & cond_b_codes & cond_c_codes
    print(f"  Aのみ:     {len(only_a)}社")
    print(f"  Bのみ:     {len(only_b)}社")
    print(f"  Cのみ:     {len(only_c)}社")
    print(f"  A+B:       {len(ab)}社")
    print(f"  A+C:       {len(ac)}社")
    print(f"  B+C:       {len(bc)}社")
    print(f"  A+B+C:     {len(abc)}社")
    print(f"  ─────────────────")
    print(f"  合計:      {len(new_codes)}社")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
