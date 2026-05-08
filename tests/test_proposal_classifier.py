from __future__ import annotations

from src.models import ProposalType
from src.proposal_classifier import ProposalCategory, classify_proposal


class TestClassifyProposal:
    """classify_proposal のテスト。"""

    # --- 取締役選任 ---

    def test_director_election(self) -> None:
        title = "取締役（監査等委員である取締役を除く。）4名選任の件"
        result = classify_proposal(title, ProposalType.COMPANY)
        assert result == ProposalCategory.DIRECTOR_ELECTION

    def test_director_election_simple(self) -> None:
        title = "取締役3名選任の件"
        result = classify_proposal(title, ProposalType.COMPANY)
        assert result == ProposalCategory.DIRECTOR_ELECTION

    # --- 監査等委員選任 ---

    def test_audit_committee(self) -> None:
        title = "監査等委員である取締役1名選任の件"
        result = classify_proposal(title, ProposalType.COMPANY)
        assert result == ProposalCategory.AUDIT_COMMITTEE

    def test_audit_committee_priority(self) -> None:
        """監査等委員は取締役選任より優先される。"""
        title = "監査等委員である取締役2名選任の件"
        result = classify_proposal(title, ProposalType.COMPANY)
        assert result == ProposalCategory.AUDIT_COMMITTEE

    # --- 剰余金処分 ---

    def test_dividend(self) -> None:
        title = "剰余金の処分の件"
        result = classify_proposal(title, ProposalType.COMPANY)
        assert result == ProposalCategory.DIVIDEND

    def test_dividend_haitou(self) -> None:
        title = "期末配当金支払いの件"
        result = classify_proposal(title, ProposalType.COMPANY)
        assert result == ProposalCategory.DIVIDEND

    # --- 定款変更 ---

    def test_articles_change(self) -> None:
        title = "定款一部変更の件"
        result = classify_proposal(title, ProposalType.COMPANY)
        assert result == ProposalCategory.ARTICLES_CHANGE

    # --- 報酬 ---

    def test_compensation(self) -> None:
        title = "取締役の報酬額改定の件"
        result = classify_proposal(title, ProposalType.COMPANY)
        assert result == ProposalCategory.COMPENSATION

    # --- 資本変動 ---

    def test_capital_change(self) -> None:
        title = "資本準備金及び利益準備金の額の減少の件"
        result = classify_proposal(title, ProposalType.COMPANY)
        assert result == ProposalCategory.CAPITAL_CHANGE

    # --- 自己株式取得 ---

    def test_buyback(self) -> None:
        title = "自己株式の取得の件"
        result = classify_proposal(title, ProposalType.COMPANY)
        assert result == ProposalCategory.BUYBACK

    # --- 会計監査人 ---

    def test_auditor_election(self) -> None:
        title = "会計監査人選任の件"
        result = classify_proposal(title, ProposalType.COMPANY)
        assert result == ProposalCategory.AUDITOR_ELECTION

    # --- 株主提案 ---

    def test_shareholder_dismissal(self) -> None:
        """取締役解任は取締役選任にマッチしない→株主提案その他。"""
        title = "取締役佐藤英志氏解任の件"
        result = classify_proposal(title, ProposalType.SHAREHOLDER)
        assert result == ProposalCategory.SHAREHOLDER_OTHER

    def test_shareholder_dividend(self) -> None:
        """株主提案でも剰余金処分はDIVIDENDに分類。"""
        title = "剰余金の配当（増配）の件"
        result = classify_proposal(title, ProposalType.SHAREHOLDER)
        assert result == ProposalCategory.DIVIDEND

    # --- その他 ---

    def test_other_company(self) -> None:
        title = "吸収合併契約承認の件"
        result = classify_proposal(title, ProposalType.COMPANY)
        assert result == ProposalCategory.OTHER

    def test_other_shareholder(self) -> None:
        title = "情報開示に関する定款変更の件"
        result = classify_proposal(title, ProposalType.SHAREHOLDER)
        # 定款にマッチするためARTICLES_CHANGE
        assert result == ProposalCategory.ARTICLES_CHANGE
