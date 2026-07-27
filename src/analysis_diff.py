"""継続/新規/卒業の差分分析と実戦ウォッチリスト構築。

trigger_comparison_2425.csv / _2526.csv / trigger_holdings.csv を入力に、
- 継続・新規・卒業の集合
- 著名アクティビストのホワイトリスト判定
- 実戦ウォッチリスト(Tier 1/2/3、撤退・パッシブ・極小を除外)
を計算し、output/derived/ に永続化する。

data/notes_2026.json の corrections(誤検出補正)と thesis(銘柄メモ)を反映する。
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
DERIVED_DIR = OUTPUT_DIR / "derived"
DATA_DIR = PROJECT_ROOT / "data"

# 著名アクティビストのホワイトリスト。
# _norm()がNFKC正規化するため全角/半角の重複登録は不要。
# 短すぎる断片(AVI等)は偽陽性の温床なので固有名で書く。
ACTIVIST_FUNDS = [
    "アセット・バリュー", "Asset Value",  # AVI
    "オアシス", "Oasis",
    "3D Invest",
    "ストラテジックキャピタル", "Strategic Capital",
    "カナメ", "Kaname",
    "ひびき",
    "AXIUM",
    "みさき", "Misaki",
    "NIPPON ACTIVE VALUE",  # NAVF
    "ダルトン", "Dalton",
    "エフィッシモ", "Effissimo",
    "シルチェスター", "Silchester",
    "村上世彰", "株式会社レノ", "シティインデックス", "City Index",  # 村上系
    "シンフォニー・フィナンシャル", "Symphony Financial",
    "LIM Advisors",
    "Old Peak", "オールドピーク",
    "Be Brave",
    "fundnote", "Kaihou",
    "ありあけ",
    "インダス", "Indus",
    "Charon",
    "Farallon",
    "ヴァレックス", "Valuex",
    "UGSアセット",
    "MIRI Capital",
    "Taiyo Pacific", "タイヨウ・パシフィック",
    "Ucapi", "成成", "バックト", "カルチュア",
    "RMB Capital", "RMBキャピタル",
    "スパークス", "SPARX",
    "GLOBAL MANAGEMENT", "BROOKLANDS",
]

# 除外: パッシブ/インデックス運用(アクティビストではない)
PASSIVE_HOLDERS = [
    "スパークス", "SPARX", "FMR", "ブラックロック", "BlackRock",
    "三井住友トラスト", "キャピタル・リサーチ", "レオス",
]
# 除外: ディープバリューの縮小保有(非アクティビスト)
VALUE_REDUCERS = ["シルチェスター", "Silchester"]


def _norm(s: str | None) -> str:
    """NFKC正規化で全角英数/全角スペースを吸収して小文字化。

    EDINETの提出者名は「Ｂｅ　Ｂｒａｖｅ株式会社」等の全角表記が混在するため、
    表記ゆれをここで一括吸収する(場当たりの表記追加をしない)。
    """
    return unicodedata.normalize("NFKC", s or "").lower()


def is_activist(holder_name: str | None) -> bool:
    n = _norm(holder_name)
    return any(_norm(f) in n for f in ACTIVIST_FUNDS)


def _clean_key(k: str) -> str:
    return k.lstrip("﻿")


def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [
            {_clean_key(k): v for k, v in row.items()}
            for row in csv.DictReader(f)
        ]


def load_triggers(path: Path) -> dict[str, dict]:
    """trigger_comparison CSV → {code: {name, newlogic, A, B, C, 詳細}}"""
    out: dict[str, dict] = {}
    for r in _read_csv(path):
        code = r["証券コード"]
        out[code] = {
            "name": r["企業名"],
            "status": r["ステータス"],
            "newlogic": r["ステータス"] in ("新規追加", "既存継続"),
            "A": r["条件A:賛成率低下"] == "○",
            "B": r["条件B:新規株主提案"] == "○",
            "C": r["条件C:会社提案否決"] == "○",
            "Ad": r["条件A詳細"],
            "Bd": r["条件B詳細"],
            "Cd": r["条件C詳細"],
        }
    return out


def parse_trend(s: str | None) -> tuple[float | None, float | None, float | None]:
    """'24/03: 7.62% → 24/08: 4.44%' → (first, last, delta)

    負の保有割合(空売り由来の '-0.29%' 等)も符号を保持する。
    """
    nums = re.findall(r"(-?\d+\.?\d*)%", s or "")
    if not nums:
        return (None, None, None)
    f, l = float(nums[0]), float(nums[-1])
    return (f, l, round(l - f, 2))


def parse_trend_points(s: str | None) -> list[tuple[str, float]]:
    """'24/03: 7.62% → 24/08: 4.44%' → [('24/03', 7.62), ...]"""
    return [
        (m.group(1), float(m.group(2)))
        for m in re.finditer(r"(\d{2}/\d{2}):\s*(-?\d+\.?\d*)%", s or "")
    ]


def load_holdings(path: Path | None = None) -> dict[str, list[dict]]:
    """trigger_holdings.csv → {code: [holder rows]}"""
    path = path or OUTPUT_DIR / "trigger_holdings.csv"
    by_code: dict[str, list[dict]] = defaultdict(list)
    if not path.exists():
        return by_code
    for h in _read_csv(path):
        first, last, delta = parse_trend(h["保有割合推移"])
        by_code[h["証券コード"]].append({
            "holder": (h["保有者名"] or "").replace("　", " ").strip(),
            "ratio": last,
            "trend": h["保有割合推移"],
            "purpose": h["保有目的"],
            "first": first,
            "delta": delta,
            "n_reports": h["報告書件数"],
            "activist": is_activist(h["保有者名"]),
        })
    return by_code


def load_notes() -> dict:
    path = DATA_DIR / "notes_2026.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"corrections": {}, "thesis": {}, "caveats": []}


def _count_meetings(year: int) -> int | None:
    """指定年の総会キャッシュ(全社)の社数。無ければNone。"""
    path = OUTPUT_DIR / "cache" / f"{year}_meetings.json"
    if not path.exists():
        return None
    try:
        return len(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return None


def _profile(v: dict) -> str:
    return "".join(k for k in "ABC" if v[k]) or "-"


def _tier(ratio: float, delta: float, rejected: bool, seg: str) -> str:
    """実戦リストの優先度 Tier を返す(1=最優先, 2=要注目, 3=ウォッチ)。

    ※トリガー条件A/B/Cとは別物。混同を避けるためTierは数字にしている。
    """
    strong_build = delta >= 4
    if ratio >= 10 and (rejected or strong_build or seg == "継続"):
        return "1"
    if ratio >= 5 and (rejected or delta >= 2 or seg == "継続"):
        return "2"
    return "3"


def build_all(
    prev_csv: Path | None = None,
    curr_csv: Path | None = None,
) -> dict:
    """差分＋実戦リストを計算し output/derived/ に保存。結果dictを返す。"""
    prev_csv = prev_csv or OUTPUT_DIR / "trigger_comparison_2425.csv"
    curr_csv = curr_csv or OUTPUT_DIR / "trigger_comparison_2526.csv"
    t_prev = load_triggers(prev_csv)
    t_curr = load_triggers(curr_csv)
    s_prev = {c for c, v in t_prev.items() if v["newlogic"]}
    s_curr = {c for c, v in t_curr.items() if v["newlogic"]}

    cont = sorted(s_prev & s_curr)
    new = sorted(s_curr - s_prev)
    grad = sorted(s_prev - s_curr)

    holdings = load_holdings()
    notes = load_notes()
    corrections = notes.get("corrections", {})
    thesis = notes.get("thesis", {})

    def top_activist(code: str) -> dict | None:
        hs = [h for h in holdings.get(code, []) if h["activist"] and h["ratio"]]
        hs.sort(key=lambda x: -(x["ratio"] or 0))
        return hs[0] if hs else None

    def rejected_flag(code: str) -> bool:
        c = t_curr[code]["C"]
        fix = corrections.get(code, {})
        if "C_override" in fix:
            return bool(fix["C_override"])
        return c

    # --- 実戦リスト候補: 継続×アクティビスト + 新規×アクティビスト ---
    rows = []
    for code in cont:
        ta = top_activist(code)
        if ta:
            rows.append({"code": code, "seg": "継続", "p_prev": _profile(t_prev[code]), **_base(code, t_curr, ta)})
    for code in new:
        ta = top_activist(code)
        if ta:
            rows.append({"code": code, "seg": "新規", "p_prev": "-", **_base(code, t_curr, ta)})

    kept, excluded = [], []
    for r in rows:
        r["C"] = rejected_flag(r["code"])
        # C_override補正を「条件」プロファイル表示にも反映(表示と判定の矛盾防止)
        if r["C"] and "C" not in r["p_curr"]:
            r["p_curr"] = (r["p_curr"].rstrip("-") + "C") or "C"
        elif not r["C"] and "C" in r["p_curr"]:
            r["p_curr"] = r["p_curr"].replace("C", "") or "-"
        r["thesis"] = thesis.get(r["code"], "")
        if r["code"] in corrections:
            r["correction"] = corrections[r["code"]].get("reason", "")
        ratio = r["ratio"] or 0
        delta = r["delta"] if r["delta"] is not None else 0
        holder = r["holder"]
        reason = None
        if any(_norm(p) in _norm(holder) for p in PASSIVE_HOLDERS):
            reason = "パッシブ/インデックス運用"
        elif any(_norm(p) in _norm(holder) for p in VALUE_REDUCERS):
            reason = "バリュー保有・縮小中(非アクティビスト)"
        elif ratio < 3:
            reason = f"保有極小({ratio}%)"
        elif delta <= -2:
            reason = f"撤退方向(Δ{delta})"
        if reason:
            excluded.append({**r, "exclude_reason": reason})
        else:
            r["tier"] = _tier(ratio, delta, r["C"], r["seg"])
            kept.append(r)

    order = {"1": 0, "2": 1, "3": 2}
    kept.sort(key=lambda r: (order[r["tier"]], -(r["ratio"] or 0)))

    # 株価・PER・PBR を倉庫(mart_latest)から焼き込む。
    # Cloud には warehouse が無いので、ここで JSON に埋めた値がそのまま配布される。
    fund_asof = _attach_fundamentals(kept + excluded)

    # スクリーニングの流れ(漏斗)の各段の社数。使い方タブで表示する。
    # 条件Cは notes_2026.json の C_override 補正を適用した数を出す
    # (全トリガー表・実戦リストは補正後で数えているので、ここだけ生値だと食い違う)。
    funnel = {
        "meetings": _count_meetings(2026),          # ① 総会データを取得した全社
        "condA": sum(1 for c in s_curr if t_curr[c]["A"]),
        "condB": sum(1 for c in s_curr if t_curr[c]["B"]),
        "condC": sum(1 for c in s_curr if rejected_flag(c)),
        "trigger": len(s_curr),                     # ② 3条件トリガー(和集合)
        "activist_pool": len(kept) + len(excluded), # ③ アクティビストが筆頭の社
        "excluded": len(excluded),                  # 除外(パッシブ/縮小/極小/撤退)
        "kept": len(kept),                          # ④ 実戦リスト
    }

    result = {
        "fundamentals_asof": fund_asof,
        "sets": {"cont": cont, "new": new, "grad": grad},
        "counts": {
            "prev_total": len(s_prev), "curr_total": len(s_curr),
            "cont": len(cont), "new": len(new), "grad": len(grad),
            "kept": len(kept), "excluded": len(excluded),
            # Tier別社数(1=最優先, 2=要注目, 3=ウォッチ)
            "t1": sum(1 for r in kept if r["tier"] == "1"),
            "t2": sum(1 for r in kept if r["tier"] == "2"),
            "t3": sum(1 for r in kept if r["tier"] == "3"),
        },
        "funnel": funnel,
        "watchlist": kept,
        "excluded": excluded,
        "grad_names": {c: t_prev[c]["name"] for c in grad},
        "caveats": notes.get("caveats", []),
    }

    DERIVED_DIR.mkdir(parents=True, exist_ok=True)
    (DERIVED_DIR / "diff_watchlist.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    _export_watchlist_csv(kept)
    return result


def _load_prev_fundamentals() -> dict[str, dict]:
    """前回の derived JSON に焼かれている fund を {code: fund} で返す。

    倉庫に繋げない環境(Streamlit Cloud)で再生成しても、配布済みの株価/PERが
    消えないよう引き継ぐために使う。
    """
    path = DERIVED_DIR / "diff_watchlist.json"
    if not path.exists():
        return {}
    try:
        prev = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[str, dict] = {}
    for row in list(prev.get("watchlist", [])) + list(prev.get("excluded", [])):
        if row.get("fund"):
            out[row["code"]] = row["fund"]
    return out


def _attach_fundamentals(rows: list[dict]) -> str:
    """各行に fund(株価/PER/PBR/利回り/ROE)を付ける。取得日を返す。

    倉庫が無ければ前回値を引き継ぎ、それも無ければ fund=None のままにする
    (アプリ側は None を「—」表示にフォールバックする)。
    """
    from src import warehouse_client

    codes = [r["code"] for r in rows]
    fetched = warehouse_client.get_fundamentals(codes)
    carried = {} if fetched else _load_prev_fundamentals()
    asof = ""
    for r in rows:
        f = fetched.get(r["code"]) or carried.get(r["code"])
        r["fund"] = f
        if f and f.get("date") > asof:
            asof = f["date"]
    return asof


def _base(code: str, t_curr: dict, ta: dict) -> dict:
    v = t_curr[code]
    return {
        "name": v["name"],
        "p_curr": _profile(v),
        "holder": ta["holder"],
        "ratio": ta["ratio"],
        "delta": ta["delta"],
        "trend": ta["trend"],
        "purpose": ta["purpose"],
    }


def _export_watchlist_csv(kept: list[dict]) -> None:
    path = OUTPUT_DIR / "watchlist_2026.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Tier", "区分", "証券コード", "企業名", "主要アクティビスト",
                    "保有%", "推移Δpp", "否決", "条件",
                    "株価", "PER", "PBR", "配当利回り%", "株価日付",
                    "推移", "メモ"])
        for r in kept:
            f = r.get("fund") or {}
            w.writerow([r["tier"], r["seg"], r["code"], r["name"], r["holder"],
                        r["ratio"], r["delta"], "○" if r["C"] else "",
                        r["p_curr"],
                        f.get("price", ""), f.get("per", ""), f.get("pbr", ""),
                        f.get("yield_pct", ""), f.get("date", ""),
                        r["trend"], r["thesis"]])


if __name__ == "__main__":
    res = build_all()
    c = res["counts"]
    print(f"継続{c['cont']} 新規{c['new']} 卒業{c['grad']} / "
          f"実戦{c['kept']}社(T1:{c['t1']}/T2:{c['t2']}/T3:{c['t3']}) 除外{c['excluded']}")
