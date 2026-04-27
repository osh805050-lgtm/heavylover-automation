"""Layer 4 — Claude Haiku로 공고 자격요건 자동 검증

목적: 키워드 점수만으로는 잡히지 않는 자격 미달(예: "10년 이상 중견기업",
      "여성기업 한정", "농민·어민 한정")을 LLM 의미 판정으로 걸러냄.

비용:
  - Haiku 4.5 (claude-haiku-4-5-20251001) — 가장 저렴
  - 적합도 ≥5 공고에만 호출 (일 30~50건 추정)
  - 입력 ~600 토큰 (프로필 캐싱 적용 시 ~150 토큰), 출력 ~80 토큰
  - 월 예상 비용: 30건 × 30일 × $0.001 ≈ $1

캐싱:
  - heavylover_profile.json은 prompt cache에 ephemeral 등록 → 1시간 캐시
  - 30분에 1번만 미스나면 비용 90% 절감

사용:
  from lib.eligibility_checker import check_eligibility
  result = check_eligibility(item)
  # → {"eligible": "yes"|"no"|"unsure", "reason": str, "model_used": str}
"""

import json
import logging
import os
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent.parent / ".env"
PROFILE_PATH = Path(__file__).parent.parent / "data" / "heavylover_profile.json"
MODEL = "claude-haiku-4-5-20251001"
KST_LOG = logging.getLogger(__name__)

# 모듈 캐시
_profile_cache = None
_client_cache = None


def _load_profile():
    global _profile_cache
    if _profile_cache is None:
        _profile_cache = json.dumps(
            json.loads(PROFILE_PATH.read_text(encoding="utf-8")),
            ensure_ascii=False,
            indent=2,
        )
    return _profile_cache


def _get_client():
    global _client_cache
    if _client_cache is None:
        load_dotenv(ENV_PATH, override=True)
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY 미설정")
        _client_cache = Anthropic(api_key=key)
    return _client_cache


SYSTEM_PROMPT = """너는 한국 정부 지원사업 자격 심사관이다.
주어진 헤비로버 회사 프로필과 공고 정보를 비교해서, 헤비로버가 이 공고에 신청 자격이 되는지 판정한다.

판정 기준:
- "yes": 자격요건 충족 (지역·업종·법인·매출·연차 등 모두 적합 또는 무관)
- "no": 명백한 자격 미달 (예: 본사 다른 지역 한정, 여성기업 한정, 10년 이상, 농민 한정)
- "unsure": 정보 부족 또는 판단 모호 (자격이 본문에 명시 안 됨)

출력은 반드시 JSON 한 줄:
{"eligible": "yes|no|unsure", "reason": "한 줄 한국어"}

reason은 50자 이내. 추측 금지, 본문 근거만 사용."""


def check_eligibility(item: dict, max_body_chars: int = 800) -> dict:
    """공고 한 건의 자격 적합성 판정.

    Args:
        item: govt_radar 공통 스키마
              ({"title", "agency", "body_excerpt", "deadline", ...})
        max_body_chars: 본문 잘라낼 길이 (토큰 절약)

    Returns:
        {"eligible": "yes"|"no"|"unsure", "reason": str, "model_used": str}
        실패 시 {"eligible": "unsure", "reason": "검증 실패: ...", "model_used": ""}
    """
    title = (item.get("title") or "").strip()
    agency = (item.get("agency") or "").strip()
    body = (item.get("body_excerpt") or "")[:max_body_chars].strip()
    target = ((item.get("raw") or {}).get("trgetNm") or "").strip()

    if not title:
        return {"eligible": "unsure", "reason": "제목 없음", "model_used": ""}

    profile_json = _load_profile()
    user_msg = (
        f"# 헤비로버 프로필\n```json\n{profile_json}\n```\n\n"
        f"# 공고\n"
        f"제목: {title}\n"
        f"발주: {agency}\n"
        f"대상: {target}\n"
        f"본문: {body}\n\n"
        f"위 공고에 헤비로버가 신청 자격 있는지 판정. JSON 한 줄."
    )

    try:
        client = _get_client()
        resp = client.messages.create(
            model=MODEL,
            max_tokens=200,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_msg}],
        )
        raw_text = resp.content[0].text.strip()
    except Exception as e:
        KST_LOG.warning(f"자격검증 API 실패: {type(e).__name__}: {e}")
        return {
            "eligible": "unsure",
            "reason": f"API 실패: {type(e).__name__}",
            "model_used": "",
        }

    # JSON 추출 (모델이 ```json...``` 감쌀 수 있음)
    text = raw_text
    if "```" in text:
        # 첫 번째 코드블록 내용만 추출
        parts = text.split("```")
        for p in parts:
            if "{" in p and "}" in p:
                text = p
                break
    text = text.strip().lstrip("json").strip()

    try:
        parsed = json.loads(text)
        eligible = parsed.get("eligible", "unsure")
        reason = parsed.get("reason", "").strip()[:80]
        if eligible not in ("yes", "no", "unsure"):
            eligible = "unsure"
        return {"eligible": eligible, "reason": reason, "model_used": MODEL}
    except (json.JSONDecodeError, AttributeError) as e:
        KST_LOG.warning(f"자격검증 JSON 파싱 실패: {raw_text[:100]}")
        return {
            "eligible": "unsure",
            "reason": f"파싱 실패: {raw_text[:60]}",
            "model_used": MODEL,
        }


def batch_check(items: list, threshold_score: float = 5.0, limit: int = 80) -> list:
    """적합도 ≥ threshold 공고에 한해 자격 검증, 결과를 item에 inline 추가.

    Args:
        items: scored items list
        threshold_score: 이 점수 이상만 검증 (기본 5.0)
        limit: 1회 호출 상한 (비용 보호)

    Returns:
        items (in-place modified) — 각 item에 "eligibility" 필드 추가
        {item: {..., "eligibility": {"eligible": ..., "reason": ..., "model_used": ...}}}
    """
    eligible_for_check = [
        i for i in items
        if (i.get("score") or 0) >= threshold_score
        and not (i.get("tier") or "").startswith("타지역")
        and not (i.get("tier") or "").startswith("제외")
    ]

    if len(eligible_for_check) > limit:
        KST_LOG.warning(
            f"자격검증 대상 {len(eligible_for_check)}건이 limit({limit})보다 많음 → 점수 상위 {limit}건만"
        )
        eligible_for_check.sort(key=lambda x: -(x.get("score") or 0))
        eligible_for_check = eligible_for_check[:limit]

    KST_LOG.info(f"자격검증 시작: {len(eligible_for_check)}건 (threshold={threshold_score})")

    yes = no = unsure = 0
    for item in eligible_for_check:
        result = check_eligibility(item)
        item["eligibility"] = result
        if result["eligible"] == "yes":
            yes += 1
        elif result["eligible"] == "no":
            no += 1
        else:
            unsure += 1

    KST_LOG.info(
        f"자격검증 완료: yes={yes}, no={no}, unsure={unsure} "
        f"(false positive 제거 {no}건)"
    )
    return items


if __name__ == "__main__":
    import sys
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # 샘플 테스트
    samples = [
        {
            "title": "2026년 여성기업 창업도약 패키지 모집",
            "agency": "한국여성경제인협회",
            "body_excerpt": "여성기업 확인서 보유 기업만 신청 가능. 만 39세 이하 여성 대표.",
            "raw": {"trgetNm": "여성기업"},
        },
        {
            "title": "초기창업패키지 통합공고",
            "agency": "창업진흥원",
            "body_excerpt": "전국 창업 3년 이내 기업 대상.",
            "raw": {"trgetNm": "창업기업"},
        },
        {
            "title": "농어촌 식품가공 시설 신축 지원",
            "agency": "농림축산식품부",
            "body_excerpt": "농어업인이 직접 운영하는 가공시설 신축 지원. 농업경영체 등록 필수.",
            "raw": {"trgetNm": "농민"},
        },
    ]
    print(f"=== 자격검증 샘플 테스트 (모델: {MODEL}) ===\n")
    for s in samples:
        r = check_eligibility(s)
        print(f"[{r['eligible']:>6}] {s['title'][:50]}")
        print(f"         이유: {r['reason']}")
        print()
