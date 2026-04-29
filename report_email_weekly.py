"""주간 멀티 에이전트 심층 리포트 (일요일 21:00).

3회 왕복 진짜 멀티 에이전트:
1. 전략가 — 1주 추세 분석 + 다음 주 우선순위 3개 (초안 2000자)
2. 회의주의자 — 1차 결과 비판 (약점·과대해석·누락 지적)
3. 전략가 — 1차+2차 반영해 최종본 작성

Anthropic 401 시 fallback: 1주 누적 표만 발송.
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
from lib import recommendation_log
from lib.charts import generate_weekly_charts
from report_email_daily import _md_to_html, _wrap_html

KST = timezone(timedelta(hours=9))
ENV_PATH = Path(__file__).parent / ".env"


SYSTEM_STRATEGIST_V1 = """당신은 10년차 D2C 이커머스 전략가다. HeavyLover(냉동 도시락 D2C) 1주일치 데이터를 받아 전략 제언을 작성한다.

작성 형식:
## 0. 한 줄 헤드라인
- 이번 주 가장 중요한 변화·신호 1줄

## 1. 이번 주 핵심 변화 (3개)
- 숫자 근거와 함께 가장 중요한 변화 3개

## 2. 원인 가설
- 변화의 원인을 가능한 한 다층적으로 (외부 요인·내부 운영·계절성·광고 효율)

## 3. 다음 주 우선순위 3개
- 각 항목: 액션 / 예상 효과 / 검증 방법 / 기간 / 비용
- 구체 수치·기간 포함, 모호한 권고 금지

규칙:
- 입력 JSON 숫자만 사용. 1200~1800자. 한국어. 불릿·표 적극.
- WoW→지난주 대비, MoM→지난달 대비, YoY→작년 같은 달 대비, P50→재구매 간격 중앙값으로 풀어서. M+1·CAC·LTV·AOV·CTR·CPA는 약어 그대로."""

SYSTEM_SKEPTIC = """당신은 10년차 회의주의자 분석가다. 동료 전략가의 분석 초안을 비판적으로 검토한다.

다음을 명확히 지적하라:
1. **과대해석**: 데이터로 단정 못 할 결론을 단정한 부분
2. **누락 변수**: 고려 안 한 외부 요인·교란 변수
3. **샘플 한계**: 통계적 신뢰성 부족한 부분
4. **권고 약점**: 실행 가능성·검증 가능성이 떨어지는 권고
5. **재무 영향 누락**: 권고 실행 비용·이익률·마진 영향 안 따진 부분
6. **타이밍 리스크**: 시즌·재고·자금 흐름 무시한 부분

500~1000자. 동료를 존중하되 솔직하게. 한국어. 동어반복 금지."""

SYSTEM_STRATEGIST_V2 = """당신은 10년차 D2C 전략가다. 자신의 보강안에 대해 회의주의자가 두 차례 비판을 했다. 두 비판을 모두 반영해 최종 주간 전략 리포트를 작성한다.

작성 형식:
## 0. 한 줄 헤드라인 (최종 — 의사결정자용)
- 이번 주 가장 중요한 1줄

## 1. 이번 주 핵심 변화 (3개) — 확신도 명시
- 각 변화에 (확신도: 높음/중간/낮음) 표시 + 근거 1줄

## 2. 원인 가설 — 회의주의자 반박 반영
- 단정 가능한 것과 가설로 남기는 것 구분
- 각 가설에 검증 가능한 1차 데이터 명시

## 3. 다음 주 우선순위 3개 — 검증·재무 보강
- 각 권고: 액션 / 예상 효과 / 검증 방법 / 검증 기간 / 실패 시 대안 / **비용·재무 영향**

## 4. 의사결정 트리 (NEW)
- IF-THEN 형식 분기 시나리오:
  - "IF 다음 주 M+1이 X% 미만 → THEN 액션 A 즉시 실행"
  - "IF 매출이 Y원 이상 → THEN 액션 B 보류"
- 최소 3가지 분기. 임계값을 구체 수치로.

## 5. 다음 주 추적 KPI 대시보드 (NEW)
- 일주일 후 다시 측정할 지표 표:
- 컬럼: 지표 / 현재값 / 1주일 후 목표값 / 측정 방법

## 6. 데이터 한계 명시
- 이 분석에서 답할 수 없는 것
- 추가 수집해야 할 데이터

2000~3500자. 한국어. AI 화법 금지.
WoW→지난주 대비, MoM→지난달 대비, YoY→작년 같은 달 대비, P50→재구매 간격 중앙값으로 풀어서. M+1·CAC·LTV·AOV·CTR·CPA는 약어 그대로."""


def _aggregate_week(history: list[dict], today_gt: dict) -> dict:
    """1주일치 핵심 지표 집계."""
    all_gt = list(history) + [today_gt]

    # 매출 시계열
    sales = []
    rates_1to2 = []
    rates_2to3 = []
    m1_values = []

    for g in all_gt:
        cur = g.get("월별_재구매_매출", {}).get("통합", {}).get("당월", {})
        if cur.get("매출") is not None:
            sales.append(cur["매출"])

        stages = g.get("단계별_전환율_현재", {}).get("통합") or []
        for s in stages:
            if s.get("단계") == "1→2" and s.get("전환율") is not None:
                rates_1to2.append(s["전환율"])
            if s.get("단계") == "2→3" and s.get("전환율") is not None:
                rates_2to3.append(s["전환율"])

        mn = g.get("M+N_리텐션_통합") or []
        if mn and mn[-1].get("M+1") is not None:
            m1_values.append(mn[-1]["M+1"])

    def _stats(arr):
        if not arr:
            return {"count": 0}
        return {
            "count": len(arr),
            "first": arr[0],
            "last": arr[-1],
            "min": min(arr),
            "max": max(arr),
            "avg": round(sum(arr) / len(arr), 2),
            "변화량": round(arr[-1] - arr[0], 2) if isinstance(arr[0], (int, float)) else None,
        }

    return {
        "기간": f"{all_gt[0].get('리포트_날짜', '?')} ~ {all_gt[-1].get('리포트_날짜', '?')}",
        "관측일수": len(all_gt),
        "매출": _stats(sales),
        "1→2_전환율": _stats(rates_1to2),
        "2→3_전환율": _stats(rates_2to3),
        "M+1_리텐션": _stats(m1_values),
        "오늘_시점": today_gt.get("월별_재구매_매출", {}).get("통합", {}),
        "최신_단계별": today_gt.get("단계별_전환율_현재", {}).get("통합", []),
        "벤치마크": today_gt.get("업계_벤치마크", {}),
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
            max_tokens=4500,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"Claude API 오류: {e}")
        return None


def run_multi_agent(weekly_summary: dict, rec_block: str) -> str | None:
    """4회 왕복 멀티에이전트: 전략가→회의주의자→전략가→회의주의자→전략가 최종(5단계)."""
    summary_json = json.dumps(weekly_summary, ensure_ascii=False, indent=2, default=str)

    print("[1차] 전략가 초안 생성 중...")
    v1 = call_claude(SYSTEM_STRATEGIST_V1, f"""1주일치 KPI 집계:
```json
{summary_json}
```

{rec_block}

위 데이터로 1차 전략 리포트 초안 작성.""")
    if not v1:
        return None
    print(f"[1차] 완료 ({len(v1)}자)")

    print("[2차] 회의주의자 1차 비판 중...")
    c1 = call_claude(SYSTEM_SKEPTIC, f"""동료 전략가 1차 초안:

---
{v1}
---

원본 데이터:
```json
{summary_json}
```

위 초안 1차 비판. 과대해석·누락·샘플 한계·약한 권고 지적.""")
    if not c1:
        return v1
    print(f"[2차] 완료 ({len(c1)}자)")

    print("[3차] 전략가 보강안 작성 중...")
    v2 = call_claude(SYSTEM_STRATEGIST_V1, f"""당신의 1차 초안:
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

비판 반영해 보강안 작성. 형식은 그대로 유지하되 가설 신뢰도·검증 가능성 보강.""")
    if not v2:
        return v1
    print(f"[3차] 완료 ({len(v2)}자)")

    print("[4차] 회의주의자 2차 비판 중...")
    c2 = call_claude(SYSTEM_SKEPTIC, f"""동료 전략가 보강안 (1차 비판 반영본):

---
{v2}
---

원본 데이터:
```json
{summary_json}
```

남은 약점·재무 영향 누락·타이밍 리스크·동어반복 지적. 이미 지적한 내용 반복 금지, 새 관점만.""")
    if not c2:
        return v2
    print(f"[4차] 완료 ({len(c2)}자)")

    print("[5차] 전략가 최종본 작성 중...")
    final = call_claude(SYSTEM_STRATEGIST_V2, f"""당신의 보강안 (2번째 버전):
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

두 차례 비판 모두 반영해 최종 리포트 작성. 의사결정 트리·다음 주 추적 KPI 대시보드 포함 필수.""")
    if not final:
        return v2
    print(f"[5차] 완료 ({len(final)}자)")

    appendix = f"""

---

## 부록 — 4회 왕복 분석 과정

### 1차 초안 (전략가)
{v1}

### 2차 비판 (회의주의자, 1차)
{c1}

### 3차 보강 (전략가, 1차 반영)
{v2}

### 4차 비판 (회의주의자, 2차)
{c2}
"""
    return final + appendix


def main() -> int:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    try:
        ss = _open_sheet()
        gt = build_ground_truth(ss)
        enriched = enrich(gt)
        history = load_recent_gt(days=7)
        weekly = _aggregate_week(history, gt)
        rec_block = recommendation_log.format_for_prompt(days=14)

        analysis = run_multi_agent(weekly, rec_block)

        try:
            charts = generate_weekly_charts(gt, enriched, history)
        except Exception as e:
            print(f"주간 차트 생성 실패: {e}")
            charts = {}

        if analysis:
            html = _wrap_html(_md_to_html(analysis), enriched, chart_cids=list(charts.keys()))
            send_email(
                subject=f"📊 HeavyLover 주간 심층 (멀티 에이전트) — {today}",
                text_body=analysis,
                html_body=html,
                inline_images=charts,
            )
            # 다음주 우선순위를 recommendations에 저장
            if "다음 주 우선순위" in analysis or "우선순위 3개" in analysis:
                section = analysis.split("우선순위")[-1].split("##")[0][:500]
                recommendation_log.append(today, "weekly", section)
            print(f"주간 멀티 에이전트 메일 발송 완료 ({today})")
            return 0
        else:
            # fallback
            txt = f"""HeavyLover 주간 심층 (fallback)
⚠️ Anthropic API 사용 불가 — 1주일 누적 데이터만 첨부

```json
{json.dumps(weekly, ensure_ascii=False, indent=2, default=str)}
```

결제 활성 후 멀티 에이전트 분석 재개."""
            send_email(
                subject=f"⚠️ HeavyLover 주간 (fallback) — {today}",
                text_body=txt,
                html_body=_wrap_html(_md_to_html(txt), enriched, chart_cids=list(charts.keys())),
                inline_images=charts,
            )
            return 0
    except Exception as e:
        err = f"주간 메일 치명적 오류: {e}"
        print(err)
        try:
            send_email(subject=f"🚨 주간 리포트 오류 — {today}", text_body=err)
        except Exception:
            pass
        return 2


if __name__ == "__main__":
    sys.exit(main())
