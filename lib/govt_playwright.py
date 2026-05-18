"""Playwright primary 수집 — API/requests 누락 공고를 화면에서 직접 추출.

govt_sources.py의 fetcher는 requests + BeautifulSoup 또는 공공데이터포털 API에
의존하므로, 사이트가 SPA·셀렉터 변경·URL 이동·서브도메인 분리될 때 silent failure
가 발생한다 (예: 경기테크노파크 메인은 비어있고 pms.gtp.or.kr 서브가 진짜 공고함).

본 모듈은 동일한 25 사이트에 대해 Playwright로 화면을 직접 렌더링한 후 공고 카드/
리스트를 추출한다. 결과는 govt_sources와 동일한 공통 스키마(_norm_item).
reconciler가 양쪽 결과를 합쳐 "Playwright에만 있는 항목" = API/requests 누락을
검출한다.

설계 원칙:
  - 사이트별 try/except 격리 — 한 사이트 실패해도 나머지 진행
  - _fetch_with_playwright() 재사용 — 좀비 프로세스 방지 + 25초 timeout
  - 공통 스키마 _norm_item() 재사용 — reconciler 매칭 가능

우선순위(7개) — source_revival_audit.md 기준:
  1. 경기테크노파크 (probe 51, pms 서브도메인)
  2. 중소기업유통센터 (probe 47, D2C 직결)
  3. 농림축산식품부 (probe 24, 식품 직결)
  4. 국가식품클러스터 (식품 7천만원)
  5. 창업진흥원 (probe 36, lstyle_list)
  6. 중진공 (정책자금 1억 트랙)
  7. 경기스타트업플랫폼 (SPA, UVSD0001.do 카드)
"""

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .govt_sources import _fetch_with_playwright, _norm_item, _parse_date

log = logging.getLogger(__name__)


def _clean_text(s: str) -> str:
    """탭·연속 공백·개행 정규화."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()


def _is_announcement_text(text: str) -> bool:
    """공고/모집 텍스트로 보이는지 (제외: 채용공고·입법예고·예산낭비신고 등)."""
    if not text or len(text) < 8:
        return False
    if any(x in text for x in ["[채용공고]", "[입법예고]", "예산낭비", "예산절감"]):
        return False
    return any(k in text for k in ["공고", "모집", "지원", "신청", "선정", "사업", "지침"])


# ==================== 1. 경기테크노파크 (pms 서브도메인) ====================
def fetch_gtek_pw():
    """경기테크노파크 — gtp.or.kr 메인의 사업공고 위젯에서 webBusinessView 링크 추출.

    실제 상세는 pms.gtp.or.kr 서브도메인이지만, 메인 페이지 위젯이 최신 공고를
    리스트화해서 노출함 (probe 51건, dedup 후 14건).
    """
    url = "https://www.gtp.or.kr/"
    html, final_url = _fetch_with_playwright(
        url, wait_selector="a[href*='webBusinessView']"
    )
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    items = []
    seen = set()
    for a in soup.select("a[href*='webBusinessView.do']"):
        href = a.get("href", "")
        if not href:
            continue
        full_url = urljoin(final_url, href)
        if full_url in seen:
            continue
        seen.add(full_url)
        raw_text = a.get_text("\n", strip=True)
        # "사업공고\n\n제목\n\n2026.05.14" 패턴 — 줄바꿈 보존 후 분리
        parts = [p.strip() for p in raw_text.split("\n") if p.strip()]
        title = ""
        for p in parts:
            if p in ("사업공고", "공지", "공고", "교육 및 행사"):
                continue
            if re.match(r"^\d{4}[.\-]\d{1,2}[.\-]\d{1,2}", p):
                continue
            title = p
            break
        title = _clean_text(title)
        if len(title) < 5:
            continue
        deadline = None
        for p in parts:
            d = _parse_date(p)
            if d:
                deadline = d
                break
        items.append(_norm_item(
            source="경기테크노파크",
            title=title[:200],
            url=full_url,
            agency="경기테크노파크",
            deadline=deadline,
        ))
    log.info(f"경기테크노파크(PW): {len(items)}건")
    return items[:50]


# ==================== 2. 중소기업유통센터 (kodma) ====================
def fetch_kodma_pw():
    """한국중소벤처기업유통원(KODMA) — 공고 게시판 화면에서 직접."""
    url = "https://www.kodma.or.kr/usr/pbancInfo/selectPbancInfoList.do"
    html, final_url = _fetch_with_playwright(
        url, wait_selector=".board-list, table, .pbanc, li"
    )
    if not html:
        url = "https://www.kodma.or.kr/index.do"
        html, final_url = _fetch_with_playwright(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    items = []
    seen = set()
    for a in soup.select("li.board-list a, .board-list a, table a, td.title a, .pbanc a"):
        href = a.get("href", "")
        text = _clean_text(a.get_text(" ", strip=True))
        if not href or not text or "javascript:" in href:
            continue
        if not _is_announcement_text(text):
            continue
        full_url = urljoin(final_url, href)
        if full_url in seen:
            continue
        seen.add(full_url)
        items.append(_norm_item(
            source="중소기업유통센터",
            title=text[:200],
            url=full_url,
            agency="한국중소벤처기업유통원",
            deadline=_parse_date(text),
        ))
    log.info(f"중소기업유통센터(PW): {len(items)}건")
    return items[:50]


# ==================== 3. 농림축산식품부 (mafra) ====================
def fetch_mafra_pw():
    """농림축산식품부 — 메인 페이지 recentBbsInnerUl이 진짜 공고 위치."""
    url = "https://www.mafra.go.kr/"
    html, final_url = _fetch_with_playwright(
        url, wait_selector="ul.recentBbsInnerUl, .recentBbsInnerUl, a[href*='/bbs/home/']"
    )
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    items = []
    seen = set()
    for a in soup.select("a[href*='/bbs/home/']"):
        href = a.get("href", "")
        text = _clean_text(a.get_text(" ", strip=True))
        text = text.replace("작성일", "").replace("작성", "").strip()
        if not _is_announcement_text(text):
            continue
        full_url = urljoin(final_url, href)
        if full_url in seen:
            continue
        seen.add(full_url)
        items.append(_norm_item(
            source="농림축산식품부",
            title=text[:200],
            url=full_url,
            agency="농림축산식품부",
            deadline=_parse_date(text),
        ))
    log.info(f"농림축산식품부(PW): {len(items)}건")
    return items[:30]


# ==================== 4. 국가식품클러스터 (foodpolis) ====================
def fetch_foodpolis_pw():
    """국가식품클러스터 — 식품 전용 최대 7천만원 사업화 자금."""
    url = "https://www.foodpolis.kr/web/Board/1/list.do"
    html, final_url = _fetch_with_playwright(
        url, wait_selector="table tbody tr, .board-list, .bbs-list"
    )
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    items = []
    seen = set()
    for a in soup.select("table tbody tr a, .board-list a, .bbs-list a, td a"):
        href = a.get("href", "")
        text = _clean_text(a.get_text(" ", strip=True))
        if not href or not text or "javascript:" in href:
            continue
        if not _is_announcement_text(text):
            continue
        full_url = urljoin(final_url, href)
        if full_url in seen:
            continue
        seen.add(full_url)
        items.append(_norm_item(
            source="국가식품클러스터",
            title=text[:200],
            url=full_url,
            agency="국가식품클러스터지원센터",
            deadline=_parse_date(text),
        ))
    log.info(f"국가식품클러스터(PW): {len(items)}건")
    return items[:30]


# ==================== 5. 창업진흥원 (KISED) ====================
def fetch_kised_pw():
    """창업진흥원 misAnnouncement — lstyle_list 셀렉터 (probe 25건)."""
    url = "https://www.kised.or.kr/misAnnouncement/index.es?mid=a10302000000"
    html, final_url = _fetch_with_playwright(
        url, wait_selector="li.lstyle_list, .list_wrap, .board-list"
    )
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    items = []
    seen = set()
    selectors = [
        "li.lstyle_list a",
        ".list_wrap li a",
        ".board-list a",
        "a[href*='bizpbanc']",
    ]
    for sel in selectors:
        for a in soup.select(sel):
            href = a.get("href", "")
            text = _clean_text(a.get_text(" ", strip=True))
            if not href or not text or "javascript:" in href:
                continue
            if not _is_announcement_text(text):
                continue
            full_url = urljoin(final_url, href)
            if full_url in seen:
                continue
            seen.add(full_url)
            items.append(_norm_item(
                source="창업진흥원",
                title=text[:200],
                url=full_url,
                agency="창업진흥원",
                deadline=_parse_date(text),
            ))
    log.info(f"창업진흥원(PW): {len(items)}건")
    return items[:50]


# ==================== 6. 중진공 (KOSMES) ====================
def fetch_kosmes_pw():
    """중소벤처기업진흥공단 — 정책자금 융자 직접 창구."""
    url = "https://www.kosmes.or.kr/nsh/SH/NTS/SHNTS001M0.do"
    html, final_url = _fetch_with_playwright(
        url, wait_selector="table tbody tr, .board-list, .list"
    )
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    items = []
    seen = set()
    for a in soup.select("table tbody tr a, .board-list a, td a, .list a"):
        href = a.get("href", "")
        text = _clean_text(a.get_text(" ", strip=True))
        if not href or not text or "javascript:" in href:
            continue
        if not _is_announcement_text(text):
            continue
        full_url = urljoin(final_url, href)
        if full_url in seen:
            continue
        seen.add(full_url)
        items.append(_norm_item(
            source="중소벤처기업진흥공단",
            title=text[:200],
            url=full_url,
            agency="중소벤처기업진흥공단",
            deadline=_parse_date(text),
        ))
    log.info(f"중진공(PW): {len(items)}건")
    return items[:30]


# ==================== 7. 경기스타트업플랫폼 (gsp) ====================
def fetch_gsp_pw():
    """경기스타트업플랫폼 — 메인 페이지에 노출된 UVSD0001.do?sportSeq= 카드 추출.

    supportProject 페이지(UVSL0001.do)는 카드를 swiper로 SPA 렌더링하면서 href를
    "#"으로 두고 onclick으로 이동시킴 → href 셀렉터 매칭 불가. 메인 페이지가 동일
    카드를 실제 URL과 함께 노출하므로 그쪽이 더 안전.
    """
    url = "https://gsp.or.kr/"
    html, final_url = _fetch_with_playwright(
        url, wait_selector="a[href*='UVSD0001.do?sportSeq=']"
    )
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    items = []
    seen = set()
    for a in soup.select("a[href*='UVSD0001.do?sportSeq=']"):
        href = a.get("href", "")
        text = _clean_text(a.get_text(" ", strip=True))
        if not href or not text or len(text) < 5:
            continue
        full_url = urljoin(final_url, href)
        if full_url in seen:
            continue
        seen.add(full_url)
        items.append(_norm_item(
            source="경기스타트업플랫폼",
            title=text[:200],
            url=full_url,
            agency="경기경제과학진흥원",
            deadline=None,
        ))
    log.info(f"경기스타트업플랫폼(PW): {len(items)}건")
    return items[:30]


# ==================== 통합 ====================
# stats 키는 "(PW)" 접미사를 붙여 기존 stats_l1과 분리 추적한다.
# items의 source 필드는 그대로 (예: "경기테크노파크") — reconciler가 매칭 가능.
PLAYWRIGHT_SOURCES = [
    ("경기테크노파크(PW)", fetch_gtek_pw),
    ("중소기업유통센터(PW)", fetch_kodma_pw),
    ("농림축산식품부(PW)", fetch_mafra_pw),
    ("국가식품클러스터(PW)", fetch_foodpolis_pw),
    ("창업진흥원(PW)", fetch_kised_pw),
    ("중소벤처기업진흥공단(PW)", fetch_kosmes_pw),
    ("경기스타트업플랫폼(PW)", fetch_gsp_pw),
]


def fetch_all_playwright(verbose=False):
    """Playwright fetcher 전체 실행. 사이트별 try/except 격리.

    Returns:
        (results: list[dict], stats: dict[name, int|"ERROR: ..."])
    """
    results = []
    stats = {}
    for name, fn in PLAYWRIGHT_SOURCES:
        try:
            items = fn()
            stats[name] = len(items)
            results.extend(items)
            if verbose:
                print(f"  [{name}](PW) {len(items)}건")
        except Exception as e:
            stats[name] = f"ERROR: {e}"
            if verbose:
                print(f"  [{name}](PW) 실패: {e}")
            log.exception(f"{name}(PW) 크롤링 실패")
    return results, stats


if __name__ == "__main__":
    import json as _json
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if len(sys.argv) > 1:
        name = sys.argv[1]
        fn_map = dict(PLAYWRIGHT_SOURCES)
        if name not in fn_map:
            print(f"알 수 없는 소스: {name}. 사용 가능: {list(fn_map.keys())}")
            sys.exit(1)
        items = fn_map[name]()
        print(f"=== {name}(PW) {len(items)}건 ===")
        for it in items[:5]:
            print(f"\n  {it['title']}")
            print(f"  URL:    {it['url']}")
            print(f"  마감:   {it['deadline'] or '미상'}")
    else:
        results, stats = fetch_all_playwright(verbose=True)
        print(f"\n=== 전체(PW) {len(results)}건 ===")
        print(_json.dumps(stats, ensure_ascii=False, indent=2))
