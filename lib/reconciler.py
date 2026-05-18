"""API/requests 결과와 Playwright 결과를 cross-check하고 누락된 공고를 검출.

사용 의도:
  - 기존 lib/govt_sources.py(API/requests) 결과 = items_api
  - lib/govt_playwright.py(Playwright) 결과 = items_pw
  - 두 결과를 합치되 dedup
  - Playwright에만 있는 항목 = 사이트 화면엔 있는데 API/requests fetcher가 누락한 것
    → 텔레그램 즉시 알림 후보

매칭 규칙(보수적):
  1. URL 정규화(fragment·tracking 파라미터 제거) 일치 → 동일 공고
  2. 제목 정규화 일치 (+ agency 같음 또는 한쪽 미상) → 동일 공고

설계 의도: "API로 받은 데이터에 누락이 있는지 모른다"는 문제를 Playwright 결과와의
차이로 직접 검출. 정부 사이트의 의미있는 쿼리(pblancId, sportSeq 등)는 절대 제거 X.
"""

import logging
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

log = logging.getLogger(__name__)

# 광고/세션 파라미터만 제거. pbancId·sportSeq·b_idx 등 의미있는 쿼리는 보존.
_DROP_QUERY_KEYS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "fbclid", "gclid", "_", "t", "_ga",
}

_TITLE_NORMALIZE_RE = re.compile(r"[\s\W_]+", re.UNICODE)
_YEAR_RE = re.compile(r"\b20\d{2}\s*년?\b")
_PAREN_RE = re.compile(r"\([^)]{0,40}\)")


def _normalize_url(url: str) -> str:
    """tracking 파라미터·fragment 제거 후 소문자화. 식별자 쿼리는 보존."""
    if not url:
        return ""
    try:
        u = urlparse(url.strip())
        qs = [
            (k, v) for (k, v) in parse_qsl(u.query, keep_blank_values=False)
            if k.lower() not in _DROP_QUERY_KEYS
        ]
        qs.sort()
        path = u.path.rstrip("/") or "/"
        return urlunparse((u.scheme.lower(), u.netloc.lower(), path, "", urlencode(qs), ""))
    except Exception:
        return url.strip().lower()


def _normalize_title(title: str) -> str:
    """제목 정규화: 공백·기호 제거 + 연도/괄호 보조어 정리."""
    if not title:
        return ""
    s = title.lower()
    s = _YEAR_RE.sub("", s)
    s = _PAREN_RE.sub("", s)
    return _TITLE_NORMALIZE_RE.sub("", s).strip()


def _agency_key(it: dict) -> str:
    return (it.get("agency") or "").strip().lower()


def reconcile(items_api, items_pw):
    """API/requests 결과와 Playwright 결과 매칭.

    Returns:
        {
            "merged":           list[dict]  # dedup된 합집합 (API 우선)
            "api_only":         list[dict]  # API에만 있는 항목
            "playwright_only":  list[dict]  # PW에만 있는 항목 = API 누락 후보
            "stats":            dict        # 카운트 요약
        }
    """
    items_api = list(items_api or [])
    items_pw = list(items_pw or [])

    # API 인덱스 (URL + 제목)
    api_by_url = {}
    api_by_title = {}
    for it in items_api:
        url = _normalize_url(it.get("url", ""))
        title = _normalize_title(it.get("title", ""))
        if url:
            api_by_url[url] = it
        if title:
            api_by_title.setdefault(title, []).append(it)

    # PW 항목 분류
    playwright_only = []
    matched_pw = []
    seen_pw_urls = set()
    matched_api_keys = set()  # api_only 계산용

    for it in items_pw:
        url = _normalize_url(it.get("url", ""))
        title = _normalize_title(it.get("title", ""))
        agency = _agency_key(it)
        if url and url in seen_pw_urls:
            continue
        if url:
            seen_pw_urls.add(url)

        matched_with = None
        # 매칭 1: URL
        if url and url in api_by_url:
            matched_with = api_by_url[url]
        # 매칭 2: 제목 + agency
        elif title:
            for cand in api_by_title.get(title, []):
                cand_agency = _agency_key(cand)
                if not agency or not cand_agency or agency == cand_agency:
                    matched_with = cand
                    break

        if matched_with is not None:
            matched_pw.append(it)
            matched_api_keys.add(id(matched_with))
        else:
            playwright_only.append(it)

    api_only = [it for it in items_api if id(it) not in matched_api_keys]
    merged = list(items_api) + playwright_only

    return {
        "merged": merged,
        "api_only": api_only,
        "playwright_only": playwright_only,
        "stats": {
            "api_count": len(items_api),
            "pw_count": len(items_pw),
            "merged_count": len(merged),
            "matched_count": len(matched_pw),
            "playwright_only_count": len(playwright_only),
            "api_only_count": len(api_only),
        },
    }


def select_missing_alerts(playwright_only, min_score=5.0):
    """playwright_only 중 적합도 ≥ min_score 항목을 알림 후보로 선별.

    scorer가 호출되기 전 단계에서는 score 키가 없으므로, score/fit_score 둘 다 확인.
    """
    selected = []
    for it in playwright_only:
        score = it.get("score") or it.get("fit_score") or 0
        if score >= min_score:
            selected.append(it)
    return selected


def format_alert_text(items, max_show=10):
    """누락 알림용 텔레그램 텍스트 빌드."""
    if not items:
        return ""
    lines = [f"⚠️ API 누락 감지 — Playwright에서만 발견된 공고 {len(items)}건"]
    for it in items[:max_show]:
        title = (it.get("title") or "")[:80]
        source = it.get("source") or "?"
        deadline = it.get("deadline") or "마감 미상"
        lines.append(f"\n[{source}] {title}\n  마감: {deadline}\n  URL: {it.get('url','')}")
    if len(items) > max_show:
        lines.append(f"\n... 외 {len(items) - max_show}건")
    return "\n".join(lines)
