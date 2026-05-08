from __future__ import annotations

from pathlib import Path

from src.models import (
    Candidate,
    MeetingResult,
    Proposal,
    ProposalType,
    VoteResult,
)
from src.trend_cache import load_year_data, save_year_data


def _make_sample_meetings() -> list[MeetingResult]:
    """テスト用MeetingResultを生成する。"""
    return [
        MeetingResult(
            doc_id="S100TEST",
            edinet_code="E00001",
            sec_code="46260",
            company_name="テスト株式会社",
            submit_date="2025-06-23",
            proposals=[
                Proposal(
                    number=1,
                    title="剰余金の処分の件",
                    proposal_type=ProposalType.COMPANY,
                    result=VoteResult.APPROVED,
                    approval_rate=95.50,
                    votes_for=100000,
                    votes_against=5000,
                    votes_abstain=500,
                ),
                Proposal(
                    number=2,
                    title="取締役3名選任の件",
                    proposal_type=ProposalType.COMPANY,
                    candidates=[
                        Candidate(
                            name="山田 太郎",
                            votes_for=90000,
                            votes_against=10000,
                            votes_abstain=500,
                            approval_rate=89.55,
                        ),
                        Candidate(
                            name="佐藤 花子",
                            votes_for=95000,
                            votes_against=5000,
                            votes_abstain=500,
                            approval_rate=94.53,
                        ),
                    ],
                ),
                Proposal(
                    number=3,
                    title="取締役解任の件",
                    proposal_type=ProposalType.SHAREHOLDER,
                    result=VoteResult.REJECTED,
                    approval_rate=30.00,
                    votes_for=30000,
                    votes_against=70000,
                    votes_abstain=500,
                ),
            ],
        )
    ]


class TestTrendCache:
    """trend_cache のテスト。"""

    def test_roundtrip(self, tmp_path: Path) -> None:
        """保存→読み込みでデータが一致する。"""
        meetings = _make_sample_meetings()
        save_year_data(2025, meetings, cache_dir=tmp_path)
        loaded = load_year_data(2025, cache_dir=tmp_path)

        assert loaded is not None
        assert len(loaded) == 1

        m = loaded[0]
        assert m.doc_id == "S100TEST"
        assert m.sec_code == "46260"
        assert m.company_name == "テスト株式会社"
        assert len(m.proposals) == 3

    def test_proposal_fields(self, tmp_path: Path) -> None:
        """議案フィールドが正しく復元される。"""
        meetings = _make_sample_meetings()
        save_year_data(2025, meetings, cache_dir=tmp_path)
        loaded = load_year_data(2025, cache_dir=tmp_path)

        p1 = loaded[0].proposals[0]
        assert p1.title == "剰余金の処分の件"
        assert p1.proposal_type == ProposalType.COMPANY
        assert p1.result == VoteResult.APPROVED
        assert p1.approval_rate == 95.50
        assert p1.votes_for == 100000

    def test_candidates_restored(self, tmp_path: Path) -> None:
        """候補者データが正しく復元される。"""
        meetings = _make_sample_meetings()
        save_year_data(2025, meetings, cache_dir=tmp_path)
        loaded = load_year_data(2025, cache_dir=tmp_path)

        p2 = loaded[0].proposals[1]
        assert len(p2.candidates) == 2
        assert p2.candidates[0].name == "山田 太郎"
        assert p2.candidates[0].approval_rate == 89.55
        assert p2.candidates[1].name == "佐藤 花子"

    def test_shareholder_proposal(self, tmp_path: Path) -> None:
        """株主提案が正しく復元される。"""
        meetings = _make_sample_meetings()
        save_year_data(2025, meetings, cache_dir=tmp_path)
        loaded = load_year_data(2025, cache_dir=tmp_path)

        p3 = loaded[0].proposals[2]
        assert p3.proposal_type == ProposalType.SHAREHOLDER
        assert p3.result == VoteResult.REJECTED

    def test_has_shareholder_proposals_property(
        self, tmp_path: Path
    ) -> None:
        """has_shareholder_proposalsプロパティが動作する。"""
        meetings = _make_sample_meetings()
        save_year_data(2025, meetings, cache_dir=tmp_path)
        loaded = load_year_data(2025, cache_dir=tmp_path)

        assert loaded[0].has_shareholder_proposals is True

    def test_cache_miss(self, tmp_path: Path) -> None:
        """キャッシュが存在しない場合はNoneを返す。"""
        result = load_year_data(2020, cache_dir=tmp_path)
        assert result is None

    def test_corrupted_cache(self, tmp_path: Path) -> None:
        """壊れたキャッシュファイルはNoneを返す。"""
        path = tmp_path / "2025_meetings.json"
        path.write_text("not valid json", encoding="utf-8")
        result = load_year_data(2025, cache_dir=tmp_path)
        assert result is None
