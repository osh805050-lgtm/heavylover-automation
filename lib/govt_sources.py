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
from datetime import datetime
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


# ==================== 1. 기업마당 (공식 Open API) ====================
def fetch_bizinfo():
    """기업마당 통합 — 공공데이터포털 공식 API

    중앙부처·지자체·유관기관(소상공인진흥공단·창업진흥원 포함) 통합 공고.
    DATA_GO_KR_API_KEY 필요.
    """
    try:
        return bizinfo_api.fetch_announcements(per_page=100, max_pages=3)
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
    """중기부 — 부처 직접 공고"""
    url = "https://www.mss.go.kr/site/smba/ex/bbs/List.do?cbIdx=86"
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
        # SPA라 직접 크롤링 어려움 — API 폴백 시도
        api = "https://www.sbiz24.kr/api/pbanc/list"
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
    """경기도경제과학진흥원 — 경기/용인 지역"""
    url = "https://www.gbsa.or.kr/pages/board/list.asp?b_code=K_BIZ"
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
            "source": "경기경제과학진흥원",
            "title": title,
            "url": full_url,
            "agency": "경기도경제과학진흥원",
            "deadline": deadline,
            "posted_date": None,
            "raw": {},
        })

    return items[:40]


# ==================== 8. 용인시산업진흥원 (YPA) ====================
def fetch_ypa():
    """용인시산업진흥원 — 지역 직접 (실측 메일에서 확인된 고가치 소스)"""
    url = "https://www.ypa.or.kr/ypa/sub/news/notice.do"
    r = _safe_get(url)
    if not r:
        url = "https://www.ypa.or.kr/"
        r = _safe_get(url)
        if not r:
            return []

    soup = BeautifulSoup(r.text, "lxml")
    items = []

    for link in soup.select("a"):
        text = link.get_text(strip=True)
        if not text or len(text) < 8:
            continue
        if not any(k in text for k in ["지원", "모집", "공고", "신청", "교육"]):
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

    return items


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
    """창업진흥원 직접 — K-Startup과 별도 페이지"""
    url = "https://www.kised.or.kr/menu.es?mid=a10302000000"
    r = _safe_get(url)
    if not r:
        return []

    soup = BeautifulSoup(r.text, "lxml")
    items = []

    for row in soup.select("table tbody tr, .board_list li, ul.list li"):
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
            "source": "창업진흥원",
            "title": title,
            "url": full_url,
            "agency": "창업진흥원",
            "deadline": deadline,
            "posted_date": None,
            "raw": {},
        })

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


# ==================== 통합 (15개 소스) ====================
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
