from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, timedelta

import httpx

from src.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

EDINET_BASE_URL = "https://disclosure.edinet-fsa.go.jp/api/v2"

EXTRAORDINARY_REPORT_CODE = "180"
TAIRYO_HOYU_CODES = frozenset({"350", "360"})


class EdinetApiError(Exception):
    """EDINET API呼び出しエラー。"""


class EdinetClient:
    """EDINET APIクライアント。

    コンテキストマネージャとして使用可能。スキャン中のHTTPコネクションを
    再利用し、パフォーマンスを向上させる。

    Usage::

        with EdinetClient(api_key="...") as client:
            docs = client.get_extraordinary_reports(date.today())
    """

    def __init__(
        self, api_key: str, timeout: int = 30, rate_limit: float = 1.0
    ) -> None:
        self._timeout = timeout
        self._headers = (
            {"Ocp-Apim-Subscription-Key": api_key} if api_key else {}
        )
        self._limiter = RateLimiter(min_interval=rate_limit)
        self._client = httpx.Client(
            timeout=self._timeout, headers=self._headers
        )

    def close(self) -> None:
        """HTTPクライアントを閉じる。"""
        self._client.close()

    def __enter__(self) -> EdinetClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _get_documents(self, target_date: date) -> list[dict]:
        """指定日の全書類メタデータを取得する。

        Args:
            target_date: 取得対象日。

        Returns:
            書類メタデータリスト。

        Raises:
            EdinetApiError: API呼び出しに失敗した場合。
        """
        self._limiter.wait()
        url = f"{EDINET_BASE_URL}/documents.json"
        params = {"date": target_date.isoformat(), "type": 2}

        try:
            response = self._client.get(url, params=params)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise EdinetApiError(
                f"EDINET API呼び出し失敗 ({target_date}): {e}"
            ) from e

        body = response.json()
        if "statusCode" in body:
            raise EdinetApiError(
                f"EDINET APIエラー: {body.get('message', 'unknown')}"
            )

        return body.get("results", []) or []

    def get_extraordinary_reports(
        self, target_date: date
    ) -> list[dict]:
        """指定日の臨時報告書一覧を取得する。

        Args:
            target_date: 取得対象日。

        Returns:
            docTypeCode=180のメタデータリスト。
        """
        results = self._get_documents(target_date)
        return [
            doc
            for doc in results
            if doc.get("docTypeCode") == EXTRAORDINARY_REPORT_CODE
        ]

    def get_holding_reports(self, target_date: date) -> list[dict]:
        """指定日の大量保有報告書一覧を取得する。

        Args:
            target_date: 取得対象日。

        Returns:
            docTypeCode=350/360のメタデータリスト。
        """
        results = self._get_documents(target_date)
        return [
            doc
            for doc in results
            if doc.get("docTypeCode") in TAIRYO_HOYU_CODES
        ]

    def scan_date_range(
        self,
        start_date: date,
        end_date: date,
        doc_filter: Callable[[dict], bool] | None = None,
    ) -> list[dict]:
        """日付範囲をスキャンし、条件にマッチする書類を収集する。

        土日はスキップする。

        Args:
            start_date: スキャン開始日。
            end_date: スキャン終了日（含む）。
            doc_filter: 書類メタデータのフィルタ関数。

        Returns:
            マッチした書類メタデータリスト。
        """
        collected: list[dict] = []
        current = start_date

        while current <= end_date:
            # 土日スキップ
            if current.weekday() >= 5:
                current += timedelta(days=1)
                continue

            logger.info("スキャン中: %s", current.isoformat())
            try:
                docs = self._get_documents(current)
                for doc in docs:
                    if doc_filter is None or doc_filter(doc):
                        collected.append(doc)
            except EdinetApiError:
                logger.warning(
                    "API呼び出し失敗（スキップ）: %s", current.isoformat()
                )

            current += timedelta(days=1)

        return collected

    def download_document_zip(self, doc_id: str) -> bytes:
        """書類ZIPファイルをダウンロードする。

        Args:
            doc_id: 書類管理番号。

        Returns:
            ZIPファイルのバイト列。

        Raises:
            EdinetApiError: ダウンロードに失敗した場合。
        """
        self._limiter.wait()
        url = f"{EDINET_BASE_URL}/documents/{doc_id}"
        params = {"type": 1}

        try:
            response = self._client.get(
                url, params=params, timeout=60
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise EdinetApiError(
                f"書類ダウンロード失敗 ({doc_id}): {e}"
            ) from e

        return response.content
