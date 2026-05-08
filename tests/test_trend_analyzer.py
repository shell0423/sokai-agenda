from __future__ import annotations

from src.models import (
    Candidate,
    MeetingResult,
    Proposal,
    ProposalType,
    VoteResult,
)
from src.trend_analyzer import TrendAnalyzer


def _taiyo_2024() -> MeetingResult:
    """太陽HD 2024年（株主提案なし）。"""
    return MeetingResult(
        doc_id="S100TMO6",
        edinet_code="E02810",
        sec_code="46260",
        company_name="太陽ホールディングス株式会社",
        submit_date="2024-06-17",
        proposals=[
            Proposal(
                number=1,
                title="剰余金の処分の件",
                proposal_type=ProposalType.COMPANY,
                result=VoteResult.APPROVED,
                approval_rate=99.31,
            ),
            Proposal(
                number=2,
                title=(
                    "取締役（監査等委員である取締役を除く。）"
                    "5名選任の件"
                ),
                proposal_type=ProposalType.COMPANY,
                candidates=[
                    Candidate(
                        name="佐藤 英志",
                        approval_rate=97.95,
                        votes_for=95000,
                        votes_against=2000,
                    ),
                    Candidate(
                        name="齋藤 斉",
                        approval_rate=98.50,
                        votes_for=96000,
                        votes_against=1500,
                    ),
                ],
            ),
            Proposal(
                number=3,
                title="監査等委員である取締役2名選任の件",
                proposal_type=ProposalType.COMPANY,
                candidates=[
                    Candidate(
                        name="鈴木 一郎",
                        approval_rate=96.00,
                    ),
                ],
            ),
        ],
    )


def _taiyo_2025() -> MeetingResult:
    """太陽HD 2025年（株主提案あり、佐藤英志否決）。"""
    return MeetingResult(
        doc_id="S100XXXX",
        edinet_code="E02810",
        sec_code="46260",
        company_name="太陽ホールディングス株式会社",
        submit_date="2025-06-23",
        proposals=[
            Proposal(
                number=1,
                title="資本準備金及び利益準備金の額の減少の件",
                proposal_type=ProposalType.COMPANY,
                result=VoteResult.APPROVED,
                approval_rate=64.50,
            ),
            Proposal(
                number=2,
                title=(
                    "取締役（監査等委員である取締役を除く。）"
                    "4名選任の件"
                ),
                proposal_type=ProposalType.COMPANY,
                candidates=[
                    Candidate(
                        name="佐藤 英志",
                        approval_rate=46.09,
                        votes_for=45000,
                        votes_against=52000,
                    ),
                    Candidate(
                        name="齋藤 斉",
                        approval_rate=83.45,
                        votes_for=81000,
                        votes_against=16000,
                    ),
                    Candidate(
                        name="土屋 恵子",
                        approval_rate=73.38,
                        votes_for=71000,
                        votes_against=26000,
                    ),
                    Candidate(
                        name="丸山 みさえ",
                        approval_rate=96.30,
                        votes_for=94000,
                        votes_against=3500,
                    ),
                ],
            ),
            Proposal(
                number=3,
                title="監査等委員である取締役1名選任の件",
                proposal_type=ProposalType.COMPANY,
                candidates=[
                    Candidate(
                        name="嶋村 紀明",
                        approval_rate=96.32,
                    ),
                ],
            ),
            Proposal(
                number=4,
                title="取締役佐藤英志氏解任の件",
                proposal_type=ProposalType.SHAREHOLDER,
                result=VoteResult.REJECTED,
                approval_rate=49.90,
            ),
            Proposal(
                number=5,
                title="取締役髙野聖史氏解任の件",
                proposal_type=ProposalType.SHAREHOLDER,
                result=VoteResult.REJECTED,
                approval_rate=24.44,
            ),
        ],
    )


class TestTrendAnalyzer:
    """TrendAnalyzer のテスト。"""

    def test_declining_director_approval(self) -> None:
        """取締役選任の平均賛成率低下を検出する。"""
        analyzer = TrendAnalyzer(threshold=-5.0)
        report = analyzer.analyze(
            {2024: [_taiyo_2024()], 2025: [_taiyo_2025()]}
        )

        # 取締役選任カテゴリの低下を検出
        director_declines = [
            t
            for t in report.declining_proposals
            if t.category == "取締役選任"
            and t.candidate_name == ""
        ]
        assert len(director_declines) == 1
        trend = director_declines[0]
        assert trend.sec_code == "4626"
        assert trend.year_rates[2024] > 90.0
        assert trend.year_rates[2025] < 80.0
        assert trend.delta < 0

    def test_declining_candidate_sato(self) -> None:
        """佐藤英志の個別賛成率低下を検出する。"""
        analyzer = TrendAnalyzer(threshold=-5.0)
        report = analyzer.analyze(
            {2024: [_taiyo_2024()], 2025: [_taiyo_2025()]}
        )

        sato_declines = [
            t
            for t in report.declining_proposals
            if "佐藤" in t.candidate_name
        ]
        assert len(sato_declines) == 1
        trend = sato_declines[0]
        assert trend.year_rates[2024] == 97.95
        assert trend.year_rates[2025] == 46.09
        assert abs(trend.delta - (-51.86)) < 0.01

    def test_new_shareholder_proposals(self) -> None:
        """2025年に株主提案が新規出現したことを検出する。"""
        analyzer = TrendAnalyzer()
        report = analyzer.analyze(
            {2024: [_taiyo_2024()], 2025: [_taiyo_2025()]}
        )

        assert len(report.new_shareholder_proposals) == 1
        ns = report.new_shareholder_proposals[0]
        assert ns.sec_code == "4626"
        assert ns.first_year == 2025
        assert len(ns.proposal_titles) == 2
        assert "解任" in ns.proposal_titles[0]

    def test_no_new_shareholder_if_existed_before(self) -> None:
        """前年にも株主提案がある場合は検出しない。"""
        taiyo_2024_with_shareholder = _taiyo_2024()
        taiyo_2024_with_shareholder.proposals.append(
            Proposal(
                number=4,
                title="株主提案テスト",
                proposal_type=ProposalType.SHAREHOLDER,
                result=VoteResult.REJECTED,
                approval_rate=10.0,
            )
        )

        analyzer = TrendAnalyzer()
        report = analyzer.analyze(
            {
                2024: [taiyo_2024_with_shareholder],
                2025: [_taiyo_2025()],
            }
        )
        assert len(report.new_shareholder_proposals) == 0

    def test_threshold_filtering(self) -> None:
        """閾値以下の低下のみがdeclining_proposalsに含まれる。"""
        # 閾値を-60に設定（非常に厳格）
        analyzer = TrendAnalyzer(threshold=-60.0)
        report = analyzer.analyze(
            {2024: [_taiyo_2024()], 2025: [_taiyo_2025()]}
        )
        # 佐藤英志の-51.86ppは-60.0より大きいので含まれない
        assert len(report.declining_proposals) == 0

    def test_single_year_returns_empty(self) -> None:
        """1年分のデータでは空のレポートを返す。"""
        analyzer = TrendAnalyzer()
        report = analyzer.analyze({2025: [_taiyo_2025()]})
        assert len(report.declining_proposals) == 0
        assert len(report.new_shareholder_proposals) == 0
        assert len(report.all_trends) == 0

    def test_all_trends_includes_non_declining(self) -> None:
        """all_trendsには低下していないものも含まれる。"""
        analyzer = TrendAnalyzer(threshold=-5.0)
        report = analyzer.analyze(
            {2024: [_taiyo_2024()], 2025: [_taiyo_2025()]}
        )
        # all_trendsにはカテゴリ＋候補者レベルの全トレンドが入る
        assert len(report.all_trends) > len(
            report.declining_proposals
        )
