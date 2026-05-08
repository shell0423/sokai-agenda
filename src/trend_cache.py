from __future__ import annotations

import json
import logging
from enum import Enum
from pathlib import Path

from src.models import (
    Candidate,
    MeetingResult,
    Proposal,
    ProposalType,
    VoteResult,
)

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("output/cache")


def save_year_data(
    year: int,
    meetings: list[MeetingResult],
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> Path:
    """年度データをJSONファイルに保存する。

    Args:
        year: 対象年度。
        meetings: MeetingResultリスト。
        cache_dir: キャッシュディレクトリ。

    Returns:
        保存先のパス。
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{year}_meetings.json"

    data = [_meeting_to_dict(m) for m in meetings]
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("キャッシュ保存: %s (%d社)", path, len(meetings))
    return path


def load_year_data(
    year: int,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> list[MeetingResult] | None:
    """年度データをJSONファイルから読み込む。

    Args:
        year: 対象年度。
        cache_dir: キャッシュディレクトリ。

    Returns:
        MeetingResultリスト。キャッシュがなければNone。
    """
    path = cache_dir / f"{year}_meetings.json"
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        meetings = [_dict_to_meeting(d) for d in data]
        logger.info(
            "キャッシュ読み込み: %s (%d社)", path, len(meetings)
        )
        return meetings
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        logger.warning("キャッシュ読み込み失敗: %s (%s)", path, e)
        return None


def _meeting_to_dict(meeting: MeetingResult) -> dict:
    """MeetingResultを辞書に変換する。"""

    def _convert(obj: object) -> object:
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_convert(v) for v in obj]
        return obj

    proposals = []
    for p in meeting.proposals:
        candidates = [
            {
                "name": c.name,
                "votes_for": c.votes_for,
                "votes_against": c.votes_against,
                "votes_abstain": c.votes_abstain,
                "approval_rate": c.approval_rate,
            }
            for c in p.candidates
        ]
        proposals.append(
            {
                "number": p.number,
                "title": p.title,
                "proposal_type": p.proposal_type.value,
                "result": (
                    p.result.value if p.result is not None else None
                ),
                "approval_rate": p.approval_rate,
                "votes_for": p.votes_for,
                "votes_against": p.votes_against,
                "votes_abstain": p.votes_abstain,
                "candidates": candidates,
            }
        )

    return {
        "doc_id": meeting.doc_id,
        "edinet_code": meeting.edinet_code,
        "sec_code": meeting.sec_code,
        "company_name": meeting.company_name,
        "submit_date": meeting.submit_date,
        "proposals": proposals,
    }


def _dict_to_meeting(d: dict) -> MeetingResult:
    """辞書からMeetingResultを復元する。"""
    proposals = []
    for p in d["proposals"]:
        candidates = [
            Candidate(
                name=c["name"],
                votes_for=c.get("votes_for"),
                votes_against=c.get("votes_against"),
                votes_abstain=c.get("votes_abstain"),
                approval_rate=c.get("approval_rate"),
            )
            for c in p.get("candidates", [])
        ]

        result = None
        if p.get("result") is not None:
            result = VoteResult(p["result"])

        proposals.append(
            Proposal(
                number=p["number"],
                title=p["title"],
                proposal_type=ProposalType(p["proposal_type"]),
                result=result,
                approval_rate=p.get("approval_rate"),
                votes_for=p.get("votes_for"),
                votes_against=p.get("votes_against"),
                votes_abstain=p.get("votes_abstain"),
                candidates=candidates,
            )
        )

    return MeetingResult(
        doc_id=d["doc_id"],
        edinet_code=d["edinet_code"],
        sec_code=d["sec_code"],
        company_name=d["company_name"],
        submit_date=d["submit_date"],
        proposals=proposals,
    )
