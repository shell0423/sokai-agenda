"""実戦ウォッチリスト＋卒業(決着)の自己完結ローカルHTMLダッシュボード生成。

derived/diff_watchlist.json と data/graduations_2026.json を読み、
output/dashboard_2026.html を書き出す。外部リソース参照なし・テーマ対応。
"""
from __future__ import annotations

import html
import json
from datetime import date
from pathlib import Path

from src.analysis_diff import DERIVED_DIR, OUTPUT_DIR, PROJECT_ROOT
from src.app_data import load_graduations, load_trigger_table
from src.detail_data import build_details

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

# 行クリック→銘柄詳細モーダルのスクリプト。
# f-string の外に置いてブレースの二重化を避ける（{MODAL_JS} で差し込む）。
MODAL_JS = r"""
var SERIES_COLORS = ["#2f6df6", "#0a8f5b", "#d1435b", "#b05a00", "#6b52d6", "#00918f"];
var _chart = null;

function esc(s) {
  return String(s === null || s === undefined ? "" : s)
    .replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
}
function num(v, d) {
  if (v === null || v === undefined || v === "") return "—";
  return Number(v).toLocaleString("ja-JP", {
    minimumFractionDigits: d === undefined ? 2 : d,
    maximumFractionDigits: d === undefined ? 2 : d,
  });
}

function propTable(rows, year) {
  if (!rows || !rows.length) {
    return '<div class="reason">' + year + " の議案データなし（未提出／キャッシュ未取得）</div>";
  }
  var h = '<div class="tblwrap"><table><thead><tr><th>No</th><th>議案</th>'
        + "<th>区分</th><th>賛成率</th><th></th></tr></thead><tbody>";
  rows.forEach(function (p) {
    var cand = p["候補者"]
      ? '<br><span style="color:var(--sub);font-size:11px">' + esc(p["候補者"]) + "</span>"
      : "";
    h += "<tr><td>" + esc(p["No"]) + "</td>"
       + '<td class="nm" style="min-width:0">' + esc(p["議案"]) + cand + "</td>"
       + "<td>" + esc(p["区分"]) + "</td>"
       + '<td class="num">' + (p["賛成率%"] === null || p["賛成率%"] === undefined
            ? "—" : num(p["賛成率%"]) + "%") + "</td>"
       + "<td>" + (p["否決"] ? '<span class="chip rej">否決</span>' : "") + "</td></tr>";
  });
  return h + "</tbody></table></div>";
}

function holderTable(holders) {
  if (!holders || !holders.length) {
    return '<div class="reason">大量保有報告書なし（5%超の大口保有者がいない）</div>';
  }
  var h = '<div class="tblwrap"><table><thead><tr><th>保有者</th><th>最新</th>'
        + "<th>Δpp</th><th>報告</th><th>保有目的</th></tr></thead><tbody>";
  holders.forEach(function (x) {
    h += "<tr><td " + (x.a ? 'class="fund"' : "") + ">" + esc(x.h) + "</td>"
       + '<td class="num">' + (x.r === null ? "—" : num(x.r) + "%") + "</td>"
       + '<td class="num">' + (x.d === null ? "—" : (x.d > 0 ? "▲" : "") + num(x.d)) + "</td>"
       + '<td class="num">' + esc(x.n) + "</td>"
       + '<td class="th">' + esc(x.pu) + "</td></tr>";
  });
  return h + "</tbody></table></div>";
}

function drawChart(holders) {
  var box = document.getElementById("chartbox");
  if (!box || typeof LightweightCharts === "undefined") return;
  var series = (holders || []).filter(function (x) { return x.pts && x.pts.length >= 2; })
                              .slice(0, 6);
  if (!series.length) {
    box.innerHTML = '<div class="reason">推移を描ける保有者がいません（報告書が1件のみ）</div>';
    return;
  }
  var dark = getComputedStyle(document.body).backgroundColor === "rgb(15, 18, 22)"
          || document.documentElement.dataset.theme === "dark"
          || (window.matchMedia("(prefers-color-scheme:dark)").matches
              && document.documentElement.dataset.theme !== "light");
  var ink = dark ? "#e8ebef" : "#1a1d21";
  var line = dark ? "#262c34" : "#e5e8ec";
  // 元データは月までしか無く（trigger_holdings.csv が "24/03" 形式）、日は
  // 同一月内の並び順を保つための連番。そのため軸・クロスヘアには年月だけを出し、
  // 存在しない「日」を表示しない。
  // time は BusinessDay({year,month,day}) / UTCTimestamp(number) / "YYYY-MM-DD" の
  // どれで渡ってくるか実装依存なので全部受ける（型を決め打つとラベルが空になる）。
  var ym = function (t) {
    if (t && typeof t === "object" && t.year) {
      return String(t.year).slice(2) + "/" + ("0" + t.month).slice(-2);
    }
    if (typeof t === "number") {
      var d = new Date(t * 1000);
      return String(d.getUTCFullYear()).slice(2) + "/"
           + ("0" + (d.getUTCMonth() + 1)).slice(-2);
    }
    if (typeof t === "string") return t.slice(2, 7).replace("-", "/");
    return "";
  };
  _chart = LightweightCharts.createChart(box, {
    width: box.clientWidth,
    height: 230,
    layout: { background: { color: "transparent" }, textColor: ink, fontSize: 11 },
    grid: { vertLines: { color: line }, horzLines: { color: line } },
    rightPriceScale: { borderColor: line },
    timeScale: {
      borderColor: line, fixLeftEdge: true, fixRightEdge: true,
      tickMarkFormatter: function (t) { return ym(t); },
    },
    localization: { timeFormatter: function (t) { return ym(t); } },
    crosshair: { mode: 0 },
    handleScale: false,
    handleScroll: false,
  });
  var legend = [];
  series.forEach(function (x, i) {
    var color = SERIES_COLORS[i % SERIES_COLORS.length];
    var s = _chart.addLineSeries({
      color: color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
      priceFormat: { type: "custom", formatter: function (p) { return p.toFixed(2) + "%"; } },
    });
    s.setData(x.pts.map(function (p) { return { time: p.t, value: p.v }; }));
    legend.push('<span><i style="background:' + color + '"></i>' + esc(x.h.slice(0, 22)) + "</span>");
  });
  document.getElementById("legend").innerHTML = legend.join("");
  _chart.timeScale().fitContent();
}

function openDetail(code) {
  var d = DETAILS[code];
  if (!d) return;
  var f = d.fund || {};
  var links = ['<a href="https://kabutan.jp/stock/?code=' + code
      + '" target="_blank" rel="noopener">📈 株探</a>'];
  if (d.edinet) {
    links.push('<a href="https://irbank.net/' + d.edinet
      + '/share" target="_blank" rel="noopener">🏦 IRBANK 大量保有</a>');
    if (d.doc26) {
      links.push('<a href="https://irbank.net/' + d.edinet + "/ext?f=" + d.doc26
        + '" target="_blank" rel="noopener">📄 2026臨時報告書</a>');
    }
    if (d.doc25) {
      links.push('<a href="https://irbank.net/' + d.edinet + "/ext?f=" + d.doc25
        + '" target="_blank" rel="noopener">📄 2025臨時報告書</a>');
    }
  }
  var kpi = [
    ["株価(円)", f.price === undefined || f.price === null ? "—" : num(f.price, 0)],
    ["PER(倍)", f.per === undefined || f.per === null ? "—" : num(f.per, 1) + (f.per_outlier ? "⚠" : "")],
    ["PBR(倍)", f.pbr === undefined || f.pbr === null ? "—" : num(f.pbr, 2) + (f.pbr_outlier ? "⚠" : "")],
    ["配当利回り", f.yield_pct === undefined || f.yield_pct === null ? "—" : num(f.yield_pct, 2) + "%"],
    ["ROE", f.roe_pct === undefined || f.roe_pct === null ? "—" : num(f.roe_pct, 1) + "%"],
  ].map(function (x) { return "<div><b>" + x[1] + "</b><span>" + x[0] + "</span></div>"; }).join("");

  var reasons = [];
  if (d.trig.A) reasons.push("<b>A 賛成率低下</b>: " + esc(d.trig.A));
  if (d.trig.B) reasons.push("<b>B 新規株主提案</b>: " + esc(d.trig.B));
  if (d.trig.C) reasons.push("<b>C 会社提案否決</b>: " + esc(d.trig.C));

  var html = '<button class="mclose" onclick="closeDetail()">✕ 閉じる</button>'
    + "<h3>" + esc(code) + " " + esc((d.name || "").replace("株式会社", "")) + "</h3>"
    + '<div class="msub">'
      + (d.tier ? "Tier " + esc(d.tier) + " ／ " : "") + esc(d.seg)
      + " ／ トリガー 2025:" + esc(d.trig.prev) + " → 2026:" + esc(d.trig.cur)
      + (d.sub26 ? " ／ 総会 提出日 " + esc(d.sub26) : "")
    + "</div>"
    + '<div class="mlinks">' + links.join("") + "</div>"
    + '<div class="mkpi">' + kpi + "</div>"
    + (d.thesis ? '<div class="note" style="margin:12px 0 0">💡 ' + esc(d.thesis) + "</div>" : "")
    + (d.fix ? '<div class="note" style="margin:10px 0 0">⚠️ 補正: ' + esc(d.fix) + "</div>" : "")
    + (reasons.length ? "<h4>トリガー該当理由</h4><div class=\"reason\">" + reasons.join("<br>") + "</div>" : "")
    + "<h4>大量保有の推移（2024→直近・上位6名）</h4>"
    + '<div class="legend" id="legend"></div><div class="chartbox" id="chartbox"></div>'
    + holderTable(d.holders)
    + "<h4>議案別賛成率</h4>"
    + '<div class="mgrid"><div><div class="tsub" style="margin-bottom:5px">2025年'
      + (d.sub25 ? "（" + esc(d.sub25) + "）" : "") + "</div>" + propTable(d.p25, "2025年") + "</div>"
    + '<div><div class="tsub" style="margin-bottom:5px">2026年'
      + (d.sub26 ? "（" + esc(d.sub26) + "）" : "") + "</div>" + propTable(d.p26, "2026年") + "</div></div>";

  document.getElementById("md").innerHTML = html;
  document.getElementById("ov").classList.add("on");
  document.body.style.overflow = "hidden";
  drawChart(d.holders);
}

function closeDetail() {
  document.getElementById("ov").classList.remove("on");
  document.body.style.overflow = "";
  if (_chart) { _chart.remove(); _chart = null; }
}

document.querySelectorAll("tr.rowlink").forEach(function (tr) {
  tr.onclick = function () { openDetail(tr.dataset.code); };
});
document.getElementById("ov").onclick = function (e) {
  if (e.target.id === "ov") closeDetail();
};
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape") closeDetail();
});

// ---- ページ切替（実戦リスト / 全トリガー / 卒業・決着 / 注意点）----
document.querySelectorAll(".nav button").forEach(function (b) {
  b.onclick = function () {
    document.querySelectorAll(".nav button").forEach(function (x) { x.classList.remove("on"); });
    document.querySelectorAll(".page").forEach(function (x) { x.classList.remove("on"); });
    b.classList.add("on");
    document.getElementById("page-" + b.dataset.page).classList.add("on");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
});

// ---- チップ（同じ .tabs の中だけ排他にする。Tier用とA/B/C用が別々にあるため）----
function chipGroup(sel, apply) {
  var chips = document.querySelectorAll(sel);
  chips.forEach(function (b) {
    b.onclick = function () {
      chips.forEach(function (x) { x.classList.remove("on"); });
      b.classList.add("on");
      apply();
    };
  });
}

// Tier絞り込み（実戦リスト）
chipGroup("#page-wl .tab", function () {
  var t = document.querySelector("#page-wl .tab.on").dataset.tier;
  document.querySelectorAll(".tierblock").forEach(function (s) {
    s.style.display = (t === "all" || s.dataset.tier === t) ? "" : "none";
  });
});

// A/B/C絞り込み ＋ コード/社名検索（全トリガー）
function filterTriggers() {
  var chip = document.querySelector("#page-trig .tab.on");
  var cond = chip ? chip.dataset.cond : "all";
  var qbox = document.getElementById("q");
  var q = qbox ? qbox.value.trim().toLowerCase() : "";
  var shown = 0;
  document.querySelectorAll("#trigbody tr").forEach(function (tr) {
    var okCond = cond === "all" || tr.dataset[cond] === "1";
    var okQ = !q || (tr.dataset.q || "").toLowerCase().indexOf(q) >= 0;
    var show = okCond && okQ;
    tr.style.display = show ? "" : "none";
    if (show) shown++;
  });
  var out = document.getElementById("trigcount");
  if (out) out.textContent = shown + "社を表示" + (cond === "all" && !q ? "" : "（絞り込み中）");
}
chipGroup("#page-trig .tab", filterTriggers);
if (document.getElementById("q")) {
  document.getElementById("q").oninput = filterTriggers;
}
filterTriggers();
"""


def _esc(s) -> str:
    return html.escape(str(s or ""))


def _coname(s: str | None) -> str:
    return (s or "").replace("株式会社", "").replace("　", " ").strip()


def _fund(s: str | None) -> str:
    for k, v in FUND_SHORT.items():
        if k.lower() in (s or "").lower():
            return v
    return _coname(s)[:14]


def _kabutan(code: str, name: str) -> str:
    """銘柄名を株探の銘柄ページへのリンクにする(某哲也サイトと同じ導線)。

    行クリック(詳細モーダル)と競合しないよう stopPropagation する。
    """
    return (f'<a class="klink" href="https://kabutan.jp/stock/?code={_esc(code)}" '
            f'target="_blank" rel="noopener" onclick="event.stopPropagation()" '
            f'title="株探で{_esc(name)}を開く">{_esc(name)}</a>')


def _num_cell(v, unit: str = "", digits: int = 2) -> str:
    if v is None or v == "":
        return '<td class="num dim">—</td>'
    try:
        return f'<td class="num">{float(v):,.{digits}f}{unit}</td>'
    except (TypeError, ValueError):
        return f'<td class="num">{_esc(v)}</td>'


def _wl_rows(kept: list[dict], tier: str) -> str:
    out = []
    for r in kept:
        if r["tier"] != tier:
            continue
        f = r.get("fund") or {}
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
            f'<tr class="rowlink" data-code="{_esc(r["code"])}" '
            f'title="クリックで銘柄詳細（議案別賛成率・大量保有の推移）">'
            f'<td class="code">{_esc(r["code"])}</td>'
            f'<td class="nm">{_kabutan(r["code"], _coname(r["name"]))} {seg}</td>'
            f'<td class="fund">{_esc(_fund(r["holder"]))}</td>'
            f'<td class="num">{_esc(r["ratio"])}%</td>'
            f'<td class="num">{darr}</td><td>{rej}</td>'
            + _num_cell(f.get("price"), "", 1)
            + _num_cell(f.get("per"))
            + _num_cell(f.get("pbr"))
            + f'<td class="th">{_esc(r["thesis"])}</td></tr>'
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
    fund_asof = derived.get("fundamentals_asof") or ""

    # 行クリックで開く銘柄詳細（議案別賛成率・大量保有の推移・トリガー理由）。
    # 対象は 2026 と 2025 のトリガー該当社すべて（実戦リスト・除外・卒業を含む）。
    # 抽出後は 491社で 965KB・gzip後 157KB なので全部入れてよい
    # （総会キャッシュ原本13MBを抱えるわけではない）。
    trig_rows = load_trigger_table("2526")
    grad_codes = sorted(derived.get("grad_names", {}).keys())
    detail_codes = list(dict.fromkeys(
        [r["code"] for r in kept + excluded]
        + [r["証券コード"] for r in trig_rows]
        + grad_codes
    ))
    details = build_details(detail_codes)
    for r in kept + excluded:
        d = details.get(r["code"])
        if d is not None:
            d["name"] = r["name"]
            d["seg"] = r.get("seg", "")
            d["tier"] = r.get("tier", "")
            d["fund"] = r.get("fund")
    details_json = json.dumps(details, ensure_ascii=False, separators=(",", ":"))

    # TradingView lightweight-charts を HTML へインライン（外部参照ゼロを保つ）。
    chart_lib = (PROJECT_ROOT / "assets"
                 / "lightweight-charts.standalone.production.js")
    chart_js = chart_lib.read_text(encoding="utf-8") if chart_lib.exists() else ""
    if not chart_js:
        print(f"⚠️  {chart_lib} が無いためチャートなしで生成します")

    # Tierごとのブロック。data-tier でJSのフィルタ対象にする（topix-review と同方式）。
    wl_sections = ""
    for t in "123":
        label, cond = TIER_META[t]
        wl_sections += f"""<section class="tierblock" data-tier="{t}">
<div class="tierhead"><span class="tbadge b{t}">Tier {t}</span> {label} <span class="tsub">— {cond} ／ {counts['t' + t]}社</span></div>
<div class="tblwrap"><table class="wl">
<thead><tr><th>コード</th><th>企業</th><th>アクティビスト</th><th>保有</th><th>推移Δ</th><th>否決</th><th>株価</th><th>PER</th><th>PBR</th><th>メモ</th></tr></thead>
<tbody>{_wl_rows(kept, t)}</tbody></table></div></section>"""

    # 全トリガー表（2026該当の全社）。data-* をJSの絞り込み・検索キーにする。
    trig_html = "\n".join(
        f'<tr class="rowlink" data-code="{_esc(r["証券コード"])}"'
        f' data-a="{1 if r["A:賛成率低下"] else 0}"'
        f' data-b="{1 if r["B:新規株主提案"] else 0}"'
        f' data-c="{1 if r["C:否決"] else 0}"'
        f' data-q="{_esc(r["証券コード"] + " " + _coname(r["企業名"]))}">'
        f'<td class="code">{_esc(r["証券コード"])}</td>'
        f'<td class="nm">{_kabutan(r["証券コード"], _coname(r["企業名"]))}</td>'
        f'<td class="ctr">{"○" if r["A:賛成率低下"] else ""}</td>'
        f'<td class="ctr">{"○" if r["B:新規株主提案"] else ""}</td>'
        f'<td class="ctr">{"○" if r["C:否決"] else ""}</td>'
        f'<td class="th">{_esc(r["補正"])}</td></tr>'
        for r in trig_rows
    )

    tier_tabs = (
        f'<button class="tab on" data-tier="all">全て {counts["kept"]}社</button>'
        + "".join(
            f'<button class="tab" data-tier="{t}">Tier {t} {counts["t" + t]}社</button>'
            for t in "123"
        )
    )

    grad_rows = "\n".join(
        f'<tr class="rowlink" data-code="{_esc(g["code"])}" title="クリックで銘柄詳細">'
        f'<td class="code">{_esc(g["code"])}</td>'
        f'<td class="nm">{_kabutan(g["code"], _coname(g["name"]))}</td>'
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
.klink{{color:var(--ink);text-decoration:none;border-bottom:1px dotted var(--accent)}}
.klink:hover{{color:var(--accent)}}.num.dim{{color:var(--flat)}}
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
/* ページ切替タブ（topix-review と同方式: .nav button[data-page] → .page.on） */
.nav{{display:flex;gap:8px;flex-wrap:wrap;margin:22px 0 0;border-bottom:2px solid var(--line);padding-bottom:10px}}
.nav button{{border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:8px;padding:7px 14px;font-size:13.5px;font-weight:600;cursor:pointer;font-family:inherit}}
.nav button:hover{{border-color:var(--accent)}}
.nav button.on{{background:var(--accent);color:#fff;border-color:var(--accent)}}
.page{{display:none}}.page.on{{display:block}}
/* Tier絞り込みチップ */
.tabs{{display:flex;gap:6px;flex-wrap:wrap;margin:16px 0 2px}}
.tab{{border:1px solid var(--line);background:var(--card);color:var(--sub);border-radius:6px;padding:4px 12px;font-size:12.5px;cursor:pointer;font-family:inherit}}
.tab:hover{{border-color:var(--accent)}}
.tab.on{{background:var(--accent);color:#fff;border-color:var(--accent);font-weight:600}}
/* 行クリック → 銘柄詳細モーダル */
tr.rowlink{{cursor:pointer}}
tr.rowlink:hover td{{background:color-mix(in srgb,var(--accent) 7%,transparent)}}
.overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:50;padding:24px 14px;overflow-y:auto}}
.overlay.on{{display:block}}
.modal{{background:var(--card);border:1px solid var(--line);border-radius:14px;max-width:880px;margin:0 auto;padding:22px 24px 26px;box-shadow:0 12px 44px rgba(0,0,0,.3)}}
.modal h3{{margin:0 0 2px;font-size:19px}}
.modal .msub{{color:var(--sub);font-size:12.5px;margin-bottom:12px}}
.mclose{{float:right;border:1px solid var(--line);background:var(--bg);color:var(--sub);border-radius:6px;padding:3px 11px;font-size:13px;cursor:pointer;font-family:inherit}}
.mclose:hover{{border-color:var(--accent);color:var(--accent)}}
.mlinks a{{color:var(--accent);text-decoration:none;font-size:12.5px;margin-right:12px;white-space:nowrap}}
.mlinks a:hover{{text-decoration:underline}}
.mkpi{{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0 4px}}
.mkpi div{{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:7px 13px;min-width:82px}}
.mkpi b{{display:block;font-size:17px;font-variant-numeric:tabular-nums}}
.mkpi span{{color:var(--sub);font-size:11px}}
.modal h4{{font-size:13.5px;margin:20px 0 7px;color:var(--sub);border-bottom:1px solid var(--line);padding-bottom:5px}}
.chartbox{{height:230px;margin:6px 0 4px}}
.legend{{display:flex;gap:12px;flex-wrap:wrap;font-size:11.5px;color:var(--sub);margin-bottom:6px}}
.legend i{{display:inline-block;width:10px;height:3px;vertical-align:3px;margin-right:4px}}
.mgrid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
@media(max-width:700px){{.mgrid{{grid-template-columns:1fr}}}}
.modal table{{min-width:0;font-size:12.5px}}
.modal td,.modal th{{padding:6px 9px}}
.reason{{font-size:12.5px;color:var(--sub);line-height:1.7}}
.reason b{{color:var(--ink)}}
.ctr{{text-align:center}}
.search{{width:100%;box-sizing:border-box;margin:10px 0 12px;padding:9px 13px;font-size:14px;font-family:inherit;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:9px}}
.search:focus{{outline:none;border-color:var(--accent)}}
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

<nav class="nav">
<button class="on" data-page="wl">🎯 実戦リスト</button>
<button data-page="trig">📋 全トリガー({len(trig_rows)})</button>
<button data-page="grad">🎓 卒業・決着</button>
<button data-page="note">⚠️ 注意点</button>
</nav>

<div class="page on" id="page-wl">
<h2>実戦ウォッチリスト（現在も張れる {counts['kept']}社）</h2>
<div class="note">Tierは <b>保有比率 × 買い増し × 否決/継続の強度</b> で機械分類。<span class="chip seg-c">継続</span>=昨年から継続 <span class="chip seg-n">新規</span>=2026初トリガー。Δは2024→2026の保有推移。<b>企業名クリックで株探</b>のその銘柄ページを開きます。株価/PER/PBR は warehouse mart_latest{" (" + fund_asof + " 時点)" if fund_asof else ""}。</div>
<div class="tabs">{tier_tabs}</div>
{wl_sections}
</div>

<div class="page" id="page-trig">
<h2>全トリガー {len(trig_rows)}社（2025→2026）</h2>
<div class="note">3条件のどれかに当たった会社の<b>全リスト</b>（アクティビストがいない会社も含む）。<b>行クリックで銘柄詳細</b>、企業名クリックで株探。<br>
<b>A</b>=会社提案の賛成率が10pt以上ダウン ／ <b>B</b>=前年になかった株主提案が出た ／ <b>C</b>=会社提案が否決（賛成率50%未満）。和集合なので内訳の合計＝社数にはなりません。</div>
<div class="tabs">
<button class="tab on" data-cond="all">全て {len(trig_rows)}社</button>
<button class="tab" data-cond="a">A 賛成率低下</button>
<button class="tab" data-cond="b">B 新規株主提案</button>
<button class="tab" data-cond="c">C 否決</button>
</div>
<input class="search" id="q" type="search" placeholder="🔍 コード または 会社名 で絞り込み（例: 9627 / アイン）" autocomplete="off">
<div class="tblwrap"><table><thead><tr><th>コード</th><th>企業</th><th class="ctr">A</th><th class="ctr">B</th><th class="ctr">C</th><th>補正</th></tr></thead>
<tbody id="trigbody">{trig_html}</tbody></table></div>
<div class="reason" id="trigcount"></div>
</div>

<div class="page" id="page-grad">
<h2>去年の激戦は「決着」した（卒業＝リストから外れた理由）</h2>
<div class="note">去年のTier1級は沈静化ではなく<b>資本イベントで決着</b>。<span class="gchip pv">非公開化系</span>は投資対象から消滅、<span class="gchip win">アクティビスト勝利</span>は既に経営権交代済み。一次情報(EDINET/kessanai/報道)で確認。</div>
<div class="tblwrap"><table><thead><tr><th>コード</th><th>企業</th><th>決着の型</th><th>2026に起きたこと</th></tr></thead><tbody>
{grad_rows}
</tbody></table></div>
{exceptions}
</div>

<div class="page" id="page-note">
<h2>注意点（機械処理の癖・検証済み）</h2>
<div class="note">{caveat_html}<br>・最終判断は各社の一次情報（臨時報告書・大量保有報告書）で。</div>
<div class="note"><b>実戦リストから除外した{counts['excluded']}社</b>（参考）：{exl}</div>
</div>

<div class="foot">出典: EDINET臨時報告書(議決権行使結果)・大量保有報告書／株価・PER・PBR は warehouse(J-Quants/EDINET)／kessanai／報道。<br>
※本ページは個人的な記録・学習目的の参考情報であり、<b>投資勧誘・投資助言ではありません</b>。機械抽出のため誤検出を含みます。最終判断は必ず一次情報（臨時報告書・大量保有報告書の原本）でご確認ください。</div>
</div>
<div class="overlay" id="ov"><div class="modal" id="md"></div></div>
<script>{chart_js}</script>
<script>
var DETAILS = {details_json};
</script>
<script>
{MODAL_JS}
</script>
</body></html>"""

    out_path = out_path or OUTPUT_DIR / "dashboard_2026.html"
    out_path.write_text(doc, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    p = generate_dashboard()
    print("生成:", p)
