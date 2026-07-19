#!/usr/bin/env python3
"""倉庫(wh_shareholders)へ大量保有を寄せてよいかを機械判定する常設ツール。

使い方:
    .venv/bin/python scripts/check_wh_readiness.py

「倉庫の株主EP充填が進んだ頃」を感覚でなく数値で判定する。3つのゲートを見る:
  A. 鮮度   … wh_shareholders の最新提出日が今日から何日遅れか＋直近30日の提出件数
  B. カバレッジ … 大量保有データがある社数 / 上場マスタ
  C. 一致度  … このアプリの最後のスクレイプ(output/trigger_holdings.csv)と
               倉庫を実戦リスト銘柄で突き合わせ、主要アクティビストの保有割合が
               ±0.5pt以内で一致する割合

判定:
  🔴 まだ    … 鮮度が古い(直近提出が未取込)。移行すると直近シグナルを取りこぼす。
  🟡 近い    … 鮮度は改善したが保有割合の一致がまだ弱い。要精査。
  🟢 寄せてよい … 鮮度・一致とも基準クリア。search_trigger_holdings を倉庫参照に置換検討。

判定基準は下の THRESHOLDS。基準に達したら再検証(このツール)→移行設計、の順。
"""
from __future__ import annotations

import csv
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

# --- 移行OKと判断するしきい値 -----------------------------------------
THRESHOLDS = {
    "freshness_days_max": 10,   # 最新提出が今日からこの日数以内なら鮮度OK
    "recent30_min": 50,         # 直近30日の提出がこの件数以上なら「取込が動いている」
    "coverage_min": 0.75,       # 大量保有ありの社数割合の下限
    "match_pct_min": 0.90,      # 主要アクティビストの保有割合±0.5pt一致の下限
    "match_tolerance_pt": 0.5,  # 一致とみなす保有割合の差(pt)
}


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
    sys.path.insert(0, str(WAREHOUSE_DIR))
    from client import connect  # warehouse/client.py

    return connect(read_only=True)


def main() -> int:
    today = date.today()
    con = _connect()
    try:
        # A. 鮮度
        mx = con.execute(
            "SELECT max(submit_date_time) FROM wh_shareholders"
        ).fetchone()[0]
        mx_date = datetime.fromisoformat(str(mx)[:19]).date() if mx else None
        freshness_days = (today - mx_date).days if mx_date else 9999
        recent30 = con.execute(
            "SELECT count(*) FROM wh_shareholders "
            "WHERE CAST(submit_date_time AS DATE) >= (CURRENT_DATE - INTERVAL 30 DAY)"
        ).fetchone()[0]

        # B. カバレッジ
        iss = con.execute(
            "SELECT count(DISTINCT issuer_edinet_code) FROM wh_shareholders"
        ).fetchone()[0]
        tot = con.execute("SELECT count(*) FROM wh_security").fetchone()[0]
        coverage = iss / tot if tot else 0.0

        # C. 一致度(このアプリの最後のスクレイプ vs 倉庫)
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
                    mismatches.append(
                        (code, r["name"][:12], aratio, wratio,
                         str(cand[0][2])[:10]))
        match_pct = matched / found if found else 0.0
    finally:
        con.close()

    # --- 判定 ---
    fresh_ok = (freshness_days <= THRESHOLDS["freshness_days_max"]
                and recent30 >= THRESHOLDS["recent30_min"])
    cov_ok = coverage >= THRESHOLDS["coverage_min"]
    match_ok = match_pct >= THRESHOLDS["match_pct_min"]

    print("=" * 60)
    print(f"倉庫 大量保有(wh_shareholders) 移行レディネス判定  {today}")
    print("=" * 60)
    def mark(ok): return "✅" if ok else "❌"
    print(f"A. 鮮度      {mark(fresh_ok)} 最新提出={mx_date}"
          f"（今日から{freshness_days}日遅れ / 直近30日={recent30}件）")
    print(f"             基準: {THRESHOLDS['freshness_days_max']}日以内 かつ "
          f"直近30日≥{THRESHOLDS['recent30_min']}件")
    print(f"B. カバレッジ {mark(cov_ok)} {iss}/{tot}社 ({coverage*100:.0f}%)"
          f"  基準: ≥{THRESHOLDS['coverage_min']*100:.0f}%")
    print(f"C. 一致度    {mark(match_ok)} 主要アクティビスト検出 {found}/{total_checked}、"
          f"±{THRESHOLDS['match_tolerance_pt']}pt一致 {matched}/{found}"
          f"（{match_pct*100:.0f}%）  基準: ≥{THRESHOLDS['match_pct_min']*100:.0f}%")

    if not fresh_ok:
        verdict = "🔴 まだ — 直近提出が倉庫に入っていない（鮮度不足）。移行すると総会シーズンの直近シグナルを取りこぼす。"
    elif not (cov_ok and match_ok):
        verdict = "🟡 近い — 鮮度は改善。ただしカバレッジ/一致がまだ基準未満。外れ値を精査してから。"
    else:
        verdict = "🟢 寄せてよい — 鮮度・カバレッジ・一致すべてクリア。search_trigger_holdings.py の倉庫参照化を設計してよい。"
    print("-" * 60)
    print("判定:", verdict)

    if mismatches:
        print(f"\n差1pt超（{len(mismatches)}社・倉庫の取りこぼし/鮮度落ち疑い）:")
        for code, nm, ar, wr, sd in sorted(
                mismatches, key=lambda x: -abs(x[2] - x[3]))[:10]:
            print(f"  {code} {nm:12} アプリ{ar:6.2f}% ↔ 倉庫{wr:6.2f}%"
                  f"(最新{sd}) 差{abs(ar-wr):.2f}pt")

    # 終了コード: 🟢=0 / 🟡=1 / 🔴=2 （cron等で使えるように）
    return 0 if (fresh_ok and cov_ok and match_ok) else (2 if not fresh_ok else 1)


if __name__ == "__main__":
    sys.exit(main())
