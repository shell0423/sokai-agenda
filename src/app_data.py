"""Streamlitアプリ用のデータローダー。

キャッシュJSON(議案別賛成率)・trigger CSV・derived JSON・卒業データを読み、
銘柄詳細(議案2025vs2026・保有者タイムライン)を組み立てる。
"""
from __future__ import annotations

import json
from pathlib import Path

from src.analysis_diff import (
    DATA_DIR,
    DERIVED_DIR,
    OUTPUT_DIR,
    load_holdings,
    load_notes,
    load_triggers,
    parse_trend_points,
)

CACHE_DIR = OUTPUT_DIR / "cache"


def load_meetings(year: int) -> dict[str, dict]:
    """{code4: MeetingResult dict}。キャッシュが無ければ空。"""
    path = CACHE_DIR / f"{year}_meetings.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {m["sec_code"][:4]: m for m in data}


def load_derived() -> dict | None:
    path = DERIVED_DIR / "diff_watchlist.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_graduations() -> dict:
    path = DATA_DIR / "graduations_2026.json"
    if not path.exists():
        return {"graduations": [], "exceptions": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _apply_corrections(code: str, v: dict, corrections: dict) -> tuple[dict, str]:
    """C_override等の補正を適用したコピーと補正マークを返す。"""
    fix = corrections.get(code, {})
    if not fix:
        return v, ""
    v = dict(v)
    if "C_override" in fix:
        v["C"] = bool(fix["C_override"])
        if not v["C"]:
            v["Cd"] = ""
    return v, "⚠補正"


def load_trigger_table(which: str = "2526") -> list[dict]:
    """全トリガー表(新ロジック該当のみ)を行リストで返す。correctionsを反映。"""
    path = OUTPUT_DIR / f"trigger_comparison_{which}.csv"
    if not path.exists():
        return []
    t = load_triggers(path)
    corrections = load_notes().get("corrections", {})
    rows = []
    for code, v in t.items():
        if not v["newlogic"]:
            continue
        v, mark = _apply_corrections(code, v, corrections)
        rows.append({
            "証券コード": code,
            "企業名": v["name"],
            "A:賛成率低下": "○" if v["A"] else "",
            "B:新規株主提案": "○" if v["B"] else "",
            "C:否決": "○" if v["C"] else "",
            "補正": mark,
            "A詳細": v["Ad"], "B詳細": v["Bd"], "C詳細": v["Cd"],
        })
    rows.sort(key=lambda r: r["証券コード"])
    return rows


def proposals_table(meeting: dict | None) -> list[dict]:
    """MeetingResult → 議案テーブル行。否決は賛成率<50 or result=否決。"""
    if not meeting:
        return []
    rows = []
    for p in meeting.get("proposals", []):
        ar = p.get("approval_rate")
        rejected = (p.get("result") == "否決") or (
            isinstance(ar, (int, float)) and ar is not None and ar < 50
            and (p.get("votes_for") or 0) > 0
        )
        cands = p.get("candidates") or []
        cand_names = ", ".join(
            c.get("name") if isinstance(c, dict) else str(c)
            for c in cands if c
        )
        rows.append({
            "No": p.get("number"),
            "議案": (p.get("title") or "").strip() or "(タイトル空)",
            "区分": p.get("proposal_type") or "",
            "賛成率%": ar,
            "否決": "○" if rejected else "",
            "候補者": cand_names,
        })
    return rows


def load_fundamentals(code: str) -> dict | None:
    """株価/PER/PBR を返す。まず配布済みJSON、無ければ倉庫を直接引く。

    実戦リスト/除外の銘柄は build_all が derived JSON に焼き込んでいるのでそれを使う。
    全トリガー・銘柄検索から開いた銘柄はJSONに無いため、ローカル(倉庫あり)でのみ
    その場で1銘柄だけ取得する。Cloud では倉庫が無いので None になる。
    """
    derived = load_derived()
    if derived:
        for row in derived.get("watchlist", []) + derived.get("excluded", []):
            if row["code"] == code and row.get("fund"):
                return row["fund"]
    from src import warehouse_client

    return warehouse_client.get_fundamentals([code]).get(code)


def company_detail(code: str) -> dict:
    """銘柄コード(4桁)の深掘り情報を組み立てる。"""
    m25 = load_meetings(2025)
    m26 = load_meetings(2026)
    holdings = load_holdings()
    notes = load_notes()

    corrections = notes.get("corrections", {})
    t_curr = {}
    curr_path = OUTPUT_DIR / "trigger_comparison_2526.csv"
    if curr_path.exists():
        t_curr = load_triggers(curr_path)
        if code in t_curr:
            t_curr[code], _ = _apply_corrections(
                code, t_curr[code], corrections)
    t_prev = {}
    prev_path = OUTPUT_DIR / "trigger_comparison_2425.csv"
    if prev_path.exists():
        t_prev = load_triggers(prev_path)

    name = ""
    for src in (t_curr, t_prev):
        if code in src:
            name = src[code]["name"]
            break
    if not name:
        for m in (m26.get(code), m25.get(code)):
            if m:
                name = m.get("company_name", "")
                break

    holders = holdings.get(code, [])
    # 保有者ごとの時系列点(グラフ用)
    holder_series = {
        h["holder"]: parse_trend_points(h["trend"])
        for h in holders
        if parse_trend_points(h["trend"])
    }

    # 外部リンク用: EDINETコード(IRBANKの大量保有ページ)と書類ID(臨時報告書ページ)
    edinet_code = ""
    for m in (m26.get(code), m25.get(code)):
        if m and m.get("edinet_code"):
            edinet_code = m["edinet_code"]
            break

    return {
        "code": code,
        "name": name,
        "fund": load_fundamentals(code),
        "edinet_code": edinet_code,
        "doc_id_2026": (m26.get(code) or {}).get("doc_id", ""),
        "doc_id_2025": (m25.get(code) or {}).get("doc_id", ""),
        "trigger_curr": t_curr.get(code),
        "trigger_prev": t_prev.get(code),
        "proposals_2025": proposals_table(m25.get(code)),
        "proposals_2026": proposals_table(m26.get(code)),
        "submit_2025": (m25.get(code) or {}).get("submit_date", ""),
        "submit_2026": (m26.get(code) or {}).get("submit_date", ""),
        "holders": holders,
        "holder_series": holder_series,
        "thesis": notes.get("thesis", {}).get(code, ""),
        "correction": notes.get("corrections", {}).get(code, {}).get("reason", ""),
    }
