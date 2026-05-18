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
    "판로", "유통", "라이브커머스",
    # 헤비로버 상품 카테고리
    "HMR", "냉동식품", "간편식",
    "건기식", "간식",
    # 수출·해외 확장
    "해외진출", "글로벌", "수출기업",
    # 채널
    "스마트스토어", "네이버쇼핑",
    # 식품 제조
    "포장재", "패키징",
]

GROWTH_KEYWORDS = [
    "창업", "예비창업", "벤처", "스타트업",
    "소상공인", "청년", "재도전",
    "바우처", "인증", "지식재산",
    "투자", "성장", "사업화",
    "도약",  # "소상공인 도약지원사업" 매칭용
]

# 헤비로버 직결 강한 매칭 (가중치 ×3)
STRONG_MATCH_KEYWORDS = [
    "초기창업", "초기창업패키지", "창업패키지",
    "수출기업화", "내수기업 수출",
    "K-Food", "농식품", "식품수출",
    "용인시", "수지구", "경기 창업",
    # 소상공인 핵심 사업 (구·신 명칭 모두)
    "강한 소상공인", "소상공인 도약", "소상공인도약",
    "소상공인 성장", "희망리턴패키지",
    # 식품 D2C 핵심
    "농식품글로벌성장패키지", "K-FOOD",
    # 헤비로버 §9 진행 중 핵심 사업
    "지식재산 바우처", "지식재산바우처", "IP 바우처", "IP바우처",
    "지식재산(IP) 바우처", "지식재산(ip) 바우처",
    "IP) 바우처",  # "지식재산(IP) 바우처" 안전 매칭
    "온라인 플랫폼", "온라인플랫폼",
    # 판로·유통 직결
    "수출바우처", "판로개척",
    # D2C 채널 입점 지원
    "스마트스토어 입점", "네이버쇼핑 입점",
]

# 헤비로버 우선순위 지원 유형 — 자금·인프라·공간 (가중치 ×2)
# 사용자 명시 (2026-04-28): 자금지원, 인프라 제공, 사업공간 제공 유달리 필요
HIGH_PRIORITY_SUPPORT_KEYWORDS = [
    # 자금
    "정책자금", "융자", "보조금", "지원금", "운영자금",
    "성장자금", "긴급자금", "특례보증",
    # 인프라
    "시설장비", "시설·장비", "장비활용", "장비 활용",
    "테스트베드", "공장 임대", "공유주방", "공유공장",
    "스마트공장 구축",  # "스마트공장"은 일반 R&D 의미 강해서 "구축" 한정
    # 사업공간
    "입주기업", "입주공간", "창업보육", "보육센터",
    "사무공간", "사무실 임대", "코워킹", "오피스 입주",
    "창업공간",
]

# 명백히 부적합한 지원 유형 (가중치 -1.5)
LOW_PRIORITY_SUPPORT_KEYWORDS = [
    "교육생 모집", "교육과정", "강의 수강",  # 단순 교육
    "세미나 참가", "워크숍 참가",
    "포럼 참가", "박람회 관람",
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
    "노인", "장애인 시설",
    "어린이집", "보육시설", "보육교사",  # 단순 "보육"은 창업보육센터와 충돌 → 구체화
]

# ⚠️ 본사 외 타지역 한정 공고 — 헤비로버(경기도 용인시 수지구) 지원 불가
# 약칭과 정식 명칭 모두 매칭하기 위해 alias 맵 사용
NON_ELIGIBLE_REGIONS = [
    "부산", "대구", "광주", "대전", "울산", "세종", "인천",
    "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
    "서울", "강남", "강서", "강동", "강북", "구로", "금천", "노원",
    "도봉", "동대문", "동작", "마포", "서초", "성동", "성북", "송파",
    "양천", "영등포", "용산", "은평", "종로", "중랑",  # "중구" 제거 (광역시 외 모호)
]

# ⚠️ 경기도 산하 시·군 (용인 제외) — 본사 외 시·군 한정 공고 차단용
# 광역(경기도) 또는 본사(용인) 단위 공고는 이 목록과 무관하게 통과
NON_ELIGIBLE_GG_CITIES = [
    "수원", "성남", "안양", "안산", "고양", "과천", "구리", "광명",
    "군포", "김포", "남양주", "동두천", "부천", "시흥",
    "안성", "양주", "여주", "오산", "의왕", "의정부", "이천",
    "파주", "평택", "포천", "하남", "화성",
    "양평", "연천", "가평",  # 군
    # 용인 제외 — 본사 소재
    # "광주시"는 광주광역시와 충돌 가능 → "광주" 만 NON_ELIGIBLE_REGIONS에서 처리
]

# 본문 자격요건 한정 표현
RESTRICTION_PATTERNS = [
    "에 소재한", "에 본사를 둔", "에 사업장을 둔",
    "거주자에 한", "에 한해", "기업만 신청", "거주 기업",
    "소재 기업만",
]

# 비공고 패턴 — 제목에 들어가면 헤비로버가 신청할 수 없는 항목
# (협약·평가결과·채용·메뉴 텍스트·입찰공고 등)
NON_ANNOUNCEMENT_PATTERNS = [
    # 협약·뉴스 (보도자료, 신청 대상 아님)
    "업무협약", "MOU 체결", "협약 체결", "협약식",
    # 결과 보도 (사업 종료, 모집 끝)
    "평가 결과", "선정 결과", "최종 결과", "선정자 발표",
    "합격자 발표", "합격자 안내", "면접전형 안내", "면접 안내",
    "직원 채용", "신규 채용", "채용 공고", "채용공고",
    # 메뉴·소개 텍스트 (게시글이 아닌 안내 페이지)
    "을 소개합니다", "센터를 소개", "사업 소개", "을소개합니다",
    # 입찰·용역 (지원사업이 아닌 행정 발주, 헤비로버 입찰 자격 없음)
    "입찰공고", "용역 입찰", "용역 제안서", "제안서 평가",
    "재공고)",  # "용역 입찰공고(재공고)" 같은 패턴
    # 단순 운영 안내·홍보
    "설명회 후기", "운영 보고", "월간 동향",
]

# 타지역 약칭 ↔ 정식 명칭 매핑 (둘 다 매칭)
REGION_ALIASES = {
    "충남": ["충청남도"],
    "충북": ["충청북도"],
    "전남": ["전라남도"],
    "전북": ["전라북도"],
    "경남": ["경상남도"],
    "경북": ["경상북도"],
    "강원": ["강원특별자치도", "강원도"],
    "제주": ["제주특별자치도"],
}

# 타지역 prefix가 있어도 지원 가능한 사업 키워드 — 명확한 전국 신호만
# (이전엔 "수출"/"해외" 같은 광범위 단어가 false positive 유발 → 제거)
NATIONWIDE_OVERRIDE_KEYWORDS = [
    "K-Food", "K-FOOD", "K-FOOD",
    "통상촉진단", "수출컨소시엄", "해외전시회 단체관",
    "통합공고",  # 명시적 전국 통합
    # 명확한 전국 단위 사업 (지역 무관)
    "농식품글로벌성장패키지",
    "내수기업 수출기업화",
    "초기창업패키지", "예비창업패키지",
]

# 부분 가점 도메인
# - 헤비로버 본사: 경기도 용인시 수지구 (메모리 hq_location.md)
# - "전국" 공고는 어디든 적용 가능하므로 가점 동등
# - 타지역(부산·광주 등) 공고도 본문이 헤비로버 적합하면 점수 충분히 받도록 함 (지역 가점 비중 ↓)
PREFERRED_REGIONS = ["경기", "용인", "수지", "전국"]
PREFERRED_AGENCIES = [
    "aT", "K-Food",  # 농림축산식품부 제거 — 무관 공고(방역·할당관세)에 과가점 방지
    "용인", "경기", "수지구",
    "중소벤처기업부", "창업진흥원",
    "소상공인시장진흥공단", "소진공",
    "경기테크노파크",
    "중소기업유통센터",
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
    title = item.get("title", "") or ""
    body = item.get("body_excerpt", "") or item.get("subject", "") or ""
    agency = item.get("agency", "") or ""
    source = item.get("source", "") or ""

    # 빈 데이터는 즉시 0점
    if not title.strip() and not body.strip() and not agency.strip():
        return {
            **item,
            "score": 0,
            "fit_score": 0,
            "region_score": 0,
            "deadline_score": 0,
            "region_label": "데이터 없음",
            "matched": [],
            "tier": "제외",
            "deadline_days": None,
            "tags": ["EMPTY"],
        }

    text = f"{title} {body} {agency}"
    # 키워드 점수 산출은 제목+본문만 사용 — 기관명에 '식품' 포함돼도 오매칭 방지
    text_content = f"{title} {body}"

    # 비공고 패턴 (협약·평가결과·채용·입찰공고 등) → 즉시 0점
    if any(p in title for p in NON_ANNOUNCEMENT_PATTERNS):
        return {
            **item,
            "score": 0,
            "matched": [],
            "tier": "비공고 (뉴스/협약/메뉴)",
            "deadline_days": _days_until_deadline(item.get("deadline")),
            "tags": ["NON_ANNOUNCEMENT"],
        }

    # 메뉴·카테고리 텍스트 차단 — 본문 없고 제목 12자 미만 + 공고형 키워드 없음
    if not body.strip() and len(title) < 12:
        if not _has_any(
            title,
            STRONG_MATCH_KEYWORDS + ["모집", "공고", "신청", "지원사업", "참여기업"],
        ):
            return {
                **item,
                "score": 0,
                "matched": [],
                "tier": "메뉴/소개 (제외)",
                "deadline_days": _days_until_deadline(item.get("deadline")),
                "tags": ["MENU_LIKE"],
            }

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

    # 타지역 한정 공고 제외 (본사: 경기도 용인시 수지구)
    # 우선순위 (강함 → 약함):
    #  1) 제목에 [부산]/[광주]/[경북] 등 지역 prefix → 그 지역 한정 (발주기관 무관)
    #  2) [경기]/[용인]/[수지] prefix → 통과
    #  3) prefix 없음 + 발주기관이 타 광역 + 본문도 타지역 강조 → 타지역
    #  4) 그 외 (전국 사업) → 통과
    has_home_prefix = any(
        f"[{r}]" in title or f"({r})" in title for r in ["경기", "용인", "수지"]
    )
    has_other_prefix = any(
        f"[{r}]" in title or f"({r})" in title for r in NON_ELIGIBLE_REGIONS
    )

    # prefix가 타지역이고 본사 prefix 동시에 없으면 → 무조건 제외
    # (NATIONWIDE_OVERRIDE 무시 — [광주] 같은 prefix는 명백한 지역 한정 신호)
    if has_other_prefix and not has_home_prefix:
        return {
            **item,
            "score": 0,
            "matched": [],
            "tier": "타지역 (지원불가)",
            "deadline_days": _days_until_deadline(item.get("deadline")),
            "tags": ["NON_ELIGIBLE_REGION"],
        }

    # prefix 없는 경우: 발주기관이 타 광역이고 + nationwide override 없으면 제외
    # 약칭+정식 명칭 모두 검사
    other_region_terms = list(NON_ELIGIBLE_REGIONS)
    for short, fulls in REGION_ALIASES.items():
        other_region_terms.extend(fulls)

    has_other_agency = any(
        r in agency for r in other_region_terms
        if r not in ["동구", "서구", "남구", "북구"]
    )
    has_home_agency = _has_any(
        agency, ["경기", "용인", "수지", "경기도경제과학진흥원", "용인시산업진흥원"]
    )
    has_nationwide_override = _has_any(text, NATIONWIDE_OVERRIDE_KEYWORDS)

    if has_other_agency and not has_home_agency and not has_nationwide_override:
        return {
            **item,
            "score": 0,
            "matched": [],
            "tier": "타지역 (지원불가)",
            "deadline_days": _days_until_deadline(item.get("deadline")),
            "tags": ["NON_ELIGIBLE_REGION"],
        }

    # ============================================================
    # 경기 산하 시·군 한정 공고 차단 (본사 외 — 용인 제외)
    # [경기] prefix가 있어도 실제로는 단일 시·군 한정인 경우가 다수
    # (예: "[경기] 화성시 해외전시회 단체관 지원사업" → 화성시 소재 기업만)
    # ============================================================
    has_home_city_signal = _has_any(title + agency, ["용인", "수지"])

    # 1) 제목에 타 시·군 명칭 포함 ([파주]·(파주)·파주시 등)
    has_gg_other_city_in_title = any(
        f"[{c}]" in title or f"({c})" in title or f"{c}시" in title
        for c in NON_ELIGIBLE_GG_CITIES
    )

    # 2) 발주기관이 타 시·군 (파주시·화성시·시흥산업진흥원 등)
    has_gg_other_city_agency = any(
        (f"{c}시" in agency or f"{c}산업진흥원" in agency or
         f"{c}경제진흥원" in agency or f"{c}시청" in agency or
         f"{c} 1인" in agency or f"{c}1인" in agency)
        for c in NON_ELIGIBLE_GG_CITIES
    )

    # 3) 본문 자격요건에 명시적 한정 (화성시에 소재한, 부천시 거주자에 한 등)
    has_gg_other_city_restriction = False
    for c in NON_ELIGIBLE_GG_CITIES:
        for p in RESTRICTION_PATTERNS:
            if f"{c}{p}" in body or f"{c}시{p}" in body:
                has_gg_other_city_restriction = True
                break
        if has_gg_other_city_restriction:
            break

    # 4) 본문에 "관내 본사" / "관내 기업" 명시 → 단일 시·군 한정 신호 (강함)
    has_local_only_signal = any(
        s in body for s in ["관내 본사", "관내 기업", "관내 중소기업", "관내에 소재", "관내 사업장"]
    )

    # nationwide override가 잡혔어도, 제목에 타 시·군이 명시됐거나
    # 본문에 "관내" 한정 표현이 있으면 단일 시·군 한정으로 판단 (override 무력화)
    if has_gg_other_city_in_title and (has_local_only_signal or has_gg_other_city_agency):
        return {
            **item,
            "score": 0,
            "matched": [],
            "tier": "타지역 (지원불가)",
            "deadline_days": _days_until_deadline(item.get("deadline")),
            "tags": ["NON_ELIGIBLE_REGION", "GG_OTHER_CITY", "LOCAL_ONLY"],
        }

    if (has_gg_other_city_in_title or has_gg_other_city_agency or
        has_gg_other_city_restriction) and not has_home_city_signal \
        and not has_nationwide_override:
        return {
            **item,
            "score": 0,
            "matched": [],
            "tier": "타지역 (지원불가)",
            "deadline_days": _days_until_deadline(item.get("deadline")),
            "tags": ["NON_ELIGIBLE_REGION", "GG_OTHER_CITY"],
        }

    matched = []

    # ============================================================
    # 점수 분해 — 사업적합도(0~8) + 지역(0~2) + 마감임박(-2~1)
    # ============================================================

    # ---------- 1. 사업적합도 (0~8) ----------
    fit_score = 0

    # 헤비로버 직결 강한 매칭 (초기창업패키지·강한소상공인·농식품글로벌·K-FOOD 등)
    strong_hits = _count_hits(text_content, STRONG_MATCH_KEYWORDS)
    has_strong = strong_hits > 0
    if strong_hits > 0:
        matched += [k for k in STRONG_MATCH_KEYWORDS if k.lower() in text_content.lower()][:3]
        fit_score += min(6, strong_hits * 3)  # 강한 매칭 1개 = 3점, 2개 = 6점 cap

    # 핵심 키워드 (식품·D2C·이커머스·수출 등)
    core_hits = _count_hits(text_content, CORE_KEYWORDS)
    if core_hits > 0:
        matched += [k for k in CORE_KEYWORDS if k.lower() in text_content.lower()][:3]
        fit_score += min(3, core_hits * 0.8)

    # 성장·창업 키워드
    growth_hits = _count_hits(text_content, GROWTH_KEYWORDS)
    if growth_hits > 0:
        matched += [k for k in GROWTH_KEYWORDS if k.lower() in text_content.lower()][:3]
        fit_score += min(2, growth_hits * 0.5)

    # 기술 키워드 (보너스)
    tech_hits = _count_hits(text_content, TECH_KEYWORDS)
    if tech_hits > 0:
        fit_score += min(1, tech_hits * 0.3)

    # 헤비로버 우선순위 지원 유형 가점 (자금·인프라·공간)
    high_prio_hits = _count_hits(text_content, HIGH_PRIORITY_SUPPORT_KEYWORDS)
    if high_prio_hits > 0:
        matched += [k for k in HIGH_PRIORITY_SUPPORT_KEYWORDS if k.lower() in text_content.lower()][:3]
        fit_score += min(2.5, high_prio_hits * 1.2)  # 1개 = +1.2, 2개 = +2.4 cap

    # 부적합 지원 유형 감점 (단순 교육·세미나만)
    low_prio_hits = _count_hits(text_content, LOW_PRIORITY_SUPPORT_KEYWORDS)
    if low_prio_hits > 0:
        # 단, 자금·인프라·공간 키워드도 같이 있으면 감점 안 함 (실질 지원이면 OK)
        if not high_prio_hits:
            fit_score -= min(2, low_prio_hits * 1.0)

    # 발주 기관 가점 (사업 적합도에 포함 — 농식품부·aT 같은 헤비로버 친화 기관)
    agency_text = f"{source} {agency}"
    if _has_any(agency_text, PREFERRED_AGENCIES):
        fit_score += 0.5

    # 핵심 발주기관 직접 매칭 (KOTRA·aT·창업진흥원 등) — 강한 가점
    # 헤비로버 직결 발주기관(식품·수출·창업) — 단독으로도 A 등급 도달 가능하게
    KEY_AGENCIES_STRONG = [
        "KOTRA", "aT(", "한국농수산식품유통공사",  # 식품·수출 직결
        "창업진흥원",                               # 헤비로버 핵심 (초기창업패키지)
        "용인시산업진흥원", "용인시",                # 본사 지자체
        "경기도경제과학진흥원", "(재)경기도경제과학진흥원",  # 본사 광역
        "소상공인시장진흥공단",                       # 소진공
    ]
    KEY_AGENCIES_NORMAL = [
        "농림축산식품부",  # 식품 무관 공고(방역·할당관세 등) 과가점 방지 — food 키워드와 조합 시 자연히 점수 높아짐
        "중소벤처기업부", "중소기업기술정보진흥원",
        "산업통상부", "산업통상자원부",
        "정보통신산업진흥원",
    ]
    if any(k in agency_text for k in KEY_AGENCIES_STRONG):
        fit_score += 4  # 헤비로버 직결 기관: KOTRA·aT·창업진흥원·용인 등
    elif any(k in agency_text for k in KEY_AGENCIES_NORMAL):
        fit_score += 1.5  # 일반 정부 부처

    # 강한 매칭 있으면 cap 상향 (헤비로버 직격탄 공고는 지역 무관 S 등급 가능)
    fit_score = min(8 if has_strong else 7, fit_score)

    # ---------- 2. 지역 가점 (0~2) ----------
    region_score = 0
    region_label = "타지역"
    if _has_any(title, ["[용인]", "[수지]"]) or _has_any(agency, ["용인", "수지"]):
        region_score = 2
        region_label = "본사(용인/수지)"
        matched.append("본사지역")
    elif _has_any(text, ["용인", "수지"]):
        region_score = 1.5
        region_label = "용인 본문"
        matched.append("용인본문")
    elif _has_any(title, ["[경기]"]) or _has_any(agency, ["경기"]):
        region_score = 1.5
        region_label = "경기"
        matched.append("경기")
    elif _has_any(text, ["경기"]):
        region_score = 1
        region_label = "경기 본문"
    elif _has_any(text, ["전국"]):
        region_score = 0.8
        region_label = "전국"
        matched.append("전국")
    else:
        region_score = 0.3  # 지역 표기 없음 = 전국 가능성

    # ---------- 3. 마감 임박 (0~1) ----------
    days_left = _days_until_deadline(item.get("deadline"))
    deadline_score = 0
    tags = []
    if days_left is not None:
        if days_left < 0:
            tags.append("마감지남")
            deadline_score = -2  # 강한 감점
        elif days_left <= 3:
            tags.append("D-3긴급")
            deadline_score = 1
        elif days_left <= 7:
            tags.append("D-7임박")
            deadline_score = 0.5
        elif days_left <= 14:
            deadline_score = 0.2
    else:
        deadline_score = 0.1  # 마감일 미상

    # ---------- 합산 ----------
    total = max(0, fit_score + region_score + deadline_score)
    final_score = round(min(10, total), 1)

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
        "fit_score": round(fit_score, 1),       # 사업적합도 (0~7)
        "region_score": round(region_score, 1), # 지역 가점 (0~2)
        "deadline_score": round(deadline_score, 1),  # 마감 임박 (0~1)
        "region_label": region_label,
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
