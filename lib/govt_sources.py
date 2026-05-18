"""정부지원 1차 크롤러 - 8개 공식 포털 직접 수집 (Layer 1)

각 사이트별 HTML/JSON 파싱 → 공통 스키마로 정규화.
사이트 구조 변경에 대비해 try/except로 격리, 한 사이트 실패해도 나머지 진행.

공통 스키마:
    {
        "source": str,          # 사이트명 (예: "기업마당")
        "title": str,           # 공고 제목
        "url": str,             # 상세 페이지 URL
        "agency": str | None,   # 발주 기관
        "deadline": str | None, # "YYYY-MM-DD" 또는 None
        "posted_date": str | None,
        "raw": dict,            # 원본 페이로드 (디버깅용)
    }
"""

import logging
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from . import kstartup_api
from . import bizinfo_api

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"}
TIMEOUT = 30


def _parse_date(s):
    """다양한 한국 날짜 포맷 → YYYY-MM-DD"""
    if not s:
        return None
    s = s.strip()
    patterns = [
        r"(\d{4})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})",
        r"(\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})",
    ]
    for pat in patterns:
        m = re.search(pat, s)
        if m:
            y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
            y = int(y) if len(y) == 4 else 2000 + int(y)
            try:
                return f"{y:04d}-{mo:02d}-{d:02d}"
            except ValueError:
                continue
    return None


def _safe_get(url, **kwargs):
    """타임아웃·에러 핸들링 통합"""
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=TIMEOUT, **kwargs)
        r.raise_for_status()
        return r
    except Exception as e:
        log.warning(f"[fetch fail] {url} → {e}")
        return None


def _fetch_with_playwright(url, wait_selector=None, wait_timeout_ms=10000, total_timeout_ms=25000, wait_until="domcontentloaded"):
    """Playwright Python으로 JS 렌더링 후 HTML 반환 (codex fix E 반영).

    SPA·JS 동적 사이트(중기부 main, 농림부, sbiz24 등)용. requests로 빈 HTML
    돌려받으면 이걸로 폴백.

    안전성:
      - 좀비 프로세스 방지: try/finally로 browser·page close 강제
      - 호출당 총 timeout 상한 (기본 25초)
      - User-Agent 명시 (정적 fetch와 동일)
      - 한 cron 실행에서 여러 사이트 호출 시 각각 분리된 브라우저 인스턴스

    Returns:
        (html: str, final_url: str) — 실패 시 ("", url)
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("playwright 미설치 — SPA 사이트 크롤링 불가")
        return "", url

    html, final_url = "", url
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1280, "height": 900},
                )
                page = context.new_page()
                try:
                    page.goto(url, wait_until=wait_until, timeout=total_timeout_ms)
                    if wait_selector:
                        try:
                            page.wait_for_selector(wait_selector, timeout=wait_timeout_ms)
                        except Exception:
                            # 셀렉터가 안 떠도 일단 현재 DOM 반환 — 부분 결과라도 활용
                            pass
                    else:
                        try:
                            page.wait_for_load_state("networkidle", timeout=wait_timeout_ms)
                        except Exception:
                            pass
                    html = page.content()
                    final_url = page.url
                finally:
                    page.close()
            finally:
                browser.close()
    except Exception as e:
        log.warning(f"[playwright fail] {url} → {type(e).__name__}: {str(e)[:160]}")
    return html, final_url


def _norm_item(source, title, url, agency, deadline=None, raw=None):
    """공통 스키마 dict 생성 헬퍼 — 중복 코드 감소."""
    return {
        "source": source,
        "title": title,
        "url": url,
        "agency": agency,
        "deadline": deadline,
        "posted_date": None,
        "raw": raw or {},
    }


# ==================== 1. 기업마당 (공식 Open API) ====================
def fetch_bizinfo():
    """기업마당 통합 — 공공데이터포털 공식 API

    중앙부처·지자체·유관기관(소상공인진흥공단·창업진흥원 포함) 통합 공고.
    DATA_GO_KR_API_KEY 필요.

    수집 전략:
      1) 일반 페이지네이션 3페이지 (최신 300건)
      2) 헤비로버 직결 키워드별 hashtag 검색 추가 — 페이지네이션에서 밀려나는
         식품·농식품·수출·창업·소상공인 도약 사업 보강 (P1 누락 대응)
      pblancId 기준 dedupe.
    """
    try:
        results = bizinfo_api.fetch_announcements(per_page=100, max_pages=3)
        seen = {(it.get("raw") or {}).get("pblancId") for it in results}

        # 헤비로버 직결 키워드 — 식품진흥원·농림부·KOTRA 등 발주를 보강
        boost_keywords = ["식품", "농식품", "수출", "창업", "소상공인", "K-Food"]
        for kw in boost_keywords:
            try:
                extra = bizinfo_api.fetch_announcements(
                    per_page=100, max_pages=1, search_keyword=kw
                )
            except Exception as e:
                log.warning(f"기업마당 보강검색('{kw}') 실패: {e}")
                continue
            added = 0
            for it in extra:
                pid = (it.get("raw") or {}).get("pblancId")
                if pid and pid not in seen:
                    seen.add(pid)
                    results.append(it)
                    added += 1
            if added:
                log.info(f"기업마당 보강검색 '{kw}': +{added}건")

        return results
    except RuntimeError as e:
        log.warning(f"기업마당 API 키 미설정: {e}")
        return []
    except Exception as e:
        log.warning(f"기업마당 API 실패: {e}")
        return []


# ==================== 2. K-Startup (공식 Open API) ====================
def fetch_kstartup():
    """K-Startup — 공공데이터포털 공식 API 사용 (안정적)

    DATA_GO_KR_API_KEY 필요. 미설정 시 빈 리스트 반환.
    """
    try:
        return kstartup_api.fetch_announcements(per_page=100, max_pages=3, only_recruiting=True)
    except RuntimeError as e:
        log.warning(f"K-Startup API 키 미설정: {e}")
        return []
    except Exception as e:
        log.warning(f"K-Startup API 실패: {e}")
        return []


# ==================== 3. KOTRA ====================
def fetch_kotra():
    """KOTRA — 수출기업화·해외 진출"""
    url = "https://www.kotra.or.kr/bigdata/visualization/korea/biz/notice.do"
    r = _safe_get(url)
    if not r:
        # 메인 공지로 폴백
        url = "https://www.kotra.or.kr/index.do"
        r = _safe_get(url)
        if not r:
            return []

    soup = BeautifulSoup(r.text, "lxml")
    items = []

    for link in soup.select("a"):
        text = link.get_text(strip=True)
        if not text or len(text) < 8:
            continue
        if not any(k in text for k in ["지원", "모집", "공고", "신청", "사업", "수출"]):
            continue
        href = link.get("href", "")
        if not href or href.startswith("#"):
            continue
        full_url = urljoin(url, href)

        items.append({
            "source": "KOTRA",
            "title": text,
            "url": full_url,
            "agency": "KOTRA",
            "deadline": None,
            "posted_date": None,
            "raw": {},
        })

        if len(items) >= 30:
            break

    return items


# ==================== 4. 중소벤처기업부 ====================
def fetch_mss():
    """중기부 — 부처 직접 공고 (cbIdx=126: 실측 2026-05-16 256KB 작동 확인)"""
    url = "https://www.mss.go.kr/site/smba/ex/bbs/List.do?cbIdx=126"
    r = _safe_get(url)
    if not r:
        return []

    soup = BeautifulSoup(r.text, "lxml")
    items = []

    for row in soup.select("table tbody tr, .bbs_list li"):
        title_el = row.select_one("a")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        if not title or len(title) < 5:
            continue
        href = title_el.get("href", "")
        full_url = urljoin(url, href)

        text = row.get_text(" ", strip=True)
        deadline = _parse_date(text)

        items.append({
            "source": "중기부",
            "title": title,
            "url": full_url,
            "agency": "중소벤처기업부",
            "deadline": deadline,
            "posted_date": None,
            "raw": {},
        })

    return items[:50]


# ==================== 5. 소상공인24 ====================
def fetch_sbiz24():
    """소상공인24 — 소진공·바우처"""
    url = "https://www.sbiz24.kr/#/pbanc"
    r = _safe_get(url)
    if not r:
        # SPA라 직접 크롤링 어려움 — API 폴백 시도 (2026-05-19: 실제 엔드포인트 수정)
        api = "https://www.sbiz24.kr/api/pbanc/sbiz24PbancList"
        r = _safe_get(api, params={"page": 1, "size": 50})
        if not r:
            return []
        try:
            data = r.json()
            items = []
            for it in data.get("list", [])[:50]:
                items.append({
                    "source": "소상공인24",
                    "title": it.get("title") or it.get("pbancNm", ""),
                    "url": f"https://www.sbiz24.kr/#/pbanc/{it.get('pbancId', '')}",
                    "agency": it.get("agencyNm"),
                    "deadline": _parse_date(it.get("rceptEndDt")),
                    "posted_date": _parse_date(it.get("regDt")),
                    "raw": it,
                })
            return items
        except (ValueError, KeyError):
            return []

    return []


# ==================== 6. 고비즈코리아 ====================
def fetch_gobiz():
    """고비즈코리아 — KOTRA 산하 수출 지원"""
    url = "https://kr.gobizkorea.com/notice/noticeList.do"
    r = _safe_get(url)
    if not r:
        return []

    soup = BeautifulSoup(r.text, "lxml")
    items = []

    for row in soup.select("table tbody tr, .notice-list li"):
        title_el = row.select_one("a")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        if not title or len(title) < 5:
            continue
        href = title_el.get("href", "")
        full_url = urljoin(url, href) if href else url

        items.append({
            "source": "고비즈코리아",
            "title": title,
            "url": full_url,
            "agency": "KOTRA",
            "deadline": None,
            "posted_date": None,
            "raw": {},
        })

    return items[:30]


# ==================== 7. 경기도경제과학진흥원 ====================
def fetch_gbsa():
    """경기도경제과학진흥원 — 경기기업비서(egbiz.or.kr) 지원사업 목록"""
    url = "https://egbiz.or.kr/sp/supportPrjCatList.do"
    r = _safe_get(url)
    if not r:
        return []

    soup = BeautifulSoup(r.text, "lxml")
    items = []

    for link in soup.select("a"):
        text = link.get_text(" ", strip=True)
        if not text or len(text) < 8:
            continue
        if not any(k in text for k in ["지원", "모집", "공고", "신청", "사업", "창업", "육성"]):
            continue
        href = link.get("href", "")
        if not href or href.startswith("#") or href.startswith("javascript"):
            continue
        full_url = urljoin(url, href) if not href.startswith("http") else href

        items.append({
            "source": "경기경제과학진흥원",
            "title": text,
            "url": full_url,
            "agency": "경기도경제과학진흥원",
            "deadline": _parse_date(text),
            "posted_date": None,
            "raw": {},
        })

        if len(items) >= 40:
            break

    return items


# ==================== 8. 용인시산업진흥원 (YPA) ====================
def fetch_ypa():
    """용인시산업진흥원 — 용인기업지원시스템 (ybs.ypa.or.kr) + 메인"""
    candidates = [
        "https://ybs.ypa.or.kr/application.do?pageIndex=1",
        "https://ypa.or.kr/",
    ]
    for url in candidates:
        r = _safe_get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        items = []
        for link in soup.select("a"):
            text = link.get_text(strip=True)
            if not text or len(text) < 8:
                continue
            if not any(k in text for k in ["지원", "모집", "공고", "신청", "교육", "사업"]):
                continue
            href = link.get("href", "")
            if not href or href.startswith("#"):
                continue
            full_url = urljoin(url, href)
            items.append({
                "source": "용인시산업진흥원",
                "title": text,
                "url": full_url,
                "agency": "용인시산업진흥원",
                "deadline": None,
                "posted_date": None,
                "raw": {},
            })
            if len(items) >= 30:
                break
        if items:
            return items
    return []


# ==================== 9. NIPA (정보통신산업진흥원) ====================
def fetch_nipa():
    """NIPA — ICT·SaaS·AI 지원사업"""
    url = "https://www.nipa.kr/home/2-2"
    r = _safe_get(url)
    if not r:
        return []

    soup = BeautifulSoup(r.text, "lxml")
    items = []

    for row in soup.select("table tbody tr, .board-list li, ul.list li"):
        title_el = row.select_one("a")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        if not title or len(title) < 5:
            continue
        href = title_el.get("href", "")
        full_url = urljoin(url, href)

        text = row.get_text(" ", strip=True)
        deadline = _parse_date(text)

        items.append({
            "source": "NIPA",
            "title": title,
            "url": full_url,
            "agency": "정보통신산업진흥원",
            "deadline": deadline,
            "posted_date": None,
            "raw": {},
        })

    return items[:40]


# ==================== 10. 창업진흥원 KISED ====================
def fetch_kised():
    """창업진흥원 직접 — K-Startup과 별도 페이지
    2026-05-16: misAnnouncement/index.es로 redirect됨. 셀렉터 li.lstyle_list."""
    url = "https://www.kised.or.kr/misAnnouncement/index.es?mid=a10302000000"
    r = _safe_get(url)
    if not r:
        return []

    soup = BeautifulSoup(r.text, "lxml")
    items = []

    # 새 셀렉터: li.lstyle_list 안의 a 태그 — probe 결과 25건 확인
    for li in soup.select("li.lstyle_list, ul.lstyle li, li[class*='list']"):
        title_el = li.select_one("a")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        if not title or len(title) < 8:
            continue
        href = title_el.get("href", "")
        if not href or href.startswith("#") or href.startswith("javascript"):
            continue
        full_url = urljoin(url, href)

        text = li.get_text(" ", strip=True)
        deadline = _parse_date(text)

        items.append(_norm_item("창업진흥원", title, full_url, "창업진흥원", deadline))

    return items[:40]


# ==================== 11. SMTECH (중소기업 기술개발사업) ====================
def fetch_smtech():
    """SMTECH — 중소기업 R&D 모집 (TIPA 운영)"""
    url = "https://www.smtech.go.kr/front/ifg/no/notice02_list.do"
    r = _safe_get(url)
    if not r:
        return []

    soup = BeautifulSoup(r.text, "lxml")
    items = []

    for row in soup.select("table tbody tr, .board_list li"):
        title_el = row.select_one("a")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        if not title or len(title) < 5:
            continue
        href = title_el.get("href", "")
        full_url = urljoin(url, href)

        text = row.get_text(" ", strip=True)
        deadline = _parse_date(text)

        items.append({
            "source": "SMTECH",
            "title": title,
            "url": full_url,
            "agency": "중소기업기술정보진흥원",
            "deadline": deadline,
            "posted_date": None,
            "raw": {},
        })

    return items[:40]


# ==================== 12. 한국무역보험공사 K-Sure ====================
def fetch_ksure():
    """K-Sure — 수출 보증·금융 지원"""
    url = "https://www.ksure.or.kr:8443/kr/notice.do"
    r = _safe_get(url)
    if not r:
        url = "https://www.ksure.or.kr/"
        r = _safe_get(url)
        if not r:
            return []

    soup = BeautifulSoup(r.text, "lxml")
    items = []

    for link in soup.select("a"):
        text = link.get_text(strip=True)
        if not text or len(text) < 8:
            continue
        if not any(k in text for k in ["지원", "모집", "공고", "사업", "수출"]):
            continue
        href = link.get("href", "")
        if not href or href.startswith("#"):
            continue
        full_url = urljoin(url, href)

        items.append({
            "source": "K-Sure",
            "title": text,
            "url": full_url,
            "agency": "한국무역보험공사",
            "deadline": None,
            "posted_date": None,
            "raw": {},
        })

        if len(items) >= 25:
            break

    return items


# ==================== 13. 농림축산식품부 (식품 D2C 직결) ====================
def fetch_mafra():
    """농림축산식품부 — 식품·외식·수출 (헤비로버 본업)"""
    url = "https://www.mafra.go.kr/bbs/mafra/68/list.do"
    r = _safe_get(url)
    if not r:
        return []

    soup = BeautifulSoup(r.text, "lxml")
    items = []

    for row in soup.select("table tbody tr, .board_list li"):
        title_el = row.select_one("a")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        if not title or len(title) < 5:
            continue
        href = title_el.get("href", "")
        full_url = urljoin(url, href)

        text = row.get_text(" ", strip=True)
        deadline = _parse_date(text)

        items.append({
            "source": "농림축산식품부",
            "title": title,
            "url": full_url,
            "agency": "농림축산식품부",
            "deadline": deadline,
            "posted_date": None,
            "raw": {},
        })

    return items[:30]


# ==================== 14. aT 한국농수산식품유통공사 ====================
def fetch_at():
    """aT — 식품·수출 지원 (K-Food)"""
    url = "https://www.at.or.kr/article/apko368000/list.action"
    r = _safe_get(url)
    if not r:
        url = "https://www.at.or.kr/"
        r = _safe_get(url)
        if not r:
            return []

    soup = BeautifulSoup(r.text, "lxml")
    items = []

    for link in soup.select("a"):
        text = link.get_text(strip=True)
        if not text or len(text) < 8:
            continue
        if not any(k in text for k in ["지원", "모집", "공고", "사업", "수출", "K-Food"]):
            continue
        href = link.get("href", "")
        if not href or href.startswith("#"):
            continue
        full_url = urljoin(url, href)

        items.append({
            "source": "aT(농수산식품유통공사)",
            "title": text,
            "url": full_url,
            "agency": "한국농수산식품유통공사",
            "deadline": None,
            "posted_date": None,
            "raw": {},
        })

        if len(items) >= 25:
            break

    return items


# ==================== 15. 경기도 통합 ====================
def fetch_gyeonggi():
    """경기도 — 도 직접 공고 (지역 가점)"""
    url = "https://www.gg.go.kr/contents/contents.do?ciIdx=1014&menuId=2932"
    r = _safe_get(url)
    if not r:
        # 폴백: 경기도 메인 보도자료
        url = "https://www.gg.go.kr/bbs/boardView.do?bIdx=1004"
        r = _safe_get(url)
        if not r:
            return []

    soup = BeautifulSoup(r.text, "lxml")
    items = []

    for link in soup.select("a"):
        text = link.get_text(strip=True)
        if not text or len(text) < 8:
            continue
        if not any(k in text for k in ["지원", "모집", "공고", "신청", "사업"]):
            continue
        href = link.get("href", "")
        if not href or href.startswith("#"):
            continue
        full_url = urljoin(url, href)

        items.append({
            "source": "경기도",
            "title": text,
            "url": full_url,
            "agency": "경기도청",
            "deadline": None,
            "posted_date": None,
            "raw": {},
        })

        if len(items) >= 25:
            break

    return items


# ==================== 16. 경기테크노파크 (GTP) ====================
def fetch_gtek():
    """경기테크노파크 — 경기도 입주공간·장비지원·스마트공장 (URL 수정: gtp.or.kr)"""
    url = "https://www.gtp.or.kr/"
    r = _safe_get(url)
    if not r:
        return []

    soup = BeautifulSoup(r.text, "lxml")
    items = []

    for row in soup.select("table tbody tr"):
        title_el = row.select_one("a")
        if not title_el:
            continue
        title = title_el.get_text(" ", strip=True)
        if not title or len(title) < 5:
            continue
        href = title_el.get("href", "")
        full_url = urljoin(url, href) if href else url

        text = row.get_text(" ", strip=True)
        deadline = _parse_date(text)

        items.append({
            "source": "경기테크노파크",
            "title": title,
            "url": full_url,
            "agency": "경기테크노파크",
            "deadline": deadline,
            "posted_date": None,
            "raw": {},
        })

    return items[:30]


# ==================== 17. 중소기업유통센터 (SBDC/KODMA) ====================
def fetch_sbdc():
    """중소기업유통센터(한국중소벤처기업유통원) — D2C 온라인유통·판로개척 전문

    실제 사이트 구조: div.title > a[onclick="goView('XXXXXXX')"]
    href은 모두 '#'이고 onclick에서 pstSn 추출 → bbs/view.do URL 조합
    """
    import re as _re
    BASE = "https://www.kodma.or.kr"
    BBS_KEY = "2409240028"
    url = f"{BASE}/bbs/list.do?key={BBS_KEY}"
    r = _safe_get(url)
    if not r:
        return []

    soup = BeautifulSoup(r.text, "lxml")
    items = []
    seen = set()

    for div in soup.select("div.title"):
        a = div.find("a")
        if not a:
            continue
        onclick = a.get("onclick", "")
        m = _re.search(r"goView\('(\d+)'\)", onclick)
        if not m:
            continue
        pst_sn = m.group(1)
        text = a.get_text(" ", strip=True)
        if not text or len(text) < 5:
            continue
        full_url = f"{BASE}/bbs/view.do?key={BBS_KEY}&pstSn={pst_sn}"
        if full_url in seen:
            continue
        seen.add(full_url)
        items.append({
            "source": "중소기업유통센터",
            "title": text[:200],
            "url": full_url,
            "agency": "한국중소벤처기업유통원",
            "deadline": _parse_date(text),
            "posted_date": None,
            "raw": {},
        })

    return items[:30]


# ==================== 18. 국가식품클러스터진흥원 (foodpolis) ====================
def fetch_foodpolis():
    """국가식품클러스터 — 식품 전용 최대 7,000만원. 경쟁 극히 낮음."""
    candidates = [
        "https://www.foodpolis.kr/web/Board/1/list.do",   # 공지사항
        "https://www.foodpolis.kr/web/index.do",
    ]
    for url in candidates:
        r = _safe_get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        items = []
        for link in soup.select("a"):
            text = link.get_text(strip=True)
            if not text or len(text) < 8:
                continue
            if not any(k in text for k in ["지원", "모집", "공고", "신청", "사업", "과제"]):
                continue
            href = link.get("href", "")
            if not href or href.startswith("#") or href.startswith("javascript"):
                continue
            full_url = urljoin(url, href)
            items.append({
                "source": "국가식품클러스터",
                "title": text,
                "url": full_url,
                "agency": "한국식품산업클러스터진흥원",
                "deadline": None,
                "posted_date": None,
                "raw": {},
            })
            if len(items) >= 30:
                break
        if items:
            return items
    return []


# ==================== 19. 경기스타트업플랫폼 (gsp) ====================
def fetch_gsp():
    """경기스타트업플랫폼 — SPA (href='#' 전체). Playwright로 동적 렌더링 후 카드 추출.
    실측 2026-05-16: li[class*=item] 26개 카드 확인."""
    BASE_URL = "https://gsp.or.kr/supportProject/UVSL0001.do"
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                page.goto(BASE_URL, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=20000)
                html = page.content()
            finally:
                browser.close()
    except Exception as e:
        log.warning(f"경기스타트업플랫폼 Playwright 실패: {e}")
        return []

    soup = BeautifulSoup(html, "lxml")
    items = []
    kw = ["지원", "모집", "공고", "신청", "사업", "창업", "컨설팅"]
    for card in soup.select("li[class*=item], .project-list li, .project-item"):
        text = card.get_text(" ", strip=True)
        if not text or len(text) < 10:
            continue
        if not any(k in text for k in kw):
            continue
        # 제목: 줄 구분 후 첫 의미 있는 줄
        lines = [ln.strip() for ln in text.splitlines() if ln.strip() and len(ln.strip()) > 5]
        title = lines[0][:100] if lines else text[:80]
        deadline = _parse_date(text)
        items.append({
            "source": "경기스타트업플랫폼",
            "title": title,
            "url": BASE_URL,
            "agency": "경기스타트업플랫폼",
            "deadline": deadline,
            "posted_date": None,
            "raw": {},
        })
        if len(items) >= 30:
            break
    return items


# ==================== 20. 소상공인 온라인 판로지원 (fanfandaero) ====================
def fetch_fanfandaero():
    """소상공인 온라인쇼핑몰 판매지원 — D2C 카페24/스마트스토어 직결.
    URL 실측 2026-05-16: introV2.do(0건)→preSprtBizPbancAll.do+main.do 폴백."""
    import re
    candidates = [
        "https://fanfandaero.kr/portal/v2/preSprtBizPbancAll.do",
        "https://fanfandaero.kr/portal/main.do",
    ]
    kw = ["모집", "공고", "지원", "판로", "브랜드", "쇼핑몰", "온라인", "사업"]
    for url in candidates:
        r = _safe_get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        items = []
        for link in soup.select("a"):
            text = link.get_text(" ", strip=True)
            if not text or len(text) < 8:
                continue
            if not any(k in text for k in kw):
                continue
            href = link.get("href", "")
            m = re.search(r"detailPage\('(\d+)'\)", href or "")
            if m:
                full_url = f"https://fanfandaero.kr/portal/v2/readNtcBbsDtl.do?ntcSn={m.group(1)}"
            elif href and not href.startswith("#") and not href.startswith("javascript"):
                full_url = urljoin(url, href)
            else:
                continue
            title = re.sub(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}", "", text).strip()
            parent = link.find_parent()
            deadline = _parse_date(parent.get_text(" ", strip=True) if parent else text)
            items.append({
                "source": "소상공인판로지원",
                "title": title,
                "url": full_url,
                "agency": "소상공인시장진흥공단",
                "deadline": deadline,
                "posted_date": None,
                "raw": {},
            })
            if len(items) >= 25:
                break
        if items:
            return items
    return []


# ==================== 21. 한국식품산업협회 (kfia) ====================
def fetch_kfia():
    """한국식품산업협회 — 식품 업종 전용 지원사업. 협회 회원사 우대."""
    url = "https://www.kfia.or.kr/"
    r = _safe_get(url)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "lxml")
    items = []
    for link in soup.select("a"):
        text = link.get_text(strip=True)
        if not text or len(text) < 8:
            continue
        if not any(k in text for k in ["지원", "모집", "공고", "신청", "사업", "교육"]):
            continue
        href = link.get("href", "")
        if not href or href.startswith("#") or href.startswith("javascript"):
            continue
        full_url = urljoin(url, href)
        items.append({
            "source": "한국식품산업협회",
            "title": text,
            "url": full_url,
            "agency": "한국식품산업협회",
            "deadline": None,
            "posted_date": None,
            "raw": {},
        })
        if len(items) >= 20:
            break
    return items


# ==================== 22. 경기바로 (ggbaro) ====================
def fetch_ggbaro():
    """경기바로 — 경기도 소상공인 전용 플랫폼. 기업마당 미등록 공고 포함."""
    url = "https://ggbaro.kr/apply/biz-announce.do"
    r = _safe_get(url)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "lxml")
    items = []
    for link in soup.select("a"):
        text = link.get_text(strip=True)
        if not text or len(text) < 8:
            continue
        if not any(k in text for k in ["지원", "모집", "공고", "신청", "사업", "창업", "자금"]):
            continue
        href = link.get("href", "")
        if not href or href.startswith("#") or href.startswith("javascript"):
            continue
        full_url = urljoin(url, href)
        items.append({
            "source": "경기바로",
            "title": text,
            "url": full_url,
            "agency": "경기도시장상권진흥원",
            "deadline": None,
            "posted_date": None,
            "raw": {},
        })
        if len(items) >= 25:
            break
    return items


# ==================== 23. 중소벤처기업진흥공단 (중진공) ====================
def fetch_kosmes():
    """중진공 — 정책자금 직접 융자 핵심 창구 (청년창업자금·사업화자금 등)"""
    candidates = [
        "https://www.kosmes.or.kr/nsh/SH/NTS/SHNTS001M0.do",
        "https://www.kosmes.or.kr/",
    ]
    for url in candidates:
        r = _safe_get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        items = []
        for link in soup.select("a"):
            text = link.get_text(strip=True)
            if not text or len(text) < 8:
                continue
            if not any(k in text for k in ["지원", "모집", "공고", "신청", "사업", "융자", "자금", "창업"]):
                continue
            href = link.get("href", "")
            if not href or href.startswith("#") or href.startswith("javascript"):
                continue
            full_url = urljoin(url, href)
            items.append({
                "source": "중소벤처기업진흥공단",
                "title": text,
                "url": full_url,
                "agency": "중소벤처기업진흥공단",
                "deadline": None,
                "posted_date": None,
                "raw": {},
            })
            if len(items) >= 30:
                break
        if items:
            return items
    return []


# ==================== 19. 경기신용보증재단 (GCGF) ====================
def fetch_gcgf():
    """경기신용보증재단 — 경기도 소재 기업 보증·저리 대출 (용인 직결)"""
    candidates = [
        "https://www.gcgf.or.kr/gcgf/main.do",
        "https://untact.gcgf.or.kr/",
    ]
    for url in candidates:
        r = _safe_get(url)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        items = []
        for link in soup.select("a"):
            text = link.get_text(strip=True)
            if not text or len(text) < 8:
                continue
            if not any(k in text for k in ["지원", "모집", "공고", "신청", "보증", "자금", "사업"]):
                continue
            href = link.get("href", "")
            if not href or href.startswith("#") or href.startswith("javascript"):
                continue
            full_url = urljoin(url, href)
            items.append({
                "source": "경기신용보증재단",
                "title": text,
                "url": full_url,
                "agency": "경기신용보증재단",
                "deadline": None,
                "posted_date": None,
                "raw": {},
            })
            if len(items) >= 30:
                break
        if items:
            return items
    return []


# ==================== 20. 중소벤처24 (SMES) ====================
def fetch_smes24():
    """중소벤처24 — 중기부 통합 원스톱 포털 공고"""
    url = "https://www.smes.go.kr/main/sportsBsnsPolicy"
    r = _safe_get(url)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "lxml")
    items = []
    for row in soup.select("li, .item, .card, article, tr"):
        title_el = row.select_one("a")
        if not title_el:
            continue
        text = title_el.get_text(" ", strip=True)
        if not text or len(text) < 8:
            continue
        if not any(k in text for k in ["지원", "모집", "공고", "신청", "사업", "창업"]):
            continue
        href = title_el.get("href", "")
        full_url = urljoin(url, href) if href else url
        raw_text = row.get_text(" ", strip=True)
        deadline = _parse_date(raw_text)
        items.append({
            "source": "중소벤처24",
            "title": text,
            "url": full_url,
            "agency": "중소벤처기업부",
            "deadline": deadline,
            "posted_date": None,
            "raw": {},
        })
    return items[:50]


# ==================== 통합 (20개 소스) ====================
ALL_SOURCES = [
    ("기업마당", fetch_bizinfo),                # 1
    ("K-Startup", fetch_kstartup),              # 2
    ("KOTRA", fetch_kotra),                     # 3
    ("중기부", fetch_mss),                       # 4
    ("소상공인24", fetch_sbiz24),                # 5
    ("고비즈코리아", fetch_gobiz),               # 6
    ("경기경제과학진흥원", fetch_gbsa),          # 7
    ("용인시산업진흥원", fetch_ypa),             # 8
    ("NIPA", fetch_nipa),                       # 9
    ("창업진흥원", fetch_kised),                 # 10
    ("SMTECH", fetch_smtech),                   # 11
    ("K-Sure", fetch_ksure),                    # 12
    ("농림축산식품부", fetch_mafra),             # 13
    ("aT(농수산식품유통공사)", fetch_at),         # 14
    ("경기도", fetch_gyeonggi),                  # 15
    ("경기테크노파크", fetch_gtek),              # 16
    ("중소기업유통센터", fetch_sbdc),            # 17
    ("국가식품클러스터", fetch_foodpolis),        # 18
    ("경기스타트업플랫폼", fetch_gsp),           # 19
    ("소상공인판로지원", fetch_fanfandaero),     # 20
    ("한국식품산업협회", fetch_kfia),            # 21
    ("경기바로", fetch_ggbaro),                 # 22
    ("중소벤처기업진흥공단", fetch_kosmes),      # 23
    ("경기신용보증재단", fetch_gcgf),            # 24
    ("중소벤처24", fetch_smes24),               # 25
]


def fetch_all(verbose=False):
    """모든 1차 소스 크롤링. 한 사이트 실패해도 나머지 진행.

    Returns:
        (results: list[dict], stats: dict[name, count_or_error])
    """
    results = []
    stats = {}

    for name, fn in ALL_SOURCES:
        try:
            items = fn()
            stats[name] = len(items)
            results.extend(items)
            if verbose:
                print(f"  [{name}] {len(items)}건")
        except Exception as e:
            stats[name] = f"ERROR: {e}"
            if verbose:
                print(f"  [{name}] 실패: {e}")
            log.exception(f"{name} 크롤링 실패")

    return results, stats


if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if len(sys.argv) > 1:
        # 단일 소스 테스트
        name = sys.argv[1]
        fn_map = dict(ALL_SOURCES)
        if name not in fn_map:
            print(f"알 수 없는 소스: {name}. 사용 가능: {list(fn_map.keys())}")
            sys.exit(1)
        items = fn_map[name]()
        print(f"=== {name} {len(items)}건 ===")
        for it in items[:5]:
            print(f"\n  {it['title']}")
            print(f"  URL: {it['url']}")
            print(f"  마감: {it['deadline'] or '미상'}")
    else:
        results, stats = fetch_all(verbose=True)
        print(f"\n=== 전체 {len(results)}건 ===")
        print(json.dumps(stats, ensure_ascii=False, indent=2))
