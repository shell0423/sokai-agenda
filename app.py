"""株主総会議案分析 — アクティビスト実戦リスト Streamlitアプリ。

起動: .venv/bin/streamlit run app.py
機能:
  - 実戦ウォッチリスト / 全トリガー / 卒業・決着 の閲覧、銘柄クリックで深掘り
    (議案別賛成率 2025 vs 2026・大量保有タイムライン・トリガー該当理由)
  - サイドバーのボタンで再生成・EDINET再スキャン・充足チェックを実行
"""
from __future__ import annotations

import os

# pyarrow 25.0.0 の mimalloc が rerun毎の新スレッドで SIGSEGV する実バグへの対策。
# pyarrow が import される前(=pandas/streamlitより前)に設定する必要がある。
# 検証済み: これ無しだと「行クリック→任意のrerun」でサーバプロセスごと落ちる。
os.environ.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")

from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from src import jobs, wh_readiness
from src.analysis_diff import OUTPUT_DIR
from src.app_data import (
    company_detail,
    load_derived,
    load_graduations,
    load_trigger_table,
)

st.set_page_config(
    page_title="株主総会 アクティビスト実戦リスト",
    page_icon="📊",
    layout="wide",
)


# ------------------------------------------------------------------
# 実行環境判定: Streamlit Community Cloud か、ローカル (Mac) か
# ------------------------------------------------------------------
# Cloud では warehouse (~/Claude/warehouse) と bash スクリプト (full_update.sh)
# が使えないため、機能を制限する必要がある。判定は多重チェック(どれか1つが真ならCloud):
#   ① 明示フラグ STREAMLIT_RUNTIME_ENV=cloud
#   ② HOSTNAME に "streamlit" を含む(Cloud ランナーの慣習)
#   ③ warehouse/client.py が存在しない
def _is_cloud() -> bool:
    if os.environ.get("STREAMLIT_RUNTIME_ENV", "").lower() == "cloud":
        return True
    if "streamlit" in os.environ.get("HOSTNAME", "").lower():
        return True
    if not Path(os.path.expanduser("~/Claude/warehouse/client.py")).exists():
        return True
    return False


IS_CLOUD = _is_cloud()

# Cloud では EDINET_API_KEY を st.secrets 経由で受け取り、環境変数に注入する
# （src/jobs.py など下流モジュールは os.getenv("EDINET_API_KEY") を使うため）。
if IS_CLOUD:
    try:
        _cloud_edinet_key = st.secrets.get("EDINET_API_KEY", "")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        _cloud_edinet_key = ""
    if _cloud_edinet_key and not os.environ.get("EDINET_API_KEY"):
        os.environ["EDINET_API_KEY"] = _cloud_edinet_key
    _cloud_warehouse = ""
    try:
        _cloud_warehouse = st.secrets.get("WAREHOUSE_DIR", "")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    if _cloud_warehouse and not os.environ.get("WAREHOUSE_DIR"):
        os.environ["WAREHOUSE_DIR"] = _cloud_warehouse


TIER_LABEL = {"1": "🟦 Tier1 最優先", "2": "🟪 Tier2 要注目", "3": "⬜ Tier3 ウォッチ"}

# Tierの正確な定義(src/analysis_diff.py の _tier / 除外ロジックと一致させる)。
# 使い方タブと実戦リストタブの両方でこの文言を使う。
TIER_HELP = """
**Tier =「今どれだけ張れそうか」の3段階。** 保有量の多さだけでなく、
**否決・買い増し・継続といった「動き」があるか**で決まります。

> ※ **トリガー条件（A / B / C）とは別物**です。混同しないよう、
> 「引っかかった条件」はアルファベット **A・B・C**、
> 「リストの優先度」は数字 **Tier 1・2・3** と使い分けています。

まず前提として、実戦リストに載るのは
**著名アクティビストが筆頭株主で、保有3%以上・撤退方向でない**銘柄だけです
（パッシブ/インデックス運用、バリュー縮小中、保有を減らしている先は除外）。その上で:

- 🟦 **Tier 1（最優先）** … **保有10%以上** かつ 次のどれか1つ以上に該当
  ① 会社提案が否決された　② 2024→2026で **+4pt以上の買い増し**　③ **継続**（去年もトリガー該当）
- 🟪 **Tier 2（要注目）** … **保有5%以上** かつ 次のどれか　① 否決　② **+2pt以上の買い増し**　③ 継続
- ⬜ **Tier 3（ウォッチ）** … 上の“動き”に届かないもの
  （保有3〜5%、または大口でも横ばい・否決なし・新規で動意が薄い）

💡 **保有量が多いだけでは Tier 1・2 になりません。** 例）日産車体はエフィッシモが29.7%と大口ですが、
横ばい・否決なしのため **Tier 3**。逆に否決や買い増しがあると、保有5〜10%台でも Tier 1・2 に上がります。
"""


# ------------------------------------------------------------------
# ヘルパー
# ------------------------------------------------------------------

def _mtime(path: Path) -> str:
    if not path.exists():
        return "なし"
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%m/%d %H:%M")


def _select_code_from(df: pd.DataFrame, event, code_col: str) -> None:
    rows = (event.selection.rows or []) if event and event.selection else []
    # フィルタ変更後に残留した位置indexが範囲外になることがあるため必ず境界確認
    if rows and 0 <= rows[0] < len(df):
        st.session_state["selected_code"] = str(df.iloc[rows[0]][code_col])


def _fmt(v, unit: str = "", digits: int = 2) -> str:
    """数値を表示用に整形。None は「—」。"""
    if v is None or v == "":
        return "—"
    try:
        return f"{float(v):,.{digits}f}{unit}"
    except (TypeError, ValueError):
        return str(v)


def external_links(d: dict) -> str:
    """株探・IRBANK への外部リンクを markdown で返す。"""
    code = d["code"]
    links = [f"[📈 株探](https://kabutan.jp/stock/?code={code})"]
    if d.get("edinet_code"):
        links.append(
            f"[🏦 IRBANK 大量保有](https://irbank.net/{d['edinet_code']}/share)")
        if d.get("doc_id_2026"):
            links.append(
                f"[📄 2026臨時報告書](https://irbank.net/{d['edinet_code']}"
                f"/ext?f={d['doc_id_2026']})")
        if d.get("doc_id_2025"):
            links.append(
                f"[📄 2025臨時報告書](https://irbank.net/{d['edinet_code']}"
                f"/ext?f={d['doc_id_2025']})")
    return "　".join(links)


def render_fundamentals(d: dict) -> None:
    """株価・PER・PBR・配当利回り・ROE を表示する(倉庫 mart_latest 由来)。"""
    f = d.get("fund")
    if not f:
        st.caption("💹 株価・PER・PBR: データなし"
                   "（倉庫未接続、または配布スナップショットに含まれない銘柄）")
        return
    # metric は列幅が狭いと値が省略される(331.0円 → "331...")。
    # 単位はラベル側に出し、値は桁を詰めて表示する。
    price = f.get("price")
    price_txt = _fmt(price, "", 0 if (price or 0) >= 100 else 1)
    per_mark = "⚠" if f.get("per_outlier") else ""
    pbr_mark = "⚠" if f.get("pbr_outlier") else ""
    c = st.columns(5)
    c[0].metric("株価(円)", price_txt)
    c[1].metric("PER(倍)", _fmt(f.get("per"), "", 1) + per_mark)
    c[2].metric("PBR(倍)", _fmt(f.get("pbr"), "", 2) + pbr_mark)
    c[3].metric("配当利回り", _fmt(f.get("yield_pct"), "%", 2))
    c[4].metric("ROE", _fmt(f.get("roe_pct"), "%", 1))
    bits = [f"📅 {f.get('date') or '—'} 時点"]
    if f.get("fy"):
        bits.append(f"FY{f['fy']}実績")
    if f.get("eps") is not None:
        bits.append(f"EPS {_fmt(f['eps'])}")
    if f.get("bps") is not None:
        bits.append(f"BPS {_fmt(f['bps'])}")
    if f.get("dps") is not None:
        bits.append(f"DPS {_fmt(f['dps'])}")
    warn = " ／ ⚠は倉庫の外れ値フラグ" if (per_mark or pbr_mark) else ""
    st.caption("　".join(bits) + f"（出典: warehouse mart_latest）{warn}")


def render_detail(code: str) -> None:
    d = company_detail(code)
    st.subheader(f"🔍 {code} {d['name'] or '(名称不明)'}")
    st.markdown(external_links(d))
    render_fundamentals(d)

    # トリガープロファイル
    cols = st.columns(4)
    tp, tc = d["trigger_prev"], d["trigger_curr"]

    def prof(t):
        if not t:
            return "—"
        p = "".join(k for k in "ABC" if t[k])
        return p or "該当なし"

    cols[0].metric("2025トリガー(2024→25)", prof(tp))
    cols[1].metric("2026トリガー(2025→26)", prof(tc))
    cols[2].metric("総会 提出日 2025", d["submit_2025"] or "—")
    cols[3].metric("総会 提出日 2026", d["submit_2026"] or "—")

    if d["correction"]:
        st.warning(f"⚠️ 補正: {d['correction']}")
    if d["thesis"]:
        st.info(f"💡 {d['thesis']}")

    if tc:
        details = [
            f"**A(賛成率低下)**: {tc['Ad']}" if tc["A"] else None,
            f"**B(新規株主提案)**: {tc['Bd']}" if tc["B"] else None,
            f"**C(否決)**: {tc['Cd']}" if tc["C"] else None,
        ]
        details = [x for x in details if x]
        if details:
            st.markdown("　".join(details))

    # 議案テーブル 2025 vs 2026
    c1, c2 = st.columns(2)
    for col, year, props in (
        (c1, 2025, d["proposals_2025"]),
        (c2, 2026, d["proposals_2026"]),
    ):
        with col:
            st.markdown(f"##### 議案別賛成率 {year}")
            if props:
                st.dataframe(
                    pd.DataFrame(props), width="stretch", hide_index=True,
                    height=min(38 * len(props) + 40, 420),
                )
            else:
                st.caption("データなし(未提出/キャッシュ未取得)")

    # 大量保有
    st.markdown("##### 大量保有タイムライン (2024→直近)")
    if d["holders"]:
        hdf = pd.DataFrame([
            {
                "保有者": h["holder"],
                "アクティビスト": "○" if h["activist"] else "",
                "最新%": h["ratio"],
                "Δpp": h["delta"],
                "推移": h["trend"],
                "保有目的": (h["purpose"] or "")[:60],
                "報告数": h["n_reports"],
            }
            for h in sorted(d["holders"], key=lambda x: -(x["ratio"] or 0))
        ])
        st.dataframe(hdf, width="stretch", hide_index=True)

        series = {k: v for k, v in d["holder_series"].items() if len(v) >= 2}
        if series:
            frames = []
            for holder, pts in series.items():
                frames.append(pd.DataFrame(
                    {"時点": [p[0] for p in pts],
                     "保有%": [p[1] for p in pts],
                     "保有者": holder}))
            chart_df = (
                pd.concat(frames)
                .pivot_table(index="時点", columns="保有者", values="保有%")
                .sort_index()
            )
            st.line_chart(chart_df)
    else:
        st.caption("大量保有報告書なし(5%超の大口保有者がいない)")


# ------------------------------------------------------------------
# サイドバー: 実行ボタン
# ------------------------------------------------------------------

with st.sidebar:
    st.title("📊 総会×アクティビスト")

    # 常時表示バッジ: 倉庫レディネスの前回結果(押さなくても一目で分かる)
    _wr = st.session_state.get("wh_readiness") or wh_readiness.load_last()
    if _wr and _wr.get("available"):
        _emoji = {"red": "🔴 まだ", "yellow": "🟡 近い", "green": "🟢 寄せてよい"}
        _ga = "✅" if _wr["gates"]["freshness"]["ok"] else "❌"
        _line = (f"倉庫レディネス {_emoji.get(_wr['level'], '?')}"
                 f"（{_wr['date']}確認・A鮮度{_ga}）")
        if _wr["level"] == "green":
            st.success(_line)
        elif _wr["level"] == "yellow":
            st.warning(_line)
        else:
            st.caption("🏭 " + _line + " ／ 下の「判定を実行」で更新")

    st.caption(
        f"2026総会キャッシュ: {_mtime(OUTPUT_DIR / 'cache' / '2026_meetings.json')}\n\n"
        f"大量保有CSV: {_mtime(OUTPUT_DIR / 'trigger_holdings.csv')}\n\n"
        f"実戦リスト: {_mtime(OUTPUT_DIR / 'derived' / 'diff_watchlist.json')}"
    )
    st.divider()

    # ① 高速再生成
    st.markdown("### ⚡ 高速再生成")
    st.caption("キャッシュから トリガー比較→差分→実戦リスト→HTML を再計算(数秒〜1分)")
    if st.button("再生成を実行", type="primary", width="stretch"):
        ok = False
        with st.status("再生成中…", expanded=True) as status:
            try:
                jobs.fast_regen(progress=st.write)
                status.update(label="✅ 再生成完了", state="complete")
                st.cache_data.clear()
                ok = True
            except Exception as e:  # noqa: BLE001
                status.update(label="❌ 失敗", state="error")
                st.error(str(e))
        if ok:
            # 失敗時はrerunしない(エラー表示が消えてしまうため)
            st.rerun()

    st.divider()

    # ② フル更新(EDINET再スキャン)
    st.markdown("### 🔄 フル更新 (EDINET)")
    st.caption("2026総会＋大量保有を再取得→分析まで一括(40分〜2時間)。"
               "アインHD総会(7/30)後などに")
    if IS_CLOUD:
        # Cloud には bash スクリプト・warehouse・長時間ランタイムが無いため、
        # フル更新は「キャッシュからの高速再生成」に縮退させる。
        st.caption("⚠️ Streamlit Cloud では bash スクリプトと warehouse が使えないため、"
                   "フル更新は『キャッシュのみでの高速再生成』に縮退します。"
                   "本格的な EDINET 再スキャンはローカル環境で実行してください。")
        if st.button("Cloud用: 高速再生成のみ実行", width="stretch"):
            ok = False
            with st.status("再生成中…", expanded=True) as status:
                try:
                    jobs.fast_regen(progress=st.write)
                    status.update(label="✅ 再生成完了", state="complete")
                    st.cache_data.clear()
                    ok = True
                except Exception as e:  # noqa: BLE001
                    status.update(label="❌ 失敗", state="error")
                    st.error(str(e))
            if ok:
                st.rerun()
    else:
        fu = jobs.full_update_status()
        if fu["running"]:
            st.info(f"🏃 実行中 (PID {fu['pid']})")
            if st.button("ログを更新", width="stretch"):
                st.rerun()
            if st.button("⛔ 停止", width="stretch"):
                jobs.stop_full_update()
                st.rerun()
            with st.expander("ログ (末尾)", expanded=True):
                st.code(fu["log_tail"] or "(まだ出力なし)", language=None)
        else:
            if fu["failed"]:
                st.error("前回のフル更新はエラー終了しました(ログ参照)")
            elif fu["done"]:
                st.success("前回のフル更新は完了しています")
            ok = st.checkbox("長時間ジョブを了解して実行する")
            if st.button("フル更新を開始", disabled=not ok, width="stretch"):
                jobs.start_full_update()
                st.rerun()
            if fu["log_tail"]:
                with st.expander("前回ログ (末尾)"):
                    st.code(fu["log_tail"], language=None)

    st.divider()

    # ③ データ充足チェック
    st.markdown("### 📡 データ充足チェック")
    st.caption("EDINETメタデータのみで日次の臨時報告書件数を確認(1日≒0.5秒)")
    cc1, cc2 = st.columns(2)
    y = date.today().year
    cov_start = cc1.date_input("開始", value=date(y, 6, 1), key="cov_s")
    cov_end = cc2.date_input("終了", value=date.today(), key="cov_e")
    if st.button("チェック実行", width="stretch"):
        if cov_start > cov_end:
            st.error("開始日が終了日より後になっています")
        else:
            bar = st.progress(0.0, text="開始…")
            try:
                rows = jobs.check_coverage(
                    cov_start, cov_end,
                    progress=lambda f, m: bar.progress(f, text=m),
                )
                bar.empty()
                if rows:
                    st.session_state["coverage"] = rows
                else:
                    # 土日のみの期間 → 平日フィルタで0日。空を保存するとKeyErrorになる
                    st.warning("期間内に平日がありません(EDINETは土日提出なし)")
            except Exception as e:  # noqa: BLE001
                bar.empty()
                st.error(str(e))

    if st.session_state.get("coverage"):
        cov = pd.DataFrame(st.session_state["coverage"])
        total = int(cov["count"].fillna(0).sum())
        st.metric("期間内 臨時報告書(上場)", f"{total:,} 件")
        st.bar_chart(cov.set_index("date")["count"], height=160)

    st.divider()

    # ④ 倉庫レディネス判定（大量保有を倉庫wh_shareholdersに寄せてよいか）
    st.markdown("### 🏭 倉庫レディネス判定")
    st.caption("大量保有を倉庫(wh_shareholders)に寄せてよいか手動チェック。"
               "月1くらいで押して「ゲートA(鮮度)」が✅になるのを待つ。")
    if IS_CLOUD:
        st.warning("🏭 このタブは warehouse (`~/Claude/warehouse`) への接続が必要です。"
                   "Streamlit Cloud では機能しません（ローカル環境限定）。")
    if st.button("判定を実行", width="stretch", disabled=IS_CLOUD):
        with st.spinner("倉庫を確認中…"):
            res = wh_readiness.evaluate()
        st.session_state["wh_readiness"] = res
        wh_readiness.save_last(res)  # 次回起動時のバッジ用に保存

    r = st.session_state.get("wh_readiness")
    if r:
        if not r.get("available"):
            st.error("倉庫に接続できませんでした: " + r.get("error", "")[:80])
        else:
            g = r["gates"]
            def _g(ok): return "✅" if ok else "❌"
            st.markdown(
                f"- A. 鮮度 {_g(g['freshness']['ok'])} 最新 {g['freshness']['latest']}"
                f"（{g['freshness']['days_behind']}日遅れ・直近30日{g['freshness']['recent30']}件）\n"
                f"- B. カバレッジ {_g(g['coverage']['ok'])} {g['coverage']['pct']*100:.0f}%\n"
                f"- C. 一致度 {_g(g['match']['ok'])} ±0.5pt一致 {g['match']['pct']*100:.0f}%"
            )
            msg = {"red": st.error, "yellow": st.warning, "green": st.success}[r["level"]]
            msg(r["verdict"])
            if r["mismatches"]:
                with st.expander(f"差1pt超 {len(r['mismatches'])}社"):
                    st.dataframe(pd.DataFrame([
                        {"コード": m["code"],
                         "企業名": m["name"].replace("株式会社", "")[:12],
                         "アプリ%": m["app"], "倉庫%": m["wh"],
                         "倉庫最新": m["wh_date"], "差pt": m["diff"]}
                        for m in r["mismatches"]
                    ]), width="stretch", hide_index=True)


# ------------------------------------------------------------------
# メイン: タブ
# ------------------------------------------------------------------

derived = load_derived()

_htitle, _hbtn = st.columns([4, 1])
_htitle.title("株主総会 アクティビスト実戦リスト 2026")
if IS_CLOUD:
    _htitle.caption("📅 本ページの数値は Mac ローカルの launchd が毎日 06:00 JST に "
                    "生成し、GitHub に push されたスナップショットです。"
                    "最新の生データはローカル版で確認してください。")
with _hbtn:
    st.write("")  # タイトルとボタンの縦位置合わせ
    if st.button("🔄 更新", width="stretch",
                 help="ローカルデータからリストを作り直します(数秒〜1分)。"
                      "EDINETから新しいデータを取り直すには、サイドバーの"
                      "「🔄 フル更新」を使ってください。"):
        ok = False
        with st.spinner("更新中…(トリガー比較→差分→実戦リスト)"):
            try:
                jobs.fast_regen()
                st.cache_data.clear()
                ok = True
            except Exception as e:  # noqa: BLE001
                st.error(f"更新に失敗しました: {e}")
        if ok:
            st.toast("✅ 最新の状態に更新しました", icon="🔄")
            st.rerun()

if derived is None:
    st.warning("派生データが未生成です。サイドバーの「⚡ 再生成を実行」を押してください。")
    st.stop()

counts = derived["counts"]
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("実戦リスト", f"{counts['kept']}社")
k2.metric("Tier 1/2/3", f"{counts['t1']}/{counts['t2']}/{counts['t3']}")
k3.metric("継続", f"{counts['cont']}社")
k4.metric("新規", f"{counts['new']}社")
k5.metric("卒業", f"{counts['grad']}社")

tab_wl, tab_trig, tab_grad, tab_pick, tab_help = st.tabs(
    ["🎯 実戦リスト", "📋 全トリガー(2026)", "🎓 卒業・決着", "🔍 銘柄検索",
     "❓ 使い方"])

# --- 実戦リスト ---
with tab_wl:
    st.caption("ℹ️ 今いちばん張れそうな厳選銘柄。**行をクリック**で下に詳細が出ます。")
    with st.expander("🏷️ Tier 1/2/3 の意味（クリックで開く）"):
        st.markdown(TIER_HELP)
    wl = pd.DataFrame(derived["watchlist"])
    if wl.empty:
        st.info("実戦リストが空です(トリガー0社 or 再生成失敗直後)。"
                "サイドバーの「⚡ 再生成」を実行してください。")
    else:
        tier_sel = st.multiselect(
            "Tier", ["1", "2", "3"], default=["1", "2", "3"],
            format_func=lambda t: TIER_LABEL[t])
        view = wl[wl["tier"].isin(tier_sel)]

        def _f(key: str):
            """fund列(dict または None)から指標を取り出す。旧JSONなら全てNone。"""
            if "fund" not in view.columns:
                return [None] * len(view)
            return view["fund"].map(lambda f: (f or {}).get(key))

        disp = pd.DataFrame({
            "Tier": view["tier"],
            "区分": view["seg"],
            "コード": view["code"],
            "企業名": view["name"].str.replace("株式会社", "", regex=False),
            "アクティビスト": view["holder"],
            "保有%": view["ratio"],
            "Δpp": view["delta"],
            "否決": view["C"].map({True: "○", False: ""}),
            "株価": _f("price"),
            "PER": _f("per"),
            "PBR": _f("pbr"),
            "利回り%": _f("yield_pct"),
            "条件": view["p_curr"],
            "メモ": view["thesis"],
        }).reset_index(drop=True)
        # keyにフィルタ状態を含め、フィルタ変更時に選択状態をリセットする
        # (残留した位置indexが別銘柄を指すのを防ぐ)
        ev = st.dataframe(
            disp, width="stretch", hide_index=True,
            on_select="rerun", selection_mode="single-row",
            key=f"tbl_wl_{'-'.join(sorted(tier_sel))}",
            height=min(38 * len(disp) + 40, 560),
        )
        _select_code_from(disp, ev, "コード")
        _asof = derived.get("fundamentals_asof")
        st.caption("行をクリックすると下部に銘柄詳細を表示（株探・IRBANKへのリンク付き）。"
                   f"除外{counts['excluded']}社(撤退/パッシブ/極小)は「卒業・決着」タブ末尾に記載"
                   + (f" ／ 株価・PER・PBR は {_asof} 時点(warehouse mart_latest)"
                      if _asof else ""))

# --- 全トリガー ---
with tab_trig:
    st.caption("ℹ️ 条件に引っかかった会社の**全リスト**（アクティビストがいない会社も含む）。"
               "下のチェックで A(賛成率低下)/B(新規株主提案)/C(否決) を絞り込めます。")
    rows = load_trigger_table("2526")
    tdf = pd.DataFrame(rows)
    f1, f2, f3 = st.columns(3)
    only_a = f1.checkbox("A:賛成率低下のみ")
    only_b = f2.checkbox("B:新規株主提案のみ")
    only_c = f3.checkbox("C:否決のみ")
    if only_a:
        tdf = tdf[tdf["A:賛成率低下"] == "○"]
    if only_b:
        tdf = tdf[tdf["B:新規株主提案"] == "○"]
    if only_c:
        tdf = tdf[tdf["C:否決"] == "○"]
    tdf = tdf.reset_index(drop=True)
    st.caption(f"{len(tdf)}社 (2025→2026トリガー該当・新ロジック)")
    ev2 = st.dataframe(
        tdf, width="stretch", hide_index=True,
        on_select="rerun", selection_mode="single-row",
        key=f"tbl_trig_{int(only_a)}{int(only_b)}{int(only_c)}",
        height=560,
    )
    _select_code_from(tdf, ev2, "証券コード")
    st.caption("行をクリックすると下部に銘柄詳細を表示")

# --- 卒業・決着 ---
with tab_grad:
    st.caption("ℹ️ 去年ホットだったのに今年リストから外れた会社と、その**理由**"
               "（非公開化・アクティビスト勝利・撤退など）。なぜ消えたかが分かります。")
    grads = load_graduations()
    st.markdown("#### 去年の激戦は「決着」した (一次情報で検証済み)")
    gdf = pd.DataFrame([
        {"コード": g["code"], "企業名": g["name"],
         "決着の型": g["type"], "2026に起きたこと": g["detail"]}
        for g in grads["graduations"]
    ])
    st.dataframe(gdf, width="stretch", hide_index=True)
    for e in grads.get("exceptions", []):
        st.warning(f"**例外: {e['name']}({e['code']})** — {e['detail']}")

    with st.expander(f"卒業 全{counts['grad']}社リスト"):
        gnames = derived.get("grad_names", {})
        st.dataframe(pd.DataFrame(
            [{"コード": c, "企業名": n} for c, n in sorted(gnames.items())]),
            width="stretch", hide_index=True)

    with st.expander(f"実戦リストから除外した{counts['excluded']}社"):
        st.dataframe(pd.DataFrame([
            {"コード": r["code"], "企業名": r["name"],
             "保有者": r["holder"], "保有%": r["ratio"],
             "除外理由": r["exclude_reason"]}
            for r in derived["excluded"]
        ]), width="stretch", hide_index=True)

    st.markdown("#### ⚠️ 機械処理の癖 (検証済みの注意点)")
    for c in derived.get("caveats", []):
        st.markdown(f"- {c}")

# --- 銘柄検索 ---
with tab_pick:
    st.caption("ℹ️ 証券コードや会社名から**個別の銘柄を直接**調べます。"
               "選ぶと下に議案別賛成率・大株主の推移が出ます。")
    all_rows = load_trigger_table("2526") + load_trigger_table("2425")
    opts: dict[str, str] = {}
    for r in all_rows:
        opts.setdefault(r["証券コード"], f'{r["証券コード"]} {r["企業名"]}')
    sel = st.selectbox(
        "銘柄を選択 (トリガー該当社)",
        options=sorted(opts.keys()),
        format_func=lambda c: opts[c],
        index=None,
        placeholder="コードまたは名前で検索…",
    )
    manual = st.text_input("または4桁コードを直接入力", max_chars=4)
    # 英字コード(331A等)対応で大文字化
    code = (manual.strip().upper() or sel)
    # 値が「変わった時だけ」反映する。毎rerunで上書きすると、
    # 検索欄に値が残っている間、他タブの行クリックが永遠に無効化されるため。
    if code and code != st.session_state.get("_last_pick"):
        st.session_state["_last_pick"] = code
        st.session_state["selected_code"] = code

# --- 使い方 ---
with tab_help:
    st.markdown("""
### このアプリは何をするもの？

3月決算企業の**株主総会の議決権行使結果**（EDINETの臨時報告書）を集め、
**経営に不満が高まっている会社**を機械的に見つけ、そこに**アクティビスト
（物言う株主）**がどれだけ株を持っているかを紐づけて、
「**今、張れる（投資チャンスがありそうな）銘柄**」を一覧にするツールです。

去年（2024→2025）と今年（2025→2026）を比べ、状況を **継続 / 新規 / 卒業** に分けています。
""")

    st.info("👆 上の5つのタブを切り替えて使います。**表の行をクリックすると、"
            "画面下に その銘柄の詳細**（議案別の賛成率・大株主の推移）が出ます。")

    with st.expander("⭐ 銘柄の絞り込みの流れ（スクリーニングの順番）", expanded=True):
        fn = derived.get("funnel") or {}

        def _n(key: str, prefix: str = "") -> str:
            v = fn.get(key)
            return f"{prefix}{v:,} 社" if isinstance(v, int) else "— 社"

        st.markdown(f"""
「今、張れる銘柄」は、次の**4段階の漏斗（じょうご）**で機械的に絞り込んでいます。
上から順に、対象がだんだん少なくなります。
""")
        st.markdown(f"""```
① 総会データ 全部        {_n('meetings', '約 ')}      ← 今年3月決算企業の株主総会 全部
      │  3条件のどれか1つでも当てはまる会社に絞る（A / B / C）
      ▼
② トリガー該当            {_n('trigger')}      内訳 A:{fn.get('condA','–')} / B:{fn.get('condB','–')} / C:{fn.get('condC','–')}（重複あり）
      │  大量保有報告書（5%超の開示）で「誰が株主か」を紐付け
      │  → アクティビスト（物言う株主）が筆頭の会社だけ残す
      ▼
③ アクティビスト銘柄       {_n('activist_pool')}
      │  除外：パッシブ運用・保有を減らし中・極小(3%未満)・撤退方向（− {fn.get('excluded','–')} 社）
      ▼
④ 実戦リスト              {_n('kept')}      ← Tier 1 / 2 / 3 に並べて完成
```""")
        st.markdown("""
**各ステップの中身**

1. **総会データを全部集める** — EDINET（金融庁の開示システム）の**臨時報告書**から、
   3月決算企業の株主総会の「議案ごとの賛成率」を丸ごと取得します。
2. **3条件で “不満が出ている会社” を抽出** — 前年と比べて次のどれかに当たる会社を拾います。
   - **A**：会社提案の賛成率が **10pt以上ダウン**（株主の不満増）
   - **B**：前年になかった **株主提案** が新たに出た
   - **C**：会社提案が **否決**（賛成率50%未満）
   （A・B・Cの**和集合**なので、内訳の合計＝トリガー社数にはなりません）
3. **アクティビストがいる会社だけに絞る** — 各社の**大量保有報告書**を紐付け、
   著名アクティビストが**筆頭株主**の会社だけを残します。
   さらに、実際には張りにくい先を**除外**します（パッシブ/インデックス運用、
   保有を**減らしている**先、**3%未満**の極小、**撤退方向**）。ここが「今張れる」の肝。
4. **Tier 1/2/3 に並べる** — 残った会社を、保有量と“動き”の強さで並べて**実戦リスト**の完成。
   （Tierの基準は「🏷️ Tier（1/2/3）の詳しい意味」を参照）

💡 数字は **「🔄 更新」を押すたびに再計算**されるので、常に最新の絞り込み結果です。
""")

    with st.expander("📑 各タブの見方", expanded=True):
        st.markdown(f"""
| タブ | 内容 |
|---|---|
| 🎯 **実戦リスト** | 現在も上場していてアクティビストが撤退していない **厳選{counts['kept']}社**。撤退・非公開化・パッシブ運用・極小保有は除外済み。ここがメイン。 |
| 📋 **全トリガー(2026)** | 条件に引っかかった **{counts['new'] + counts['cont']}社 全部**（アクティビスト無しも含む）。A/B/Cで絞り込み可。 |
| 🎓 **卒業・決着** | 去年ホットだったが今年リストから外れた会社と、その**理由**（非公開化・アクティビスト勝利・撤退など。一次情報で確認済み）。 |
| 🔍 **銘柄検索** | 証券コードや会社名で個別銘柄を直接呼び出す。 |
""")

    with st.expander("🏷️ Tier（1/2/3）の詳しい意味", expanded=True):
        st.markdown(TIER_HELP)

    with st.expander("🔤 区分・トリガー条件（A/B/C）の意味"):
        st.markdown("""
> **A/B/C は「引っかかった条件」**、**Tier 1/2/3 は「リストの優先度」**です。
> 記号を分けているので混同しないでください。

**区分**
- **継続** … 去年も今年もトリガー該当（居座り案件）
- **新規** … 今年はじめてトリガー該当

**トリガー条件 A/B/C**（1つでも該当すると対象）
- **A: 賛成率低下** … 会社提案への賛成率が前年比10pt以上ダウン（＝株主の不満増）
- **B: 新規株主提案** … 前年になかった株主提案が新たに出た
- **C: 否決** … 会社提案が否決された（賛成率50%未満）

> 実戦リストの「条件」列（例 `AC`）は、この A/B/C のどれに当てはまったかを表します。
""")

    with st.expander("▶️ サイドバーの実行ボタン（データ更新）"):
        st.markdown("""
| ボタン | いつ使う | 所要 |
|---|---|---|
| ⚡ **高速再生成** | 表示がおかしい時・分類ロジックを直した後。キャッシュから計算し直すだけで、通信しない。 | 数秒〜1分 |
| 🔄 **フル更新** | **総会シーズンやアインHD(7/30)総会の後**など、EDINETから最新データを取り直したい時。 | **40分〜2時間** |
| 📡 **充足チェック** | 「今年の総会データがもう出そろったか」を先に確認したい時。臨時報告書の日次件数を見る。 | 数十秒 |

⚠️ **フル更新は長時間ジョブ**です。「了解して実行する」にチェックしてから開始。
実行中は進捗ログが出て、途中で⛔停止もできます（停止してもデータは壊れません）。
アプリを閉じても裏で走り続けます。
""")

    with st.expander("⚠️ 数字を鵜呑みにしないための注意点"):
        st.markdown("""
- **「否決」の多くは “アクティビスト側の株主提案” が否決された**もの。
  経営陣が負けたのではなく、**物言う株主が票では連敗しつつ株を買い増している膠着**、という意味です。
- **賛成率の一部は自動抽出の誤検出**があり得ます（議案名が空の会社など）。
  重要な銘柄は必ず**一次情報（臨時報告書・大量保有報告書の原本）で確認**してください。
- **「新規トリガー」＝「ファンドが今年新規参入」ではない**。多くは去年から株を積み増していた会社が、
  今年になって賛成率低下の閾値を超えただけです。
- このアプリは**投資助言ではありません**。あくまで調査の出発点です。
""")

    with st.expander("📖 用語ミニ辞典"):
        st.markdown("""
- **アクティビスト（物言う株主）** … 株を大量に買い、増配・自社株買い・取締役の交代などを要求する投資ファンド。
- **大量保有報告書** … 上場株を5%超持つと提出義務がある開示。誰がどれだけ持っているか分かる。
- **臨時報告書（議決権行使結果）** … 株主総会の後、各議案の賛成・反対の数が開示される書類。
- **非公開化 / TOB / MBO** … 会社を買い取って上場をやめること。こうなると一般の投資家は株を買えなくなる（＝卒業）。
""")

    st.caption("データ出典: EDINET（臨時報告書・大量保有報告書）、kessanai、報道。"
               f"最終再生成: {_mtime(OUTPUT_DIR / 'derived' / 'diff_watchlist.json')}。"
               "詳細な運用は STATUS.md / README.md を参照。")

# --- 銘柄詳細 (どのタブで選んでも下部に1回だけ描画) ---
if st.session_state.get("selected_code"):
    st.divider()
    render_detail(st.session_state["selected_code"])
