from __future__ import annotations

import logging
from datetime import date

from src.edinet_client import EdinetClient
from src.models import HoldingContext
from src.xbrl_parser import XbrlParser

logger = logging.getLogger(__name__)


class HoldingSearcher:
    """株主提案がある企業の大量保有報告書を検索する。"""

    def __init__(self, edinet_client: EdinetClient) -> None:
        self._client = edinet_client
        self._xbrl_parser = XbrlParser()

    def search_holders(
        self,
        edinet_code: str,
        search_start: date,
        search_end: date,
    ) -> list[HoldingContext]:
        """指定企業の大量保有報告書を検索し、保有者情報を返す。

        issuerEdinetCode で対象企業に絞り込み、
        提出者ごとに最新の報告書から保有割合を取得する。

        Args:
            edinet_code: 対象企業のEDINETコード。
            search_start: 検索開始日。
            search_end: 検索終了日。

        Returns:
            保有者情報のリスト（提出者ごとに最新のもの）。
        """
        logger.info(
            "大量保有報告書検索: %s (%s 〜 %s)",
            edinet_code,
            search_start,
            search_end,
        )

        def is_holding_for_target(doc: dict) -> bool:
            doc_type = doc.get("docTypeCode", "")
            issuer = doc.get("issuerEdinetCode", "") or ""
            return doc_type in ("350", "360") and issuer == edinet_code

        docs = self._client.scan_date_range(
            start_date=search_start,
            end_date=search_end,
            doc_filter=is_holding_for_target,
        )

        if not docs:
            logger.info("大量保有報告書なし: %s", edinet_code)
            return []

        # 提出者ごとに最新の報告書のみ使用
        latest_by_filer: dict[str, dict] = {}
        for doc in docs:
            filer = doc.get("filerName", "") or "unknown"
            submit = doc.get("submitDateTime", "") or ""
            existing = latest_by_filer.get(filer)
            if (
                existing is None
                or submit > (existing.get("submitDateTime", "") or "")
            ):
                latest_by_filer[filer] = doc

        # 各報告書のXBRLを解析
        results: list[HoldingContext] = []
        for filer_name, doc in latest_by_filer.items():
            doc_id = doc.get("docID", "")
            try:
                zip_bytes = self._client.download_document_zip(doc_id)
                info = self._xbrl_parser.parse_zip(zip_bytes)
                holder_name = info.holder_name or filer_name
                results.append(
                    HoldingContext(
                        holder_name=holder_name,
                        ratio_held=info.ratio_held,
                        purpose=info.purpose,
                    )
                )
                logger.info(
                    "  %s: %.2f%%",
                    holder_name,
                    info.ratio_held or 0.0,
                )
            except Exception:
                logger.warning(
                    "大量保有報告書解析失敗: %s (%s)",
                    doc_id,
                    filer_name,
                    exc_info=True,
                )

        return results
