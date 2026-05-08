from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree as ET


@dataclass
class HoldingInfo:
    """大量保有報告書から抽出した保有情報。"""

    holder_name: str | None
    issuer_name: str | None
    securities_code: str | None
    ratio_held: float | None   # 変更後保有割合（%）
    ratio_before: float | None  # 変更前保有割合（%）。大量保有報告書（新規）はNone
    shares_held: int | None    # 保有株数
    purpose: str | None        # 保有目的
    reason: str | None         # 変更理由（変更報告書のみ）


class XbrlParseError(Exception):
    """XBRLパースエラー。"""


class XbrlParser:
    """大量保有報告書XBRLパーサー。

    EDINETからダウンロードしたZIPファイルを解析し、
    保有者情報・発行者情報・保有割合などを抽出する。
    XBRL要素名はタクソノミバージョンにより変動するため、
    候補リストを優先順に試行するフォールバック方式を採用している。
    """

    # 保有者名の候補要素名（優先順）
    _HOLDER_NAME_KEYS = (
        "NameOfFilerOfLargeVolumeHolding",
        "NameOfHolderOfLargeVolumeHolding",
        "HolderName",
        "FilerName",
    )

    # 発行者名の候補要素名（優先順）
    _ISSUER_NAME_KEYS = (
        "NameOfIssuerOfTargetSecurities",
        "NameOfIssuer",
        "IssuerName",
        "CompanyName",
    )

    # 証券コードの候補要素名（優先順）
    _SECURITIES_CODE_KEYS = (
        "SecuritiesCode",
        "SecurityCode",
        "StockCode",
        "IssuerSecuritiesCode",
    )

    # 変更後保有割合の候補要素名（優先順）
    # EDINET v2 XBRL は小数表現（0.0622 = 6.22%）で格納される
    _RATIO_KEYS = (
        "HoldingRatioOfShareCertificatesEtc",
        "RatioOfSharesHeldAfterChange",
        "RatioOfSharesHeld",
        "HoldingRatio",
        "OwnershipRatio",
        "RatioOfVotingRightsHeld",
    )

    # 変更前保有割合の候補要素名（変更報告書のみ存在）
    _RATIO_BEFORE_KEYS = (
        "HoldingRatioOfShareCertificatesEtcPerLastReport",
        "RatioOfSharesHeldBeforeChange",
        "PreviousRatioOfSharesHeld",
    )

    # 保有株数の候補要素名（優先順）
    _SHARES_KEYS = (
        "TotalNumberOfStocksEtcHeld",
        "NumberOfSharesHeldAfterChange",
        "NumberOfSharesHeld",
        "SharesHeld",
        "TotalNumberOfSharesHeld",
    )

    # 保有目的の候補要素名（優先順）
    _PURPOSE_KEYS = (
        "PurposeOfHolding",
        "HoldingPurpose",
        "PurposeOfAcquisition",
    )

    # 変更理由の候補要素名（変更報告書のみ存在）
    _REASON_KEYS = (
        "ReasonForFilingChangeReportCoverPage",
        "ReasonForChange",
        "ReasonForFilingChangeReport",
    )

    def parse_zip(self, zip_bytes: bytes) -> HoldingInfo:
        """ZIPバイト列からHoldingInfoを抽出する。

        Args:
            zip_bytes: EDINETからダウンロードしたZIPのバイト列。

        Returns:
            抽出した保有情報。取得できない項目はNone。
        """
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                xbrl_path = self._find_xbrl_path(zf)
                if xbrl_path is None:
                    return HoldingInfo(None, None, None, None, None, None, None, None)
                with zf.open(xbrl_path) as f:
                    return self._parse_xbrl(f.read())
        except zipfile.BadZipFile:
            return HoldingInfo(None, None, None, None, None, None, None, None)

    def _find_xbrl_path(self, zf: zipfile.ZipFile) -> str | None:
        """ZIPからメインXBRLファイルのパスを探す。"""
        # PublicDoc配下のXBRLファイルを優先
        for name in zf.namelist():
            if name.endswith(".xbrl") and "PublicDoc" in name:
                return name
        # フォールバック: 任意の.xbrlファイル
        for name in zf.namelist():
            if name.endswith(".xbrl"):
                return name
        return None

    def _parse_xbrl(self, xbrl_bytes: bytes) -> HoldingInfo:
        """XBRLバイト列をパースしてHoldingInfoを返す。"""
        try:
            root = ET.fromstring(xbrl_bytes)
        except ET.ParseError:
            return HoldingInfo(None, None, None, None, None, None, None, None)

        # ローカル名 → テキスト の辞書を構築
        elements: dict[str, str] = {}
        for el in root.iter():
            local = self._local_name(el.tag)
            if el.text and el.text.strip() and local not in elements:
                elements[local] = el.text.strip()

        ratio_held = self._to_percent(
            self._parse_float(self._find_first(elements, self._RATIO_KEYS))
        )
        ratio_before = self._to_percent(
            self._parse_float(self._find_first(elements, self._RATIO_BEFORE_KEYS))
        )

        return HoldingInfo(
            holder_name=self._find_first(elements, self._HOLDER_NAME_KEYS),
            issuer_name=self._find_first(elements, self._ISSUER_NAME_KEYS),
            securities_code=self._find_first(elements, self._SECURITIES_CODE_KEYS),
            ratio_held=ratio_held,
            ratio_before=ratio_before,
            shares_held=self._parse_int(
                self._find_first(elements, self._SHARES_KEYS)
            ),
            purpose=self._find_first(elements, self._PURPOSE_KEYS),
            reason=self._find_first(elements, self._REASON_KEYS),
        )

    @staticmethod
    def _local_name(tag: str) -> str:
        """名前空間プレフィックスを除いたローカル名を返す。"""
        return tag.split("}")[-1] if "}" in tag else tag

    @staticmethod
    def _find_first(elements: dict[str, str], keys: tuple[str, ...]) -> str | None:
        """候補キーを順に試して最初に見つかった値を返す。"""
        for key in keys:
            if key in elements:
                return elements[key]
        return None

    @staticmethod
    def _to_percent(value: float | None) -> float | None:
        """XBRL小数表現（0.0622）をパーセント表現（6.22）に変換する。

        EDINETのXBRLは保有割合を小数（fraction）で格納するため、
        100倍してパーセント値に変換する。
        既にパーセント値（> 1.0）の場合はそのまま返す。
        """
        if value is None:
            return None
        return value * 100 if value <= 1.0 else value

    @staticmethod
    def _parse_float(value: str | None) -> float | None:
        """文字列を浮動小数点数に変換する。失敗時はNone。"""
        if value is None:
            return None
        try:
            return float(value.replace(",", "").replace("%", ""))
        except ValueError:
            return None

    @staticmethod
    def _parse_int(value: str | None) -> int | None:
        """文字列を整数に変換する。失敗時はNone。"""
        if value is None:
            return None
        try:
            return int(value.replace(",", ""))
        except ValueError:
            return None
