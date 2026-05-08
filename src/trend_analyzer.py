from __future__ import annotations

import logging
from collections import defaultdict

from src.models import (
    ApprovalTrend,
    MeetingResult,
    NewShareholderProposal,
    ProposalType,
    TrendReport,
)
from src.proposal_classifier import classify_proposal

logger = logging.getLogger(__name__)


class TrendAnalyzer:
    """年度間のトレンドを分析する。"""

    def __init__(self, threshold: float = -5.0) -> None:
        """初期化。

        Args:
            threshold: 賛成率低下アラートの閾値（pp）。
                デフォルトは-5.0（5ポイント以上の低下でフラグ）。
        """
        self._threshold = threshold

    def analyze(
        self, year_data: dict[int, list[MeetingResult]]
    ) -> TrendReport:
        """複数年のデータを比較分析する。

        Args:
            year_data: {年度: MeetingResultリスト} の辞書。

        Returns:
            トレンド分析レポート。
        """
        years = sorted(year_data.keys())
        if len(years) < 2:
            return TrendReport()

        # 企業ごと・年度ごとにグループ化
        # key: sec_code[:4] → {year: MeetingResult}
        company_years: dict[
            str, dict[int, MeetingResult]
        ] = defaultdict(dict)
        for year, meetings in year_data.items():
            for m in meetings:
                code4 = m.sec_code[:4]
                company_years[code4][year] = m

        all_trends: list[ApprovalTrend] = []
        declining: list[ApprovalTrend] = []
        new_shareholder: list[NewShareholderProposal] = []

        for code4, year_map in sorted(company_years.items()):
            # 複数年にデータがある企業のみ比較
            present_years = sorted(
                y for y in years if y in year_map
            )

            if len(present_years) >= 2:
                # 賛成率トレンドの分析
                trends = self._compare_approval_rates(
                    code4, year_map, present_years
                )
                all_trends.extend(trends)
                declining.extend(
                    t for t in trends if t.delta < self._threshold
                )

            # 株主提案の新規出現チェック
            ns = self._check_new_shareholder_proposals(
                code4, year_map, present_years
            )
            if ns:
                new_shareholder.append(ns)

        # 低下幅が大きい順にソート
        declining.sort(key=lambda t: t.delta)

        return TrendReport(
            declining_proposals=declining,
            new_shareholder_proposals=new_shareholder,
            all_trends=all_trends,
        )

    def _compare_approval_rates(
        self,
        code4: str,
        year_map: dict[int, MeetingResult],
        years: list[int],
    ) -> list[ApprovalTrend]:
        """企業の賛成率を年度間で比較する。"""
        # カテゴリごとに賛成率を集計
        # key: (category, proposal_type) → {year: rate}
        category_rates: dict[
            tuple[str, str], dict[int, float]
        ] = defaultdict(dict)
        # 候補者レベル: (category, candidate_name) → {year: rate}
        candidate_rates: dict[
            tuple[str, str], dict[int, float]
        ] = defaultdict(dict)

        company_name = ""
        for year in years:
            meeting = year_map[year]
            company_name = meeting.company_name or company_name

            for proposal in meeting.proposals:
                cat = classify_proposal(
                    proposal.title, proposal.proposal_type
                )
                key = (cat.value, proposal.proposal_type.value)

                if proposal.candidates:
                    # 候補者議案: 全候補者の平均賛成率
                    rates = [
                        c.approval_rate
                        for c in proposal.candidates
                        if c.approval_rate is not None
                    ]
                    if rates:
                        avg_rate = sum(rates) / len(rates)
                        category_rates[key][year] = avg_rate

                    # 個別候補者の追跡
                    for c in proposal.candidates:
                        if c.approval_rate is not None:
                            cand_key = (cat.value, c.name)
                            candidate_rates[cand_key][year] = (
                                c.approval_rate
                            )
                else:
                    # 非候補者議案
                    if proposal.approval_rate is not None:
                        category_rates[key][year] = (
                            proposal.approval_rate
                        )

        trends: list[ApprovalTrend] = []

        # カテゴリレベルのトレンド
        for (cat, ptype), yr_rates in category_rates.items():
            if len(yr_rates) < 2:
                continue
            sorted_yrs = sorted(yr_rates.keys())
            latest = sorted_yrs[-1]
            prev = sorted_yrs[-2]
            delta = yr_rates[latest] - yr_rates[prev]

            trends.append(
                ApprovalTrend(
                    sec_code=code4,
                    company_name=company_name,
                    category=cat,
                    proposal_type=ptype,
                    year_rates=yr_rates,
                    delta=delta,
                )
            )

        # 候補者レベルのトレンド（同名候補者が複数年にいる場合）
        for (cat, cand_name), yr_rates in candidate_rates.items():
            if len(yr_rates) < 2:
                continue
            sorted_yrs = sorted(yr_rates.keys())
            latest = sorted_yrs[-1]
            prev = sorted_yrs[-2]
            delta = yr_rates[latest] - yr_rates[prev]

            trends.append(
                ApprovalTrend(
                    sec_code=code4,
                    company_name=company_name,
                    category=cat,
                    proposal_type=ProposalType.COMPANY.value,
                    year_rates=yr_rates,
                    delta=delta,
                    candidate_name=cand_name,
                )
            )

        return trends

    def _check_new_shareholder_proposals(
        self,
        code4: str,
        year_map: dict[int, MeetingResult],
        years: list[int],
    ) -> NewShareholderProposal | None:
        """株主提案の新規出現を検出する。"""
        if len(years) < 2:
            return None

        latest_year = years[-1]
        latest = year_map.get(latest_year)
        if not latest or not latest.has_shareholder_proposals:
            return None

        # 前年に株主提案がなかったかチェック
        prev_years = years[:-1]
        had_shareholder = any(
            year_map[y].has_shareholder_proposals
            for y in prev_years
            if y in year_map
        )

        if had_shareholder:
            return None

        # 新規株主提案の情報を収集
        titles = []
        rates: list[float | None] = []
        for p in latest.proposals:
            if p.proposal_type == ProposalType.SHAREHOLDER:
                titles.append(p.title)
                rates.append(p.approval_rate)

        return NewShareholderProposal(
            sec_code=code4,
            company_name=latest.company_name,
            first_year=latest_year,
            proposal_titles=titles,
            approval_rates=rates,
        )
