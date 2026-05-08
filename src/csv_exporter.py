from __future__ import annotations

import csv
import logging
from pathlib import Path

import pandas as pd

from src.models import AnalysisRecord

logger = logging.getLogger(__name__)

CSV_COLUMNS = [
    "証券コード",
    "企業名",
    "議案番号",
    "議案タイトル",
    "提案区分",
    "候補者",
    "結果",
    "賛成率(%)",
    "賛成票",
    "反対票",
    "棄権票",
    "大量保有者",
    "提出日",
    "docID",
]


def _record_to_row(record: AnalysisRecord) -> dict[str, object]:
    """AnalysisRecordをCSV行の辞書に変換する。"""
    return {
        "証券コード": record.sec_code,
        "企業名": record.company_name,
        "議案番号": f"第{record.proposal_number}号議案",
        "議案タイトル": record.proposal_title,
        "提案区分": record.proposal_type,
        "候補者": record.candidate_name,
        "結果": record.result,
        "賛成率(%)": record.approval_rate,
        "賛成票": record.votes_for,
        "反対票": record.votes_against,
        "棄権票": record.votes_abstain,
        "大量保有者": record.major_holders,
        "提出日": record.submit_date,
        "docID": record.doc_id,
    }


class CsvExporter:
    """分析結果をCSV/Excelに出力する。"""

    def export_csv(
        self,
        records: list[AnalysisRecord],
        output_path: Path,
    ) -> None:
        """CSVファイルに出力する。

        Args:
            records: 分析結果レコードリスト。
            output_path: 出力ファイルパス。
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for record in records:
                writer.writerow(_record_to_row(record))

        logger.info("CSV出力完了: %s (%d件)", output_path, len(records))

    def export_excel(
        self,
        records: list[AnalysisRecord],
        output_path: Path,
    ) -> None:
        """Excelファイルに出力する。

        Args:
            records: 分析結果レコードリスト。
            output_path: 出力ファイルパス。
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        rows = [_record_to_row(r) for r in records]
        df = pd.DataFrame(rows, columns=CSV_COLUMNS)
        df.to_excel(output_path, index=False, engine="openpyxl")

        logger.info(
            "Excel出力完了: %s (%d件)", output_path, len(records)
        )
