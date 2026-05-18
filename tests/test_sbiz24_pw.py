"""fetch_sbiz24_pw + _fetch_with_playwright wait_until 단위 테스트 (TDD Red→Green)."""
import inspect
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


# ─── _fetch_with_playwright 파라미터 테스트 ───────────────────────────────────

def test_fetch_with_playwright_accepts_wait_until_param():
    """`wait_until` 파라미터가 시그니처에 있고 기본값이 'domcontentloaded'."""
    from lib.govt_sources import _fetch_with_playwright
    sig = inspect.signature(_fetch_with_playwright)
    assert "wait_until" in sig.parameters
    assert sig.parameters["wait_until"].default == "domcontentloaded"


# ─── fetch_sbiz24_pw 파싱 테스트 ─────────────────────────────────────────────

_SAMPLE_HTML = """
<table>
  <tbody>
    <tr>
      <td>1</td><td>모집공고</td>
      <td class="q-td text-left c_pbancNm">2026년 소상공인 고용보험료 지원사업 공고</td>
      <td>2026.01.01</td>
      <td>2026.03.01 ~ 2026.09.30</td>
      <td>신청</td>
    </tr>
    <tr>
      <td>2</td><td>모집공고</td>
      <td class="q-td text-left c_pbancNm">강한 소상공인 성장지원사업 모집공고</td>
      <td>2026.01.01</td>
      <td>2026.03.01 ~ 2026.12.31</td>
      <td>신청</td>
    </tr>
  </tbody>
</table>
"""

_EMPTY_RESULT = ("", "https://www.sbiz24.kr/#/pbanc")
_SAMPLE_RESULT = (_SAMPLE_HTML, "https://www.sbiz24.kr/#/pbanc")


def test_fetch_sbiz24_pw_returns_empty_on_no_html():
    """HTML이 없으면 빈 리스트 반환."""
    from lib import govt_playwright
    with patch.object(govt_playwright, "_fetch_with_playwright", return_value=_EMPTY_RESULT):
        assert govt_playwright.fetch_sbiz24_pw() == []


def test_fetch_sbiz24_pw_parses_two_rows():
    """정상 HTML에서 2건 파싱."""
    from lib import govt_playwright
    with patch.object(govt_playwright, "_fetch_with_playwright", return_value=_SAMPLE_RESULT):
        items = govt_playwright.fetch_sbiz24_pw()
    assert len(items) == 2


def test_fetch_sbiz24_pw_schema():
    """source·url·agency 스키마 준수."""
    from lib import govt_playwright
    with patch.object(govt_playwright, "_fetch_with_playwright", return_value=_SAMPLE_RESULT):
        items = govt_playwright.fetch_sbiz24_pw()
    item = items[0]
    assert item["source"] == "소상공인24"
    assert item["url"] == "https://www.sbiz24.kr/#/pbanc"
    assert item["agency"] == "소상공인시장진흥공단"
    assert "고용보험료" in item["title"]


def test_fetch_sbiz24_pw_extracts_deadline():
    """접수기간 'YYYY.MM.DD ~ YYYY.MM.DD'에서 마감일(뒷날짜) 추출."""
    from lib import govt_playwright
    with patch.object(govt_playwright, "_fetch_with_playwright", return_value=_SAMPLE_RESULT):
        items = govt_playwright.fetch_sbiz24_pw()
    # 첫 번째 row: ~ 2026.09.30
    assert items[0]["deadline"] == "2026-09-30"


def test_fetch_sbiz24_pw_deduplicates_same_title():
    """동일 제목 중복 제거."""
    dup_html = """
    <table><tbody>
      <tr><td class="c_pbancNm">동일 공고 제목 모집공고</td></tr>
      <tr><td class="c_pbancNm">동일 공고 제목 모집공고</td></tr>
    </tbody></table>
    """
    from lib import govt_playwright
    with patch.object(govt_playwright, "_fetch_with_playwright", return_value=(dup_html, "https://www.sbiz24.kr/#/pbanc")):
        items = govt_playwright.fetch_sbiz24_pw()
    assert len(items) == 1


def test_fetch_sbiz24_pw_uses_networkidle():
    """networkidle wait_until으로 _fetch_with_playwright를 호출하는지."""
    from lib import govt_playwright
    with patch.object(govt_playwright, "_fetch_with_playwright", return_value=_EMPTY_RESULT) as mock_fetch:
        govt_playwright.fetch_sbiz24_pw()
    _, kwargs = mock_fetch.call_args
    assert kwargs.get("wait_until") == "networkidle"
