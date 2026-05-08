from __future__ import annotations

import re
from enum import Enum

from src.models import ProposalType


class ProposalCategory(Enum):
    """議案のカテゴリ（年度間比較用）。"""

    DIRECTOR_ELECTION = "取締役選任"
    AUDIT_COMMITTEE = "監査等委員選任"
    AUDITOR_ELECTION = "会計監査人選任"
    DIVIDEND = "剰余金処分"
    ARTICLES_CHANGE = "定款変更"
    COMPENSATION = "役員報酬"
    CAPITAL_CHANGE = "資本変動"
    BUYBACK = "自己株式取得"
    SHAREHOLDER_OTHER = "株主提案（その他）"
    OTHER = "その他"


# 分類ルール: (カテゴリ, 正規表現パターン) のリスト。
# 上から順に評価し、最初にマッチしたカテゴリを返す。
_CLASSIFICATION_RULES: list[tuple[ProposalCategory, re.Pattern[str]]] = [
    (
        ProposalCategory.DIRECTOR_ELECTION,
        re.compile(r"取締役.*(?:除く|除き).*(?:選任|選定)"),
    ),
    (
        ProposalCategory.AUDIT_COMMITTEE,
        re.compile(r"監査等委員.*(?:選任|選定)"),
    ),
    (
        ProposalCategory.DIRECTOR_ELECTION,
        re.compile(r"取締役.*(?:選任|選定)"),
    ),
    (
        ProposalCategory.AUDITOR_ELECTION,
        re.compile(r"会計監査人.*選任"),
    ),
    (
        ProposalCategory.DIVIDEND,
        re.compile(r"剰余金|配当"),
    ),
    (
        ProposalCategory.ARTICLES_CHANGE,
        re.compile(r"定款"),
    ),
    (
        ProposalCategory.COMPENSATION,
        re.compile(r"報酬"),
    ),
    (
        ProposalCategory.CAPITAL_CHANGE,
        re.compile(r"資本.*(?:減少|増加|準備金)"),
    ),
    (
        ProposalCategory.BUYBACK,
        re.compile(r"自己株式.*取得"),
    ),
]


def classify_proposal(
    title: str, proposal_type: ProposalType
) -> ProposalCategory:
    """議案タイトルからカテゴリを判定する。

    Args:
        title: 議案タイトル。
        proposal_type: 提案種別（会社提案/株主提案）。

    Returns:
        議案カテゴリ。
    """
    for category, pattern in _CLASSIFICATION_RULES:
        if pattern.search(title):
            return category

    # 上記に該当しない株主提案
    if proposal_type == ProposalType.SHAREHOLDER:
        return ProposalCategory.SHAREHOLDER_OTHER

    return ProposalCategory.OTHER
