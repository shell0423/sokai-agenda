from __future__ import annotations

import logging

import jquantsapi
import pandas as pd

logger = logging.getLogger(__name__)


class JQuantsClient:
    """JQuants APIを使った銘柄情報取得。"""

    def __init__(self, api_key: str) -> None:
        self._client = jquantsapi.ClientV2(api_key=api_key)

    def get_stock_master(self) -> dict[str, dict[str, str]]:
        """全銘柄マスタを取得する。

        Returns:
            証券コード（4桁） → 銘柄情報辞書のマッピング。
            銘柄情報: name, sector, market。
        """
        df = self._client.get_list()
        master: dict[str, dict[str, str]] = {}

        for _, row in df.iterrows():
            code5 = str(row.get("Code", ""))
            code4 = code5[:4] if len(code5) >= 4 else code5
            master[code4] = {
                "name": str(row.get("CoName", "")),
                "sector": str(row.get("S33Nm", "")),
                "market": str(row.get("MktNm", "")),
            }

        logger.info("銘柄マスタ取得完了: %d件", len(master))
        return master

    def get_fiscal_year_end(self, code5: str) -> str | None:
        """指定銘柄の直近決算期末日を取得する。

        Args:
            code5: 5桁証券コード（例: "46260"）。

        Returns:
            決算期末日の月部分（例: "03"）。取得失敗時はNone。
        """
        try:
            df = self._client.get_fin_summary(code=code5)
            if df.empty:
                return None
            # 最新の決算情報を取得
            latest = df.iloc[-1]
            fy_end = latest.get("CurFYEn")
            if pd.isna(fy_end):
                return None
            # Timestamp → 月を抽出
            if hasattr(fy_end, "month"):
                return f"{fy_end.month:02d}"
            return str(fy_end)[5:7]
        except Exception:
            logger.warning(
                "決算期末日取得失敗: %s", code5, exc_info=True
            )
            return None
