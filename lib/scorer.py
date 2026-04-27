"""공고 적합도 점수 산출 (Layer 3)

CLAUDE.md §2 헤비로버 프로필 + §3 제품 라인업 기반.
키워드 매칭 + 지역 가중치 + 마감 임박 보너스.
Claude API 의미 판정은 Layer 4에서 (비용 절감 위해 분리).

점수 0~10:
  3 이상 → 텔레그램 알림
  7 이상 → 캘린더 등록 + 사업계획서 초안 후보
  9 이상 → 긴급 알림 (별도 이모지)
"""

import re
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

# ==================== 헤비로버 적합 키워드 (CLAUDE.md §2·§3) ====================
CORE_KEYWORDS = [
    "식품", "냉동", "단백질", "도시락", "시리얼",
    "D2C", "이커머스", "온라인", "쇼핑몰",
    "HACCP", "K-Food", "수출", "아마존",
    "마케팅", "브랜드", "콘텐츠",
]

GROWTH_KEYWORDS = [
    "창업", "예비창업", "벤처", "스타트업",
    "소상공인", "청년", "재도전",
    "바우처", "인증", "지식재산",
    "투자", "성장", "사업화",
]

# 헤비로버 직결 강한 매칭 (가중치 ×3)
STRONG_MATCH_KEYWORDS = [
    "초기창업", "초기창업패키지", "창업패키지",
    "수출기업화", "내수기업 수출",
    "K-Food", "농식품", "식품수출",
    "용인시", "경기 창업",
]

TECH_KEYWORDS = [
    "AI", "데이터", "ICT", "디지털", "스마트공장",
    "R&D", "기술개발", "혁신",
]

# 강한 제외 (관련 없음)
EXCLUDE_KEYWORDS = [
    "농민", "어민", "어업", "축산농가", "임업",
    "건축", "토목", "건설현장",
    "의료기기", "제약", "바이오의약",
    "철강", "조선", "항공우주",
    "노인", "장애인 시설", "보육",
]

# 부분 가점 도메인
PREFERRED_REGIONS = ["경기", "용인", "전국"]
PREFERRED_AGENCIES = [
    "농림축산식품부", "aT", "K-Food",
    "용인", "경기",
    "중소벤처기업부", "창업진흥원",
]


def _has_any(text, keywords):
    return any(k.lower() in text.lower() for k in keywords)


def _count_hits(text, keywords):
    return sum(1 for k in keywords if k.lower() in text.lower())


def _days_until_deadline(deadline_str):
    """마감일까지 남은 일수. None이면 None."""
    if not deadline_str:
        return None
    try:
        dt = datetime.strptime(deadline_str, "%Y-%m-%d").replace(tzinfo=KST)
        today = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
        return (dt - today).days
    except (ValueError, TypeError):
        return None


def score_announcement(item):
    """공고 한 건 점수 산출.

    Args:
        item: {"title", "agency"?, "source"?, "deadline"?, "body_excerpt"?, ...}

    Returns:
        dict: 원본 + {"score", "matched", "tier", "deadline_days", "tags"}
    """
    title = item.get("title", "")
    body = item.get("body_excerpt", "") or item.get("subject", "")
    agency = item.get("agency", "") or ""
    source = item.get("source", "")

    text = f"{title} {body} {agency}"

    # 강한 제외 → 즉시 0점
    if _has_any(text, EXCLUDE_KEYWORDS):
        # 단, 헤비로버 핵심 키워드가 동시에 있으면 제외 안 함 (식품·D2C 우선)
        if not _has_any(text, ["식품", "D2C", "냉동", "도시락", "시리얼", "단백질"]):
            return {
                **item,
                "score": 0,
                "matched": [],
                "tier": "제외",
                "deadline_days": _days_until_deadline(item.get("deadline")),
                "tags": ["EXCLUDED"],
            }

    matched = []
    score = 0

    # 헤비로버 직결 강한 매칭 (최우선 가점)
    strong_hits = _count_hits(text, STRONG_MATCH_KEYWORDS)
    if strong_hits > 0:
        matched += [k for k in STRONG_MATCH_KEYWORDS if k.lower() in text.lower()][:3]
        score += min(6, strong_hits * 3)

    # 핵심 키워드 매칭 (가중치 높음)
    core_hits = _count_hits(text, CORE_KEYWORDS)
    if core_hits > 0:
        matched += [k for k in CORE_KEYWORDS if k.lower() in text.lower()][:3]
        score += min(5, core_hits * 1.5)

    # 성장·창업 키워드
    growth_hits = _count_hits(text, GROWTH_KEYWORDS)
    if growth_hits > 0:
        matched += [k for k in GROWTH_KEYWORDS if k.lower() in text.lower()][:2]
        score += min(3, growth_hits * 0.7)

    # 기술 키워드 (보너스)
    tech_hits = _count_hits(text, TECH_KEYWORDS)
    if tech_hits > 0:
        score += min(1.5, tech_hits * 0.5)

    # 지역 가점
    if _has_any(text, PREFERRED_REGIONS):
        score += 1
        matched.append("지역가점")

    # 발주 기관 가점
    if _has_any(f"{source} {agency}", PREFERRED_AGENCIES):
        score += 0.5

    # 마감 임박 보너스 (점수 자체는 동일, 태그로 표시)
    days_left = _days_until_deadline(item.get("deadline"))
    tags = []
    if days_left is not None:
        if days_left < 0:
            tags.append("마감지남")
            score = max(0, score - 3)
        elif days_left <= 3:
            tags.append("D-3긴급")
            score += 1.5
        elif days_left <= 7:
            tags.append("D-7임박")
            score += 0.5

    final_score = round(min(10, max(0, score)), 1)

    if final_score >= 9:
        tier = "S (긴급)"
    elif final_score >= 7:
        tier = "A (계획서)"
    elif final_score >= 5:
        tier = "B (검토)"
    elif final_score >= 3:
        tier = "C (참고)"
    else:
        tier = "D (낮음)"

    return {
        **item,
        "score": final_score,
        "matched": list(dict.fromkeys(matched)),
        "tier": tier,
        "deadline_days": days_left,
        "tags": tags,
    }


def score_all(items):
    """전체 공고 리스트 점수 산출 + 점수 내림차순 정렬"""
    scored = [score_announcement(it) for it in items]
    scored.sort(key=lambda x: (-x["score"], x.get("deadline_days") or 999))
    return scored


if __name__ == "__main__":
    import json

    sample = [
        {"title": "2026년 초기창업패키지 모집공고", "agency": "창업진흥원", "deadline": "2026-05-15"},
        {"title": "냉동식품 K-Food 수출 바우처 지원사업", "agency": "aT", "deadline": "2026-04-30"},
        {"title": "농민 영농자금 융자 지원", "agency": "농협"},
        {"title": "용인시 청년 창업 디딤돌", "agency": "용인시", "deadline": "2026-04-29"},
        {"title": "축산농가 사료비 지원", "agency": "농림축산식품부"},
    ]
    for it in score_all(sample):
        print(f"[{it['tier']}] {it['score']}/10 | {it['title']}")
        print(f"  매칭: {it['matched']} | 태그: {it['tags']} | D{it['deadline_days']}")
