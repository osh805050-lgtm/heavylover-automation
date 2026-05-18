import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parent.parent))

GOBIZ_HTML = """
<html><body>
  <a href="/support/ebsns/supporteBsnsInfo.do?svc=e54">칠레 전자상거래플랫폼 진출지원 사업 참여기업 모집공고</a>
  <a href="/support/ebsns/supporteBsnsInfo.do?svc=e56">K-패션 해외(일본) 유통망 공동 진출사업 모집공고</a>
  <a href="#">메뉴 (제외 — href=#)</a>
  <a href="javascript:goNoticeDetail('1')">JS 공고 (제외)</a>
</body></html>
"""

_EMPTY = ("", "https://kr.gobizkorea.com/")
_SAMPLE = (GOBIZ_HTML, "https://kr.gobizkorea.com/")

def test_fetch_gobiz_pw_returns_empty_on_no_html():
    from lib import govt_playwright
    with patch.object(govt_playwright, "_fetch_with_playwright", return_value=_EMPTY):
        assert govt_playwright.fetch_gobiz_pw() == []

def test_fetch_gobiz_pw_parses_support_links():
    from lib import govt_playwright
    with patch.object(govt_playwright, "_fetch_with_playwright", return_value=_SAMPLE):
        items = govt_playwright.fetch_gobiz_pw()
    assert len(items) == 2

def test_fetch_gobiz_pw_excludes_hash_and_js():
    from lib import govt_playwright
    with patch.object(govt_playwright, "_fetch_with_playwright", return_value=_SAMPLE):
        items = govt_playwright.fetch_gobiz_pw()
    urls = [it["url"] for it in items]
    assert not any(u == "#" or "javascript" in u for u in urls)

def test_fetch_gobiz_pw_schema():
    from lib import govt_playwright
    with patch.object(govt_playwright, "_fetch_with_playwright", return_value=_SAMPLE):
        items = govt_playwright.fetch_gobiz_pw()
    assert all(it["source"] == "고비즈코리아" for it in items)
    assert all(it["url"].startswith("https://") for it in items)

def test_fetch_gobiz_pw_in_playwright_sources():
    from lib.govt_playwright import PLAYWRIGHT_SOURCES
    names = [name for name, _ in PLAYWRIGHT_SOURCES]
    assert "고비즈코리아(PW)" in names
