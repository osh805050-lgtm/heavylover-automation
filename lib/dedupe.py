"""공고 중복 제거 (Layer 1+2 통합)

같은 공고가 1차 크롤링·메일·다른 사이트에서 동시 발견 가능.
title 정규화 + 발주기관 + 마감일 3-튜플로 dedupe.
"""

import hashlib
import re


def _normalize_title(title):
    """공고 제목 정규화 — 비교 가능한 형태로"""
    if not title:
        return ""
    # 앞쪽 [태그] 모두 제거 (반복)
    while True:
        new = re.sub(r"^\s*\[[^\]]+\]\s*", "", title)
        if new == title:
            break
        title = new
    # 일자 표시 제거 (4/24일자, 4월 24일자 등)
    title = re.sub(r"\d+[/.\-월]\d+\s*일\s*자", "", title)
    title = re.sub(r"\d+월\s*\d+일", "", title)
    # 일반 정부 뉴스레터 prefix
    title = re.sub(r"^\s*-\s*", "", title)
    title = re.sub(r"지원사업\s*-\s*", "", title)
    # 연도 표기 제거 (2026년 등 — 매년 다른 공고일 수 있어서 보존하려면 주석 처리)
    # title = re.sub(r"20\d{2}년\s*", "", title)
    # 공백 정규화
    title = re.sub(r"\s+", " ", title).strip()
    # 핵심부 비교 (앞 35자)
    return title[:35].lower()


def _make_key(item):
    """공고 식별 키 — title + agency + deadline"""
    title = _normalize_title(item.get("title", ""))
    agency = (item.get("agency") or "").strip().lower()
    deadline = item.get("deadline") or ""
    raw = f"{title}|{agency}|{deadline}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def dedupe(items, prefer_sources=None):
    """중복 제거. 같은 키면 prefer_sources 우선, 그 다음 정보 풍부한 것 우선.

    Args:
        items: 공고 리스트
        prefer_sources: 우선 유지할 source 리스트 (예: ["기업마당"] — 1차가 메일보다 우선)

    Returns:
        list: 중복 제거된 공고 (원본 정렬 보존, found_in 필드 추가)
    """
    prefer_sources = prefer_sources or []
    seen = {}

    for item in items:
        key = _make_key(item)
        if key not in seen:
            seen[key] = {**item, "found_in": [item.get("source", "unknown")]}
        else:
            existing = seen[key]
            # found_in 누적
            new_source = item.get("source", "unknown")
            if new_source not in existing["found_in"]:
                existing["found_in"].append(new_source)

            # 우선순위 비교
            existing_pref = next(
                (i for i, s in enumerate(prefer_sources) if s in existing.get("source", "")),
                999,
            )
            new_pref = next(
                (i for i, s in enumerate(prefer_sources) if s in new_source), 999
            )

            if new_pref < existing_pref:
                # 새 것이 우선 — 교체하되 found_in은 유지
                merged = {**item, "found_in": existing["found_in"]}
                seen[key] = merged
            else:
                # 기존 유지 — 단, 새 것에서 부족한 정보 보충
                if not existing.get("deadline") and item.get("deadline"):
                    existing["deadline"] = item["deadline"]
                if not existing.get("agency") and item.get("agency"):
                    existing["agency"] = item["agency"]

    return list(seen.values())


if __name__ == "__main__":
    samples = [
        {"title": "[기업마당]4/24일자 지원사업 - 2026년 초기창업패키지 모집공고", "source": "기업마당", "agency": "창업진흥원"},
        {"title": "2026년 초기창업패키지 모집공고", "source": "naver_mail", "agency": "창업진흥원", "deadline": "2026-05-15"},
        {"title": "K-Food 수출 바우처", "source": "기업마당"},
    ]
    result = dedupe(samples, prefer_sources=["기업마당"])
    print(f"입력 {len(samples)}건 → 출력 {len(result)}건")
    for r in result:
        print(f"  {r['title']}")
        print(f"    found_in: {r['found_in']}, deadline: {r.get('deadline')}")
