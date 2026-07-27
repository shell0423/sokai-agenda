"""会社マスタ・現在ファンダを warehouse(~/Claude/warehouse) から取得する。

旧 J-Quants 企業マスタの置き換え。全アプリで共通のマスタ(wh_security)に一本化する。
株価・PER・PBR は mart 層の `mart_latest`(倉庫が算出済みの最新スナップショット)を読む。

倉庫の作法(STATUS.md)を守る:
  - read_only で開く。
  - 取得したら **即クローズ** して接続を保持しない
    (DuckDBはプロセス跨ぎで「複数リーダー or 単一ライター」。接続を握り続けると
     夜間18:30のライター(daily_update)をブロックしてしまう=過去のkabusoku事故)。
  - 倉庫が無い/失敗しても空dictを返し、呼び出し側はEDINETの提出者名にフォールバックする。
"""
from __future__ import annotations

import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

logger = logging.getLogger(__name__)

WAREHOUSE_DIR = Path(
    os.getenv("WAREHOUSE_DIR", os.path.expanduser("~/Claude/warehouse"))
)


def get_stock_master() -> dict[str, dict[str, str]]:
    """{code4: {"name", "sector", "market"}} を wh_security から返す。

    失敗時(倉庫なし/ロック/スキーマ差異)は空dictを返す(呼び出し側でスキップ)。
    """
    if not (WAREHOUSE_DIR / "client.py").exists():
        logger.warning("warehouse client.py が見つかりません: %s", WAREHOUSE_DIR)
        return {}
    try:
        if str(WAREHOUSE_DIR) not in sys.path:
            sys.path.insert(0, str(WAREHOUSE_DIR))
        from client import connect  # warehouse/client.py

        con = connect(read_only=True)
        try:
            rows = con.execute(
                "SELECT code, name, sector17_name, market_name FROM wh_security"
            ).fetchall()
        finally:
            con.close()  # 即クローズ=ライターをブロックしない
    except Exception:
        logger.warning("warehouse wh_security 取得に失敗（スキップ）", exc_info=True)
        return {}

    master: dict[str, dict[str, str]] = {}
    for code, name, sector, market in rows:
        code4 = (str(code) if code else "")[:4]
        if code4 and name:
            master[code4] = {
                "name": name,
                "sector": sector or "",
                "market": market or "",
            }
    return master


def _pct(value: object) -> float | None:
    """倉庫の比率(0.0269)を % 表記(2.69)に直す。Noneはそのまま。"""
    if value is None:
        return None
    try:
        return round(float(value) * 100, 2)
    except (TypeError, ValueError):
        return None


def _num(value: object, digits: int = 2) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def get_fundamentals(codes: Sequence[str]) -> dict[str, dict]:
    """証券コード(4桁)ごとの現在ファンダを `mart_latest` から返す。

    倉庫が算出済みの最新スナップショット(株価・PER・PBR・配当利回り・ROE)を読むだけで、
    このアプリ側では再計算しない(倉庫が唯一の正)。倉庫は Cloud には無いため、
    呼び出し側(analysis_diff.build_all)が結果を derived JSON に焼き込んで配布する。

    Args:
        codes: 4桁証券コードのリスト。

    Returns:
        {code4: {"price", "date", "per", "pbr", "yield_pct", "roe_pct",
                 "eps", "bps", "dps", "fy", "per_outlier", "pbr_outlier",
                 "missing"}}。取得できない銘柄はキーごと欠落。
        倉庫が無い/失敗した場合は空dict。
    """
    codes = [c for c in dict.fromkeys(codes) if c]
    if not codes:
        return {}
    if not (WAREHOUSE_DIR / "client.py").exists():
        logger.info("warehouse なし。PER/PBR の取得はスキップ: %s", WAREHOUSE_DIR)
        return {}
    try:
        if str(WAREHOUSE_DIR) not in sys.path:
            sys.path.insert(0, str(WAREHOUSE_DIR))
        from client import connect  # warehouse/client.py

        con = connect(read_only=True)
        try:
            placeholders = ",".join("?" for _ in codes)
            rows = con.execute(
                "SELECT left(CAST(code AS VARCHAR),4) AS c4, last_date, last_close, "
                "per, pbr, dividend_yield, roe_official, eps, bps, dps, latest_fy, "
                "per_outlier, pbr_outlier, missing_fundamentals FROM mart_latest "
                f"WHERE left(CAST(code AS VARCHAR),4) IN ({placeholders})",
                list(codes),
            ).fetchall()
        finally:
            con.close()  # 即クローズ=ライターをブロックしない
    except Exception:
        logger.warning("warehouse mart_latest 取得に失敗（スキップ）", exc_info=True)
        return {}

    out: dict[str, dict] = {}
    for (c4, last_date, close, per, pbr, dy, roe, eps, bps, dps, fy,
         per_out, pbr_out, missing) in rows:
        out[str(c4)] = {
            "price": _num(close, 1),
            "date": str(last_date)[:10] if last_date else "",
            "per": _num(per),
            "pbr": _num(pbr),
            "yield_pct": _pct(dy),
            "roe_pct": _pct(roe),
            "eps": _num(eps),
            "bps": _num(bps),
            "dps": _num(dps),
            "fy": int(fy) if fy is not None else None,
            "per_outlier": bool(per_out),
            "pbr_outlier": bool(pbr_out),
            "missing": bool(missing),
        }
    return out


def apply_master_names(meetings) -> int:
    """MeetingResultのcompany_nameが空の行を warehouse の社名で補完する。

    Returns:
        補完した件数。
    """
    empties = [m for m in meetings if not (m.company_name or "").strip()]
    if not empties:
        return 0
    master = get_stock_master()
    if not master:
        return 0
    filled = 0
    for m in empties:
        info = master.get((m.sec_code or "")[:4])
        if info:
            m.company_name = info["name"]
            filled += 1
    return filled
