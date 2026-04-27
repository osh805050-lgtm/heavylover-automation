"""기업마당 통합 사업공고 API 클라이언트 (공공데이터포털)

엔드포인트: 중소벤처기업부_중소기업 지원사업 공고 조회 서비스
출처: 중앙부처·지자체·유관기관(소상공인진흥공단·창업진흥원·KOTRA 등) 통합
인증: data.go.kr 발급 인증키 (DATA_GO_KR_API_KEY) — K-Startup과 동일 키 사용

⚠️ 중요: requests의 params= 자동 인코딩이 인증키를 한 번 더 인코딩해 망가뜨림.
       URL에 직접 쿼리스트링 삽입 방식 필수.

사용:
    from lib.bizinfo_api import fetch_announcements
    items = fetch_announcements(per_page=100, max_pages=3)
"""

import logging
import os
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import requests
from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent.parent / ".env"
API_URL = "https://apis.data.go.kr/1421000/bizinfo/pblancBsnsService"
KST = timezone(timedelta(hours=9))

log = logging.getLogger(__name__)


def _get_key():
    load_dotenv(ENV_PATH, override=True)
    key = os.getenv("DATA_GO_KR_API_KEY")
    if not key:
        raise RuntimeError(
            "DATA_GO_KR_API_KEY가 .env에 없습니다. "
            "docs/govt-radar/04-public-data-api.md 참고."
        )
    return key


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        if data.strip():
            self.parts.append(data.strip())


def _strip_html(html):
    if not html:
        return ""
    p = _HTMLStripper()
    try:
        p.feed(html)
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)
    text = " ".join(p.parts)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _parse_period(period_str):
    """'2026-04-23 ~ 2026-05-07' → ('2026-04-23', '2026-05-07')"""
    if not period_str or period_str == "사업별 상이":
        return None, None
    m = re.search(
        r"(\d{4}[-./]\d{1,2}[-./]\d{1,2}).*?(\d{4}[-./]\d{1,2}[-./]\d{1,2})",
        period_str,
    )
    if m:
        start = m.group(1).replace(".", "-").replace("/", "-")
        end = m.group(2).replace(".", "-").replace("/", "-")
        return start, end
    # 단일 마감일만 있는 경우
    m = re.search(r"(\d{4}[-./]\d{1,2}[-./]\d{1,2})", period_str)
    if m:
        return None, m.group(1).replace(".", "-").replace("/", "-")
    return None, None


def _normalize(item):
    """기업마당 API 응답 → 공통 스키마"""
    title = (item.get("pblancNm") or "").strip()
    url = (item.get("pblancUrl") or "").strip()
    pblanc_id = item.get("pblancId")
    agency_main = item.get("jrsdInsttNm") or ""        # 발주기관 (예: 경상남도)
    agency_exec = item.get("excInsttNm") or ""         # 시행기관 (예: 한국생산기술연구원)
    agency = agency_main or agency_exec or "기업마당"

    # 모집기간 파싱
    posted, deadline = _parse_period(item.get("reqstBeginEndDe", ""))
    if not posted:
        creat = (item.get("creatPnttm") or "")[:10]
        posted = creat if creat else None

    # 본문 (HTML 태그 제거)
    summary = _strip_html(item.get("bsnsSumryCn", ""))[:1500]

    target = item.get("trgetNm") or ""
    realm = item.get("pldirSportRealmLclasCodeNm") or ""
    hashtags = item.get("hashtags") or ""

    return {
        "source": "기업마당(API)",
        "title": title,
        "url": url,
        "agency": agency,
        "deadline": deadline,
        "posted_date": posted,
        "body_excerpt": summary,
        "raw": {
            "pblancId": pblanc_id,
            "agency_main": agency_main,
            "agency_exec": agency_exec,
            "trgetNm": target,
            "realm": realm,
            "hashtags": hashtags,
            "reqstMthPapersCn": item.get("reqstMthPapersCn"),  # 신청방법
            "refrncNm": item.get("refrncNm"),                   # 문의처
            "fileNm": item.get("fileNm"),                       # 첨부파일명
            "flpthNm": item.get("flpthNm"),                     # 첨부 다운로드 URL
        },
    }


def fetch_announcements(per_page=100, max_pages=3, search_keyword=None):
    """기업마당 사업공고 조회.

    Args:
        per_page: 페이지당 건수 (최대 100)
        max_pages: 최대 페이지 수 (300건이면 전국 1주일치 수준)
        search_keyword: 해시태그 검색 (예: "식품" — 미지정 시 전체)

    Returns:
        list[dict]: 공통 스키마 형식
    """
    key = _get_key()
    key_enc = urllib.parse.quote(key, safe="")

    results = []
    seen_ids = set()

    for page in range(1, max_pages + 1):
        # URL 직접 조립 (requests params= 사용 시 키 이중 인코딩 문제)
        params_parts = [
            f"serviceKey={key_enc}",
            "dataType=json",
            f"pageNo={page}",
            f"numOfRows={per_page}",
        ]
        if search_keyword:
            params_parts.append(f"hashtags={urllib.parse.quote(search_keyword)}")

        url = f"{API_URL}?" + "&".join(params_parts)

        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning(f"기업마당 API 페이지 {page} 실패: {e}")
            break

        body = data.get("response", {}).get("body", {})
        items_wrap = body.get("items", {})
        items = items_wrap.get("item", []) if isinstance(items_wrap, dict) else items_wrap
        if not items:
            break
        if not isinstance(items, list):
            items = [items]

        for it in items:
            pid = it.get("pblancId")
            if pid and pid in seen_ids:
                continue
            seen_ids.add(pid)
            results.append(_normalize(it))

        if len(items) < per_page:
            break

    return results


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    items = fetch_announcements(per_page=100, max_pages=2)
    print(f"=== 기업마당 통합공고 {len(items)}건 ===\n")
    for it in items[:8]:
        print(f"[{it['deadline'] or '?'}] {it['title'][:70]}")
        print(f"  발주: {it['agency']} | 대상: {it['raw'].get('trgetNm')} | 분야: {it['raw'].get('realm')}")
        print(f"  본문: {it['body_excerpt'][:120]}...")
        print(f"  URL: {it['url']}")
        print()
