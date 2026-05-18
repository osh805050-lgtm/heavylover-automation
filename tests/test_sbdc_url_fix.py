import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).parent.parent))

# 실제 kodma.or.kr 공지사항 게시판 HTML 구조 반영:
# - 공고 링크: href="#", onclick="goView('XXXXXXX')", parent div.title
# - 채용: href="/incruit/list.do?..." (div.title 밖)
# - 입찰: href="/bid/..." (div.title 밖)
SAMPLE_HTML = """
<html><body>
  <div class="title">
    <a href="#" onclick="goView('2605140002')">[공고] 2026 브랜드 소상공인 점프업사업 참여기업 모집 공고</a>
  </div>
  <div class="title">
    <a href="#" onclick="goView('2605110001')">[공고] 2026년 소상공인 온라인판로 지원사업 참여기업 모집공고</a>
  </div>
  <a href="/incruit/list.do?key=2409240031&sc_chkInct=inct">채용공고 (제외)</a>
  <a href="/bid/view.do?key=1&bidSn=1">입찰공고 (제외)</a>
  <div class="pagination">
    <a href="#" onclick="fn_egov_link_page(2); return false;">2</a>
  </div>
</body></html>
"""

def test_sbdc_fetches_correct_url():
    from lib import govt_sources
    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_HTML
    with patch.object(govt_sources, "_safe_get", return_value=mock_resp) as mock_get:
        govt_sources.fetch_sbdc()
    called_url = mock_get.call_args[0][0]
    assert "bbs/list.do" in called_url
    assert "2409240028" in called_url

def test_sbdc_parses_bbs_view_links():
    from lib import govt_sources
    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_HTML
    with patch.object(govt_sources, "_safe_get", return_value=mock_resp):
        items = govt_sources.fetch_sbdc()
    assert len(items) == 2
    assert all("bbs/view.do" in it["url"] for it in items)

def test_sbdc_excludes_bid_and_incruit():
    from lib import govt_sources
    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_HTML
    with patch.object(govt_sources, "_safe_get", return_value=mock_resp):
        items = govt_sources.fetch_sbdc()
    urls = [it["url"] for it in items]
    assert not any("incruit" in u for u in urls)
    assert not any("bid" in u for u in urls)

def test_sbdc_source_name():
    from lib import govt_sources
    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_HTML
    with patch.object(govt_sources, "_safe_get", return_value=mock_resp):
        items = govt_sources.fetch_sbdc()
    assert all(it["source"] == "중소기업유통센터" for it in items)
