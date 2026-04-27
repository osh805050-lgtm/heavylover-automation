"""정부지원 레이더 점수 알고리즘 회귀 테스트

본사: 경기도 용인시 수지구 (memory/hq_location.md)

핵심 케이스:
  1) 본사 외 경기 시·군 (파주·화성·부천 등) 한정 공고 차단
  2) 본사(용인) 공고 통과
  3) 광역(경기도) 공고 통과
  4) 전국 사업(통합공고·통상촉진단) 통과
  5) 헤비로버 직격탄 사업(초기창업패키지·강한소상공인·K-FOOD) S 등급
"""

import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.scorer import score_announcement


# ============================================================
# 케이스 정의
# ============================================================
CASES = [
    # ---------- 차단되어야 함 (타지역) ----------
    {
        "name": "파주시 청년창업 활성화 — 발주기관 파주시",
        "input": {
            "title": "파주시 청년창업 활성화 지원사업 참여기업 모집",
            "agency": "파주시, (재)경기테크노파크",
            "body_excerpt": "파주시 관내 청년 창업기업을 모집합니다.",
        },
        "expect_tier_starts": "타지역",
    },
    {
        "name": "[경기] 화성시 해외전시회 단체관 — 화성 한정",
        "input": {
            "title": "[경기] 화성시 2026년 해외전시회 단체관 지원사업 참가기업 모집 공고",
            "agency": "경기도",
            "body_excerpt": "화성시는 관내 중소기업의 수출 판로 개척 지원을 위하여 「2026년 화성시 해외전시회 단체관 지원사업」에 참여할 기업을 모집합니다. 관내 본사 또는 공장이 소재한 전년도 수출액 2,000만불 이하 중소기업.",
        },
        "expect_tier_starts": "타지역",
    },
    {
        "name": "[경기] 군포시 2026년 2차 지식재산 긴급지원",
        "input": {
            "title": "[경기] 군포시 2026년 2차 지식재산 긴급지원 사업 모집 공고",
            "agency": "지식재산처",
            "body_excerpt": "군포시 소재 기업만 신청 가능.",
        },
        "expect_tier_starts": "타지역",
    },
    {
        "name": "[경기] 부천시 G-FAIR — 부천 한정",
        "input": {
            "title": "[경기] 부천시 2026년 제29회 G-FAIR KOREA(대한민국우수상품전시회) 참가기업 모집 공고",
            "agency": "경기도",
            "body_excerpt": "부천시는 관내 중소기업의 판로 확대를 위해 G-FAIR KOREA 참가기업을 모집합니다. 관내 본사 또는 공장이 소재한 부천시 중소기업.",
        },
        "expect_tier_starts": "타지역",
    },
    {
        "name": "[부산] 광역시 한정 — 기존 필터 회귀 검증",
        "input": {
            "title": "[부산] 2026년 부산창업패키지 모집",
            "agency": "부산경제진흥원",
            "body_excerpt": "부산광역시 소재 기업.",
        },
        "expect_tier_starts": "타지역",
    },

    # ---------- 통과해야 함 (본사·광역·전국) ----------
    {
        "name": "[용인] 용인시 1인기업 마케팅 지원 — 본사",
        "input": {
            "title": "[용인] 용인시 1인기업 마케팅 지원사업 참여기업 모집",
            "agency": "용인시산업진흥원",
            "body_excerpt": "용인특례시 1인 창업기업 대상 마케팅 비용 지원.",
            "deadline": "2026-05-30",
        },
        "expect_tier_in": ["S", "A"],
    },
    {
        "name": "경기도 광역 — 용인 시·군 명시 없음",
        "input": {
            "title": "[경기] 2026년 경기도 수출기업 지원사업 모집 공고",
            "agency": "경기도경제과학진흥원",
            "body_excerpt": "경기도 소재 중소기업의 수출 판로 개척을 지원합니다.",
            "deadline": "2026-05-15",
        },
        "expect_tier_in": ["S", "A", "B"],
    },
    {
        "name": "초기창업패키지 통합공고 — 전국 (헤비로버 핵심)",
        "input": {
            "title": "2026년도 초기창업패키지 통합공고",
            "agency": "창업진흥원",
            "body_excerpt": "전국 창업 3년 이내 기업 대상.",
            "deadline": "2026-05-31",
        },
        "expect_tier_in": ["S", "A"],
    },
    {
        "name": "K-FOOD 페루 통상촉진단 — 전국 (nationwide override)",
        "input": {
            "title": "2026년 무역위기 대응 K-FOOD 페루 통상촉진단 참가기업 모집",
            "agency": "한국농수산식품유통공사",
            "body_excerpt": "전국 식품 수출기업 대상 페루 통상촉진단 운영.",
            "deadline": "2026-04-30",
        },
        "expect_tier_in": ["S"],
    },
    {
        "name": "농식품글로벌성장패키지 — 전국 (식품 직격)",
        "input": {
            "title": "2026 농식품 글로벌성장패키지 지원사업 모집",
            "agency": "농림축산식품부",
            "body_excerpt": "농식품 수출기업 글로벌 진출 지원.",
            "deadline": "2026-06-30",
        },
        "expect_tier_in": ["S", "A"],
    },
    {
        "name": "소상공인 도약지원사업 — 강한 소상공인 명칭 변경 매칭",
        "input": {
            "title": "2026년 소상공인 도약지원사업 모집공고",
            "agency": "소상공인시장진흥공단",
            "body_excerpt": "소상공인 매출 성장 단계별 맞춤형 지원.",
            "deadline": "2026-05-20",
        },
        "expect_tier_in": ["S", "A"],
    },
    {
        "name": "지식재산 바우처 — 전국",
        "input": {
            "title": "2026년 지식재산(IP) 바우처 지원사업 모집",
            "agency": "한국발명진흥회",
            "body_excerpt": "중소기업 IP 출원·등록·평가 비용 지원.",
            "deadline": "2026-05-31",
        },
        "expect_tier_in": ["S", "A", "B"],
    },

    # ---------- 비공고 차단 (협약·평가결과·채용·메뉴) ----------
    {
        "name": "무안군 업무협약 보도 — 비공고 (헤비로버 신청 불가)",
        "input": {
            "title": "무안군과 농수산식품 수출확대·저탄소 식생활 확산 업무협약",
            "agency": "한국농수산식품유통공사",
            "body_excerpt": "",
        },
        "expect_tier_starts": "비공고",
    },
    {
        "name": "직원 채용 면접전형 안내 — 비공고",
        "input": {
            "title": "2026년 제3차 직원 채용 필기전형 합격자 및 면접전형 안내 공고",
            "agency": "용인시산업진흥원",
            "body_excerpt": "",
        },
        "expect_tier_starts": "비공고",
    },
    {
        "name": "용역 제안서 평가 결과 — 비공고",
        "input": {
            "title": "2026년 판로개척 역량강화 교육 운영 용역 제안서 평가 결과",
            "agency": "용인시산업진흥원",
            "body_excerpt": "",
        },
        "expect_tier_starts": "비공고",
    },
    {
        "name": "센터 소개 페이지 — 비공고",
        "input": {
            "title": "용인시산업진흥원 창업지원센터를 소개합니다.",
            "agency": "용인시산업진흥원",
            "body_excerpt": "",
        },
        "expect_tier_starts": "비공고",
    },
    {
        "name": "메뉴 텍스트 (마케팅·판로지원) — 메뉴/소개",
        "input": {
            "title": "마케팅·판로지원",
            "agency": "용인시산업진흥원",
            "body_excerpt": "",
        },
        "expect_tier_starts": "메뉴",
    },

    # ---------- 우선순위 지원 유형 가점 (자금·인프라·공간) ----------
    {
        "name": "자금지원 — 정책자금/보조금 (가점 적용)",
        "input": {
            "title": "2026년 중소기업 정책자금 지원사업 모집 공고",
            "agency": "중소벤처기업부",
            "body_excerpt": "전국 중소기업 대상 운영자금 융자 지원.",
            "deadline": "2026-05-31",
        },
        "expect_tier_in": ["S", "A", "B"],
    },
    {
        "name": "사업공간 — 창업보육센터 입주",
        "input": {
            "title": "2026년 용인 창업보육센터 입주기업 모집",
            "agency": "용인시산업진흥원",
            "body_excerpt": "용인 소재 창업기업 입주공간 제공.",
            "deadline": "2026-05-15",
        },
        "expect_tier_in": ["S", "A"],
    },
    {
        "name": "단순 교육 (자금·공간 없음) — 점수 낮음",
        "input": {
            "title": "2026년 4기 마케팅 교육생 모집 (8회 과정)",
            "agency": "어디",
            "body_excerpt": "마케팅 강의 8회 수강. 수료증 발급.",
            "deadline": "2026-05-30",
        },
        "expect_tier_in": ["B", "C", "D"],
    },
]


def run():
    pass_count = 0
    fail_count = 0
    fails = []

    for c in CASES:
        result = score_announcement(c["input"])
        tier = result.get("tier") or ""
        ok = False

        if "expect_tier_starts" in c:
            ok = tier.startswith(c["expect_tier_starts"])
            expected = f"starts with '{c['expect_tier_starts']}'"
        elif "expect_tier_in" in c:
            ok = any(tier.startswith(t) for t in c["expect_tier_in"])
            expected = f"in {c['expect_tier_in']}"

        if ok:
            pass_count += 1
            print(f"  [PASS] {c['name']}")
            print(f"         tier={tier} score={result.get('score')}")
        else:
            fail_count += 1
            fails.append((c["name"], expected, tier, result.get("score")))
            print(f"  [FAIL] {c['name']}")
            print(f"         expected {expected}, got tier={tier} score={result.get('score')}")

    print()
    print("=" * 60)
    print(f"통과: {pass_count} / {len(CASES)}  실패: {fail_count}")
    if fails:
        print()
        print("실패 케이스:")
        for name, exp, got, score in fails:
            print(f"  - {name}: expected {exp}, got tier={got} score={score}")

    return fail_count == 0


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
