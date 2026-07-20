"""倉庫(wh_shareholders)へ大量保有を寄せてよいかを機械判定するロジック。

CLI(scripts/check_wh_readiness.py)とアプリ(app.py の手動ボタン)の両方から使う。
evaluate() が構造化した結果dictを返し、format_text() がCLI表示用の文字列を作る。

3ゲート:
  A. 鮮度   … wh_shareholders の最新提出日が今日から何日遅れか＋直近30日の提出件数
  B. カバレッジ … 大量保有データがある社数 / 上場マスタ
  C. 一致度  … このアプリの最後のスクレイプ(derived/diff_watchlist.json)と倉庫を
               実戦リスト銘柄で突き合わせ、主要アクティビストの保有割合が±0.5pt一致する割合
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT / "output"
WAREHOUSE_DIR = Path(
    os.getenv("WAREHOUSE_DIR", os.path.expanduser("~/Claude/warehouse"))
)

# 移行OKと判断するしきい値
THRESHOLDS = {
    "freshness_days_max": 10,   # 最新提出が今日からこの日数以内なら鮮度OK
    "recent30_min": 50,         # 直近30日の提出がこの件数以上なら「取込が動いている」
    "coverage_min": 0.75,       # 大量保有ありの社数割合の下限
    "match_pct_min": 0.90,      # 主要アクティビストの保有割合±0.5pt一致の下限
    "match_tolerance_pt": 0.5,  # 一致とみなす保有割合の差(pt)
}


# 判定結果の保存先(常時表示バッジ用に前回結果を残す)
LAST_PATH = OUTPUT / "derived" / "wh_readiness_last.json"


def save_last(result: dict) -> None:
    """判定結果を保存(次回起動時のバッジ表示用)。"""
    try:
        LAST_PATH.parent.mkdir(parents=True, exist_ok=True)
        LAST_PATH.write_text(
            json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def load_last() -> dict | None:
    """前回の判定結果を読む。無ければNone。"""
    if not LAST_PATH.exists():
        return None
    try:
        return json.loads(LAST_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[\s　（）()・,，.．株式会社リミテッドｌｔｄltd]", "", s)


def _hmatch(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    short, long = (na, nb) if len(na) <= len(nb) else (nb, na)
    return short[:10] in long or long[:10] in short or short in long


def _connect():
    if str(WAREHOUSE_DIR) not in sys.path:
        sys.path.insert(0, str(WAREHOUSE_DIR))
    from client import connect  # warehouse/client.py

    return connect(read_only=True)


def evaluate() -> dict:
    """3ゲートを測って構造化結果を返す。倉庫接続は read_only で即クローズ。

    Returns:
        {available, date, gates:{freshness,coverage,match}, verdict, level, mismatches}
        倉庫に繋げない場合は available=False。
    """
    today = date.today()
    try:
        con = _connect()
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": str(e), "date": today.isoformat()}

    try:
        mx = con.execute(
            "SELECT max(submit_date_time) FROM wh_shareholders"
        ).fetchone()[0]
        mx_date = datetime.fromisoformat(str(mx)[:19]).date() if mx else None
        freshness_days = (today - mx_date).days if mx_date else 9999
        recent30 = con.execute(
            "SELECT count(*) FROM wh_shareholders "
            "WHERE CAST(submit_date_time AS DATE) >= (CURRENT_DATE - INTERVAL 30 DAY)"
        ).fetchone()[0]

        iss = con.execute(
            "SELECT count(DISTINCT issuer_edinet_code) FROM wh_shareholders"
        ).fetchone()[0]
        tot = con.execute("SELECT count(*) FROM wh_security").fetchone()[0]
        coverage = iss / tot if tot else 0.0

        wl_path = OUTPUT / "derived" / "diff_watchlist.json"
        found = matched = total_checked = 0
        mismatches = []
        if wl_path.exists():
            wl = json.loads(wl_path.read_text(encoding="utf-8"))["watchlist"]
            for r in wl:
                code, holder = r["code"], r["holder"]
                aratio = float(r["ratio"] or 0)
                rows = con.execute(
                    "SELECT holder_name, holding_ratio, submit_date_time "
                    "FROM wh_shareholders "
                    "WHERE left(CAST(issuer_sec_code AS VARCHAR),4)=?",
                    [code],
                ).fetchall()
                cand = [x for x in rows if _hmatch(holder, x[0])]
                total_checked += 1
                if not cand:
                    continue
                found += 1
                cand.sort(key=lambda x: str(x[2]), reverse=True)
                wratio = (cand[0][1] or 0) * 100
                diff = abs(aratio - wratio)
                if diff <= THRESHOLDS["match_tolerance_pt"]:
                    matched += 1
                elif diff > 1.0:
                    mismatches.append({
                        "code": code, "name": r["name"],
                        "app": round(aratio, 2), "wh": round(wratio, 2),
                        "wh_date": str(cand[0][2])[:10],
                        "diff": round(diff, 2),
                    })
        match_pct = matched / found if found else 0.0
    finally:
        con.close()

    t = THRESHOLDS
    fresh_ok = (freshness_days <= t["freshness_days_max"]
                and recent30 >= t["recent30_min"])
    cov_ok = coverage >= t["coverage_min"]
    match_ok = match_pct >= t["match_pct_min"]

    if not fresh_ok:
        level, verdict = "red", (
            "🔴 まだ — 直近提出が倉庫に入っていない（鮮度不足）。"
            "移行すると総会シーズンの直近シグナルを取りこぼす。")
    elif not (cov_ok and match_ok):
        level, verdict = "yellow", (
            "🟡 近い — 鮮度は改善。ただしカバレッジ/一致がまだ基準未満。外れ値を精査してから。")
    else:
        level, verdict = "green", (
            "🟢 寄せてよい — 鮮度・カバレッジ・一致すべてクリア。"
            "search_trigger_holdings.py の倉庫参照化を設計してよい。")

    return {
        "available": True,
        "date": today.isoformat(),
        "gates": {
            "freshness": {"ok": fresh_ok, "latest": (mx_date.isoformat() if mx_date else None),
                          "days_behind": freshness_days, "recent30": recent30},
            "coverage": {"ok": cov_ok, "issuers": iss, "total": tot, "pct": round(coverage, 3)},
            "match": {"ok": match_ok, "found": found, "checked": total_checked,
                      "matched": matched, "pct": round(match_pct, 3)},
        },
        "verdict": verdict,
        "level": level,
        "mismatches": sorted(mismatches, key=lambda m: -m["diff"]),
    }


def format_text(r: dict) -> str:
    if not r.get("available"):
        return "倉庫に接続できませんでした: " + r.get("error", "")
    t = THRESHOLDS
    g = r["gates"]
    def mk(ok): return "✅" if ok else "❌"
    lines = [
        "=" * 60,
        f"倉庫 大量保有(wh_shareholders) 移行レディネス判定  {r['date']}",
        "=" * 60,
        f"A. 鮮度      {mk(g['freshness']['ok'])} 最新提出={g['freshness']['latest']}"
        f"（今日から{g['freshness']['days_behind']}日遅れ / 直近30日={g['freshness']['recent30']}件）",
        f"             基準: {t['freshness_days_max']}日以内 かつ 直近30日≥{t['recent30_min']}件",
        f"B. カバレッジ {mk(g['coverage']['ok'])} {g['coverage']['issuers']}/{g['coverage']['total']}社"
        f" ({g['coverage']['pct']*100:.0f}%)  基準: ≥{t['coverage_min']*100:.0f}%",
        f"C. 一致度    {mk(g['match']['ok'])} 主要アクティビスト検出 {g['match']['found']}/{g['match']['checked']}、"
        f"±{t['match_tolerance_pt']}pt一致 {g['match']['matched']}/{g['match']['found']}"
        f"（{g['match']['pct']*100:.0f}%）  基準: ≥{t['match_pct_min']*100:.0f}%",
        "-" * 60,
        "判定: " + r["verdict"],
    ]
    if r["mismatches"]:
        lines.append(f"\n差1pt超（{len(r['mismatches'])}社・倉庫の取りこぼし/鮮度落ち疑い）:")
        for m in r["mismatches"][:10]:
            nm = m["name"].replace("株式会社", "")[:12]
            lines.append(f"  {m['code']} {nm:12} アプリ{m['app']:6.2f}% ↔ 倉庫{m['wh']:6.2f}%"
                         f"(最新{m['wh_date']}) 差{m['diff']:.2f}pt")
    return "\n".join(lines)
