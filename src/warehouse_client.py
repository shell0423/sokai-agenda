"""会社マスタを warehouse(~/Claude/warehouse) の wh_security から取得する。

旧 J-Quants 企業マスタの置き換え。全アプリで共通のマスタ(wh_security)に一本化する。

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
