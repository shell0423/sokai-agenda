from __future__ import annotations

import io
import logging
import re
import zipfile

from src.models import Candidate, Proposal, ProposalType, VoteResult

logger = logging.getLogger(__name__)

# 株主総会における決議を示すXBRLタグ
RESOLUTION_TAG = "ResolutionOfShareholdersMeetingTextBlock"

# 全角数字→半角変換テーブル
_ZEN2HAN = str.maketrans("０１２３４５６７８９", "0123456789")


def _zen_to_han(s: str) -> str:
    """全角数字を半角に変換する。"""
    return s.translate(_ZEN2HAN)


def _parse_number(s: str) -> int | None:
    """カンマ付き数値文字列をintに変換。'－'等はNone。"""
    s = _zen_to_han(s.strip().replace(",", "").replace("，", ""))
    if re.match(r"^\d+$", s):
        return int(s)
    return None


class ResolutionParseError(Exception):
    """議決結果パースエラー。"""


class ResolutionParser:
    """臨時報告書から株主総会議決結果を解析する。

    2025年時点のEDINET iXBRL臨時報告書の実際の構造に対応:
    - 議案ごとに「第N号議案」行のあとに候補者名→賛成→反対→棄権→結果が
      インターリーブで並ぶテーブル形式
    - 全角・半角数字の混在
    - 結果表記の複数バリエーション
    """

    def has_resolution_tag(self, zip_bytes: bytes) -> bool:
        """ZIPファイル内にResolutionOfShareholdersMeetingタグがあるか確認する。

        株式報酬等の別件臨時報告書を除外するための高速チェック。

        Args:
            zip_bytes: EDINETからダウンロードしたZIPのバイト列。

        Returns:
            株主総会決議の臨時報告書ならTrue。
        """
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                ixbrl_path = self._find_ixbrl_path(zf)
                if ixbrl_path is None:
                    return False
                content = zf.read(ixbrl_path).decode("utf-8")
                return RESOLUTION_TAG in content
        except (zipfile.BadZipFile, UnicodeDecodeError):
            return False

    def parse_zip(self, zip_bytes: bytes) -> list[Proposal] | None:
        """ZIPバイト列から議案一覧を抽出する。

        Args:
            zip_bytes: EDINETからダウンロードしたZIPのバイト列。

        Returns:
            議案リスト。株主総会議決結果でない場合はNone。
        """
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                ixbrl_path = self._find_ixbrl_path(zf)
                if ixbrl_path is None:
                    return None
                content = zf.read(ixbrl_path).decode("utf-8")
        except (zipfile.BadZipFile, UnicodeDecodeError):
            logger.warning("ZIPファイルの読み込みに失敗")
            return None

        if RESOLUTION_TAG not in content:
            return None

        lines = self._extract_text_lines(content)
        return self._parse_voting_section(lines)

    def _find_ixbrl_path(self, zf: zipfile.ZipFile) -> str | None:
        """ZIP内のiXBRL本文ファイルを探す。"""
        for name in zf.namelist():
            if "honbun" in name and name.endswith("ixbrl.htm"):
                return name
        # フォールバック: PublicDoc配下のixbrl.htm
        for name in zf.namelist():
            if "PublicDoc" in name and name.endswith("ixbrl.htm"):
                return name
        return None

    def _extract_text_lines(self, html: str) -> list[str]:
        """HTMLタグを除去してテキスト行を取得する。

        Args:
            html: iXBRL HTMLコンテンツ。

        Returns:
            空行を除いたテキスト行リスト。
        """
        # style要素を除去
        text = re.sub(
            r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL
        )
        # HTMLタグを改行に変換
        text = re.sub(r"<[^>]+>", "\n", text)
        # HTML実体参照を空白に変換
        text = re.sub(r"&#\d+;", " ", text)
        text = re.sub(r"&\w+;", " ", text)

        return [line.strip() for line in text.split("\n") if line.strip()]

    # ------------------------------------------------------------------
    # 議決結果セクションの検出
    # ------------------------------------------------------------------

    def _extract_vote_section(
        self, lines: list[str]
    ) -> list[str]:
        """議決結果セクション (3) を切り出す。

        複数のバリエーションに対応:
        - "(3）当該決議事項に対する賛成..."
        - "(3）決議事項に対する賛成..."
        - "③決議事項に対する賛成..."
        """
        start_idx = None
        end_idx = None

        for i, line in enumerate(lines):
            if start_idx is None:
                # 広めのマッチ: "決議事項" + "賛成" が同じ行にあればOK
                if "決議事項" in line and "賛成" in line:
                    start_idx = i
            else:
                # 次のセクション (4) の開始を検出
                if re.match(
                    r"^(④|[（\(][4４]|４[　\s])", line
                ):
                    end_idx = i
                    break
                # 「以　上」「以上」で文書終了
                if re.match(r"^以[　\s]*上$", line):
                    end_idx = i
                    break

        if start_idx is None:
            return []

        return lines[start_idx : end_idx or len(lines)]

    # ------------------------------------------------------------------
    # 議案行検出
    # ------------------------------------------------------------------

    _HEADER_WORDS = frozenset({
        "決議事項", "賛成（個）", "反対（個）",
        "棄権（個）", "可決要件",
        "決議の結果及び賛成割合（％）",
        "決議の結果及び", "賛成割合（％）",
        "賛成数", "反対数", "棄権数",
        "(個)", "（個）",
        "賛成割合(％)", "決議の結果及び賛成割合(％)",
    })

    _PROPOSAL_RE = re.compile(
        r"第[０-９0-9]+号議案"
    )

    def _match_proposal_line(
        self, line: str
    ) -> tuple[int, str] | None:
        """「第N号議案...」行をパースする。

        Returns:
            (議案番号, タイトル) or None。
        """
        m = re.match(
            r"第([０-９0-9]+)号議案[　\s]*(.*)", line
        )
        if m:
            num_str = _zen_to_han(m.group(1))
            title = m.group(2).strip()
            return int(num_str), title
        return None

    _BARE_PROPOSAL_RE = re.compile(
        r"^議[　\s]*案[　\s]*(.*)"
    )

    def _match_bare_proposal_line(
        self, line: str
    ) -> str | None:
        """番号なし「議案 ...」行をパースする。

        Returns:
            タイトル部分 or None。
        """
        m = self._BARE_PROPOSAL_RE.match(line)
        if m:
            return m.group(1).strip()
        return None

    # ------------------------------------------------------------------
    # 結果行パース
    # ------------------------------------------------------------------

    _RESULT_RE = re.compile(
        r"(可決|否決)[　\s]*[（(]?[　\s]*([\d０-９.．]+)[　\s]*[％%]?[　\s]*[）)]?"
    )

    def _parse_result_line(
        self, line: str
    ) -> tuple[VoteResult, float | None] | None:
        """結果行（"可決　95.04" "可決（97.73％）"等）をパースする。"""
        m = self._RESULT_RE.match(line)
        if m:
            result = (
                VoteResult.APPROVED
                if m.group(1) == "可決"
                else VoteResult.REJECTED
            )
            rate_str = _zen_to_han(
                m.group(2).replace("．", ".")
            )
            try:
                rate = float(rate_str)
            except ValueError:
                rate = None
            return result, rate
        return None

    def _is_bare_result(self, line: str) -> VoteResult | None:
        """「可決」「否決」のみの行を検出する（数値なし）。"""
        stripped = line.strip()
        if stripped == "可決":
            return VoteResult.APPROVED
        if stripped == "否決":
            return VoteResult.REJECTED
        return None

    def _is_bare_rate(self, line: str) -> float | None:
        """結果なしの賛成率行（"92.51"等）を検出する。"""
        s = _zen_to_han(line.strip().replace("．", "."))
        m = re.match(r"^(\d+\.\d+)$", s)
        if m:
            val = float(m.group(1))
            if 0.0 <= val <= 100.0:
                return val
        return None

    # ------------------------------------------------------------------
    # 数値行判定
    # ------------------------------------------------------------------

    def _is_number_line(self, line: str) -> bool:
        """カンマ付き数値行か判定する。"""
        cleaned = _zen_to_han(
            line.replace(",", "").replace("，", "").strip()
        )
        return bool(re.match(r"^\d+$", cleaned))

    def _is_dash_line(self, line: str) -> bool:
        """ダッシュ（ゼロ票を意味する）か判定する。"""
        return line.strip() in ("－", "―", "-", "–", "—", "０", "0")

    def _is_vote_number(self, line: str) -> bool:
        """票数行（数値 or ダッシュ or 数値+個）か判定する。"""
        if self._is_number_line(line) or self._is_dash_line(line):
            return True
        # "128,451個" のような票数+単位行
        cleaned = _zen_to_han(
            line.replace(",", "").replace("，", "").strip()
        )
        if re.match(r"^\d+個$", cleaned):
            return True
        return False

    def _get_vote_number(self, line: str) -> int | None:
        """票数行から数値を取得する。ダッシュは0。"""
        if self._is_dash_line(line):
            return 0
        return _parse_number(line)

    # ------------------------------------------------------------------
    # タイトルとして不適切な行の判定
    # ------------------------------------------------------------------

    _BARE_VOTE_LABELS = frozenset(
        {"賛成", "反対", "棄権", "賛成数", "反対数", "棄権数"}
    )

    def _is_non_title_line(self, line: str) -> bool:
        """タイトルとして使用すべきでない行を検出する。

        議決権の票数ラベル、票数+単位、注記参照、パーセント表記など
        議案タイトルとしては明らかに不適切な行を True で返す。
        """
        stripped = line.strip()
        if not stripped:
            return True

        # 裸の投票ラベル（"賛成", "反対", "棄権" 等）
        if stripped in self._BARE_VOTE_LABELS:
            return True

        # 票数 + 単位「個」（"128,451個" "200,003個"）
        cleaned = _zen_to_han(
            stripped.replace(",", "").replace("，", "")
            .replace(" ", "").replace("　", "")
        )
        if re.match(r"^\d+個$", cleaned):
            return True

        # 注記参照（"(注)1", "（注）４", "(注)2・3" 等）
        if re.match(r"^[（\(]注[）\)]", stripped):
            return True

        # パーセント表記（"95.04%"）
        han = _zen_to_han(stripped.replace("．", "."))
        if re.match(r"^\d+\.\d+[％%]?$", han):
            return True

        # 純粋な数値行（カンマ含む）
        if re.match(r"^[\d,，]+$", _zen_to_han(stripped)):
            return True

        return False

    # ------------------------------------------------------------------
    # 候補者名の判定
    # ------------------------------------------------------------------

    def _is_candidate_name(self, line: str) -> bool:
        """行が候補者名かどうかを判定する。

        日本語の人名（漢字・ひらがな・カタカナ、全角スペース含む）を検出。
        議案関連のキーワードや数値行、結果行は除外する。
        """
        stripped = line.strip()

        # 空行
        if not stripped:
            return False

        # 数値行
        if self._is_vote_number(stripped):
            return False

        # 結果行
        if self._parse_result_line(stripped) is not None:
            return False

        # 注記行
        if stripped.startswith("（注）") or stripped.startswith("(注)"):
            return False

        # 議案行（第N号議案形式）
        if self._PROPOSAL_RE.match(stripped):
            return False

        # 番号なし議案行
        if self._match_bare_proposal_line(stripped) is not None:
            return False

        # スキップすべきキーワード
        skip_keywords = {
            "提案", "決議", "賛成", "反対", "要件",
            "割合", "棄権", "可決", "否決", "以上", "以　上",
            "会社提案", "株主提案",
        }
        if any(kw in stripped for kw in skip_keywords):
            return False

        # テーブルヘッダー行
        if stripped in self._HEADER_WORDS:
            return False

        # 数字（全角・半角）を含む行は候補者名ではない
        if re.search(r"[0-9０-９]", stripped):
            return False

        # 「の件」「に関する」等の議案タイトル表現を含む場合は除外
        title_phrases = {"の件", "に関する", "について", "決定の件"}
        if any(tp in stripped for tp in title_phrases):
            return False

        # 日本語文字（漢字・ひらがな・カタカナ・全角スペース・
        # アルファベット）のみで構成
        clean = stripped.replace(" ", "").replace("\u3000", "")
        if not (2 <= len(clean) <= 15):
            return False

        # 主に漢字・ひらがな・カタカナで構成されていること
        jp_chars = re.findall(
            r"[\u3000-\u9fff\uf900-\ufaff]", clean
        )
        if len(jp_chars) < 2:
            return False

        return True

    # ------------------------------------------------------------------
    # メインパーサー（インターリーブ構造対応）
    # ------------------------------------------------------------------

    def _parse_voting_section(
        self, lines: list[str]
    ) -> list[Proposal]:
        """議決結果セクションをパースする。

        実際のEDINET臨時報告書のテーブル構造に対応:
        - 議案行 → (候補者名 → 賛成 → 反対 → 棄権 → (注) → 結果) × N人
        - 候補者なし議案: 議案行 → 賛成 → 反対 → 棄権 → (注) → 結果

        Args:
            lines: テキスト行リスト。

        Returns:
            議案リスト。
        """
        vote_lines = self._extract_vote_section(lines)
        if not vote_lines:
            logger.warning("議決結果セクションが見つかりません")
            return []

        results: list[Proposal] = []
        current_type = ProposalType.COMPANY
        i = 0

        bare_proposal_num = 0  # 番号なし議案のカウンター

        while i < len(vote_lines):
            line = vote_lines[i]

            # テーブルヘッダー行はスキップ
            if line in self._HEADER_WORDS:
                i += 1
                continue

            # セクションタイトルもスキップ
            if "決議事項" in line and "賛成" in line:
                i += 1
                continue

            # 提案種別の検出
            if "会社提案" in line and "株主提案" not in line:
                current_type = ProposalType.COMPANY
                i += 1
                continue
            if "株主提案" in line:
                current_type = ProposalType.SHAREHOLDER
                i += 1
                continue

            # 議案行の検出（第N号議案形式）
            proposal_info = self._match_proposal_line(line)
            if proposal_info:
                num, title = proposal_info
                i += 1
                proposal, i = self._parse_one_proposal(
                    vote_lines, i, num, title, current_type
                )
                results.append(proposal)
                continue

            # 番号なし議案行の検出（「議　案」「議案 タイトル」形式）
            bare_title = self._match_bare_proposal_line(line)
            if bare_title is not None:
                bare_proposal_num += 1
                # 次行にタイトルがある場合
                title = bare_title
                i += 1
                if not title and i < len(vote_lines):
                    next_line = vote_lines[i]
                    # 次行がデータ行・投票ラベル等でなければ
                    # タイトルとして取得
                    if (
                        not self._is_non_title_line(next_line)
                        and not self._is_vote_number(next_line)
                        and not self._is_candidate_name(next_line)
                        and self._parse_result_line(next_line)
                        is None
                    ):
                        title = next_line
                        i += 1
                proposal, i = self._parse_one_proposal(
                    vote_lines, i, bare_proposal_num,
                    title, current_type
                )
                results.append(proposal)
                continue

            i += 1

        return results

    @staticmethod
    def _calc_approval_rate(
        votes_for: int | None,
        votes_against: int | None,
        votes_abstain: int | None,
    ) -> float | None:
        """票数から賛成率を計算する。

        Args:
            votes_for: 賛成票数。
            votes_against: 反対票数。
            votes_abstain: 棄権票数。

        Returns:
            賛成率（%）。計算不能ならNone。
        """
        if votes_for is None or votes_against is None:
            return None
        abstain = votes_abstain if votes_abstain is not None else 0
        total = votes_for + votes_against + abstain
        if total == 0:
            return None
        return round(votes_for / total * 100, 2)

    def _parse_one_proposal(
        self,
        lines: list[str],
        start: int,
        number: int,
        title: str,
        proposal_type: ProposalType,
    ) -> tuple[Proposal, int]:
        """1つの議案のデータブロックをパースする。

        Args:
            lines: 議決結果セクションの行リスト。
            start: この議案のデータ開始位置。
            number: 議案番号。
            title: 議案タイトル。
            proposal_type: 会社提案/株主提案。

        Returns:
            (Proposal, 次の処理位置) のタプル。
        """
        i = start

        # タイトルが空の場合、次行からタイトルを取得する
        if not title and i < len(lines):
            next_line = lines[i]
            # データ行・ヘッダー行・投票ラベル等でなければ
            # タイトルとして使用
            if (
                not self._is_non_title_line(next_line)
                and not self._is_vote_number(next_line)
                and not self._is_candidate_name(next_line)
                and self._parse_result_line(next_line) is None
                and next_line not in self._HEADER_WORDS
                and "会社提案" not in next_line
                and "株主提案" not in next_line
                and self._match_proposal_line(next_line) is None
                and self._match_bare_proposal_line(next_line)
                is None
                and self._is_bare_result(next_line) is None
            ):
                title = next_line.strip()
                i += 1

        # 次の議案行またはセクション末を見つけて、
        # この議案に属する行の範囲を確定
        block_end = len(lines)
        for j in range(i, len(lines)):
            if self._match_proposal_line(lines[j]):
                block_end = j
                break
            # 番号なし議案行も区切り
            if (
                self._match_bare_proposal_line(lines[j])
                is not None
            ):
                block_end = j
                break
            # 提案種別行も区切りとする
            if ("会社提案" in lines[j] or "株主提案" in lines[j]):
                if not self._is_candidate_name(lines[j]):
                    block_end = j
                    break

        block = lines[i:block_end]

        # ブロック内で候補者パターンを検出して判定
        candidates = self._parse_candidate_block(block)
        if candidates:
            # 候補者の賛成率がnullの場合、票数から計算
            for c in candidates:
                if c.approval_rate is None:
                    c.approval_rate = self._calc_approval_rate(
                        c.votes_for, c.votes_against,
                        c.votes_abstain,
                    )
            return (
                Proposal(
                    number=number,
                    title=title,
                    proposal_type=proposal_type,
                    candidates=candidates,
                ),
                block_end,
            )

        # 候補者なし（単純議案）
        simple = self._parse_simple_block(block)
        rate = simple.get("rate")
        v_for = simple.get("for")
        v_against = simple.get("against")
        v_abstain = simple.get("abstain")
        # 賛成率がnullの場合、票数から計算
        if rate is None:
            rate = self._calc_approval_rate(
                v_for, v_against, v_abstain
            )
        return (
            Proposal(
                number=number,
                title=title,
                proposal_type=proposal_type,
                result=simple.get("result"),
                approval_rate=rate,
                votes_for=v_for,
                votes_against=v_against,
                votes_abstain=v_abstain,
            ),
            block_end,
        )

    def _parse_candidate_block(
        self, block: list[str]
    ) -> list[Candidate]:
        """候補者ありブロックをパースする。

        2つの形式を自動検出:
        1. グループ型: 全候補者名 → 全賛成票 → 全反対票 → 全棄権票 → 結果
        2. インターリーブ型: (名前→賛成→反対→棄権→結果) × 候補者数
        """
        # まず候補者名を先頭から連続で収集してフォーマット判定
        consecutive_names: list[str] = []
        first_name_idx = -1
        for i, line in enumerate(block):
            if self._is_candidate_name(line):
                if first_name_idx < 0:
                    first_name_idx = i
                if i == first_name_idx + len(consecutive_names):
                    consecutive_names.append(line)
                else:
                    break
            elif first_name_idx >= 0 and len(consecutive_names) > 0:
                break

        if len(consecutive_names) >= 2:
            # グループ型: 複数の候補者名が連続している
            return self._parse_grouped_candidates(
                block, first_name_idx, consecutive_names
            )

        # インターリーブ型
        return self._parse_interleaved_candidates(block)

    def _parse_grouped_candidates(
        self,
        block: list[str],
        name_start: int,
        names: list[str],
    ) -> list[Candidate]:
        """グループ型候補者ブロックをパースする。

        構造: 名前1, 名前2, ..., 名前N,
              賛成1, 賛成2, ..., 賛成N,
              反対1, 反対2, ..., 反対N,
              棄権1, 棄権2, ..., 棄権N,
              (注)X,
              結果1, 結果2, ..., 結果N
        """
        n = len(names)
        after_names = name_start + n

        # 名前以降の数値を全て収集
        nums: list[int | None] = []
        results: list[tuple[VoteResult, float]] = []
        i = after_names

        pending_rate: float | None = None
        while i < len(block):
            line = block[i]
            if self._is_vote_number(line):
                nums.append(self._get_vote_number(line))
                i += 1
            elif re.match(r"^[（\(]注[）\)]", line):
                i += 1
            elif self._parse_result_line(line):
                res = self._parse_result_line(line)
                if res:
                    results.append(res)
                pending_rate = None
                i += 1
            else:
                # 率→結果の順序に対応
                br = self._is_bare_rate(line)
                if br is not None:
                    pending_rate = br
                    i += 1
                elif self._is_bare_result(line) is not None:
                    r = pending_rate
                    result_val = (
                        VoteResult.APPROVED
                        if line.strip() == "可決"
                        else VoteResult.REJECTED
                    )
                    results.append((result_val, r))
                    pending_rate = None
                    i += 1
                else:
                    i += 1

        # 数値をN人分に分割
        votes_for = nums[0:n]
        votes_against = nums[n : 2 * n]
        votes_abstain = nums[2 * n : 3 * n]

        candidates: list[Candidate] = []
        for k, raw_name in enumerate(names):
            name = re.sub(r"[　\s]+", " ", raw_name).strip()
            rate: float | None = None
            if k < len(results):
                _, rate = results[k]
            candidates.append(
                Candidate(
                    name=name,
                    votes_for=(
                        votes_for[k] if k < len(votes_for) else None
                    ),
                    votes_against=(
                        votes_against[k]
                        if k < len(votes_against)
                        else None
                    ),
                    votes_abstain=(
                        votes_abstain[k]
                        if k < len(votes_abstain)
                        else None
                    ),
                    approval_rate=rate,
                )
            )

        return candidates

    def _parse_interleaved_candidates(
        self, block: list[str]
    ) -> list[Candidate]:
        """インターリーブ型候補者ブロックをパースする。

        構造: (名前 → 賛成 → 反対 → 棄権 → [(注)] → 結果) × 候補者数
        結果は1行（"可決　95.04"）か2行（"可決" + "95.04"）のケースあり。
        """
        candidates: list[Candidate] = []
        i = 0

        while i < len(block):
            line = block[i]

            if self._is_candidate_name(line):
                name = re.sub(r"[　\s]+", " ", line).strip()
                i += 1

                # 票数を読む（賛成、反対、棄権の最大3つ）
                votes: list[int | None] = []
                while i < len(block) and len(votes) < 3:
                    if self._is_vote_number(block[i]):
                        votes.append(
                            self._get_vote_number(block[i])
                        )
                        i += 1
                    else:
                        break

                # 注記行をスキップ
                while i < len(block) and re.match(
                    r"^[（\(]注[）\)]", block[i]
                ):
                    i += 1

                # 結果行を読む（率→結果 or 結果→率 の両方に対応）
                rate: float | None = None
                if i < len(block):
                    res = self._parse_result_line(block[i])
                    if res:
                        _, rate = res
                        i += 1
                    else:
                        # 率が先に来るケース: "92.05" → "可決"
                        pre_rate = self._is_bare_rate(block[i])
                        if pre_rate is not None:
                            rate = pre_rate
                            i += 1
                            # 続く"可決"/"否決"行はスキップ
                            if i < len(block):
                                if (
                                    self._is_bare_result(block[i])
                                    is not None
                                ):
                                    i += 1
                        else:
                            # 結果が先: "可決" → "92.05"
                            bare = self._is_bare_result(block[i])
                            if bare is not None:
                                i += 1
                                if i < len(block):
                                    r = self._is_bare_rate(
                                        block[i]
                                    )
                                    if r is not None:
                                        rate = r
                                        i += 1

                candidates.append(
                    Candidate(
                        name=name,
                        votes_for=(
                            votes[0] if len(votes) > 0 else None
                        ),
                        votes_against=(
                            votes[1] if len(votes) > 1 else None
                        ),
                        votes_abstain=(
                            votes[2] if len(votes) > 2 else None
                        ),
                        approval_rate=rate,
                    )
                )
            else:
                i += 1

        return candidates

    def _parse_simple_block(
        self, block: list[str]
    ) -> dict:
        """候補者なしブロック（単純議案）をパースする。

        構造: 賛成票 → 反対票 → 棄権票 → [(注)N] → 結果行
        結果は1行 or 2行のケースあり。
        率と結果の順序は「可決（96.58）」「可決→96.58」
        「96.58→可決」のいずれも対応。
        """
        result: dict = {}
        votes: list[int | None] = []
        pending_rate: float | None = None
        i = 0

        while i < len(block):
            line = block[i]

            if self._is_vote_number(line) and len(votes) < 3:
                votes.append(self._get_vote_number(line))
                i += 1
                continue

            # 注記行スキップ
            if re.match(r"^[（\(]注[）\)]", line):
                i += 1
                continue

            # 結果行（1行完結: "可決（96.58％）"）
            res = self._parse_result_line(line)
            if res:
                vote_result, rate = res
                result["result"] = vote_result
                result["rate"] = rate
                i += 1
                continue

            # 率が先に来るケース: "96.58" → "可決"
            bare_rate = self._is_bare_rate(line)
            if bare_rate is not None and "rate" not in result:
                pending_rate = bare_rate
                i += 1
                continue

            # 結果行（"可決" のみ）
            bare = self._is_bare_result(line)
            if bare is not None:
                result["result"] = bare
                i += 1
                # 保留中の率があればそれを使う
                if pending_rate is not None:
                    result["rate"] = pending_rate
                    pending_rate = None
                elif i < len(block):
                    # 可決の後に率が来るケース
                    r = self._is_bare_rate(block[i])
                    if r is not None:
                        result["rate"] = r
                        i += 1
                continue

            i += 1

        if len(votes) > 0:
            result["for"] = votes[0]
        if len(votes) > 1:
            result["against"] = votes[1]
        if len(votes) > 2:
            result["abstain"] = votes[2]

        return result
