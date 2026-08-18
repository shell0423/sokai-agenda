#!/usr/bin/env python3
"""トリガー該当企業の大量保有を **倉庫(wh_shareholders)** から組み立てる。

`search_trigger_holdings.py` の置き換え。あちらは EDINET を自前スキャンし
`src/xbrl_parser.py` で解析していたが、そのパーサは contextRef を見ないため
**共同保有報告書で先頭の保有者しか拾えず**、2人目以降が丸ごと消えていた
(実例 ステラケミファ4109: NAVF 個別4.24% だけが出てグループ合算22.73% が見えない)。
倉庫側は 2026-08-15 に共同保有者の行展開を修復済みなので、そちらを読む。

置き換えたのは「大量保有の取得」だけで、**トリガー分析(Step 1)は従来どおり**
`compare_triggers.analyze_triggers` を再利用する(キャッシュのみ・API不要)。
出力CSVのスキーマは既存の `export_timeline_csv` / `export_summary_csv` を
そのまま使うので下流(`analysis_diff.load_holdings` → app/dashboard)は無改修で動く。
末尾に「グループ合算(%)」「共同保有者数」の2列を**追加**する(名前で読む消費側は無影響)。

使い方:
    .venv/bin/python scripts/build_trigger_holdings_wh.py --dry-run   # 表示のみ
    .venv/bin/python scripts/build_trigger_holdings_wh.py             # CSV出力
"""
from __future__ import annotations

import argparse
import csv
import html
import re
import sys
import unicodedata
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from compare_triggers import _resolve_years, analyze_triggers  # noqa: E402
from search_trigger_holdings import (  # noqa: E402
    HolderTimeline,
    export_summary_csv,
)
from src.warehouse_client import get_holdings  # noqa: E402

OUTPUT_DIR = BASE / "output"


def _holder_key(name: str) -> str:
    """保有者の名寄せキー。同一保有者が表記ゆれで分裂するのを防ぐ。

    倉庫には出所が2系統ある(edinetdb.jp由来の旧era / FSA直取得の新era)。
    同じ保有者でも **NBSP(U+00A0) と通常スペースが混在**し、生の文字列で束ねると
    タイムラインが2本に割れる(実例 ステラケミファ4109 のダルトンが
    2026-04以前と06-10以降で別人扱いになり、推移が繋がらなかった)。
    NFKC正規化＋空白畳み込みで吸収する。**法人格の違い(Inc. と LLC)は別物として残す**
    ため、これ以上は寄せない。
    """
    return re.sub(
        r"\s+", " ",
        unicodedata.normalize("NFKC", html.unescape(name or ""))
    ).strip().lower()


def build_timelines_from_warehouse(
    holdings: dict[str, list[dict]],
    name_map: dict[str, str],
    conditions_map: dict[str, str],
) -> tuple[list[HolderTimeline], dict[tuple[str, str], dict]]:
    """倉庫の行を (社 × 保有者) のタイムラインへ畳む。

    Returns:
        (timelines, extra) — extra は (sec_code, holder) → {"total", "joint"}
        で、CSVの追加2列に使う最新値。
    """
    timelines: list[HolderTimeline] = []
    extra: dict[tuple[str, str], dict] = {}

    for code4 in sorted(holdings):
        by_holder: dict[str, list[dict]] = {}
        for r in holdings[code4]:
            if not r["holder"]:
                continue
            by_holder.setdefault(_holder_key(r["holder"]), []).append(r)

        for rows in by_holder.values():
            rows.sort(key=lambda x: x["submit_date"])
            holder = rows[-1]["holder"]  # 表示は最新の表記を採る
            tl = HolderTimeline(
                sec_code=code4,
                company_name=name_map.get(code4, "不明"),
                holder_name=holder,
                purpose=rows[-1]["purpose"],
                trigger_conditions=conditions_map.get(code4, ""),
                entries=[(r["submit_date"], r["ratio"]) for r in rows],
            )
            timelines.append(tl)
            extra[(code4, holder)] = {
                "total": rows[-1]["total_ratio"],
                "joint": rows[-1]["joint_count"],
                # グループ合算の**推移**。個別値だけでは共同保有の実勢が測れず、
                # 「個別は減ったがグループは積み増している/その逆」を取り違える。
                "total_entries": [(r["submit_date"], r["total_ratio"]) for r in rows],
            }

    # 社ごと・最新保有割合の降順(既存CSVと同じ「大きい順に見たい」意図)
    timelines.sort(
        key=lambda t: (
            t.sec_code,
            -(next((r for _, r in reversed(t.entries) if r is not None), 0) or 0),
        )
    )
    return timelines, extra


def export_timeline_csv_wh(
    timelines: list[HolderTimeline],
    extra: dict[tuple[str, str], dict],
    path: Path,
) -> None:
    """既存スキーマ + 「グループ合算(%)」「共同保有者数」でCSV出力する。

    既存8列の並び・書式は `search_trigger_holdings.export_timeline_csv` と同一。
    消費側(`analysis_diff.load_holdings`)は列名で読むので追加は安全。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "証券コード", "企業名", "保有者名", "最新保有割合(%)", "保有割合推移",
        "保有目的", "トリガー条件", "報告書件数",
        "グループ合算(%)", "共同保有者数", "グループ合算推移",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for tl in timelines:
            entries_str = " → ".join(
                f"{d[2:7].replace('-', '/')}: "
                + (f"{r:.2f}%" if r is not None else "N/A")
                for d, r in tl.entries
            )
            latest = next(
                (r for _, r in reversed(tl.entries) if r is not None), None
            )
            ex = extra.get((tl.sec_code, tl.holder_name), {})
            w.writerow([
                tl.sec_code, tl.company_name, tl.holder_name,
                f"{latest:.2f}" if latest is not None else "",
                entries_str, tl.purpose, tl.trigger_conditions, len(tl.entries),
                f"{ex.get('total'):.2f}" if ex.get("total") is not None else "",
                ex.get("joint") or "",
                " → ".join(
                    f"{d[2:7].replace('-', '/')}: "
                    + (f"{r:.2f}%" if r is not None else "N/A")
                    for d, r in ex.get("total_entries", [])
                ),
            ])
    print(f"CSV出力: {path} ({len(timelines)}行)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--years", help="対象年(例 2025,2026)。既定は compare_triggers と同じ")
    ap.add_argument("--since", default="2024-01-01", help="この提出日以降(既定 2024-01-01)")
    ap.add_argument("--holding-threshold", type=float, default=-10.0)
    ap.add_argument("-o", "--output", default=str(OUTPUT_DIR / "trigger_holdings.csv"))
    ap.add_argument("--summary-output",
                    default=str(OUTPUT_DIR / "trigger_holdings_summary.csv"))
    ap.add_argument("--dry-run", action="store_true", help="CSVを書かず統計だけ表示")
    args = ap.parse_args()

    years = _resolve_years(args.years)
    print(f"Step 1: トリガー分析（{','.join(str(y) for y in years)}）… API不要")
    triggers, stats = analyze_triggers(
        years=years, holding_threshold=args.holding_threshold)
    targets = [t for t in triggers if t.status in ("新規追加", "既存継続")]
    print(f"  対象企業: {len(targets)}社"
          f"(新規追加 {stats['added']} / 既存継続 {stats['common']})")

    name_map = {t.sec_code: t.company_name for t in targets}
    conditions_map: dict[str, str] = {}
    for t in targets:
        conds = []
        if t.cond_a:
            conds.append("A:賛成率低下")
        if t.cond_b:
            conds.append("B:新規株主提案")
        if t.cond_c:
            conds.append("C:会社提案否決")
        conditions_map[t.sec_code] = " + ".join(conds)

    codes = sorted(name_map)
    print(f"\nStep 2: 倉庫 wh_shareholders から取得（{args.since} 以降・API不要）…")
    holdings = get_holdings(codes, since=args.since)
    if not holdings:
        print("エラー: 倉庫から1件も取得できなかった（倉庫の場所/ロックを確認）")
        return 1

    n_rows = sum(len(v) for v in holdings.values())
    print(f"  {len(holdings)}社 / {n_rows}行（大量保有報告なし: "
          f"{len(codes) - len(holdings)}社）")

    timelines, extra = build_timelines_from_warehouse(
        holdings, name_map, conditions_map)
    joint = sum(1 for e in extra.values() if (e.get("joint") or 1) > 1)
    print(f"  タイムライン {len(timelines)}件（うち共同保有 {joint}件）")

    if args.dry_run:
        print("\n[dry-run] CSV書込なし。")
        return 0

    export_timeline_csv_wh(timelines, extra, Path(args.output))
    export_summary_csv(timelines, set(codes), name_map, conditions_map,
                       Path(args.summary_output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
