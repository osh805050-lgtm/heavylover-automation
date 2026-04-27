"""Claude 액션 코멘트 자동 생성 (텔레그램 짧은 + 이메일 심층)."""

import json
import os
from datetime import timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent / ".env"
KST = timezone(timedelta(hours=9))

CLAUDE_MODEL = "claude-haiku-4-5"
MAX_TOKENS_SHORT = 600
MAX_TOKENS_DEEP = 2500


SYSTEM_PROMPT = """너는 헤비로버 Meta 광고 데이터 분석가다.

## 원칙
- 팩트 기반. 데이터 없으면 "데이터 없음" 명시. 추정으로 숫자 채우기 금지.
- 모든 액션 제안은 어느 지표가 어떻게 나왔는지 근거 명시.
- 블런트하게. "괜찮아 보입니다" 금지, 명확히 평가.
- 헤비로버 컨텍스트: D2C 피트니스 식품, 타겟 20~30대 운동 직장인 남성, ROAS 베이스라인 약 3.5.

## 벤치마크 (한국 D2C 식품, 2026)
| 지표 | 평균 | 우수 |
|---|---|---|
| CTR | 1.2% | 2.0%+ |
| CPC | 700원 | 500원 이하 |
| ROAS | 2.5 | 4.0+ |
| CPA | 30,000원 | 20,000원 이하 |
| Frequency | 2~4 | 1.5~3 |

## 자동 플래그
- Frequency > 5 → 크리에이티브 피로
- CPA > 벤치 ×1.5 (45,000원) → 오디언스/크리에이티브 재검토
- ROAS < 2.0 → 캠페인 일시 정지 검토

## 전략 전제 (재논의 금지)
- CBO Broad 메인 + ABO 크리에이티브 테스트
- Broad > Lookalike 확정
- CAPI 서버사이드 우선
"""


def _get_client():
    load_dotenv(ENV_PATH, override=True)
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None, "ANTHROPIC_API_KEY 미설정"
    try:
        from anthropic import Anthropic
    except ImportError as e:
        return None, f"anthropic SDK 미설치: {e}"
    return Anthropic(api_key=key), None


def _build_context(metrics, self_bench, flags, recent_trend, winner_patterns=None):
    ctx = {
        "target_date": metrics.get("_target_date"),
        "metrics": {k: v for k, v in metrics.items() if not k.startswith("_")},
        "self_benchmark_30d": {
            m: {"p25": b.get("p25"), "p50": b.get("p50"), "p75": b.get("p75"),
                "n": b.get("n"), "ok": b.get("ok"), "reason": b.get("reason")}
            for m, b in (self_bench or {}).items()
        },
        "auto_flags": flags or [],
        "recent_7d_trend": recent_trend or [],
    }
    if winner_patterns:
        ctx["winner_patterns_recent"] = winner_patterns[:5]
    return ctx


def generate_short(metrics, self_bench, flags, recent_trend, winner_patterns=None):
    client, err = _get_client()
    if err:
        return None, err

    ctx = _build_context(metrics, self_bench, flags, recent_trend, winner_patterns)
    user = f"""아래 데이터 기반으로 텔레그램 알림용 압축 분석을 작성해라.

[데이터]
```json
{json.dumps(ctx, ensure_ascii=False, indent=2, default=str)}
```

[출력 형식]
한줄평: (현재 상태 한 줄, 30자 이내)

액션:
1. {{무엇}} — {{왜, 어느 지표 근거}} — {{언제까지}}
2. {{무엇}} — {{왜}} — {{언제까지}}
3. {{무엇}} — {{왜}} — {{언제까지}}

(액션이 2개나 1개면 그만큼만. 억지로 3개 채우지 마라.)
"""
    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS_SHORT,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
        text = resp.content[0].text if resp.content else ""
        return text.strip(), None
    except Exception as e:
        return None, f"Claude 호출 실패: {e}"


def generate_deep(metrics, self_bench, flags, recent_trend, winner_patterns=None):
    client, err = _get_client()
    if err:
        return None, err

    ctx = _build_context(metrics, self_bench, flags, recent_trend, winner_patterns)
    winner_section = ""
    if winner_patterns:
        winner_section = "\n5. 위너 패턴 활용 — 직전 30일 위너 광고에서 추출된 패턴 중 현재 상황에 응용 가능한 게 있으면 명시"

    user = f"""아래 데이터로 이메일 심층 분석 리포트를 마크다운으로 작성해라.

[데이터]
```json
{json.dumps(ctx, ensure_ascii=False, indent=2, default=str)}
```

[섹션 구조]
## 한줄 진단
한 문장.

## 핵심 지표 평가
각 지표에 대해 정적 벤치 + 자사 P50 비교 + 판정 근거.

## 7일 추세 분석
recent_7d_trend 기반, 추세 방향과 변곡점.

## 자동 플래그 검토
auto_flags 각 항목에 즉시 액션 vs 모니터 vs 무시 판정 + 근거.

## 액션 권고 (3~5개)
무엇 / 왜(지표 근거) / 언제까지 / 예상 효과(정량).
{winner_section}

## 모니터링 신호
다음 24시간 안에 봐야 할 지표 + 임계치.
"""
    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS_DEEP,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
        text = resp.content[0].text if resp.content else ""
        return text.strip(), None
    except Exception as e:
        return None, f"Claude 호출 실패: {e}"


def load_recent_trend(target_date, days=7):
    import meta_ads_history
    rows = meta_ads_history.load_recent_account(days=days + 1)
    out = []
    for r in rows:
        if r.get("date", "") > target_date:
            continue
        out.append({
            "date": r.get("date"),
            "spend": r.get("spend"),
            "ctr_pct": r.get("ctr_pct"),
            "cpc_krw": r.get("cpc_krw"),
            "roas": r.get("roas"),
            "cpa_krw": r.get("cpa_krw"),
            "frequency": r.get("frequency"),
        })
    return out[-days:]


def load_winner_patterns():
    path = Path(__file__).parent / "data" / "meta_ads" / "winner_patterns.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    out.sort(key=lambda x: x.get("week_start", ""), reverse=True)
    return out


if __name__ == "__main__":
    dummy_metrics = {"_target_date": "2026-04-26", "spend": 150000, "ctr_pct": 1.5,
                     "cpc_krw": 650, "roas": 3.4, "cpa_krw": 28000, "frequency": 2.3,
                     "purchases": 5, "impressions": 23000, "clicks": 345}
    out, err = generate_short(dummy_metrics, {}, [], [])
    print("short:", out or err)
