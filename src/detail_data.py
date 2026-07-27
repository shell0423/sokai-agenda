"""公開ダッシュボードに埋め込む銘柄詳細データを組み立てる。

Streamlit アプリの銘柄詳細（議案別賛成率・大量保有タイムライン・トリガー理由）を
静的HTMLでも見せるため、対象銘柄ぶんだけを JSON 化する。全社ぶんだと総会キャッシュが
13MB あるので、実戦リスト＋除外の銘柄に限定して 100KB 程度に収める。

ローダーは Streamlit 側と同じ src/app_data.py・src/analysis_diff.py を使う
（判定ロジックを二重に持たない）。
"""
from __future__ import annotations

from src.analysis_diff import (
    OUTPUT_DIR,
    load_holdings,
    load_notes,
    load_triggers,
    parse_trend_points,
)
from src.app_data import load_meetings, proposals_table

# 保有推移の時点は "24/03" と月までしか無い（trigger_holdings.csv の書式）。
# lightweight-charts は時刻の重複を受け付けないため、同一月内の連番で日を振って
# 並び順だけ保つ。ツールチップには元の "24/03" を出すので、日付を偽らない。
_MAX_DAY = 28


def _chart_points(points: list[tuple[str, float]]) -> list[dict]:
    """[('24/03', 7.62), ...] → [{"t": "2024-03-01", "l": "24/03", "v": 7.62}, ...]"""
    seen: dict[str, int] = {}
    out: list[dict] = []
    for label, value in points:
        yy, mm = label.split("/")
        seen[label] = seen.get(label, 0) + 1
        day = min(seen[label], _MAX_DAY)
        out.append({
            "t": f"20{yy}-{mm}-{day:02d}",
            "l": label,
            "v": value,
        })
    return out


def _trigger_reasons(code: str, t_curr: dict, t_prev: dict) -> dict:
    cur = t_curr.get(code) or {}
    prev = t_prev.get(code) or {}
    return {
        "cur": "".join(k for k in "ABC" if cur.get(k)) or "-",
        "prev": "".join(k for k in "ABC" if prev.get(k)) or "-",
        "A": cur.get("Ad", ""),
        "B": cur.get("Bd", ""),
        "C": cur.get("Cd", ""),
    }


def build_details(codes: list[str]) -> dict[str, dict]:
    """{code: 詳細dict} を返す。キーは4桁証券コード。

    Args:
        codes: 対象の証券コード（実戦リスト＋除外を想定）。

    Returns:
        {code: {"p25", "p26", "sub25", "sub26", "holders", "trig",
                "edinet", "doc25", "doc26", "thesis", "fix"}}
    """
    m25, m26 = load_meetings(2025), load_meetings(2026)
    holdings = load_holdings()
    notes = load_notes()
    thesis = notes.get("thesis", {})
    corrections = notes.get("corrections", {})

    t_curr = t_prev = {}
    curr_path = OUTPUT_DIR / "trigger_comparison_2526.csv"
    prev_path = OUTPUT_DIR / "trigger_comparison_2425.csv"
    if curr_path.exists():
        t_curr = load_triggers(curr_path)
    if prev_path.exists():
        t_prev = load_triggers(prev_path)

    out: dict[str, dict] = {}
    for code in codes:
        meet25, meet26 = m25.get(code), m26.get(code)
        edinet = ""
        for m in (meet26, meet25):
            if m and m.get("edinet_code"):
                edinet = m["edinet_code"]
                break

        holders = []
        for h in sorted(holdings.get(code, []), key=lambda x: -(x["ratio"] or 0)):
            holders.append({
                "h": h["holder"],
                "r": h["ratio"],
                "d": h["delta"],
                "a": h["activist"],
                "n": h["n_reports"],
                "pu": (h["purpose"] or "")[:100],
                "pts": _chart_points(parse_trend_points(h["trend"])),
            })

        out[code] = {
            "p25": proposals_table(meet25),
            "p26": proposals_table(meet26),
            "sub25": (meet25 or {}).get("submit_date", ""),
            "sub26": (meet26 or {}).get("submit_date", ""),
            "holders": holders,
            "trig": _trigger_reasons(code, t_curr, t_prev),
            "edinet": edinet,
            "doc25": (meet25 or {}).get("doc_id", ""),
            "doc26": (meet26 or {}).get("doc_id", ""),
            "thesis": thesis.get(code, ""),
            "fix": corrections.get(code, {}).get("reason", ""),
        }
    return out
