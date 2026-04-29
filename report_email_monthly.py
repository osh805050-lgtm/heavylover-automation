"""매월 1일 09:30 — 월간 액션 권고 메일 (5회 왕복 멀티 에이전트).

흐름:
1. 전전월 마감 vs 전월 마감 vs 이번달 MTD (09:30 시점) 집계
2. 5회 왕복: 전략가 → 회의주의자 → 전략가 → 회의주의자 → 전략가 최종
3. 이번달 핵심 액션 3개 + 각 (예상 효과·검증 KPI·실패 시 대안)
4. 차트 5종 인라인 첨부 (주간과 동일)
5. recommendation_log에 "monthly" 태그로 액션 누적
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from anthropic import Anthropic
from dotenv import load_dotenv

from sheets_sync import _open_sheet
from repurchase_report import build_ground_truth
from email_sender import send_email
from lib.historical_data import enrich, load_recent_gt
from lib.charts import generate_weekly_charts
from lib import recommendation_log
from report_email_daily import _md_to_html, _wrap_html

KST = timezone(timedelta(hours=9))
ENV_PATH = Path(__file__).parent / ".env"


SYSTEM_STRATEGIST = """당신은 10년차 D2C 이커머스 전략가다. HeavyLover(냉동 도시락 + 시리얼 D2C, 20~30대 운동 직장인 남성 타겟) 월간 데이터를 받아 이번달 우선순위 3대 액션을 작성한다.

작성 형식:
## 1. 전월 마감 vs 전전월 — 핵심 변화 3개
- 숫자 근거 명시. 지난달 대비·분기 대비·작년 같은 달 대비 가능한 한.

## 2. 이번달 지금까지 신호
- 이번달 현재 시점 누적 — 전월 같은 시점 대비 페이스
- 위험·기회 신호 식별

## 3. 이번달 우선순위 3대 액션
- 각 액션:
  - **무엇을** (구체 액션)
  - **왜** (데이터 근거)
  - **예상 효과** (KPI 수치 변화 예측)
  - **검증 방법** (어떤 지표를 며칠 후 측정)
  - **실패 시 대안** (효과 없으면 다음 카드)

규칙:
- 입력 JSON 숫자만 사용. 창작 금지.
- 1500~2500자. 한국어. 표·불릿 적극.
- 모호한 권고 금지 ("개선하자", "강화하자" X)
"""

SYSTEM_SKEPTIC = """당신은 10년차 회의주의자 분석가다. 동료 전략가의 월간 액션 권고를 비판적으로 검토한다.

다음을 명확히 지적하라:
1. **과대해석**: 월간 데이터 한 달치로 단정 못 할 결론
2. **누락 변수**: 외부 요인(시즌·경쟁사·광고 효율 변화)·내부 운영 변수 무시
3. **샘플 한계**: 이번달 며칠치만으로 전월 비교 신뢰성 충분한가?
4. **권고 약점**: 실행·검증 가능성, 비용 대비 효과
5. **재무 영향**: 권고 실행 시 이익률·마진·현금흐름 어떻게 변하는가?

500~1000자. 동료를 존중하되 솔직하게. 한국어."""

SYSTEM_FINAL = """당신은 10년차 D2C 전략가다. 회의주의자의 두 차례 비판을 받아 최종 월간 액션 리포트를 작성한다.

작성 형식:
## 1. 전월 마감 핵심 — 확신도 명시
- 각 변화에 (확신도: 높음/중간/낮음)

## 2. 이번달 MTD 페이스 — 회의주의자 반박 반영
- 단정 가능한 것 vs 가설로 남기는 것 구분

## 3. 이번달 3대 액션 (수정·보강된 최종안)
- 각 액션:
  - **무엇을** / **왜** / **예상 효과** / **검증 방법·기간** / **실패 시 대안** / **재무 영향**
- 회의주의자 비판 모두 반영 또는 명시적 반박

## 4. 데이터 한계 명시
- 이 분석으로 답할 수 없는 것
- 추가 수집해야 할 데이터 있다면 명시

2000~3000자. 한국어.
WoW→지난주 대비, MoM→지난달 대비, YoY→작년 같은 달 대비, P50→재구매 간격 중앙값, MTD→이번달 현재까지로 풀어서. M+1·CAC·LTV·AOV·CTR·CPA는 약어 그대로."""


def _aggregate_month(gt: dict, history: list[dict]) -> dict:
    """전전월·전월·이번달 MTD 집계."""
    inm = gt.get("월별_재구매_매출", {}) or {}
    integrated = inm.get("통합", {}) or {}

    return {
        "리포트_날짜": gt.get("리포트_날짜"),
        "당월": gt.get("당월"),
        "전월": gt.get("전월"),
        "전월_마감": integrated.get("전월", {}),
        "이번달_MTD": integrated.get("당월", {}),
        "MoM": {
            "변화_금액": integrated.get("MoM_변화_금액"),
            "변화_pct": integrated.get("MoM_변화_pct"),
        },
        "채널별": {
            "카페24": inm.get("카페24", {}),
            "스마트스토어": inm.get("스마트스토어", {}),
        },
        "단계별_전환율": gt.get("단계별_전환율_현재", {}),
        "코호트_추세": gt.get("코호트_추세_통합", {}),
        "M+N_리텐션": gt.get("M+N_리텐션_통합", []),
        "재구매_간격": gt.get("재구매_간격", {}),
        "벤치마크": gt.get("업계_벤치마크", {}),
        "관측_history_수": len(history),
    }


def call_claude(system: str, user: str) -> str | None:
    load_dotenv(ENV_PATH, override=True)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    client = Anthropic(api_key=api_key)
    try:
        resp = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"Claude API 오류: {e}")
        return None


def run_5round(monthly_summary: dict, rec_block: str) -> str | None:
    """5회 왕복: 전략가→회의주의자→전략가→회의주의자→전략가 최종."""
    summary_json = json.dumps(monthly_summary, ensure_ascii=False, indent=2, default=str)

    print("[1차] 전략가 초안...")
    v1 = call_claude(SYSTEM_STRATEGIST, f"""월간 KPI 집계:
```json
{summary_json}
```

{rec_block}

위 데이터로 1차 월간 액션 리포트 초안 작성.""")
    if not v1:
        return None
    print(f"[1차] 완료 ({len(v1)}자)")

    print("[2차] 회의주의자 1차 비판...")
    c1 = call_claude(SYSTEM_SKEPTIC, f"""동료 전략가 1차 초안:

---
{v1}
---

원본 데이터:
```json
{summary_json}
```

위 초안 1차 비판.""")
    if not c1:
        return v1
    print(f"[2차] 완료 ({len(c1)}자)")

    print("[3차] 전략가 보강안...")
    v2 = call_claude(SYSTEM_STRATEGIST, f"""당신의 1차 초안:
---
{v1}
---

회의주의자 1차 비판:
---
{c1}
---

원본 데이터:
```json
{summary_json}
```

비판 반영해 보강안 작성. 동일 형식 유지하되 구체성·검증 가능성 강화.""")
    if not v2:
        return v1
    print(f"[3차] 완료 ({len(v2)}자)")

    print("[4차] 회의주의자 2차 비판...")
    c2 = call_claude(SYSTEM_SKEPTIC, f"""동료 전략가 보강안 (1차 비판 반영본):

---
{v2}
---

원본 데이터:
```json
{summary_json}
```

남은 약점·과대해석·재무 영향 누락 지적. 동어반복 금지, 새 관점만.""")
    if not c2:
        return v2
    print(f"[4차] 완료 ({len(c2)}자)")

    print("[5차] 전략가 최종본...")
    v3 = call_claude(SYSTEM_FINAL, f"""당신의 보강안 (2번째 버전):
---
{v2}
---

회의주의자 2차 비판:
---
{c2}
---

원본 데이터:
```json
{summary_json}
```

두 차례 비판 모두 반영해 최종 월간 액션 리포트 작성. 확신도·검증 방법·재무 영향·데이터 한계 명시.""")
    if not v3:
        return v2
    print(f"[5차] 완료 ({len(v3)}자)")

    appendix = f"""

---

## 부록 — 5회 왕복 분석 과정

### 1차 초안 (전략가)
{v1}

### 2차 비판 (회의주의자, 1차)
{c1}

### 3차 보강 (전략가, 1차 반영)
{v2}

### 4차 비판 (회의주의자, 2차)
{c2}
"""
    return v3 + appendix


def main() -> int:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    try:
        ss = _open_sheet()
        gt = build_ground_truth(ss)
        enriched = enrich(gt)
        history = load_recent_gt(days=30)  # 월간이라 30일 누적
        monthly = _aggregate_month(gt, history)
        rec_block = recommendation_log.format_for_prompt(days=30)

        analysis = run_5round(monthly, rec_block)

        try:
            charts = generate_weekly_charts(gt, enriched, history)
        except Exception as e:
            print(f"월간 차트 실패: {e}")
            charts = {}

        if analysis:
            html = _wrap_html(_md_to_html(analysis), enriched, chart_cids=list(charts.keys()))
            send_email(
                subject=f"📅 HeavyLover 월간 액션 (5회 왕복) — {today}",
                text_body=analysis,
                html_body=html,
                inline_images=charts,
            )
            # 액션 3개를 recommendation_log에 누적
            if "3대 액션" in analysis or "우선순위" in analysis:
                section = analysis.split("3대 액션")[-1].split("##")[0][:800] if "3대 액션" in analysis else analysis[:800]
                recommendation_log.append(today, "monthly", section)
            print(f"월간 메일 발송 완료 ({today})")
            return 0
        else:
            txt = f"""HeavyLover 월간 액션 (fallback)
⚠️ Anthropic API 사용 불가 — 월간 누적 데이터만 첨부

```json
{json.dumps(monthly, ensure_ascii=False, indent=2, default=str)}
```

결제 활성 후 5회 왕복 분석 재개."""
            send_email(
                subject=f"⚠️ HeavyLover 월간 (fallback) — {today}",
                text_body=txt,
                html_body=_wrap_html(_md_to_html(txt), enriched, chart_cids=list(charts.keys())),
                inline_images=charts,
            )
            return 0
    except Exception as e:
        err = f"월간 메일 치명적 오류: {e}"
        print(err)
        try:
            send_email(subject=f"🚨 월간 리포트 오류 — {today}", text_body=err)
        except Exception:
            pass
        return 2


if __name__ == "__main__":
    sys.exit(main())
