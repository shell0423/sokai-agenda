"""実戦ウォッチリスト＋卒業(決着)の自己完結ローカルHTMLダッシュボード生成。

derived/diff_watchlist.json と data/graduations_2026.json を読み、
output/dashboard_2026.html を書き出す。外部リソース参照なし・テーマ対応。
"""
from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path

from src.analysis_diff import DERIVED_DIR, OUTPUT_DIR
from src.app_data import load_graduations

FUND_SHORT = {
    "アセット・バリュー": "AVI", "Asset Value": "AVI",
    "エフィッシモ": "エフィッシモ", "ストラテジックキャピタル": "ストラテジックC",
    "カナメ": "カナメC", "インダス": "インダスC",
    "Charon": "Charon", "Ｃｈａｒｏｎ": "Charon",
    "Ｆａｒａｌｌｏｎ": "Farallon", "Farallon": "Farallon",
    "ヴァレックス": "ヴァレックス", "シンフォニー": "シンフォニー",
    "Ｂｅ Ｂｒａｖｅ": "Be Brave", "Be Brave": "Be Brave",
    "ｆｕｎｄｎｏｔｅ": "fundnote", "fundnote": "fundnote",
    "ダルトン": "ダルトン", "ＵＧＳ": "UGS", "ＬＩＭ": "LIM",
    "ＧＬＯＢＡＬ": "Global Mgmt P", "ＢＲＯＯＫＬＡＮＤＳ": "Brooklands",
    "オアシス": "Oasis", "Ｏａｓｉｓ": "Oasis", "Oasis": "Oasis",
}

TIER_META = {
    "1": ("最優先", "保有10%以上×(否決/+4pt買い増し/継続)"),
    "2": ("要注目", "保有5%以上×(否決/+2pt買い増し/継続)"),
    "3": ("ウォッチ", "初期・大口だが動意待ち"),
}


def _esc(s) -> str:
    return html.escape(str(s or ""))


def _coname(s: str | None) -> str:
    return (s or "").replace("株式会社", "").replace("　", " ").strip()


def _fund(s: str | None) -> str:
    for k, v in FUND_SHORT.items():
        if k.lower() in (s or "").lower():
            return v
    return _coname(s)[:14]


def _wl_rows(kept: list[dict], tier: str) -> str:
    out = []
    for r in kept:
        if r["tier"] != tier:
            continue
        try:
            dlnum = float(r["delta"]) if r["delta"] is not None else 0.0
        except (TypeError, ValueError):
            dlnum = 0.0
        if dlnum > 0:
            darr = f'<span class="up">▲{_esc(r["delta"])}</span>'
        elif dlnum < 0:
            darr = f'<span class="down">▼{_esc(abs(dlnum))}</span>'
        else:
            darr = f'<span class="flat">{_esc(r["delta"])}</span>'
        rej = '<span class="chip rej">否決</span>' if r["C"] else ""
        seg_cls = "seg-c" if r["seg"] == "継続" else "seg-n"
        seg = f'<span class="chip {seg_cls}">{r["seg"]}</span>'
        out.append(
            f'<tr><td class="code">{_esc(r["code"])}</td>'
            f'<td class="nm">{_esc(_coname(r["name"]))} {seg}</td>'
            f'<td class="fund">{_esc(_fund(r["holder"]))}</td>'
            f'<td class="num">{_esc(r["ratio"])}%</td>'
            f'<td class="num">{darr}</td><td>{rej}</td>'
            f'<td class="th">{_esc(r["thesis"])}</td></tr>'
        )
    return "\n".join(out)


def generate_dashboard(out_path: Path | None = None) -> Path:
    derived = json.loads(
        (DERIVED_DIR / "diff_watchlist.json").read_text(encoding="utf-8"))
    kept = derived["watchlist"]
    excluded = derived["excluded"]
    counts = derived["counts"]
    grads = load_graduations()
    caveats = derived.get("caveats", [])
    today = date.today().isoformat()

    wl_sections = ""
    for t in "123":
        label, cond = TIER_META[t]
        wl_sections += f"""<div class="tierhead"><span class="tbadge b{t}">Tier {t}</span> {label} <span class="tsub">— {cond} ／ {counts['t' + t]}社</span></div>
<div class="tblwrap"><table class="wl">
<thead><tr><th>コード</th><th>企業</th><th>アクティビスト</th><th>保有</th><th>推移Δ</th><th>否決</th><th>メモ</th></tr></thead>
<tbody>{_wl_rows(kept, t)}</tbody></table></div>"""

    grad_rows = "\n".join(
        f'<tr><td class="code">{_esc(g["code"])}</td>'
        f'<td class="nm">{_esc(_coname(g["name"]))}</td>'
        f'<td><span class="gchip {g["type_class"]}">{_esc(g["type"])}</span></td>'
        f'<td class="th">{_esc(g["detail"])}</td></tr>'
        for g in grads["graduations"]
    )
    exceptions = "".join(
        f'<div class="note"><b>例外:</b> {_esc(e["name"])}({_esc(e["code"])}) — {_esc(e["detail"])}</div>'
        for e in grads.get("exceptions", [])
    )
    caveat_html = "<br>\n".join(f"・{_esc(c)}" for c in caveats)
    exl = "、".join(
        f'{_esc(r["code"])} {_esc(_coname(r["name"]))}({_esc(r["exclude_reason"])})'
        for r in excluded
    )

    doc = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>株主総会 アクティビスト実戦リスト 2026</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#1a1d21;--sub:#5b636c;--line:#e5e8ec;--accent:#2f6df6;--up:#0a8f5b;--down:#d1435b;--flat:#9aa2ab;--rej:#b4531a;--A:#2f6df6;--B:#6b52d6;--C:#7a828c;--pv:#8a6d3b;--win:#0a8f5b;--exit:#b4531a;--settle:#5b636c}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1216;--card:#171b21;--ink:#e8ebef;--sub:#9aa2ab;--line:#262c34;--accent:#5b8cff;--up:#3ecf8e;--down:#ff6b81;--flat:#6b737c;--rej:#e08a4e;--A:#5b8cff;--B:#9d86ff;--C:#8892a0;--pv:#c9a66b;--win:#3ecf8e;--exit:#e08a4e;--settle:#9aa2ab}}}}
:root[data-theme=dark]{{--bg:#0f1216;--card:#171b21;--ink:#e8ebef;--sub:#9aa2ab;--line:#262c34;--accent:#5b8cff;--up:#3ecf8e;--down:#ff6b81;--flat:#6b737c;--rej:#e08a4e;--A:#5b8cff;--B:#9d86ff;--C:#8892a0;--pv:#c9a66b;--win:#3ecf8e;--exit:#e08a4e;--settle:#9aa2ab}}
:root[data-theme=light]{{--bg:#f6f7f9;--card:#fff;--ink:#1a1d21;--sub:#5b636c;--line:#e5e8ec;--accent:#2f6df6;--up:#0a8f5b;--down:#d1435b;--flat:#9aa2ab;--rej:#b4531a;--A:#2f6df6;--B:#6b52d6;--C:#7a828c;--pv:#8a6d3b;--win:#0a8f5b;--exit:#b4531a;--settle:#5b636c}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif;line-height:1.5;font-size:15px}}
.wrap{{max-width:1080px;margin:0 auto;padding:28px 18px 60px}}
h1{{font-size:24px;margin:0 0 4px}}.lede{{color:var(--sub);margin:0 0 22px;font-size:14px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:26px}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}}
.kpi .v{{font-size:26px;font-weight:700;letter-spacing:-.5px}}.kpi .l{{color:var(--sub);font-size:12px;margin-top:2px}}
.kpi .v.a{{color:var(--A)}}.kpi .v.n{{color:var(--up)}}.kpi .v.g{{color:var(--pv)}}
h2{{font-size:17px;margin:30px 0 10px;padding-bottom:6px;border-bottom:2px solid var(--line)}}
.tierhead{{margin:18px 0 8px;font-weight:600;font-size:14px}}.tsub{{color:var(--sub);font-weight:400;font-size:12.5px}}
.tbadge{{display:inline-block;color:#fff;border-radius:6px;padding:1px 9px;font-size:12px;font-weight:700;margin-right:4px}}
.b1{{background:var(--A)}}.b2{{background:var(--B)}}.b3{{background:var(--C)}}
.tblwrap{{overflow-x:auto;border:1px solid var(--line);border-radius:12px;background:var(--card)}}
table{{width:100%;border-collapse:collapse;font-size:13.5px;min-width:640px}}
th{{text-align:left;color:var(--sub);font-weight:600;font-size:12px;padding:9px 12px;border-bottom:1px solid var(--line);white-space:nowrap}}
td{{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:top}}
tr:last-child td{{border-bottom:none}}
.code{{font-variant-numeric:tabular-nums;color:var(--sub);font-weight:600;white-space:nowrap}}
.nm{{font-weight:600;min-width:150px}}.fund{{color:var(--accent);font-weight:600;white-space:nowrap}}
.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
.up{{color:var(--up);font-weight:600}}.down{{color:var(--down);font-weight:600}}.flat{{color:var(--flat)}}
.th{{color:var(--sub);font-size:12.5px}}
.chip{{display:inline-block;border-radius:5px;padding:0 7px;font-size:11px;font-weight:600;margin-left:4px;vertical-align:1px}}
.chip.rej{{background:color-mix(in srgb,var(--rej) 18%,transparent);color:var(--rej)}}
.seg-c{{background:color-mix(in srgb,var(--B) 16%,transparent);color:var(--B)}}
.seg-n{{background:color-mix(in srgb,var(--up) 16%,transparent);color:var(--up)}}
.gchip{{display:inline-block;color:#fff;border-radius:6px;padding:1px 8px;font-size:11.5px;font-weight:600;white-space:nowrap}}
.gchip.pv{{background:var(--pv)}}.gchip.win{{background:var(--win)}}.gchip.exit{{background:var(--exit)}}.gchip.settle{{background:var(--settle)}}
.note{{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:8px;padding:12px 15px;font-size:13px;color:var(--sub);margin:14px 0}}
.note b{{color:var(--ink)}}
.foot{{color:var(--sub);font-size:12px;margin-top:30px;border-top:1px solid var(--line);padding-top:14px}}
.toggle{{float:right;font-size:12px;color:var(--sub);cursor:pointer;border:1px solid var(--line);border-radius:6px;padding:3px 10px;background:var(--card)}}
</style></head><body><div class="wrap">
<button class="toggle" onclick="var r=document.documentElement;r.dataset.theme=(r.dataset.theme==='dark'?'light':'dark')">◐ テーマ</button>
<h1>株主総会 アクティビスト実戦リスト 2026</h1>
<p class="lede">2025→2026のトリガー差分から、<b>現在も上場していてアクティビストが撤退していない</b>銘柄に厳選。非公開化・撤退・パッシブ・極小保有は除外。データ生成 {today}。</p>
<div class="kpis">
<div class="kpi"><div class="v a">{counts['kept']}</div><div class="l">実戦リスト採用社</div></div>
<div class="kpi"><div class="v">{counts['t1']}/{counts['t2']}/{counts['t3']}</div><div class="l">Tier 1 / 2 / 3</div></div>
<div class="kpi"><div class="v n">{counts['new']}</div><div class="l">新規トリガー(全体)</div></div>
<div class="kpi"><div class="v g">{len(grads['graduations'])}</div><div class="l">去年の激戦→決着</div></div>
</div>

<h2>① 実戦ウォッチリスト（現在も張れる {counts['kept']}社）</h2>
<div class="note">Tierは <b>保有比率 × 買い増し × 否決/継続の強度</b> で機械分類。<span class="chip seg-c">継続</span>=昨年から継続 <span class="chip seg-n">新規</span>=2026初トリガー。Δは2024→2026の保有推移。</div>
{wl_sections}

<h2>② 去年の激戦は「決着」した（卒業＝リストから外れた理由）</h2>
<div class="note">去年のTier1級は沈静化ではなく<b>資本イベントで決着</b>。<span class="gchip pv">非公開化系</span>は投資対象から消滅、<span class="gchip win">アクティビスト勝利</span>は既に経営権交代済み。一次情報(EDINET/kessanai/報道)で確認。</div>
<div class="tblwrap"><table><thead><tr><th>コード</th><th>企業</th><th>決着の型</th><th>2026に起きたこと</th></tr></thead><tbody>
{grad_rows}
</tbody></table></div>
{exceptions}

<h2>③ 注意点（機械処理の癖・検証済み）</h2>
<div class="note">{caveat_html}<br>・最終判断は各社の一次情報（臨時報告書・大量保有報告書）で。</div>
<div class="note"><b>除外した{counts['excluded']}社</b>（参考）：{exl}</div>

<div class="foot">出典: EDINET臨時報告書(議決権行使結果)/大量保有報告書、kessanai MCP、報道。ツール: ~/Claude/株主総会議案分析/。関連: diff_2025_2026.md / trigger_analysis_2026.md / watchlist_2026.csv</div>
</div></body></html>"""

    out_path = out_path or OUTPUT_DIR / "dashboard_2026.html"
    out_path.write_text(doc, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    p = generate_dashboard()
    print("生成:", p)
