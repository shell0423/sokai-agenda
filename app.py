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

from src import jobs
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

TIER_LABEL = {"A": "🟦 A 最優先", "B": "🟪 B 要注目", "C": "⬜ C ウォッチ"}


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


def render_detail(code: str) -> None:
    d = company_detail(code)
    st.subheader(f"🔍 {code} {d['name'] or '(名称不明)'}")

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


# ------------------------------------------------------------------
# メイン: タブ
# ------------------------------------------------------------------

derived = load_derived()

st.title("株主総会 アクティビスト実戦リスト 2026")

if derived is None:
    st.warning("派生データが未生成です。サイドバーの「⚡ 再生成を実行」を押してください。")
    st.stop()

counts = derived["counts"]
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("実戦リスト", f"{counts['kept']}社")
k2.metric("Tier A/B/C", f"{counts['A']}/{counts['B']}/{counts['C']}")
k3.metric("継続", f"{counts['cont']}社")
k4.metric("新規", f"{counts['new']}社")
k5.metric("卒業", f"{counts['grad']}社")

tab_wl, tab_trig, tab_grad, tab_pick = st.tabs(
    ["🎯 実戦リスト", "📋 全トリガー(2026)", "🎓 卒業・決着", "🔍 銘柄検索"])

# --- 実戦リスト ---
with tab_wl:
    wl = pd.DataFrame(derived["watchlist"])
    if wl.empty:
        st.info("実戦リストが空です(トリガー0社 or 再生成失敗直後)。"
                "サイドバーの「⚡ 再生成」を実行してください。")
    else:
        tier_sel = st.multiselect(
            "Tier", ["A", "B", "C"], default=["A", "B", "C"],
            format_func=lambda t: TIER_LABEL[t])
        view = wl[wl["tier"].isin(tier_sel)]
        disp = pd.DataFrame({
            "Tier": view["tier"],
            "区分": view["seg"],
            "コード": view["code"],
            "企業名": view["name"].str.replace("株式会社", "", regex=False),
            "アクティビスト": view["holder"],
            "保有%": view["ratio"],
            "Δpp": view["delta"],
            "否決": view["C"].map({True: "○", False: ""}),
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
        st.caption("行をクリックすると下部に銘柄詳細を表示。"
                   f"除外{counts['excluded']}社(撤退/パッシブ/極小)は「卒業・決着」タブ末尾に記載")

# --- 全トリガー ---
with tab_trig:
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

# --- 銘柄詳細 (どのタブで選んでも下部に1回だけ描画) ---
if st.session_state.get("selected_code"):
    st.divider()
    render_detail(st.session_state["selected_code"])
