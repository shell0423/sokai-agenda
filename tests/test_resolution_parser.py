from __future__ import annotations

import io
import zipfile

import pytest

from src.models import ProposalType, VoteResult
from src.resolution_parser import ResolutionParser

# 太陽HD 2024年（株主提案なし、8議案）の議決結果セクションを模擬
TAIYO_2024_HTML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns:ix="http://www.xbrl.org/2008/inlineXBRL"
      xmlns:jpcrp-esr_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp-esr/2021-11-01/jpcrp-esr_cor">
<head><title>test</title></head>
<body>
<ix:nonNumeric name="jpcrp-esr_cor:ResolutionOfShareholdersMeetingTextBlock" contextRef="FilingDateInstant" escape="true">
<p>(3）当該決議事項に対する賛成、反対及び棄権の意思の表示に係る議決権の数、当該決議事項が可決されるための要件並びに当該決議の結果</p>
<table>
<tr><td>決議事項</td><td>賛成（個）</td><td>反対（個）</td><td>棄権（個）</td><td>可決要件</td><td>決議の結果及び</td><td>賛成割合（％）</td></tr>
<tr><td>第1号議案　剰余金処分の件</td></tr>
<tr><td>487,750</td></tr>
<tr><td>303</td></tr>
<tr><td>286</td></tr>
<tr><td>（注）1</td></tr>
<tr><td>可決（99.31％）</td></tr>
<tr><td>第2号議案　定款一部変更の件</td></tr>
<tr><td>470,016</td></tr>
<tr><td>18,036</td></tr>
<tr><td>286</td></tr>
<tr><td>（注）2</td></tr>
<tr><td>可決（95.70％）</td></tr>
<tr><td>第3号議案　取締役（監査等委員である取締役を除く。）4名選任の件</td></tr>
<tr><td>佐藤　英志</td></tr>
<tr><td>齋藤　斉</td></tr>
<tr><td>髙野　聖史</td></tr>
<tr><td>土屋　恵子</td></tr>
<tr><td>481,036</td></tr>
<tr><td>484,663</td></tr>
<tr><td>484,647</td></tr>
<tr><td>485,463</td></tr>
<tr><td>6,901</td></tr>
<tr><td>3,386</td></tr>
<tr><td>3,402</td></tr>
<tr><td>2,586</td></tr>
<tr><td>402</td></tr>
<tr><td>290</td></tr>
<tr><td>290</td></tr>
<tr><td>290</td></tr>
<tr><td>（注）3</td></tr>
<tr><td>可決（97.95％）</td></tr>
<tr><td>可決（98.69％）</td></tr>
<tr><td>可決（98.68％）</td></tr>
<tr><td>可決（98.85％）</td></tr>
</table>
<p>(4）議決権の数に</p>
</ix:nonNumeric>
</body>
</html>"""

# 太陽HD 2025年（株主提案あり、佐藤英志否決）の議決結果セクション
TAIYO_2025_HTML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns:ix="http://www.xbrl.org/2008/inlineXBRL"
      xmlns:jpcrp-esr_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp-esr/2021-11-01/jpcrp-esr_cor">
<head><title>test</title></head>
<body>
<ix:nonNumeric name="jpcrp-esr_cor:ResolutionOfShareholdersMeetingTextBlock" contextRef="FilingDateInstant" escape="true">
<p>③当該決議事項に対する賛成、反対及び棄権の意思の表示に係る議決権の数、当該決議事項が可決されるための要件並びに当該決議の結果</p>
<p>〈会社提案（第1号議案から第3号議案まで）〉</p>
<table>
<tr><td>決議事項</td><td>賛成（個）</td><td>反対（個）</td><td>棄権（個）</td><td>可決要件</td><td>決議の結果及び</td><td>賛成割合（％）</td></tr>
<tr><td>第1号議案　資本準備金及び利益準備金の額の減少の件</td></tr>
<tr><td>328,219</td></tr>
<tr><td>170,562</td></tr>
<tr><td>5,467</td></tr>
<tr><td>（注）1</td></tr>
<tr><td>可決（64.50％）</td></tr>
<tr><td>第2号議案　取締役（監査等委員である取締役を除く。）4名選任の件</td></tr>
<tr><td>佐藤　英志</td></tr>
<tr><td>齋藤　斉</td></tr>
<tr><td>土屋　恵子</td></tr>
<tr><td>丸山　みさえ</td></tr>
<tr><td>234,557</td></tr>
<tr><td>424,626</td></tr>
<tr><td>373,414</td></tr>
<tr><td>490,032</td></tr>
<tr><td>264,215</td></tr>
<tr><td>74,146</td></tr>
<tr><td>125,359</td></tr>
<tr><td>8,742</td></tr>
<tr><td>5,467</td></tr>
<tr><td>5,467</td></tr>
<tr><td>5,467</td></tr>
<tr><td>5,467</td></tr>
<tr><td>（注）2</td></tr>
<tr><td>否決（46.09％）</td></tr>
<tr><td>可決（83.45％）</td></tr>
<tr><td>可決（73.38％）</td></tr>
<tr><td>可決（96.30％）</td></tr>
<tr><td>第3号議案　監査等委員である取締役1名選任の件</td></tr>
<tr><td>嶋村　紀明</td></tr>
<tr><td>490,062</td></tr>
<tr><td>8,656</td></tr>
<tr><td>5,467</td></tr>
<tr><td>（注）2</td></tr>
<tr><td>可決（96.32％）</td></tr>
</table>
<p>〈株主提案（第4号議案及び第5号議案）〉</p>
<table>
<tr><td>決議事項</td><td>賛成（個）</td><td>反対（個）</td><td>棄権（個）</td><td>可決要件</td><td>決議の結果及び</td><td>賛成割合（％）</td></tr>
<tr><td>第4号議案　取締役佐藤英志氏解任の件</td></tr>
<tr><td>253,802</td></tr>
<tr><td>249,328</td></tr>
<tr><td>5,467</td></tr>
<tr><td>（注）2・3</td></tr>
<tr><td>否決（49.90％）</td></tr>
<tr><td>第5号議案　取締役髙野聖史氏解任の件</td></tr>
<tr><td>124,284</td></tr>
<tr><td>374,225</td></tr>
<tr><td>5,467</td></tr>
<tr><td>（注）2</td></tr>
<tr><td>否決（24.44％）</td></tr>
</table>
<p>④議決権の数に</p>
</ix:nonNumeric>
</body>
</html>"""

# 株式報酬制度の臨時報告書（ResolutionOfShareholdersMeetingタグなし）
NON_RESOLUTION_HTML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns:ix="http://www.xbrl.org/2008/inlineXBRL"
      xmlns:jpcrp-esr_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp-esr/2021-11-01/jpcrp-esr_cor">
<head><title>test</title></head>
<body>
<ix:nonNumeric name="jpcrp-esr_cor:IssueOfStockOptionsNotSubjectToSecuritiesRegistrationTextBlock" contextRef="FilingDateInstant" escape="true">
<p>株式報酬の件</p>
</ix:nonNumeric>
</body>
</html>"""


def _make_zip(html_content: str, filename: str = "honbun_ixbrl.htm") -> bytes:
    """テスト用ZIPファイルを作成する。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"XBRL/PublicDoc/{filename}", html_content)
    return buf.getvalue()


class TestHasResolutionTag:
    """has_resolution_tag のテスト。"""

    def test_resolution_report_returns_true(self) -> None:
        parser = ResolutionParser()
        zip_bytes = _make_zip(TAIYO_2024_HTML)
        assert parser.has_resolution_tag(zip_bytes) is True

    def test_non_resolution_report_returns_false(self) -> None:
        parser = ResolutionParser()
        zip_bytes = _make_zip(NON_RESOLUTION_HTML)
        assert parser.has_resolution_tag(zip_bytes) is False

    def test_invalid_zip_returns_false(self) -> None:
        parser = ResolutionParser()
        assert parser.has_resolution_tag(b"not a zip") is False


class TestParseTaiyo2024:
    """太陽HD 2024年（株主提案なし）のパーステスト。"""

    @pytest.fixture()
    def proposals(self) -> list:
        parser = ResolutionParser()
        zip_bytes = _make_zip(TAIYO_2024_HTML)
        result = parser.parse_zip(zip_bytes)
        assert result is not None
        return result

    def test_proposal_count(self, proposals: list) -> None:
        assert len(proposals) == 3  # 3議案（候補者付き含む）

    def test_first_proposal(self, proposals: list) -> None:
        p = proposals[0]
        assert p.number == 1
        assert p.title == "剰余金処分の件"
        assert p.proposal_type == ProposalType.COMPANY
        assert p.result == VoteResult.APPROVED
        assert p.approval_rate == 99.31
        assert p.votes_for == 487750
        assert p.votes_against == 303
        assert p.votes_abstain == 286

    def test_candidate_proposal(self, proposals: list) -> None:
        p = proposals[2]  # 第3号議案
        assert p.number == 3
        assert len(p.candidates) == 4
        assert p.candidates[0].name == "佐藤 英志"
        assert p.candidates[0].votes_for == 481036
        assert p.candidates[0].approval_rate == 97.95

    def test_all_company_proposals(self, proposals: list) -> None:
        for p in proposals:
            assert p.proposal_type == ProposalType.COMPANY


class TestParseTaiyo2025:
    """太陽HD 2025年（株主提案あり、佐藤英志否決）のパーステスト。"""

    @pytest.fixture()
    def proposals(self) -> list:
        parser = ResolutionParser()
        zip_bytes = _make_zip(TAIYO_2025_HTML)
        result = parser.parse_zip(zip_bytes)
        assert result is not None
        return result

    def test_proposal_count(self, proposals: list) -> None:
        # 第1号〜第3号（会社提案）+ 第4号・第5号（株主提案）= 5議案
        assert len(proposals) == 5

    def test_sato_rejected(self, proposals: list) -> None:
        """佐藤英志が否決されたことの確認。"""
        p2 = proposals[1]  # 第2号議案
        assert p2.number == 2
        sato = p2.candidates[0]
        assert sato.name == "佐藤 英志"
        assert sato.votes_for == 234557
        assert sato.votes_against == 264215
        assert sato.approval_rate == 46.09

    def test_maruyama_approved(self, proposals: list) -> None:
        """丸山みさえ（ひらがな名）が可決されたことの確認。"""
        p2 = proposals[1]
        maruyama = p2.candidates[3]
        assert maruyama.name == "丸山 みさえ"
        assert maruyama.approval_rate == 96.30

    def test_shareholder_proposals(self, proposals: list) -> None:
        """株主提案が正しく検出されることの確認。"""
        p4 = proposals[3]
        assert p4.number == 4
        assert p4.proposal_type == ProposalType.SHAREHOLDER
        assert p4.title == "取締役佐藤英志氏解任の件"
        assert p4.result == VoteResult.REJECTED
        assert p4.approval_rate == 49.90

        p5 = proposals[4]
        assert p5.number == 5
        assert p5.proposal_type == ProposalType.SHAREHOLDER
        assert p5.result == VoteResult.REJECTED
        assert p5.approval_rate == 24.44

    def test_company_proposals(self, proposals: list) -> None:
        """第1号〜第3号が会社提案であることの確認。"""
        for p in proposals[:3]:
            assert p.proposal_type == ProposalType.COMPANY


# インターリーブ型（ローツェ形式: 候補者→賛成→反対→棄権→結果を繰り返す）
INTERLEAVED_HTML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns:ix="http://www.xbrl.org/2008/inlineXBRL"
      xmlns:jpcrp-esr_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp-esr/2021-11-01/jpcrp-esr_cor">
<head><title>test</title></head>
<body>
<ix:nonNumeric name="jpcrp-esr_cor:ResolutionOfShareholdersMeetingTextBlock" contextRef="FilingDateInstant" escape="true">
<p>(3）決議事項に対する賛成、反対及び棄権の意思の表示に係る議決権の数、当該決議事項が可決されるための要件並びに当該決議の結果</p>
<table>
<tr><td>決議事項</td><td>賛成（個）</td><td>反対（個）</td><td>棄権（個）</td><td>可決要件</td><td>決議の結果及び</td><td>賛成割合（％）</td></tr>
<tr><td>第１号議案</td></tr>
<tr><td>1,348,500</td></tr>
<tr><td>5,769</td></tr>
<tr><td>0</td></tr>
<tr><td>（注）１</td></tr>
<tr><td>可決　95.04</td></tr>
<tr><td>第２号議案</td></tr>
<tr><td>藤代　祥之</td></tr>
<tr><td>1,302,803</td></tr>
<tr><td>51,457</td></tr>
<tr><td>0</td></tr>
<tr><td>可決　91.82</td></tr>
<tr><td>中村　秀春</td></tr>
<tr><td>1,344,688</td></tr>
<tr><td>9,581</td></tr>
<tr><td>0</td></tr>
<tr><td>可決　94.77</td></tr>
</table>
<p>(4）議決権の数に</p>
</ix:nonNumeric>
</body>
</html>"""

# ダッシュ棄権 + 括弧つき結果（アークランズ形式）
DASH_ABSTAIN_HTML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns:ix="http://www.xbrl.org/2008/inlineXBRL"
      xmlns:jpcrp-esr_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp-esr/2021-11-01/jpcrp-esr_cor">
<head><title>test</title></head>
<body>
<ix:nonNumeric name="jpcrp-esr_cor:ResolutionOfShareholdersMeetingTextBlock" contextRef="FilingDateInstant" escape="true">
<p>(3）当該決議事項に対する賛成、反対及び棄権の意思の表示に係る議決権の数、当該決議事項が可決されるための要件並びに当該決議の結果</p>
<table>
<tr><td>決議事項</td><td>賛成（個）</td><td>反対（個）</td><td>棄権（個）</td><td>可決要件</td><td>決議の結果及び賛成割合（％）</td></tr>
<tr><td>第１号議案</td></tr>
<tr><td>421,974</td></tr>
<tr><td>7,512</td></tr>
<tr><td>－</td></tr>
<tr><td>（注）１</td></tr>
<tr><td>可決　（97.73％）</td></tr>
<tr><td>第２号議案</td></tr>
<tr><td>坂本　晴彦</td></tr>
<tr><td>419,071</td></tr>
<tr><td>10,387</td></tr>
<tr><td>42</td></tr>
<tr><td>（注）２</td></tr>
<tr><td>可決　（97.06％）</td></tr>
<tr><td>佐藤　好文</td></tr>
<tr><td>419,132</td></tr>
<tr><td>10,326</td></tr>
<tr><td>42</td></tr>
<tr><td>（注）２</td></tr>
<tr><td>可決　（97.07％）</td></tr>
</table>
<p>(4）議決権の数に</p>
</ix:nonNumeric>
</body>
</html>"""


class TestParseInterleaved:
    """インターリーブ型（ローツェ形式）のパーステスト。"""

    @pytest.fixture()
    def proposals(self) -> list:
        parser = ResolutionParser()
        zip_bytes = _make_zip(INTERLEAVED_HTML)
        result = parser.parse_zip(zip_bytes)
        assert result is not None
        return result

    def test_proposal_count(self, proposals: list) -> None:
        assert len(proposals) == 2

    def test_simple_proposal(self, proposals: list) -> None:
        p = proposals[0]
        assert p.number == 1
        assert p.votes_for == 1348500
        assert p.votes_against == 5769
        assert p.votes_abstain == 0
        assert p.approval_rate == 95.04

    def test_interleaved_candidates(self, proposals: list) -> None:
        p = proposals[1]
        assert p.number == 2
        assert len(p.candidates) == 2
        assert p.candidates[0].name == "藤代 祥之"
        assert p.candidates[0].votes_for == 1302803
        assert p.candidates[0].votes_against == 51457
        assert p.candidates[0].votes_abstain == 0
        assert p.candidates[0].approval_rate == 91.82
        assert p.candidates[1].name == "中村 秀春"
        assert p.candidates[1].approval_rate == 94.77


class TestParseDashAbstain:
    """ダッシュ棄権 + 括弧つき結果（アークランズ形式）のテスト。"""

    @pytest.fixture()
    def proposals(self) -> list:
        parser = ResolutionParser()
        zip_bytes = _make_zip(DASH_ABSTAIN_HTML)
        result = parser.parse_zip(zip_bytes)
        assert result is not None
        return result

    def test_dash_is_zero(self, proposals: list) -> None:
        p = proposals[0]
        assert p.votes_abstain == 0

    def test_paren_rate(self, proposals: list) -> None:
        p = proposals[0]
        assert p.approval_rate == 97.73

    def test_candidate_with_notes(self, proposals: list) -> None:
        p = proposals[1]
        assert len(p.candidates) == 2
        assert p.candidates[0].name == "坂本 晴彦"
        assert p.candidates[0].votes_for == 419071
        assert p.candidates[0].votes_abstain == 42
        assert p.candidates[0].approval_rate == 97.06


class TestParseNonResolution:
    """株主総会決議以外の臨時報告書。"""

    def test_returns_none(self) -> None:
        parser = ResolutionParser()
        zip_bytes = _make_zip(NON_RESOLUTION_HTML)
        assert parser.parse_zip(zip_bytes) is None


# タイトルが次行にある形式 + 賛成率が結果テキストになく票数のみ
TITLE_NEXTLINE_HTML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns:ix="http://www.xbrl.org/2008/inlineXBRL"
      xmlns:jpcrp-esr_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp-esr/2021-11-01/jpcrp-esr_cor">
<head><title>test</title></head>
<body>
<ix:nonNumeric name="jpcrp-esr_cor:ResolutionOfShareholdersMeetingTextBlock" contextRef="FilingDateInstant" escape="true">
<p>(3）決議事項に対する賛成、反対及び棄権の意思の表示に係る議決権の数</p>
<table>
<tr><td>決議事項</td><td>賛成（個）</td><td>反対（個）</td><td>棄権（個）</td></tr>
<tr><td>第１号議案</td></tr>
<tr><td>剰余金の処分の件</td></tr>
<tr><td>100,000</td></tr>
<tr><td>5,000</td></tr>
<tr><td>500</td></tr>
<tr><td>（注）1</td></tr>
<tr><td>可決</td></tr>
<tr><td>第２号議案</td></tr>
<tr><td>取締役選任の件</td></tr>
<tr><td>田中 太郎</td></tr>
<tr><td>90,000</td></tr>
<tr><td>10,000</td></tr>
<tr><td>500</td></tr>
<tr><td>可決</td></tr>
<tr><td>山田 花子</td></tr>
<tr><td>95,000</td></tr>
<tr><td>5,000</td></tr>
<tr><td>500</td></tr>
<tr><td>可決</td></tr>
</table>
<p>(4）議決権の数</p>
</ix:nonNumeric>
</body>
</html>"""


class TestTitleNextLine:
    """タイトルが第N号議案の次行にある形式のテスト。"""

    @pytest.fixture()
    def proposals(self) -> list:
        parser = ResolutionParser()
        zip_bytes = _make_zip(TITLE_NEXTLINE_HTML)
        result = parser.parse_zip(zip_bytes)
        assert result is not None
        return result

    def test_proposal_count(self, proposals: list) -> None:
        assert len(proposals) == 2

    def test_title_from_next_line(self, proposals: list) -> None:
        """第N号議案の次行にあるタイトルが取得できる。"""
        assert proposals[0].title == "剰余金の処分の件"
        assert proposals[1].title == "取締役選任の件"

    def test_rate_calculated_from_votes(self, proposals: list) -> None:
        """結果テキストに賛成率がない場合、票数から計算する。"""
        p = proposals[0]
        # 100000 / (100000 + 5000 + 500) = 94.79%
        assert p.approval_rate is not None
        assert abs(p.approval_rate - 94.79) < 0.1

    def test_candidate_rate_calculated(self, proposals: list) -> None:
        """候補者の賛成率も票数から計算される。"""
        p = proposals[1]
        assert len(p.candidates) == 2
        # 田中: 90000 / (90000+10000+500) = 89.55%
        assert p.candidates[0].approval_rate is not None
        assert abs(p.candidates[0].approval_rate - 89.55) < 0.1
        # 山田: 95000 / (95000+5000+500) = 94.53%
        assert p.candidates[1].approval_rate is not None
        assert abs(p.candidates[1].approval_rate - 94.53) < 0.1


# 中国電力パターン: タイトルなし + 「賛成」「128,451個」等がタイトルに混入
CHUGOKU_PATTERN_HTML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns:ix="http://www.xbrl.org/2008/inlineXBRL"
      xmlns:jpcrp-esr_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp-esr/2021-11-01/jpcrp-esr_cor">
<head><title>test</title></head>
<body>
<ix:nonNumeric name="jpcrp-esr_cor:ResolutionOfShareholdersMeetingTextBlock" contextRef="FilingDateInstant" escape="true">
<p>(3）当該決議事項に対する賛成、反対及び棄権の意思の表示に係る議決権の数、当該決議事項が可決されるための要件並びに当該決議の結果</p>
<p>〈会社提案〉</p>
<table>
<tr><td>決議事項</td><td>賛成（個）</td><td>反対（個）</td><td>棄権（個）</td></tr>
<tr><td>第１号議案　剰余金処分の件</td></tr>
<tr><td>500,000</td></tr>
<tr><td>3,000</td></tr>
<tr><td>200</td></tr>
<tr><td>（注）１</td></tr>
<tr><td>可決（99.36％）</td></tr>
</table>
<p>〈株主提案〉</p>
<table>
<tr><td>決議事項</td><td>賛成（個）</td><td>反対（個）</td><td>棄権（個）</td></tr>
<tr><td>第２号議案</td></tr>
<tr><td>賛成</td></tr>
<tr><td>128,451個</td></tr>
<tr><td>131,653個</td></tr>
<tr><td>135,952個</td></tr>
<tr><td>否決（25.51％）</td></tr>
<tr><td>第３号議案</td></tr>
<tr><td>200,003個</td></tr>
<tr><td>262,897個</td></tr>
<tr><td>40,300個</td></tr>
<tr><td>否決（39.75％）</td></tr>
</table>
<p>(4）議決権の数に</p>
</ix:nonNumeric>
</body>
</html>"""


class TestChugokuPattern:
    """中国電力パターン: 「賛成」「128,451個」等がタイトルに混入しないことを
    確認するテスト。"""

    @pytest.fixture()
    def proposals(self) -> list:
        parser = ResolutionParser()
        zip_bytes = _make_zip(CHUGOKU_PATTERN_HTML)
        result = parser.parse_zip(zip_bytes)
        assert result is not None
        return result

    def test_sansei_not_as_title(self, proposals: list) -> None:
        """「賛成」がタイトルとして使用されない。"""
        for p in proposals:
            assert p.title != "賛成"

    def test_vote_count_not_as_title(self, proposals: list) -> None:
        """「128,451個」等の票数がタイトルとして使用されない。"""
        for p in proposals:
            assert "個" not in p.title

    def test_company_proposal_has_title(self, proposals: list) -> None:
        """会社提案の議案タイトルは正常に取得できる。"""
        p1 = proposals[0]
        assert p1.number == 1
        assert p1.title == "剰余金処分の件"
        assert p1.proposal_type == ProposalType.COMPANY

    def test_shareholder_proposals_detected(self, proposals: list) -> None:
        """株主提案が正しく検出される。"""
        shareholder = [
            p for p in proposals
            if p.proposal_type == ProposalType.SHAREHOLDER
        ]
        assert len(shareholder) >= 1


# 注記参照がタイトルに混入するパターン
NOTE_AS_TITLE_HTML = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns:ix="http://www.xbrl.org/2008/inlineXBRL"
      xmlns:jpcrp-esr_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp-esr/2021-11-01/jpcrp-esr_cor">
<head><title>test</title></head>
<body>
<ix:nonNumeric name="jpcrp-esr_cor:ResolutionOfShareholdersMeetingTextBlock" contextRef="FilingDateInstant" escape="true">
<p>(3）当該決議事項に対する賛成、反対及び棄権の意思の表示に係る議決権の数</p>
<table>
<tr><td>決議事項</td><td>賛成（個）</td><td>反対（個）</td><td>棄権（個）</td></tr>
<tr><td>第１号議案</td></tr>
<tr><td>（注）４</td></tr>
<tr><td>50,000</td></tr>
<tr><td>10,000</td></tr>
<tr><td>500</td></tr>
<tr><td>否決（82.64％）</td></tr>
</table>
<p>(4）議決権の数</p>
</ix:nonNumeric>
</body>
</html>"""


class TestNoteAsTitle:
    """注記参照がタイトルに混入しないことを確認するテスト。"""

    @pytest.fixture()
    def proposals(self) -> list:
        parser = ResolutionParser()
        zip_bytes = _make_zip(NOTE_AS_TITLE_HTML)
        result = parser.parse_zip(zip_bytes)
        assert result is not None
        return result

    def test_note_not_as_title(self, proposals: list) -> None:
        """「（注）４」がタイトルとして使用されない。"""
        p = proposals[0]
        assert "注" not in p.title


class TestIsNonTitleLine:
    """_is_non_title_line メソッドの単体テスト。"""

    def setup_method(self) -> None:
        self.parser = ResolutionParser()

    def test_bare_sansei(self) -> None:
        assert self.parser._is_non_title_line("賛成") is True

    def test_bare_hantai(self) -> None:
        assert self.parser._is_non_title_line("反対") is True

    def test_bare_kiken(self) -> None:
        assert self.parser._is_non_title_line("棄権") is True

    def test_vote_count_with_unit(self) -> None:
        assert self.parser._is_non_title_line("128,451個") is True

    def test_vote_count_with_unit_fullwidth(self) -> None:
        assert self.parser._is_non_title_line("２００，００３個") is True

    def test_note_reference(self) -> None:
        assert self.parser._is_non_title_line("（注）４") is True

    def test_note_reference_halfwidth(self) -> None:
        assert self.parser._is_non_title_line("(注)2・3") is True

    def test_percentage(self) -> None:
        assert self.parser._is_non_title_line("95.04") is True

    def test_percentage_with_symbol(self) -> None:
        assert self.parser._is_non_title_line("95.04％") is True

    def test_pure_number(self) -> None:
        assert self.parser._is_non_title_line("128,451") is True

    def test_real_title_passes(self) -> None:
        assert (
            self.parser._is_non_title_line("剰余金の処分の件")
            is False
        )

    def test_director_title_passes(self) -> None:
        assert (
            self.parser._is_non_title_line("取締役選任の件")
            is False
        )

    def test_shareholder_title_passes(self) -> None:
        assert (
            self.parser._is_non_title_line(
                "取締役佐藤英志氏解任の件"
            )
            is False
        )


class TestParseResultLineRate:
    """_parse_result_line の賛成率 None 修正テスト。"""

    def setup_method(self) -> None:
        self.parser = ResolutionParser()

    def test_normal_result(self) -> None:
        """通常の結果行。"""
        res = self.parser._parse_result_line("可決（95.04％）")
        assert res is not None
        assert res[0] == VoteResult.APPROVED
        assert res[1] == 95.04

    def test_rejected_result(self) -> None:
        """否決の結果行。"""
        res = self.parser._parse_result_line("否決（30.50）")
        assert res is not None
        assert res[0] == VoteResult.REJECTED
        assert res[1] == 30.50

    def test_no_match(self) -> None:
        """結果行でない行。"""
        assert self.parser._parse_result_line("佐藤 英志") is None


class TestGroupedCandidateRate:
    """グループ型候補者の率が None になるケースのテスト。"""

    def setup_method(self) -> None:
        self.parser = ResolutionParser()

    def test_bare_result_without_rate(self) -> None:
        """率なしの「可決」行 → approval_rate は票数から計算。"""
        # グループ型: 名前2人 → 票数 → 可決（率なし）
        block = [
            "山田 太郎",
            "鈴木 花子",
            "39296",  # 山田 賛成
            "39278",  # 鈴木 賛成
            "293",    # 山田 反対
            "311",    # 鈴木 反対
            "10",     # 山田 棄権
            "15",     # 鈴木 棄権
            "可決",   # 率なし
            "可決",   # 率なし
        ]
        candidates = self.parser._parse_grouped_candidates(
            block, 0, ["山田 太郎", "鈴木 花子"]
        )
        assert len(candidates) == 2
        # 率が None（0.0 ではない）→ _calc_approval_rate で補完
        assert candidates[0].approval_rate is None
        assert candidates[1].approval_rate is None
