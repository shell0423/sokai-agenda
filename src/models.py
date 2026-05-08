from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ProposalType(Enum):
    """議案の提案種別。"""

    COMPANY = "会社提案"
    SHAREHOLDER = "株主提案"


class VoteResult(Enum):
    """議決結果。"""

    APPROVED = "可決"
    REJECTED = "否決"


@dataclass
class Candidate:
    """選任議案の候補者。"""

    name: str
    votes_for: int | None = None
    votes_against: int | None = None
    votes_abstain: int | None = None
    approval_rate: float | None = None


@dataclass
class Proposal:
    """株主総会の個別議案。"""

    number: int
    title: str
    proposal_type: ProposalType
    result: VoteResult | None = None
    approval_rate: float | None = None
    votes_for: int | None = None
    votes_against: int | None = None
    votes_abstain: int | None = None
    candidates: list[Candidate] = field(default_factory=list)


@dataclass
class MeetingResult:
    """1社分の株主総会議決結果。"""

    doc_id: str
    edinet_code: str
    sec_code: str
    company_name: str
    submit_date: str
    proposals: list[Proposal] = field(default_factory=list)

    @property
    def has_shareholder_proposals(self) -> bool:
        """株主提案が含まれるかどうか。"""
        return any(
            p.proposal_type == ProposalType.SHAREHOLDER
            for p in self.proposals
        )


@dataclass
class HoldingContext:
    """大量保有報告書から得た株主情報。"""

    holder_name: str
    ratio_held: float | None
    purpose: str | None


@dataclass
class ApprovalTrend:
    """賛成率のトレンド（年度比較）。"""

    sec_code: str
    company_name: str
    category: str
    proposal_type: str
    year_rates: dict[int, float] = field(default_factory=dict)
    delta: float = 0.0
    candidate_name: str = ""


@dataclass
class NewShareholderProposal:
    """新規株主提案の検出結果。"""

    sec_code: str
    company_name: str
    first_year: int
    proposal_titles: list[str] = field(default_factory=list)
    approval_rates: list[float | None] = field(default_factory=list)


@dataclass
class TrendReport:
    """トレンド分析レポート。"""

    declining_proposals: list[ApprovalTrend] = field(
        default_factory=list
    )
    new_shareholder_proposals: list[NewShareholderProposal] = field(
        default_factory=list
    )
    all_trends: list[ApprovalTrend] = field(default_factory=list)


@dataclass
class AnalysisRecord:
    """CSV/Excel出力用の1レコード。"""

    sec_code: str
    company_name: str
    proposal_number: int
    proposal_title: str
    proposal_type: str
    candidate_name: str
    result: str
    approval_rate: float | None
    votes_for: int | None
    votes_against: int | None
    votes_abstain: int | None
    major_holders: str
    submit_date: str
    doc_id: str
