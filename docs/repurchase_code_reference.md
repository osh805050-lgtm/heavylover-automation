# 헤비로버 재구매 분석 시스템 — 코드 레퍼런스

**생성일**: 2026-05-08
**목적**: Codex 코드 검토용. 재구매 분석 파이프라인 5개 파일 전체 코드 + 핵심 로직 + 발견된 이슈 박제.
**코드 위치**: 로컬 `c:\Users\osh80\OneDrive\바탕 화면\heavylover-automation\` / 서버 Vultr `/root/heavylover-repurchase/`
**대상 시트**: `1DEEz2iSa_REKUsYetyZMSqZsVm6_LFbOAasrzXjYU5s` (repurchase_v5_4)
**Codex 리뷰**: 2026-05-08 실행 · Verdict 🔴 **needs-attention** · 4 findings (high 2 / medium 2)

---

## 1. 시스템 개요

### 데이터 흐름

```
[카페24 API] ──┐
               ├─→ sheets_sync.py (08:30, KST) ──→ 원본 탭 (카페24/SS 재구매매출)
[네이버 SS API]┘                                       │
                                                       ▼
                                       [Apps Script: repurchase_v5_4.gs]
                                       (수동 실행 - 시간 트리거 미설정)
                                                       │
                                                       ▼
                                       19개 분석 탭 (월별·코호트·M+N·간격)
                                                       │
                                                       ▼
                            repurchase_report.py (09:00, KST)
                              ├─ build_ground_truth() → logs/gt_YYYY-MM-DD.json
                              ├─ write_marts()        → mart_monthly/cohort/stage/summary
                              ├─ write_dashboard()    → 📊 대시보드 탭
                              ├─ telegram_brief       → report 채널
                              └─ report_email_daily.main(gt) (09:10)
                                  ├─ enrich() → WoW/이상치 (lib/historical_data.py)
                                  ├─ build_kpi_cards_html (lib/kpi_cards.py)
                                  └─ Claude API 4역할 분석 → 이메일 발송
```

### 파일별 역할

| 파일 | 라인 | 역할 |
|------|-----:|------|
| `repurchase_report.py` | 1,426 | GT 추출, 마트/대시보드 갱신, 텔레그램·이메일 트리거 |
| `sheets_sync.py` | 482 | 카페24/SS 주문 → Sheets 원본 탭 동기화 (7일 backfill, dedupe) |
| `lib/historical_data.py` | 168 | gt_*.json 누적 → WoW 비교 + ±2σ 이상치 플래그 |
| `lib/kpi_cards.py` | 127 | 이메일 상단 KPI 카드 4장 HTML 생성 |
| `report_email_daily.py` | 391 | enriched gt → Claude 4역할 분석 → 이메일 발송 (fallback 포함) |

### 운영 정책

- **월별 기준 날짜**: 결제일 (paid_date / paymentDate)
- **고객 식별**: 카페24=휴대폰, SS=ordererId 또는 buyerId
- **취소 처리**: cafe24 `canceled=='T'` 제외 / SS는 PAYED·DISPATCHED·DELIVERING·DELIVERED·PURCHASE_DECIDED·EXCHANGED 만 포함
- **0원 주문**: `payment_amount=0` → `items[].product_price × qty` 합산으로 정가 대체 (2026-04-29 추가)
- **backfill 윈도우**: 7일 (취소·환불 지연 반영)
- **Cron**: `30 8 * * 1-5` sheets_sync / `0 9 * * 1-5` repurchase_report

---

## 2. 핵심 지표 정의

### 2.1 당월 재구매율 (`재구매_통합_월별` 탭)

```
재구매율(%) = 재구매자수 / (신규구매자수 + 재구매자수) × 100
```

- 분자: 당월에 결제한 사람 중 첫 구매 이력이 있는 고객 (모든 이전 코호트 누적)
- 분모: 당월 결제자 전체 (신규 + 재구매)
- 계산 주체: Apps Script `repurchase_v5_4.gs`
- Python 추출: `repurchase_report.py:_extract_monthly()` (line 153-175)
- **월 초반 효과 주의**: 신규 유입(분모)이 적을수록 비율 급등. 8일까지 41 신규 + 23 재구매 → 36%

### 2.2 1→2 전환율 (`코호트_통합_전환율` 탭)

```
30일 전환율 = 코호트월 첫 구매 후 30일 내 2번째 구매 수 / 코호트 첫 구매자 수
60일 전환율 = 60일 내 (위와 동일)
1→2 전환율 = 60일 누적 기준 (line 203 `r[6]` 별칭)
```

- 추출: `_extract_cohort_stage()` (line 178-206)
- 평균화: `_extract_stage_flat()` 가 최근 3개월 완결 코호트 평균을 단계 형태로 변환 (line 260-279)
- **완결 기준**: `첫구매자수 >= 5` (n<5는 노이즈로 제외)

### 2.3 M+N 리텐션 (`코호트_월별잔존율` 탭)

```
M+1 = 첫구매월 +1개월 내 재구매한 코호트 비율
M+2~M+6 = 동일 패턴
```

- 추출: `_extract_mn()` (line 209-230)
- **현재 버그**: `M+1 is not None` 만으로 필터 → 진행 중 코호트도 통과 (아래 §3 참조)

### 2.4 재구매 간격 P50 (`재구매_간격분석` 탭)

```
P50 = 모든 재구매 고객의 (첫구매 → 두번째구매) 간격 중앙값
```

- 추출: `_extract_interval_stats()` (line 233-256)
- 단위: 일(day), 문자열로 저장 ("15일")

---

## 3. 발견된 이슈 (Codex 리뷰 반영)

> 이 섹션은 2026-05-08 Codex adversarial-review 결과를 반영해 재정리됨.
> Codex finding C1~C4 → ISSUE-1~4 매핑. ISSUE-5는 인프라 이슈(Codex 범위 밖)로 보존.

### 🔴 ISSUE-1 [high] — M+1 미완결 코호트가 KPI로 노출 (Codex C1)

**위치**:
- `repurchase_report.py:362-364` (`build_ground_truth` — mn_completed 필터)
- `repurchase_report.py:556-557, 566` (`write_marts → mart_summary`)
- `repurchase_report.py:736` (`write_dashboard → KPI 카드`)
- `lib/kpi_cards.py:62` (이메일 KPI 카드)

**문제 코드**:
```python
mn_completed = [m for m in mn if m.get("M+1") is not None]
# ↑ M+1이 not None이면 통과. 진행 중 코호트도 포함됨.

m1_recent = mn_recent[-1].get("M+1") if mn_recent else None
# ↑ list position[-1] = 가장 최근 = 진행 중일 가능성 높음
```

**증상**: 2026-05-08에 2026-04 코호트(M+1=3.4%, 5월 진행 중)가 KPI 카드에 "M+1 리텐션 최신 코호트 = 3.4% 🔴 위험"으로 표시. 실제로는 5월 31일 종료 후 13~15% 도달 예상.

**Codex 권고 (이전 제안 무효화)**:

이전에 제안한 `코호트월 + 1개월 < 오늘`은 **위험함**. 5/8 시점에 2026-04 코호트가 통과해버리는데, M+1 관찰 윈도우는 5월 31일까지이고 그 후 데이터 지연 backfill 7일까지 기다려야 안정. 현재 룰은 부분 데이터를 KPI로 박제하고 잘못된 CRM/오퍼 의사결정을 트리거할 수 있음.

```python
# GT 빌드 단계에서 각 코호트에 완결 메타데이터 추가
from datetime import date

DATA_LAG_DAYS = 7  # 취소·환불 backfill 윈도우와 일치 (sheets_sync.py BACKFILL_DAYS)

def _last_day_of_month(year: int, month: int) -> date:
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)

def _m1_completion(cohort_month: str, now_kst: date) -> dict:
    y, m = map(int, cohort_month.split("-"))
    # M+1 관찰 윈도우 = 코호트월 다음 달 마지막 날까지
    next_m_year = y + (1 if m == 12 else 0)
    next_m = 1 if m == 12 else m + 1
    m1_window_end = _last_day_of_month(next_m_year, next_m)
    is_complete = now_kst > (m1_window_end + timedelta(days=DATA_LAG_DAYS))
    observed_days = (now_kst - date(next_m_year, next_m, 1)).days
    return {
        "is_complete": is_complete,
        "window_end": m1_window_end.isoformat(),
        "observed_days": max(0, observed_days),
    }

# 모든 소비처는 list position 대신 is_complete 필터로 최신 완결 코호트 선택
completed = [m for m in mn if m.get("is_complete")]
m1_recent = completed[-1].get("M+1") if completed else None
```

미완결 코호트는 별도 "in-progress" 트렌드 표로 분리 표시하고 `(진행 {observed_days}/{window_days}일)` 라벨 부착.

---

### 🔴 ISSUE-2 [high] — 1→2 전환율도 미완결 코호트 평균 포함 (Codex C2, 신규/격상)

**위치**: `repurchase_report.py:_extract_stage_flat()` line 260-279

**문제**: `30일_전환율 is not None and 첫구매자수 >= 5` 만 필터. **elapsed-time gate 없음.** 60일 안 지난 코호트도 last3에 포함되어 헤드라인 1→2 전환율(60일 누적)을 끌어내림.

**영향 범위**:
- 헤드라인 KPI 카드 (대시보드 + 이메일 둘 다)
- `mart_stage` 탭
- Claude 프롬프트의 `코호트_추세_통합`
- 이상치 탐지 (`historical_data.py:flag_anomalies`)

**시나리오 (2026-05-08 기준)**:
- 2026-03 코호트 → 60일 거의 다 됨 → 정확
- 2026-04 코호트 → 60일 중 8~38일만 관찰 → 과소 추정
- 2026-05 코호트 → 60일 중 0~7일만 관찰 → 거의 0
- 평균 = 끌어내려진 값 → 헤드라인 카드 🔴 위험 표시 → 잘못된 의사결정

**Codex 권고**:

ISSUE-4를 단순히 "60일 vs 30일 정의 문제"로 본 것은 핵심을 놓친 것. **진짜 문제는 60일 값이 완결되기 전에 평균에 들어간다는 점.**

```python
# 30일·60일 메트릭 분리 + 각각 elapsed-time gate
def _is_complete_30d(cohort_month: str, now: date) -> bool:
    y, m = map(int, cohort_month.split("-"))
    # 코호트월 첫날 + 30일 + 데이터 지연
    cohort_first_day = date(y, m, 1)
    return now > cohort_first_day + timedelta(days=30 + DATA_LAG_DAYS)

def _is_complete_60d(cohort_month: str, now: date) -> bool:
    y, m = map(int, cohort_month.split("-"))
    cohort_first_day = date(y, m, 1)
    return now > cohort_first_day + timedelta(days=60 + DATA_LAG_DAYS)

# 평균은 완결 코호트만
completed_60d = [r for r in rows if _is_complete_60d(r["코호트월"], now_kst)
                 and r["첫구매자수"] >= 5]
last3 = completed_60d[-3:]
avg60 = sum(r["60일_전환율"] for r in last3) / len(last3) if last3 else None
```

미완결 코호트는 별도 "1→2 진행 중" 섹션으로 분리, in-progress 라벨로 표시.

---

### 🟡 ISSUE-3 [medium] — SS 빈 productOrderId 행 dedupe 누락 (Codex C3, 보강)

**위치**: `sheets_sync.py:sync_smartstore()` line 422-437

**문제 코드**:
```python
seen_pid = set()
deduped = []
if keep:
    deduped.append(keep[0])  # 헤더
for r in reversed(keep[1:]):
    pid = r[0] if r else ""
    if not pid or pid in seen_pid:
        if pid:
            continue
    seen_pid.add(pid)
    deduped.append(r)
```

`pid=""` 일 때 분기 분석:
- `not pid` = True (빈 문자열은 falsy) → outer if 진입
- `pid in seen_pid` = `"" in seen_pid` (첫 행은 False, 둘째부터 True지만 inner if `if pid` = False 이므로 continue 안 됨)
- → **빈 pid 행은 매번 `deduped.append(r)` 됨**

**영향**: 네이버 API 스키마 드리프트, 수동 import, 시트 손상으로 빈 pid 매출 행 발생 시 → 매일 sync마다 누적 → 다운스트림 Apps Script가 SS 매출·코호트 이중 카운트. 로그에는 "productOrderId 중복 제거: N행" 만 찍히고 빈 pid는 보이지 않음 → 운영자 인지 불가.

**Codex 권고**:
```python
# 1) 빈 pid 격리 + 알림
blank_pid_rows = [r for r in keep[1:] if not (r[0] if r else "")]
if blank_pid_rows:
    sample = blank_pid_rows[:5]
    _log(f"⚠️ 빈 productOrderId 행 {len(blank_pid_rows)}개 격리 (샘플 5개): {sample}")
    try:
        send_message(
            f"🚨 SS sync: 빈 productOrderId {len(blank_pid_rows)}행 발견\n"
            f"샘플:\n" + "\n".join(str(r[:5]) for r in sample),
            channel="ops",
        )
    except Exception:
        pass

# 2) dedupe 대상에서 빈 pid 제외
keep_with_pid = [keep[0]] + [r for r in keep[1:] if (r[0] if r else "")]

# 3) 또는 composite key로 fallback dedupe (orderId + 결제일 + 상품명 + 금액)
# 4) 빈 pid 카운트를 GT 또는 별도 메트릭에 기록 → Looker Studio에서 추적
```

---

### 🟡 ISSUE-4 [medium] — `validate()` 강제 키워드로 fallback 폭증 (Codex C4, 신규)

**위치**: `repurchase_report.py:validate()` line 1258-1294

**문제**:
```python
required_keywords = ["당월", "전월", "1→2", "2→3"]
for kw in required_keywords:
    if kw not in text:
        issues.append(f"필수 섹션 누락: '{kw}' 언급 없음")
```

연쇄 결과:
1. 새 시트는 `2→3_전환율 = None` (line 204) — 데이터 자체 없음
2. `report_email_daily.py:SYSTEM_PROMPT` 는 4블록(📌/📊/🤔/✅) 형식으로 "2→3 섹션" 요구하지 않음
3. 멀쩡한 일일 리포트가 "2→3" 미언급으로 매번 검증 실패
4. `generate_report_with_retry()` 가 3회 재시도 후 None 반환
5. → fallback (raw 숫자만) 발송
6. 이메일 제목 `⚠️ HeavyLover 재구매 일일 (fallback)` — 사용자는 API 오류와 검증 실패를 구분 못 함

**Codex 권고**:
```python
def _required_keywords(gt: dict, prompt_version: str = "v2") -> list[str]:
    """GT의 실제 데이터 유무 + 활성 프롬프트 버전 기반 동적 키워드."""
    kws = ["당월", "전월"]
    stages = gt.get("단계별_전환율_현재", {}).get("통합") or []
    if any(s.get("단계") == "1→2" and s.get("전환율") is not None for s in stages):
        kws.append("1→2")
    if any(s.get("단계") == "2→3" and s.get("전환율") is not None for s in stages):
        kws.append("2→3")
    return kws

def validate(text: str, gt: dict) -> list[str]:
    issues = []
    for phrase in BANNED_PHRASES:
        if phrase in text:
            issues.append(f"금지 표현 감지: '{phrase}'")
    for kw in _required_keywords(gt):
        if kw not in text:
            issues.append(f"필수 섹션 누락: '{kw}' 언급 없음")
    # ... 숫자 검증 ...
    return issues

# fallback 카운트 분리 로깅
import json
from pathlib import Path
FALLBACK_LOG = Path(__file__).parent / "logs" / "validation_fallback.jsonl"

def _log_fallback(date_str: str, text: str, issues: list[str]):
    import hashlib
    rec = {
        "date": date_str,
        "text_hash": hashlib.sha256(text.encode()).hexdigest()[:12],
        "issues": issues,
    }
    with FALLBACK_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
```

이메일 제목도 분리: `⚠️ (검증 실패) HeavyLover 재구매 일일` vs `⚠️ (API 오류) HeavyLover 재구매 일일`.

---

### 🔵 ISSUE-5 [info] — Apps Script `repurchase_v5_4.gs` 시간 트리거 미설정

(Codex 범위 밖. 인프라 이슈로 보존.)

- `setup-repurchase-automation.md §5` "(선택)" 표기
- `infra.md` 라인 115: "수동 실행" 의존
- 영향: 19개 분석 탭이 어제 또는 더 오래된 데이터를 유지할 수 있음
- 점검: 시트 → 확장 프로그램 → Apps Script → 시계 아이콘 → 트리거 목록

---

## 4. Codex 검토 결과 (2026-05-08)

**Verdict**: 🔴 **needs-attention** (no-ship)
**Findings**: 4건 (high 2 / medium 2)
**핵심 메시지**: *"the documented assumptions understate several production-breaking paths and one proposed fix can still mark partial cohorts as complete"*

| # | 심각도 | 요약 | ISSUE 매핑 |
|---|---|---|---|
| C1 | 🔴 high | M+1 완결 규칙이 부족. `코호트월+1개월<오늘` 제안은 5/8에 4월 코호트 통과시키지만 실제 관찰은 5/31까지 + backfill 7일 필요 | ISSUE-1 |
| C2 | 🔴 high | `_extract_stage_flat()` 도 미완결 코호트(60일 안 지난) 평균에 포함해 헤드라인 1→2 카드 끌어내림 | ISSUE-2 |
| C3 | 🟡 medium | SS dedupe 빈 productOrderId 행이 매일 살아남아 매출 이중 카운트 위험 | ISSUE-3 |
| C4 | 🟡 medium | `validate()` 강제 키워드 "2→3" 이 새 시트 None 데이터와 충돌 → fallback 폭증 | ISSUE-4 |

### Codex 권고 다음 단계

1. **GT에 완결 메타데이터 한 번 정의** — `is_complete`, `window_end`, `observed_days` 필드. 모든 대시보드/이메일/마트 소비처가 list position 대신 이걸 참조
2. **테스트 케이스 추가** — 2026-05-01, 2026-05-31, 2026-06-01 KST 경계 + 데이터 지연 윈도우 다양한 케이스
3. **빈 productOrderId fixture 추가** — 격리 동작 검증
4. **validate() fallback 카운트 로깅 분리** — API 오류와 검증 실패 구분, 운영 메트릭으로 추적

### 우선순위 (수정 권장 순서)

1. **즉시 (이번 주)**: ISSUE-1, ISSUE-2 (high) — 잘못된 KPI로 인한 의사결정 오류 위험
2. **2주 내**: ISSUE-4 (medium) — 사용자가 정상 리포트를 받지 못하는 신뢰성 문제
3. **분기 내**: ISSUE-3 (medium) — 스키마 드리프트 발생 시 중요. 평시 영향 낮음

---

## 5. 파일별 전체 코드

### 5.1 `repurchase_report.py` (1,426 줄)

```python
"""매일 09:00 재구매 분석 리포트.

1. 시트 분석 탭에서 raw 숫자 추출 (ground_truth JSON)
2. 파이썬이 모든 수치 계산 (MoM %, 추세 등)
3. Claude API는 "해석"만 담당 (숫자는 JSON에 있는 것만 사용)
4. 검증 훅 통과할 때까지 최대 3회 재분석
5. 실패 시 raw 숫자만 텔레그램 발송

.env 필요 값:
- GOOGLE_SA_KEY_PATH, REPURCHASE_SHEET_ID, ANTHROPIC_API_KEY
- TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (기존)
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

from sheets_sync import _open_sheet
from telegram_client import send_message

# Windows 콘솔(cp949)에서 이모지·한글 출력 시 UnicodeEncodeError 방지
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

KST = timezone(timedelta(hours=9))
ENV_PATH = Path(__file__).parent / ".env"

ANALYSIS_LOG_DIR = Path(__file__).parent / "logs"
ANALYSIS_LOG_DIR.mkdir(exist_ok=True)


def _log(msg: str):
    print(f"[{datetime.now(KST).strftime('%H:%M:%S')}] {msg}", flush=True)


# ============================================================
# 시트 분류 (탭 이름 + 헤더로 식별)
# ============================================================

def _classify_tabs(spreadsheet) -> dict:
    """탭 이름 기반 분류 (repurchase_v5_4.gs 산출 탭 구조).

    탭 이름 규칙:
      재구매_{플랫폼}_월별  ← 월별 매출
      코호트_{플랫폼}_전환율 ← 단계별·코호트 전환 (30일/60일)
      코호트_월별잔존율    ← M+N 리텐션
      재구매_간격분석      ← P50/P90
      구매횟수_퍼널_{플랫폼} ← 구매 횟수 분포
    """
    classified: dict = {
        "cafe24_monthly": None,
        "ss_monthly": None,
        "integrated_monthly": None,
        "cafe24_cohort": None,
        "ss_cohort": None,
        "integrated_cohort": None,
        "mn_retention": None,
        "interval_stats": None,
        "visit_count_cafe24": None,
        "visit_count_ss": None,
        "visit_count_integrated": None,
    }

    name_map = {
        "재구매_카페24_월별": "cafe24_monthly",
        "재구매_SS_월별": "ss_monthly",
        "재구매_통합_월별": "integrated_monthly",
        "코호트_카페24_전환율": "cafe24_cohort",
        "코호트_SS_전환율": "ss_cohort",
        "코호트_통합_전환율": "integrated_cohort",
        "코호트_월별잔존율": "mn_retention",
        "재구매_간격분석": "interval_stats",
        "구매횟수_퍼널_카페24": "visit_count_cafe24",
        "구매횟수_퍼널_SS": "visit_count_ss",
        "구매횟수_퍼널_통합": "visit_count_integrated",
    }

    for ws in spreadsheet.worksheets():
        key = name_map.get(ws.title)
        if key:
            classified[key] = ws

    return classified


# ============================================================
# 숫자 파싱 헬퍼
# ============================================================

def _to_int(v) -> int | None:
    if v is None or v == "":
        return None
    s = str(v).replace(",", "").replace("₩", "").replace(" ", "").strip()
    if not s or s in ("-", "─"):
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _to_pct(v) -> float | None:
    """'16.7%' → 16.7 (float)."""
    if v is None or v == "":
        return None
    s = str(v).replace("%", "").replace(",", "").strip()
    if not s or s in ("-", "─"):
        return None
    try:
        return round(float(s), 2)
    except ValueError:
        return None


# ============================================================
# Ground truth 추출
# ============================================================

_MONTH_RE = re.compile(r"^\d{4}-\d{1,2}$")


def _normalize_month(s: str) -> str:
    """'2025-1' → '2025-01' 정규화 (1자리/2자리 혼재 대응)."""
    s = (s or "").strip()
    m = _MONTH_RE.match(s)
    if not m:
        return s
    y, mm = s.split("-")
    return f"{y}-{int(mm):02d}"


def _data_rows(ws):
    """탭 1행 타이틀·2행 경고 등을 건너뛰고 헤더+데이터 영역만 반환.

    첫 컬럼이 YYYY-M(M) 또는 명시 키워드인 행만 유효 데이터로 본다.
    """
    if not ws:
        return []
    return ws.get_all_values()


def _extract_monthly(ws) -> list[dict]:
    """월별 재구매 탭 (재구매_*_월별).

    헤더 (3행): 기간|재구매자수|재구매건수|재구매매출(원)|AOV(원)|재구매빈도|재구매율(%)|신규구매자수
    """
    rows = _data_rows(ws)
    out = []
    for r in rows:
        if not r or not r[0]:
            continue
        m = _normalize_month(r[0])
        if not _MONTH_RE.match(m):
            continue
        out.append({
            "월": m,
            "재구매자수": _to_int(r[1]) if len(r) > 1 else 0,
            "재구매건수": _to_int(r[2]) if len(r) > 2 else 0,
            "재구매매출": _to_int(r[3]) if len(r) > 3 else 0,
            "AOV": _to_int(r[4]) if len(r) > 4 else 0,
            "재구매율": _to_pct(r[6]) if len(r) > 6 else 0,
            "신규구매자수": _to_int(r[7]) if len(r) > 7 else 0,
        })
    return out[-13:]


def _extract_cohort_stage(ws) -> list[dict]:
    """코호트별 30일/60일 전환율 (코호트_*_전환율).

    헤더 (3행): 코호트월|첫구매자수|30일 전환수|30일 전환율|30일 상태|60일 전환수|60일 전환율|60일 상태

    의미:
      30일 전환율 = 첫 구매 후 30일 내 2번째 구매 발생 비율 ≈ 1→2 전환의 빠른 지표
      60일 전환율 = 60일 내 2번째 구매 발생 비율 (확정에 가까움)
    """
    rows = _data_rows(ws)
    out = []
    for r in rows:
        if not r or not r[0]:
            continue
        m = _normalize_month(r[0])
        if not _MONTH_RE.match(m):
            continue
        out.append({
            "코호트월": m,
            "첫구매자수": _to_int(r[1]) if len(r) > 1 else 0,
            "30일_전환수": _to_int(r[2]) if len(r) > 2 else 0,
            "30일_전환율": _to_pct(r[3]) if len(r) > 3 else 0,
            "60일_전환수": _to_int(r[5]) if len(r) > 5 else 0,
            "60일_전환율": _to_pct(r[6]) if len(r) > 6 else 0,
            # 호환용 별칭 (기존 build_ground_truth가 1→2_전환율을 참조)
            "1→2_전환율": _to_pct(r[6]) if len(r) > 6 else 0,
            "2→3_전환율": None,  # 새 시트엔 없음
        })
    return out


def _extract_mn(ws) -> list[dict]:
    """M+N 잔존율 (코호트_월별잔존율).

    헤더 (3행): 코호트월|첫구매자수|M+1|M+2|M+3|M+4|M+5|M+6
    """
    rows = _data_rows(ws)
    out = []
    for r in rows:
        if not r or not r[0]:
            continue
        m = _normalize_month(r[0])
        if not _MONTH_RE.match(m):
            continue
        out.append({
            "코호트월": m,
            "첫구매자수": _to_int(r[1]) if len(r) > 1 else 0,
            "M+1": _to_pct(r[2]) if len(r) > 2 else None,
            "M+2": _to_pct(r[3]) if len(r) > 3 else None,
            "M+3": _to_pct(r[4]) if len(r) > 4 else None,
            "M+6": _to_pct(r[7]) if len(r) > 7 else None,
        })
    return out


def _extract_interval_stats(ws) -> dict:
    """재구매 간격 P50/P75/P90 (재구매_간격분석).

    헤더 (3행): 지표|값|의미
    행 1열에 '중앙값 (P50)', 'P75', 'P90 ← CRM 기준' 등 — 키 매칭.
    """
    rows = _data_rows(ws)
    out: dict = {}
    for r in rows:
        if len(r) < 2 or not r[0]:
            continue
        key = r[0].strip()
        val = r[1].strip()
        if "P50" in key or "중앙값" in key:
            out["P50"] = val
        elif "P75" in key:
            out["P75"] = val
        elif "P90" in key:
            out["P90"] = val
        elif key == "평균":
            out["평균"] = val
        elif "샘플" in key:
            out["샘플수"] = val
    return out


# 새 시트엔 단계별 전환율 평탄 탭이 없음. 코호트 전환율로 대체.
def _extract_stage_flat(ws) -> list[dict]:
    """30일/60일 코호트 전환율의 평균을 단계 형태로 변환 (호환용)."""
    # ⚠️ ISSUE-2 (Codex C2: high) — 미완결 코호트 평균에 포함. elapsed-time gate 없음.
    # 60일 안 지난 코호트도 last3에 들어가 헤드라인 1→2 전환율을 끌어내림.
    # FIX: 30일·60일 분리 + 각각 _is_complete_30d / _is_complete_60d 게이트 적용.
    rows = _extract_cohort_stage(ws)
    if not rows:
        return []
    completed = [r for r in rows if r["30일_전환율"] is not None and r["첫구매자수"] >= 5]
    if not completed:
        return []
    last3 = completed[-3:]
    avg30 = round(sum(r["30일_전환율"] or 0 for r in last3) / len(last3), 2)
    avg60 = round(sum(r["60일_전환율"] or 0 for r in last3) / len(last3), 2)
    base = sum(r["첫구매자수"] for r in last3)
    conv30 = sum(r["30일_전환수"] for r in last3)
    conv60 = sum(r["60일_전환수"] for r in last3)
    return [
        {"단계": "1→2", "기준고객수": base, "전환고객수": conv60, "전환율": avg60,
         "해석": f"60일 누적, 최근 3개월({last3[0]['코호트월']}~{last3[-1]['코호트월']}) 평균"},
        {"단계": "1→2_30일", "기준고객수": base, "전환고객수": conv30, "전환율": avg30,
         "해석": "30일 빠른 전환 지표"},
    ]


def build_ground_truth(spreadsheet) -> dict:
    _log("시트 탭 분류 중...")
    tabs = _classify_tabs(spreadsheet)
    missing = [k for k, v in tabs.items() if v is None]
    _log(f"  분류 결과: {len(tabs)-len(missing)}/{len(tabs)}개 식별, 누락: {missing}")

    now = datetime.now(KST)
    current_month = now.strftime("%Y-%m")
    # 직전 월
    prev_month_dt = (now.replace(day=1) - timedelta(days=1))
    prev_month = prev_month_dt.strftime("%Y-%m")

    # 월별 매출 (통합 + 플랫폼별)
    integrated_monthly = _extract_monthly(tabs.get("integrated_monthly"))
    cafe24_monthly = _extract_monthly(tabs.get("cafe24_monthly"))
    ss_monthly = _extract_monthly(tabs.get("ss_monthly"))

    def _find_month(rows, ym):
        for r in rows:
            if r["월"] == ym:
                return r
        return None

    integrated_cur = _find_month(integrated_monthly, current_month) or {}
    integrated_prev = _find_month(integrated_monthly, prev_month) or {}
    cafe24_cur = _find_month(cafe24_monthly, current_month) or {}
    cafe24_prev = _find_month(cafe24_monthly, prev_month) or {}
    ss_cur = _find_month(ss_monthly, current_month) or {}
    ss_prev = _find_month(ss_monthly, prev_month) or {}

    def _pct_change(cur, prev):
        if not prev or prev == 0:
            return None
        return round((cur - prev) / prev * 100, 1)

    # 단계별 전환율 (통합 기준) — 새 시트엔 평탄 탭 없음. 코호트 전환율의 최근 평균을 단계 형태로 변환
    integrated_stage = _extract_stage_flat(tabs.get("integrated_cohort"))
    cafe24_stage = _extract_stage_flat(tabs.get("cafe24_cohort"))
    ss_stage = _extract_stage_flat(tabs.get("ss_cohort"))

    # 코호트 추세 (통합): 최근 6개월 30일·60일 전환율
    integrated_cohort = _extract_cohort_stage(tabs.get("integrated_cohort"))
    # 최근 6개월 중 완결 코호트만 (최근 1~2개월은 아직 집계 중일 수 있음)
    cohort_recent = integrated_cohort[-8:]

    # 최근 3개월 vs 그 이전 3개월 평균
    def _avg_or_none(values):
        clean = [v for v in values if v is not None]
        return round(sum(clean) / len(clean), 2) if clean else None

    if len(integrated_cohort) >= 6:
        # 최근 1~2개월은 제외 (진행 중), 완결 코호트 중 최신 3개월 vs 그 이전 3개월
        completed = [c for c in integrated_cohort if c["1→2_전환율"] is not None and c["첫구매자수"] >= 5]
        last3 = completed[-3:] if len(completed) >= 3 else completed
        prev3 = completed[-6:-3] if len(completed) >= 6 else []
        cohort_trend_1to2 = {
            "최근3개월_평균": _avg_or_none([c["1→2_전환율"] for c in last3]),
            "이전3개월_평균": _avg_or_none([c["1→2_전환율"] for c in prev3]),
            "최근3개월_코호트": [c["코호트월"] for c in last3],
            "이전3개월_코호트": [c["코호트월"] for c in prev3],
        }
        cohort_trend_2to3 = {
            "최근3개월_평균": _avg_or_none([c["2→3_전환율"] for c in last3]),
            "이전3개월_평균": _avg_or_none([c["2→3_전환율"] for c in prev3]),
        }
    else:
        cohort_trend_1to2 = {"최근3개월_평균": None, "이전3개월_평균": None}
        cohort_trend_2to3 = {"최근3개월_평균": None, "이전3개월_평균": None}

    # 추세 변화 (%p)
    def _delta(t):
        a = t.get("최근3개월_평균")
        b = t.get("이전3개월_평균")
        if a is None or b is None:
            return None
        return round(a - b, 2)

    cohort_trend_1to2["변화_pp"] = _delta(cohort_trend_1to2)
    cohort_trend_2to3["변화_pp"] = _delta(cohort_trend_2to3)

    # M+N 리텐션 — 완결된 최신 코호트 (M+1 기준 6개월 이상 지난 것)
    # ⚠️ ISSUE-1 (Codex C1: high) — M+1 is not None 만 체크. 진행 중 코호트도 통과됨.
    # FIX: GT에 is_complete/window_end/observed_days 메타 추가 후 is_complete 필터로 변경.
    mn = _extract_mn(tabs.get("mn_retention"))
    mn_completed = [m for m in mn if m.get("M+1") is not None]

    gt = {
        "리포트_날짜": now.strftime("%Y-%m-%d"),
        "당월": current_month,
        "전월": prev_month,
        "월별_재구매_매출": {
            "통합": {
                "당월": {
                    "매출": integrated_cur.get("재구매매출"),
                    "재구매자수": integrated_cur.get("재구매자수"),
                    "재구매건수": integrated_cur.get("재구매건수"),
                    "AOV": integrated_cur.get("AOV"),
                },
                "전월": {
                    "매출": integrated_prev.get("재구매매출"),
                    "재구매자수": integrated_prev.get("재구매자수"),
                    "재구매건수": integrated_prev.get("재구매건수"),
                    "AOV": integrated_prev.get("AOV"),
                },
                "MoM_변화_금액": (
                    (integrated_cur.get("재구매매출") or 0) - (integrated_prev.get("재구매매출") or 0)
                ),
                "MoM_변화_pct": _pct_change(
                    integrated_cur.get("재구매매출") or 0,
                    integrated_prev.get("재구매매출") or 0,
                ),
            },
            "카페24": {
                "당월_매출": cafe24_cur.get("재구매매출"),
                "전월_매출": cafe24_prev.get("재구매매출"),
                "MoM_pct": _pct_change(
                    cafe24_cur.get("재구매매출") or 0,
                    cafe24_prev.get("재구매매출") or 0,
                ),
            },
            "스마트스토어": {
                "당월_매출": ss_cur.get("재구매매출"),
                "전월_매출": ss_prev.get("재구매매출"),
                "MoM_pct": _pct_change(
                    ss_cur.get("재구매매출") or 0,
                    ss_prev.get("재구매매출") or 0,
                ),
            },
        },
        "단계별_전환율_현재": {
            "통합": integrated_stage,
            "카페24": cafe24_stage,
            "스마트스토어": ss_stage,
        },
        "코호트_추세_통합": {
            "최근_6개월": cohort_recent,
            "1→2_추세": cohort_trend_1to2,
            "2→3_추세": cohort_trend_2to3,
        },
        "M+N_리텐션_통합": mn_completed[-6:] if mn_completed else [],
        "재구매_간격": _extract_interval_stats(tabs.get("interval_stats")),
        "업계_벤치마크": {
            "M+1_리텐션_평균": "20~30%",
            "D2C_식품_재구매율": "30~35%",
        },
    }
    return gt


# ============================================================
# 마트 탭 작성 (Looker Studio 데이터 소스)
# ============================================================

MART_MONTHLY_HEADER = [
    "연월", "채널", "신규구매자", "재구매자", "재구매율", "재구매AOV", "재구매매출", "갱신시각",
]
MART_COHORT_HEADER = [
    "코호트월", "채널", "첫구매자수", "M+1", "M+2", "M+3", "M+6", "갱신시각",
]
MART_STAGE_HEADER = [
    "채널", "단계", "기준고객수", "전환고객수", "전환율", "갱신시각",
]
MART_SUMMARY_HEADER = [
    "지표", "값", "벤치마크", "상태", "갱신시각",
]


def _ensure_mart_tab(spreadsheet, name: str, header: list[str]):
    """탭이 없으면 만들고 헤더를 보장. 있으면 그대로 반환."""
    try:
        ws = spreadsheet.worksheet(name)
    except Exception:
        ws = spreadsheet.add_worksheet(title=name, rows=200, cols=max(10, len(header)))
        ws.update(values=[header], range_name="A1")
        return ws

    cur = ws.row_values(1)
    if cur != header:
        ws.update(values=[header], range_name="A1")
    return ws


def _summary_status(value, good: float, warn: float, higher_is_better: bool = True) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    if higher_is_better:
        if v >= good:
            return "✅"
        if v >= warn:
            return "⚠️"
        return "🔴"
    else:
        if v <= good:
            return "✅"
        if v <= warn:
            return "⚠️"
        return "🔴"


def write_marts(spreadsheet, gt: dict, tabs: dict):
    """마트 4종(월별/코호트/단계/요약)을 long-format으로 덮어쓴다.

    - 시트=raw 저장소, Looker Studio=시각화 원칙
    - 기존 19개 분석 탭은 건드리지 않음 (롤백·검증용 보존)
    """
    now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    # ---------- mart_monthly ----------
    monthly_rows: list[list] = []
    for ch_key, ch_label in [
        ("integrated_monthly", "통합"),
        ("cafe24_monthly", "카페24"),
        ("ss_monthly", "스마트스토어"),
    ]:
        for r in _extract_monthly(tabs.get(ch_key)):
            monthly_rows.append([
                r["월"], ch_label,
                r.get("신규구매자수") or 0,
                r.get("재구매자수") or 0,
                r.get("재구매율") or 0,
                r.get("AOV") or 0,
                r.get("재구매매출") or 0,
                now_str,
            ])

    ws = _ensure_mart_tab(spreadsheet, "mart_monthly", MART_MONTHLY_HEADER)
    ws.clear()
    ws.update(values=[MART_MONTHLY_HEADER] + monthly_rows, range_name="A1")
    _log(f"  mart_monthly: {len(monthly_rows)}행")

    # ---------- mart_cohort ----------
    cohort_rows: list[list] = []
    # mn_retention 탭은 통합 1개만 존재 (코드 구조상)
    for r in _extract_mn(tabs.get("mn_retention")):
        cohort_rows.append([
            r["코호트월"], "통합",
            r.get("첫구매자수") or 0,
            r.get("M+1"), r.get("M+2"), r.get("M+3"), r.get("M+6"),
            now_str,
        ])

    ws = _ensure_mart_tab(spreadsheet, "mart_cohort", MART_COHORT_HEADER)
    ws.clear()
    ws.update(values=[MART_COHORT_HEADER] + cohort_rows, range_name="A1")
    _log(f"  mart_cohort: {len(cohort_rows)}행")

    # ---------- mart_stage ----------
    stage_rows: list[list] = []
    for ch_key, ch_label in [
        ("integrated_cohort", "통합"),
        ("cafe24_cohort", "카페24"),
        ("ss_cohort", "스마트스토어"),
    ]:
        for r in _extract_stage_flat(tabs.get(ch_key)):
            stage_rows.append([
                ch_label, r.get("단계", ""),
                r.get("기준고객수") or 0,
                r.get("전환고객수") or 0,
                r.get("전환율") or 0,
                now_str,
            ])

    ws = _ensure_mart_tab(spreadsheet, "mart_stage", MART_STAGE_HEADER)
    ws.clear()
    ws.update(values=[MART_STAGE_HEADER] + stage_rows, range_name="A1")
    _log(f"  mart_stage: {len(stage_rows)}행")

    # ---------- mart_summary ----------
    inm = gt.get("월별_재구매_매출", {}).get("통합", {})
    stage = gt.get("단계별_전환율_현재", {}).get("통합", [])
    s1_2 = next((s for s in stage if s.get("단계") == "1→2"), {})
    s2_3 = next((s for s in stage if s.get("단계") == "2→3"), {})
    mn_recent = (gt.get("M+N_리텐션_통합") or [])
    # ⚠️ ISSUE-1 (Codex C1: high) — mart_summary. 미완결 코호트가 mn_recent[-1]에 들어가
    # M+1 리텐션 최신 KPI 자리에 노출됨. is_complete 필터로 교체 필요.
    m1_recent = mn_recent[-1].get("M+1") if mn_recent else None
    interval = gt.get("재구매_간격", {}) or {}

    summary_rows = [
        ["당월 재구매 매출", inm.get("당월", {}).get("매출"), "—", "—", now_str],
        ["전월 재구매 매출", inm.get("전월", {}).get("매출"), "—", "—", now_str],
        ["MoM 변화율(%)", inm.get("MoM_변화_pct"), "0% 이상", _summary_status(inm.get("MoM_변화_pct"), 0, -10, True), now_str],
        ["1→2 전환율(%)", s1_2.get("전환율"), "30%+ ✅ / 23~30% ⚠️", _summary_status(s1_2.get("전환율"), 30, 23, True), now_str],
        ["2→3 전환율(%)", s2_3.get("전환율"), "40%+ ✅", _summary_status(s2_3.get("전환율"), 40, 30, True), now_str],
        ["M+1 리텐션 최신 코호트(%)", m1_recent, "20~30% ✅", _summary_status(m1_recent, 20, 14, True), now_str],
        ["재구매 간격 P50(일)", interval.get("P50") or interval.get("중앙값") or interval.get("50%"), "15일 부근", "—", now_str],
        ["재구매 간격 P90(일)", interval.get("P90") or interval.get("90%"), "31~62일", "—", now_str],
    ]

    ws = _ensure_mart_tab(spreadsheet, "mart_summary", MART_SUMMARY_HEADER)
    ws.clear()
    ws.update(values=[MART_SUMMARY_HEADER] + summary_rows, range_name="A1")
    _log(f"  mart_summary: {len(summary_rows)}행")


_MART_TAB_NAMES = ["mart_monthly", "mart_cohort", "mart_stage", "mart_summary"]
# 회색 탭 색상 (RGB 0~1)
_MART_TAB_COLOR = {"red": 0.6, "green": 0.6, "blue": 0.6}


def _style_mart_tabs(spreadsheet):
    """mart_* 탭을 회색으로 표시해 내부용 탭임을 구분."""
    requests = []
    for ws in spreadsheet.worksheets():
        if ws.title in _MART_TAB_NAMES:
            requests.append({
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": ws.id,
                        "tabColor": _MART_TAB_COLOR,
                        "tabColorStyle": {"rgbColor": _MART_TAB_COLOR},
                    },
                    "fields": "tabColor,tabColorStyle",
                }
            })
    if requests:
        try:
            spreadsheet.batch_update({"requests": requests})
            _log(f"  mart 탭 색상 회색 처리 ({len(requests)}개)")
        except Exception as e:
            _log(f"  ⚠️ mart 탭 색상 실패: {e}")


# ============================================================
# 탭 정리 (채널별 중복 탭 숨김)
# ============================================================

# 숨김 대상: 채널별 중복 탭 + Meta 광고 탭 + 카페24/SS 재구매매출 탭 (통합 탭으로 충분)
# 이 탭들은 맨 뒤로 이동 후 숨김 처리 (데이터 보존)
_REDUNDANT_TABS = [
    # 채널별 중복 — 통합 탭으로 충분
    "재구매_카페24_월별",
    "재구매_SS_월별",
    "코호트_카페24_전환율",
    "코호트_SS_전환율",
    "구매횟수_퍼널_카페24",
    "구매횟수_퍼널_SS",
    "구매횟수_퍼널_통합",
    # 고객마스터 — 원본 탭으로 충분, 직접 볼 필요 없음
    "코호트_고객마스터",
    # Meta 광고 — 별도 시트에서 관리
    "Meta_Ads_Daily",
    "Meta_Ads_Daily_Campaign",
    "Meta_Ads_Winners",
    # mart_* — 내부 BI용, 대시보드로 대체
    "mart_monthly",
    "mart_cohort",
    "mart_stage",
    "mart_summary",
]

# 카페24/SS 채널별 재구매매출 탭 — 맨 뒤 이동 후 숨김
_MOVE_TO_BACK_TABS = [
    "카페24 재구매매출",
    "스마트스토어 재구매매출",
]


def hide_redundant_tabs(spreadsheet):
    """숨김 대상 탭을 맨 뒤로 이동 후 일괄 숨김 처리."""
    all_ws = spreadsheet.worksheets()
    total = len(all_ws)

    requests = []
    hidden_titles = []

    for ws in all_ws:
        # 맨 뒤로 이동 대상
        if ws.title in _MOVE_TO_BACK_TABS:
            requests.append({
                "updateSheetProperties": {
                    "properties": {"sheetId": ws.id, "index": total - 1},
                    "fields": "index",
                }
            })

        # 숨김 대상 (이미 숨겨진 탭은 skip)
        if ws.title in _REDUNDANT_TABS + _MOVE_TO_BACK_TABS:
            if not ws.isSheetHidden:
                requests.append({
                    "updateSheetProperties": {
                        "properties": {"sheetId": ws.id, "hidden": True},
                        "fields": "hidden",
                    }
                })
                hidden_titles.append(ws.title)

    if requests:
        try:
            spreadsheet.batch_update({"requests": requests})
            _log(f"  탭 숨김/이동 완료: {hidden_titles}")
        except Exception as e:
            _log(f"  ⚠️ 탭 숨김 실패: {e}")
    else:
        _log("  숨김 대상 탭 없음 (이미 처리됨)")


# ============================================================
# 대시보드 탭
# ============================================================

_DASH_TAB = "📊 대시보드"

# 상태 판정 (셀 텍스트)
def _dash_status(value, good: float, warn: float, higher_is_better: bool = True) -> str:
    if value is None:
        return "데이터 없음"
    try:
        v = float(str(value).replace("%", "").replace("일", "").strip())
    except (TypeError, ValueError):
        return str(value)
    if higher_is_better:
        label = "양호" if v >= good else ("주의" if v >= warn else "위험")
    else:
        label = "양호" if v <= good else ("주의" if v <= warn else "위험")
    icon = {"양호": "🟢", "주의": "🟡", "위험": "🔴"}[label]
    return f"{icon} {label}"


def write_dashboard(spreadsheet, gt: dict):
    """[📊 대시보드] 탭을 경영자용 요약 뷰로 매일 갱신.

    탭이 없으면 생성, 있으면 전체 덮어쓰기.
    구조: KPI 카드 → 월별 추이(6개월) → 코호트 전환(6개월) → M+N 리텐션(3코호트) → 액션 포인트
    """
    try:
        ws = spreadsheet.worksheet(_DASH_TAB)
    except Exception:
        ws = spreadsheet.add_worksheet(title=_DASH_TAB, rows=60, cols=10)

    # 기존 내용 초기화 후 시트 맨 앞으로 이동
    ws.clear()
    try:
        spreadsheet.batch_update({
            "requests": [{"updateSheetProperties": {
                "properties": {"sheetId": ws.id, "index": 0},
                "fields": "index",
            }}]
        })
    except Exception:
        pass

    now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    # ── 데이터 추출 ──────────────────────────────────────────
    inm = gt.get("월별_재구매_매출", {}).get("통합", {})
    cur_m = inm.get("당월", {})
    prev_m = inm.get("전월", {})
    mom_pct = inm.get("MoM_변화_pct")

    stage = gt.get("단계별_전환율_현재", {}).get("통합", [])
    s1_2 = next((s for s in stage if s.get("단계") == "1→2"), {})

    mn_list = gt.get("M+N_리텐션_통합") or []
    # ⚠️ ISSUE-1 (Codex C1: high) — dashboard KPI. list position[-1] 대신 is_complete 필터 사용.
    m1_recent = mn_list[-1].get("M+1") if mn_list else None

    interval = gt.get("재구매_간격", {}) or {}
    p50_raw = interval.get("P50") or interval.get("중앙값") or "—"
    try:
        p50_num = float(str(p50_raw).replace("일", "").strip())
    except (TypeError, ValueError):
        p50_num = None

    conv_rate = s1_2.get("전환율")
    cohort_trend = gt.get("코호트_추세_통합", {}).get("1→2_추세", {})

    # 월별 추이 (최근 6개월)
    tabs = _classify_tabs(spreadsheet)
    monthly_rows = _extract_monthly(tabs.get("integrated_monthly"))[-6:]
    cohort_rows = _extract_cohort_stage(tabs.get("integrated_cohort"))
    cohort_recent = [r for r in cohort_rows if r.get("첫구매자수", 0) >= 5][-6:]
    mn_recent3 = mn_list[-3:] if len(mn_list) >= 3 else mn_list

    # ── 숫자 포맷 헬퍼 ───────────────────────────────────────
    def _fmt_won(v):
        """원 단위 → 만원/억원 표기. 예) 14,284,532 → 1,428만원"""
        if not v:
            return "—"
        v = int(v)
        if v >= 100_000_000:
            return f"{v / 100_000_000:.1f}억원"
        if v >= 10_000:
            return f"{v // 10_000:,}만원"
        return f"{v:,}원"

    def _fmt_pct(v, decimal=1):
        """float → '23.3%' 포맷."""
        if v is None:
            return "—"
        try:
            return f"{float(v):.{decimal}f}%"
        except (TypeError, ValueError):
            return str(v)

    def _fmt_delta(v):
        """전월 대비 % → '+2.3%' / '-1.5%' 포맷."""
        if v is None:
            return "—"
        try:
            f = float(v)
            sign = "▲" if f > 0 else ("▼" if f < 0 else "")
            return f"{sign}{abs(f):.1f}%"
        except (TypeError, ValueError):
            return str(v)

    # ── 행 구성 ──────────────────────────────────────────────
    rows: list[list] = []

    # 제목
    rows.append(["HeavyLover 재구매 현황", "", "", "", "", "", "", "", "", now_str])
    rows.append([""])

    # KPI 카드 헤더
    rows.append(["지표", "이번 달", "전월 대비", "목표 기준", "판정"])

    # KPI 카드 4개 — 전월값도 같은 행에
    mom_str = _fmt_delta(mom_pct)
    rows.append([
        "재구매 매출",
        _fmt_won(cur_m.get("매출")),
        f"{mom_str}  (전월 {_fmt_won(prev_m.get('매출'))})",
        "—",
        f"{'▲' if (mom_pct or 0) >= 0 else '▼'} {'양호' if (mom_pct or 0) >= 0 else '감소'}",
    ])
    rows.append([
        "첫 구매 → 재구매 전환율",
        _fmt_pct(conv_rate),
        "—",
        "30% 이상이면 양호",
        _dash_status(conv_rate, 30, 20, True),
    ])
    rows.append([
        "한 달 후 재구매율 (최신)",
        _fmt_pct(m1_recent),
        "—",
        "20% 이상이면 양호",
        _dash_status(m1_recent, 20, 14, True),
    ])
    rows.append([
        "재구매 평균 주기",
        f"{p50_raw}" if p50_raw != "—" else "—",
        "—",
        "15일 이내이면 양호",
        _dash_status(p50_num, 15, 25, False) if p50_num is not None else "—",
    ])
    rows.append([""])

    # 월별 추이 테이블
    rows.append(["▸ 월별 재구매 추이 (최근 6개월)", "", "", "", "", ""])
    rows.append(["월", "재구매 고객 수", "재구매 매출", "1인당 평균 결제액", "재구매율", "전월 대비"])
    prev_매출 = None
    for r in monthly_rows:
        매출 = r.get("재구매매출") or 0
        delta_str = ""
        if prev_매출 is not None and prev_매출 > 0:
            delta = round((매출 - prev_매출) / prev_매출 * 100, 1)
            sign = "▲" if delta > 0 else ("▼" if delta < 0 else "")
            delta_str = f"{sign}{abs(delta):.1f}%"
        rows.append([
            r.get("월", ""),
            f"{r.get('재구매자수') or 0:,}명",
            _fmt_won(매출),
            _fmt_won(r.get("AOV")),
            _fmt_pct(r.get("재구매율")),
            delta_str,
        ])
        prev_매출 = 매출
    rows.append([""])

    # 코호트 전환율 테이블
    rows.append(["▸ 첫 구매 → 재구매 전환율 (최근 6개월)", "", "", "", ""])
    rows.append(["구매 월", "첫 구매 고객 수", "30일 내 재구매율", "60일 내 재구매율", "판정"])
    for r in cohort_recent:
        conv60 = r.get("60일_전환율")
        rows.append([
            r.get("코호트월", ""),
            f"{r.get('첫구매자수') or 0:,}명",
            _fmt_pct(r.get("30일_전환율")),
            _fmt_pct(conv60),
            _dash_status(conv60, 30, 20, True) if conv60 is not None else "—",
        ])
    rows.append([""])

    # 재구매 유지율 테이블 (M+N)
    rows.append(["▸ 재구매 유지율 — 첫 구매 후 몇 달이 지나도 사는가 (최근 3개월)", "", "", "", "", ""])
    rows.append(["구매 월", "첫 구매 고객 수", "1개월 후", "2개월 후", "3개월 후", "6개월 후"])
    for r in mn_recent3:
        rows.append([
            r.get("코호트월", ""),
            f"{r.get('첫구매자수') or 0:,}명",
            _fmt_pct(r.get("M+1")),
            _fmt_pct(r.get("M+2")),
            _fmt_pct(r.get("M+3")),
            _fmt_pct(r.get("M+6")),
        ])
    rows.append([""])

    # 액션 포인트
    rows.append(["▸ 지금 봐야 할 것", "", "", "", ""])
    actions = _build_action_points(conv_rate, m1_recent, p50_num, mom_pct, cohort_trend)
    for a in actions:
        rows.append([a])

    # ── 시트에 쓰기 ─────────────────────────────────────────
    ws.update(values=rows, range_name="A1")

    # ── 셀 포맷 적용 ─────────────────────────────────────────
    _apply_dashboard_formats(ws, spreadsheet, rows, conv_rate, m1_recent, p50_num, mom_pct, mn_recent3)
    _log(f"  [📊 대시보드] 갱신 완료 ({len(rows)}행)")


def _build_action_points(conv_rate, m1_recent, p50_num, mom_pct, cohort_trend) -> list[str]:
    """현재 KPI 기반으로 액션 포인트 자동 생성."""
    points = []

    if m1_recent is not None:
        try:
            v = float(m1_recent)
            if v < 14:
                points.append(f"🔴 첫 구매 후 한 달 안에 재구매하는 비율이 {v}%입니다. 목표(20%)에 크게 못 미칩니다. 구매 3일·10일·17일 후 리마인드 메일 검토 필요.")
            elif v < 20:
                points.append(f"🟡 첫 구매 후 한 달 안에 재구매하는 비율이 {v}%입니다. 목표(20%)에 조금 못 미칩니다. CRM 재구매 유도 메시지 강화를 검토하세요.")
            else:
                points.append(f"🟢 첫 구매 후 한 달 안에 재구매하는 비율이 {v}%로 목표(20%) 충족입니다.")
        except (TypeError, ValueError):
            pass

    if conv_rate is not None:
        try:
            v = float(conv_rate)
            trend_str = ""
            recent_avg = cohort_trend.get("최근3개월_평균")
            prev_avg = cohort_trend.get("이전3개월_평균")
            if recent_avg is not None and prev_avg is not None:
                try:
                    delta = round(float(recent_avg) - float(prev_avg), 1)
                    trend_str = f", 최근 3개월 추세 {'↑상승' if delta > 0 else '↓하락'} {abs(delta)}%p"
                except (TypeError, ValueError):
                    pass
            if v < 20:
                points.append(f"🔴 첫 구매 후 60일 내 재구매율이 {v}%입니다{trend_str}. 상세페이지·구매 경험을 점검하세요.")
            elif v < 30:
                points.append(f"🟡 첫 구매 후 60일 내 재구매율이 {v}%입니다{trend_str}. 개선 여지가 있습니다.")
            else:
                points.append(f"🟢 첫 구매 후 60일 내 재구매율이 {v}%입니다{trend_str}. 양호합니다.")
        except (TypeError, ValueError):
            pass

    if p50_num is not None:
        if p50_num <= 15:
            points.append(f"🟢 고객의 절반이 {p50_num}일 만에 다시 구매합니다. 생활 루틴으로 자리잡은 신호입니다.")
        elif p50_num <= 25:
            points.append(f"🟡 고객의 절반이 {p50_num}일 만에 재구매합니다. 리마인드 타이밍을 점검하세요.")
        else:
            points.append(f"🔴 고객의 절반이 {p50_num}일이 지나야 재구매합니다. 구매 주기가 길어지고 있습니다. 정기 구독 유도를 검토하세요.")

    if mom_pct is not None:
        try:
            v = float(mom_pct)
            if v < -10:
                points.append(f"🔴 재구매 매출이 전월보다 {abs(v):.1f}% 급감했습니다. 원인 파악이 필요합니다.")
            elif v < 0:
                points.append(f"🟡 재구매 매출이 전월보다 {abs(v):.1f}% 소폭 감소했습니다.")
        except (TypeError, ValueError):
            pass

    if not points:
        points.append("현재 주요 이상 신호 없음. 정기 모니터링 유지.")

    return points


# 색상 상수 (RGB 0~1)
_COLOR_GREEN  = {"red": 0.851, "green": 0.918, "blue": 0.827}  # 연초록
_COLOR_YELLOW = {"red": 1.0,   "green": 0.949, "blue": 0.8}    # 연노랑
_COLOR_RED    = {"red": 0.957, "green": 0.8,   "blue": 0.8}    # 연빨강
_COLOR_HEADER = {"red": 0.235, "green": 0.522, "blue": 0.776}  # 헤비로버 블루
_COLOR_WHITE  = {"red": 1.0,   "green": 1.0,   "blue": 1.0}


def _rgb_for_status(value, good, warn, higher_is_better=True):
    """KPI 값 → 배경색 RGB dict."""
    if value is None:
        return _COLOR_WHITE
    try:
        v = float(str(value).replace("%", "").replace("일", "").strip())
    except (TypeError, ValueError):
        return _COLOR_WHITE
    if higher_is_better:
        if v >= good:
            return _COLOR_GREEN
        if v >= warn:
            return _COLOR_YELLOW
        return _COLOR_RED
    else:
        if v <= good:
            return _COLOR_GREEN
        if v <= warn:
            return _COLOR_YELLOW
        return _COLOR_RED


def _cell_fmt(bg: dict, bold=False, font_size=10) -> dict:
    fmt = {
        "backgroundColor": bg,
        "textFormat": {"bold": bold, "fontSize": font_size},
    }
    return fmt


def _apply_dashboard_formats(ws, spreadsheet, rows: list, conv_rate, m1_recent, p50_num, mom_pct, mn_recent3=None):
    """대시보드 셀 배경색·볼드·폰트 크기 일괄 적용."""
    sheet_id = ws.id
    requests = []

    def _row_range(row_idx: int, col_start=0, col_end=9):
        """0-indexed row, 0-indexed col → GridRange dict."""
        return {
            "sheetId": sheet_id,
            "startRowIndex": row_idx,
            "endRowIndex": row_idx + 1,
            "startColumnIndex": col_start,
            "endColumnIndex": col_end + 1,
        }

    def _fmt_req(row_idx, bg, bold=False, font_size=10, col_start=0, col_end=9):
        return {
            "repeatCell": {
                "range": _row_range(row_idx, col_start, col_end),
                "cell": {"userEnteredFormat": _cell_fmt(bg, bold, font_size)},
                "fields": "userEnteredFormat(backgroundColor,textFormat)",
            }
        }

    # 행 1 (0-idx=0): 제목 — 블루 배경 + 흰 볼드
    requests.append({
        "repeatCell": {
            "range": _row_range(0),
            "cell": {"userEnteredFormat": {
                "backgroundColor": _COLOR_HEADER,
                "textFormat": {"bold": True, "fontSize": 13, "foregroundColor": _COLOR_WHITE},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }
    })

    # 행 3 (0-idx=2): KPI 테이블 헤더 — 진회색 배경 볼드
    requests.append(_fmt_req(2, {"red": 0.9, "green": 0.9, "blue": 0.9}, bold=True))

    # KPI 카드 행 4~7 (0-idx=3~6): 상태 컬럼(D, col=3)에 색상
    kpi_colors = [
        # 당월 재구매 매출 — MoM 기준
        _rgb_for_status(mom_pct, 0, -10, True),
        # 1→2 전환율
        _rgb_for_status(conv_rate, 30, 20, True),
        # M+1 리텐션
        _rgb_for_status(m1_recent, 20, 14, True),
        # P50 간격
        _rgb_for_status(p50_num, 15, 25, False),
    ]
    for i, color in enumerate(kpi_colors):
        row_idx = 3 + i
        # 상태 컬럼(D=col 3)만 색상
        requests.append(_fmt_req(row_idx, color, col_start=3, col_end=3))
        # 지표명 컬럼(A=col 0)은 연한 회색
        requests.append(_fmt_req(row_idx, {"red": 0.97, "green": 0.97, "blue": 0.97}, col_start=0, col_end=0))

    # 섹션 헤더 행들 찾아서 볼드 처리 (rows에서 "▸" 포함 행)
    for idx, row in enumerate(rows):
        if row and isinstance(row[0], str) and "▸" in row[0]:
            requests.append(_fmt_req(idx, {"red": 0.851, "green": 0.886, "blue": 0.953}, bold=True, font_size=11))

    # 코호트 전환율 상태 컬럼 (E=col 4) 색상
    cohort_header_idx = None
    for idx, row in enumerate(rows):
        if row and isinstance(row[0], str) and "첫 구매 → 재구매 전환율" in row[0]:
            cohort_header_idx = idx
            break
    if cohort_header_idx is not None:
        # 컬럼 헤더 행 다음부터 데이터 행
        col_hdr_idx = cohort_header_idx + 1
        requests.append(_fmt_req(col_hdr_idx, {"red": 0.9, "green": 0.9, "blue": 0.9}, bold=True))
        # 데이터 행: 빈 행 또는 "──" 나올 때까지
        r = col_hdr_idx + 1
        while r < len(rows):
            row = rows[r]
            if not row or not row[0] or (isinstance(row[0], str) and "──" in row[0]):
                break
            # E 컬럼(col=4) 상태
            status_text = row[4] if len(row) > 4 else None
            if isinstance(status_text, str):
                if "🟢" in status_text or "양호" in status_text:
                    color = _COLOR_GREEN
                elif "🟡" in status_text or "주의" in status_text:
                    color = _COLOR_YELLOW
                elif "🔴" in status_text or "위험" in status_text:
                    color = _COLOR_RED
                else:
                    color = _COLOR_WHITE
                requests.append(_fmt_req(r, color, col_start=4, col_end=4))
            r += 1

    # M+N 리텐션 히트맵 — M+1~M+6 각 셀을 값 크기에 따라 색상 칠하기
    # 판정 기준: ≥20% 초록, 14~20% 노랑, <14% 빨강
    mn_header_idx = None
    for idx, row in enumerate(rows):
        if row and isinstance(row[0], str) and "재구매 유지율" in row[0]:
            mn_header_idx = idx
            break
    if mn_header_idx is not None:
        col_hdr_idx = mn_header_idx + 1
        requests.append(_fmt_req(col_hdr_idx, {"red": 0.9, "green": 0.9, "blue": 0.9}, bold=True))
        r = col_hdr_idx + 1
        while r < len(rows):
            row = rows[r]
            if not row or not row[0] or (isinstance(row[0], str) and "──" in row[0]):
                break
            # M+1~M+6은 col 2~5 (코호트월=0, 첫구매자=1, M+1=2, M+2=3, M+3=4, M+6=5)
            for col_i in range(2, 6):
                if col_i >= len(row):
                    break
                val = row[col_i]
                if val == "—" or val is None or val == "":
                    r_col = _COLOR_WHITE
                else:
                    r_col = _rgb_for_status(val, 20, 14, True)
                requests.append(_fmt_req(r, r_col, col_start=col_i, col_end=col_i))
            # 코호트월 컬럼은 연회색
            requests.append(_fmt_req(r, {"red": 0.97, "green": 0.97, "blue": 0.97}, col_start=0, col_end=0))
            r += 1

    # 열 너비 자동 조정 (A~G 컬럼)
    requests.append({
        "autoResizeDimensions": {
            "dimensions": {
                "sheetId": sheet_id,
                "dimension": "COLUMNS",
                "startIndex": 0,
                "endIndex": 7,
            }
        }
    })

    if requests:
        try:
            spreadsheet.batch_update({"requests": requests})
        except Exception as e:
            _log(f"  ⚠️ 포맷 적용 실패: {e}")


# ============================================================
# Claude 분석
# ============================================================

SYSTEM_PROMPT = """당신은 10년차 D2C 이커머스 경영 전문가다. HeavyLover(냉동 도시락 D2C, 20~30대 운동 직장인 남성 타겟) 재구매 KPI를 매일 진단한다.

**핵심 원칙 (절대 위반 금지):**

1. **숫자는 입력 JSON에 있는 것만 사용한다.** 새로운 숫자를 창작하거나 추정하지 않는다. JSON에 없는 값을 인용해야 할 경우 "데이터 없음"이라고 명시한다.

2. **추측·가설 금지.** 원인을 단정하지 않는다. "~때문으로 보입니다", "~일 수 있습니다", "아마도", "추정하건대", "~로 보입니다" 같은 표현 사용 금지. 관찰된 사실과 그 의미만 서술한다.

3. **향상/악화 판정은 최근 3개월 추세선 vs 그 이전 3개월 기준으로만 내린다.** 단일 월 비교는 노이즈 가능성을 언급한다.

4. **경영 관점.** 재구매 1%p 변화가 CAC 회수 속도와 LTV에 미치는 영향을 염두에 두되, 구체적 금액 계산은 JSON에 없으면 하지 않는다.

5. **포맷.** 불릿/헤더 남발 금지. 문장 중심. 전체 길이 800자 이내. 이모지는 ⚠️ ✅ 📊만 최소한으로.

6. **용어 설명.** 약어·영어 지표명이 처음 등장할 때 반드시 괄호로 한글 설명을 붙인다.
   예시: AOV(평균 주문금액), CAC(고객 획득 비용), LTV(고객 생애가치), MoM(전월대비), WoW(전주대비),
         코호트(같은 달 첫구매 고객 그룹), M+1(첫달 재구매율), M+N(N개월 후 재구매율),
         P50(재구매 간격 중앙값 — 전체 고객의 절반이 이 기간 안에 재구매함),
         1→2 전환(첫 구매 후 두 번째 구매로 이어지는 비율).
   이후 같은 글 안에서 재등장할 때는 약어만 사용해도 됨.
   "avg", "cohort", "retention" 등 영어 단어는 절대 그대로 쓰지 않는다. 반드시 한글로 표기.

7. **독자.** 비전공자 운영자(마케팅·통계 비전공)가 읽는 내부 리포트다. 수식·통계 용어 없이 "장사가 잘 되고 있냐"는 관점으로 서술한다. 각 섹션은 핵심 사실 1문장 + 그게 왜 중요한지 1문장으로 구성한다.

**리포트 필수 섹션:**

1. **매출 요약**: 당월 재구매 매출 vs 전월 (금액 + % 변화). 통합 기준, 카페24/SS 분해.
2. **1→2 전환 진단**: 현재 전환율 + 최근 3개월 추세 (향상/악화/정체 중 하나). JSON의 "변화_pp" 값 사용.
3. **2→3 전환 진단**: 동일 방식.
4. **핵심 시사점**: 오늘 승현 대표가 알아야 할 한 줄. 조치가 필요한 지점이 있다면 구체 지표로 지정.
5. **추가 확인 권고 (선택)**: 더 볼 지표가 있다면 언급.

입력 JSON의 키 구조:
- 월별_재구매_매출.통합.{당월, 전월, MoM_변화_금액, MoM_변화_pct}
- 단계별_전환율_현재.통합: [{단계, 기준고객수, 전환고객수, 전환율, 해석}]
- 코호트_추세_통합.{1→2_추세.최근3개월_평균, 이전3개월_평균, 변화_pp / 2→3_추세.*}
- M+N_리텐션_통합: 최근 6개 코호트
"""

USER_PROMPT_TEMPLATE = """다음은 오늘의 ground truth JSON이다. 이 JSON에 있는 숫자만 사용해 리포트를 작성하라.

```json
{gt_json}
```

{feedback_block}

위 원칙에 따라 리포트를 작성하라."""


def call_claude(gt: dict, feedback: str = "") -> str:
    load_dotenv(ENV_PATH, override=True)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 미설정")

    client = Anthropic(api_key=api_key)
    feedback_block = f"\n**이전 시도 피드백 (반드시 수정할 것):**\n{feedback}\n" if feedback else ""

    gt_json = json.dumps(gt, ensure_ascii=False, indent=2, default=str)
    user = USER_PROMPT_TEMPLATE.format(gt_json=gt_json, feedback_block=feedback_block)

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text.strip()


# ============================================================
# 검증 훅
# ============================================================

BANNED_PHRASES = [
    "로 보입니다", "일 수 있습니다", "로 보여집니다", "것으로 보이",
    "아마도", "추정하건대", "추측", "짐작",
    "것으로 보여", "로 사료됩니다", "가능성이 높", "가능성이 있",
    "일 것으로", "일 것 같", "라고 판단됩니다", "듯 합니다",
]


def _collect_numbers_from_gt(gt: dict) -> set[str]:
    """GT JSON에 포함된 모든 숫자를 문자열 집합으로 수집 (검증용)."""
    nums: set[str] = set()

    def _walk(x):
        if isinstance(x, dict):
            for v in x.values():
                _walk(v)
        elif isinstance(x, list):
            for v in x:
                _walk(v)
        elif isinstance(x, (int, float)):
            if x == 0:
                nums.add("0")
                return
            # 여러 포맷 허용
            nums.add(str(x))
            nums.add(str(int(x)) if x == int(x) else str(x))
            # 콤마 포맷
            try:
                nums.add(f"{int(x):,}")
            except (ValueError, OverflowError):
                pass
            # float → round 1 / round 2
            if isinstance(x, float):
                nums.add(f"{x:.1f}")
                nums.add(f"{x:.2f}")
        elif isinstance(x, str):
            # 숫자 포함 문자열도 체크 (예: "1,247건" → "1247")
            for m in re.findall(r"\d[\d,\.]*", x):
                clean = m.replace(",", "")
                nums.add(clean)
                nums.add(m)

    _walk(gt)
    return nums


def validate(text: str, gt: dict) -> list[str]:
    # ⚠️ ISSUE-4 (Codex C4: medium) — 강제 키워드 "2→3" 가 새 시트의 None 데이터와 충돌.
    # 멀쩡한 리포트도 3회 검증 실패 → fallback (raw 숫자) 발송.
    # FIX: required_keywords를 GT의 실제 데이터 유무 + 활성 프롬프트 버전 기반으로 동적 생성.
    # 추가: validation-fallback 카운트와 API 오류 카운트 분리 로깅.
    issues: list[str] = []

    # 1. 금지 표현
    for phrase in BANNED_PHRASES:
        if phrase in text:
            issues.append(f"금지 표현 감지: '{phrase}'")

    # 2. 필수 섹션 키워드
    required_keywords = ["당월", "전월", "1→2", "2→3"]
    for kw in required_keywords:
        if kw not in text:
            issues.append(f"필수 섹션 누락: '{kw}' 언급 없음")

    # 3. 숫자 검증 (원/건 단위 수치만 체크, 퍼센트 포함)
    gt_nums = _collect_numbers_from_gt(gt)

    # 리포트에서 숫자 후보 추출: 3자리 이상 또는 소수점 포함 또는 %
    candidates = re.findall(r"\d{1,3}(?:,\d{3})+|\d+\.\d+%?|\d+%", text)
    unknowns = []
    for c in candidates:
        c_clean = c.replace(",", "").replace("%", "")
        if c in gt_nums or c_clean in gt_nums:
            continue
        # 0/1/2 같은 작은 숫자는 skip
        try:
            if float(c_clean) < 10:
                continue
        except ValueError:
            continue
        unknowns.append(c)

    if unknowns:
        # 상위 3개만 보고 (너무 많으면 프롬프트 폭증)
        issues.append(f"JSON에 없는 숫자 감지: {unknowns[:5]}. 입력 JSON에 있는 숫자만 사용할 것.")

    return issues


def generate_report_with_retry(gt: dict, max_retries: int = 3) -> tuple[str | None, list[str]]:
    feedback = ""
    last_issues: list[str] = []
    for attempt in range(1, max_retries + 1):
        _log(f"Claude 분석 시도 #{attempt}")
        try:
            report = call_claude(gt, feedback)
        except Exception as e:
            _log(f"  Claude API 오류: {e}")
            last_issues = [f"Claude API 오류: {e}"]
            continue

        issues = validate(report, gt)
        if not issues:
            _log(f"  ✅ 시도 #{attempt} 통과")
            return report, []

        _log(f"  ❌ 시도 #{attempt} 검증 실패 ({len(issues)}건):")
        for i in issues:
            _log(f"     - {i}")
        last_issues = issues
        feedback = "\n".join(f"- {i}" for i in issues)

    return None, last_issues


# ============================================================
# 메인
# ============================================================

def _format_fallback(gt: dict, issues: list[str]) -> str:
    inm = gt.get("월별_재구매_매출", {}).get("통합", {})
    stage = gt.get("단계별_전환율_현재", {}).get("통합", [])
    s1_2 = next((s for s in stage if s.get("단계") == "1→2"), {})
    s2_3 = next((s for s in stage if s.get("단계") == "2→3"), {})

    lines = [
        "⚠️ 재구매 리포트 자동 분석 실패 — 원시 숫자만 전달",
        "",
        f"당월({gt.get('당월')}) 재구매 매출: {inm.get('당월', {}).get('매출')}원",
        f"전월({gt.get('전월')}) 재구매 매출: {inm.get('전월', {}).get('매출')}원",
        f"MoM 변화: {inm.get('MoM_변화_pct')}%",
        "",
        f"1→2 전환율: {s1_2.get('전환율')}% ({s1_2.get('해석')})",
        f"2→3 전환율: {s2_3.get('전환율')}% ({s2_3.get('해석')})",
        "",
        f"검증 실패 사유:",
    ]
    for i in issues[:5]:
        lines.append(f"- {i}")
    return "\n".join(lines)


def run() -> dict:
    """09:00 메인: gt 1회 계산 → 마트/대시보드 갱신 → 텔레그램 → 이메일 순 실행.

    - 일21:00 report_email_weekly.py  → 이메일 멀티 에이전트 주간 (별도 유지)
    """
    _log("=== 재구매 리포트 시작 ===")
    ss = _open_sheet()
    gt = build_ground_truth(ss)

    # 마트 4종 갱신 (Looker Studio 데이터 소스)
    try:
        _log("마트 탭 갱신 중...")
        write_marts(ss, gt, _classify_tabs(ss))
        _log("✅ 마트 탭 갱신 완료")
    except Exception as e:
        _log(f"⚠️ 마트 탭 갱신 실패: {e}")

    # 채널별 중복 탭 숨김 (첫 실행 시에만 실질적 변경, 이후는 no-op)
    try:
        _log("채널별 중복 탭 숨김 처리 중...")
        hide_redundant_tabs(ss)
    except Exception as e:
        _log(f"⚠️ 탭 숨김 실패: {e}")

    # 경영자용 대시보드 탭 갱신
    try:
        _log("대시보드 탭 갱신 중...")
        write_dashboard(ss, gt)
        _log("✅ 대시보드 탭 갱신 완료")
    except Exception as e:
        _log(f"⚠️ 대시보드 탭 갱신 실패: {e}")

    # GT 저장 (감사용)
    date_str = datetime.now(KST).strftime("%Y-%m-%d")
    gt_log = ANALYSIS_LOG_DIR / f"gt_{date_str}.json"
    gt_log.write_text(json.dumps(gt, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _log(f"ground_truth 저장: {gt_log}")

    # 텔레그램 요약 발송 (gt 재사용)
    try:
        _log("텔레그램 요약 발송 중...")
        from report_telegram_brief import build_brief
        msg = build_brief(gt)
        send_message(msg, channel="report")
        _log("✅ 텔레그램 발송 완료")
    except Exception as e:
        _log(f"⚠️ 텔레그램 발송 실패: {e}")
        try:
            send_message(f"🚨 텔레그램 요약 실패: {e}", channel="ops")
        except Exception:
            pass

    # 이메일 심층 분석 발송 (gt 재사용)
    try:
        _log("이메일 심층 분석 발송 중...")
        from report_email_daily import main as email_main
        email_main(gt=gt)
        _log("✅ 이메일 발송 완료")
    except Exception as e:
        _log(f"⚠️ 이메일 발송 실패: {e}")

    return {"status": "success", "issues": []}


if __name__ == "__main__":
    try:
        r = run()
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        sys.exit(0 if r["status"] == "success" else 1)
    except Exception as e:
        _log(f"치명적 오류: {e}")
        try:
            send_message(f"🚨 재구매 리포트 치명적 오류: {e}", channel="ops")
        except Exception:
            pass
        sys.exit(2)
```

---

### 5.2 `sheets_sync.py` (482 줄)

```python
"""재구매 분석 시트 자동 이관.

매일 08:30 실행. 카페24 + 스마트스토어 원본 탭에 최근 N일치 데이터를 덮어쓴다.
- 최근 N일 윈도우를 먼저 지우고, API에서 다시 받아와 append
- 취소/환불이 뒤늦게 반영되어도 정확히 동기화됨

.env 필요 값:
- GOOGLE_SA_KEY_PATH
- REPURCHASE_SHEET_ID
- CAFE24_*, NAVER_*, PROXY_* (기존)
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

import cafe24_client
import naver_client

KST = timezone(timedelta(hours=9))
BACKFILL_DAYS = 7  # 이 기간 내 행은 매일 지우고 다시 넣음

ENV_PATH = Path(__file__).parent / ".env"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# 탭 식별용 헤더 (첫 컬럼명)
CAFE24_HEADER_FIRST = "주문번호"
CAFE24_HEADER_SECOND = "결제일시(입금확인일)"
SS_HEADER_FIRST = "상품주문번호"


def _log(msg: str):
    print(f"[{datetime.now(KST).strftime('%H:%M:%S')}] {msg}", flush=True)


def _get_sheets_client():
    load_dotenv(ENV_PATH, override=True)
    key_path = os.getenv("GOOGLE_SA_KEY_PATH", "")

    # 1) env에 지정된 경로가 존재하면 그대로
    if key_path and Path(key_path).exists():
        pass
    else:
        # 2) 로컬 폴더에 gcp-service-account.json 있으면 폴백
        local = Path(__file__).parent / "gcp-service-account.json"
        if local.exists():
            key_path = str(local)
        else:
            raise RuntimeError(
                f"서비스 계정 키를 찾지 못했습니다. "
                f"GOOGLE_SA_KEY_PATH={key_path!r} 또는 {local} 중 하나가 필요합니다."
            )

    creds = Credentials.from_service_account_file(key_path, scopes=SCOPES)
    return gspread.authorize(creds)


def _open_sheet():
    client = _get_sheets_client()
    load_dotenv(ENV_PATH, override=True)
    sheet_id = os.getenv("REPURCHASE_SHEET_ID")
    if not sheet_id:
        raise RuntimeError("REPURCHASE_SHEET_ID 미설정")
    return client.open_by_key(sheet_id)


def _find_tab(spreadsheet, expected_first: str, expected_second: str | None = None):
    """첫 컬럼명(과 선택적으로 두 번째)으로 탭을 찾는다."""
    for ws in spreadsheet.worksheets():
        try:
            hdr = ws.row_values(1)
        except Exception:
            continue
        if not hdr:
            continue
        if hdr[0].strip() != expected_first:
            continue
        if expected_second and (len(hdr) < 2 or hdr[1].strip() != expected_second):
            continue
        return ws
    return None


# ============================================================
# 카페24
# ============================================================

def cafe24_order_to_rows(order: dict) -> list[list]:
    """카페24 order → 5컬럼 행들 (아이템 개수만큼 row 복제).

    엑셀 다운로드 포맷과 동일하게 (주문번호/결제일시/주문상태/실결제금액/주문자휴대전화).
    """
    if order.get("canceled") == "T":
        return []

    # 결제일시: paid_date 우선, 없으면 order_date
    paid = order.get("paid_date") or order.get("order_date", "")
    # ISO 8601 → "2026-01-19 23:41:59" 포맷으로 정규화
    if paid:
        paid = paid.replace("T", " ").split("+")[0].split(".")[0]

    # 주문상태: 엑셀 export와 맞추기 위해 "거래종료"로 고정
    # (취소는 위에서 걸러짐, 나머지는 모두 "거래종료"로 간주)
    status_text = "거래종료"

    amount = order.get("payment_amount") or order.get("actual_payment_amount") or 0
    try:
        amount = int(float(amount))
    except (ValueError, TypeError):
        amount = 0

    # 100% 할인 주문(결제금액 0원) → items[].price 합산으로 정가 대체
    # embed=items 이미 사용 중이므로 추가 API 호출 없음
    if amount == 0:
        fallback = 0
        for item in (order.get("items") or []):
            try:
                unit = int(float(item.get("product_price") or item.get("price") or 0))
                qty = int(item.get("quantity") or 1)
                fallback += unit * qty
            except (ValueError, TypeError):
                pass
        if fallback > 0:
            amount = fallback

    # 휴대전화: buyer 또는 billing_name 측에서 찾기
    phone = (
        order.get("buyer_cellphone")
        or order.get("billing_name_cellphone")
        or order.get("orderer_mobile")
        or order.get("mobile")
        or ""
    )
    # receivers에서도 시도 (embed된 경우)
    if not phone:
        receivers = order.get("receivers") or []
        if receivers:
            phone = receivers[0].get("cellphone", "") or ""

    items = order.get("items") or []
    n = max(len(items), 1)  # 아이템 정보 없어도 최소 1행

    row = [
        order.get("order_id", ""),
        paid,
        status_text,
        amount,
        phone,
    ]
    return [row] * n


def sync_cafe24(spreadsheet, days: int = BACKFILL_DAYS) -> int:
    """카페24 sync — cutoff 기반 행 교체 + (주문번호, 아이템번호 기준) dedupe.

    같은 주문이 옵션·수량으로 여러 행으로 분해될 수 있으므로
    (주문번호 + 결제일시 + 실결제금액) 조합 키로 시트 내 중복 제거.
    """
    ws = _find_tab(spreadsheet, CAFE24_HEADER_FIRST, CAFE24_HEADER_SECOND)
    if ws is None:
        raise RuntimeError("카페24 원본 탭을 찾지 못했습니다 (헤더 불일치)")
    _log(f"카페24 탭: {ws.title}")

    # 1) API에서 최근 days일 주문 pull
    orders = cafe24_client.fetch_orders(days_back=days + 1)
    _log(f"  카페24 API 주문 {len(orders)}건 수신")

    # 2) 5컬럼 행으로 변환
    new_rows: list[list] = []
    for o in orders:
        new_rows.extend(cafe24_order_to_rows(o))
    _log(f"  변환된 행: {len(new_rows)}")

    # 3) cutoff: 결제일시 컬럼은 "2026-04-19 18:04:28" 형식
    #   문자열 비교에서 "2026-04-19 18:04" < "2026-04-20" 이므로
    #   cutoff에 " 00:00" 같은 시간 안 붙이면 4/20 03시 행이 빠지지 않음.
    #   안전을 위해 cutoff에 " 00:00" 부착.
    cutoff_date = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    cutoff = cutoff_date + " 00:00"
    all_rows = ws.get_all_values()
    keep: list[list] = [all_rows[0]] if all_rows else []
    delete_count = 0
    for r in all_rows[1:]:
        if len(r) < 2 or not r[1]:
            keep.append(r)
            continue
        if r[1] >= cutoff:
            delete_count += 1
            continue
        keep.append(r)
    _log(f"  {cutoff} 이후 기존 행 제거: {delete_count}")

    # 4) 새 행 추가
    keep.extend(new_rows)

    # 5) (주문번호 + 결제일시 + 실결제금액) 조합 키로 시트 전체 dedupe
    #   같은 옵션·수량 분해 행은 휴대전화·금액까지 같으니 그대로 보존.
    seen = set()
    deduped = [keep[0]] if keep else []
    for r in keep[1:]:
        key = tuple(r[:5]) if len(r) >= 5 else tuple(r)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    removed_dup = len(keep) - len(deduped)
    if removed_dup > 0:
        _log(f"  완전중복 제거: {removed_dup}행")

    # 6) 시트 전체 덮어쓰기
    ws.clear()
    if deduped:
        ws.update(values=deduped, range_name="A1", value_input_option="USER_ENTERED")
    _log(f"  최종 카페24 시트 행 수: {len(deduped)-1}")
    return len(new_rows)


# ============================================================
# 스마트스토어
# ============================================================

# 46컬럼 헤더 순서 (시트와 동일)
SS_COLUMNS = [
    "상품주문번호", "주문번호", "구매확정일", "판매채널", "주문상태", "배송속성",
    "풀필먼트사(주문 기준)", "구매자명", "구매자ID", "수취인명", "발송처리일",
    "배송방법", "택배사", "송장번호", "배송완료일", "상품번호", "상품명", "상품종류",
    "반품안심케어", "멤버십N배송", "옵션정보", "옵션관리코드", "수량", "상품가격",
    "옵션가격", "최종 상품별 할인액", "최초 상품별 할인액", "판매자 부담 할인액",
    "최초 상품별 총 주문금액", "최종 상품별 총 주문금액", "판매자 상품코드",
    "판매자 내부코드1", "판매자 내부코드2", "배송비 묶음번호", "배송비 형태",
    "배송비 유형", "배송비 합계", "제주/도서 추가배송비", "배송비 할인액",
    "결제일", "결제수단", "결제위치", "네이버페이 주문관리 수수료",
    "매출연동 수수료", "정산예정금액", "판매옵션정보",
]


def _iso_to_sheet(dt_str: str) -> str:
    """ISO → 'YYYY-MM-DD HH:MM' 포맷."""
    if not dt_str:
        return ""
    s = dt_str.replace("T", " ").split("+")[0].split(".")[0]
    # 초 부분 제거
    parts = s.split(":")
    if len(parts) >= 2:
        return f"{parts[0]}:{parts[1]}"
    return s


SS_STATUS_LABEL = {
    "PAYED": "결제완료",
    "DISPATCHED": "발송처리",
    "DELIVERING": "배송중",
    "DELIVERED": "배송완료",
    "PURCHASE_DECIDED": "구매확정",
    "EXCHANGED": "교환",
    "CANCELED": "취소",
    "RETURNED": "반품",
    "CANCELED_BY_NOPAYMENT": "미결제취소",
}


def _ss_wrap_to_row(wrap: dict) -> list | None:
    """SS API wrap → 46컬럼 행.

    구매확정·결제완료·발송·배송 상태 모두 포함 (취소/반품/미결제는 제외).
    분석은 주문상태 컬럼으로 필터해서 사용.
    """
    po = wrap.get("productOrder", {}) or {}
    order = wrap.get("order", {}) or {}
    delivery = wrap.get("delivery", {}) or {}

    status = po.get("productOrderStatus", "")
    # 매출로 잡히는 유효 상태만 포함 (취소/반품/미결제 제외)
    if status not in ("PAYED", "DISPATCHED", "DELIVERING", "DELIVERED", "PURCHASE_DECIDED", "EXCHANGED"):
        return None
    status_label = SS_STATUS_LABEL.get(status, status)

    def _won(v):
        try:
            return f"₩{int(float(v)):,}" if v not in (None, "") else ""
        except (ValueError, TypeError):
            return ""

    buyer_name = order.get("ordererName", "")
    buyer_id = order.get("ordererId", "") or po.get("buyerId", "")
    recipient_name = po.get("shippingAddress", {}).get("name", "") if isinstance(po.get("shippingAddress"), dict) else ""

    row = [
        po.get("productOrderId", ""),                    # 상품주문번호
        po.get("orderId", "") or order.get("orderId", ""), # 주문번호
        _iso_to_sheet(po.get("decisionDate", "") or po.get("purchaseDecisionDate", "")),  # 구매확정일 (구매확정 상태만 채워짐)
        "스마트스토어",                                    # 판매채널
        status_label,                                       # 주문상태 (결제완료/발송처리/구매확정/...)
        po.get("shippingAttribute", "") or "",            # 배송속성
        "",                                                # 풀필먼트사
        buyer_name,                                        # 구매자명
        buyer_id,                                          # 구매자ID
        recipient_name,                                    # 수취인명
        _iso_to_sheet(delivery.get("sendDate", "")),       # 발송처리일
        "택배,등기,소포",                                   # 배송방법
        delivery.get("deliveryCompany", "") or "로젠택배",  # 택배사
        delivery.get("trackingNumber", ""),                # 송장번호
        _iso_to_sheet(delivery.get("deliveredDate", "")),  # 배송완료일
        str(po.get("productId", "")),                      # 상품번호
        po.get("productName", ""),                         # 상품명
        po.get("productClass", "") or "조합형옵션상품",      # 상품종류
        "비대상",                                          # 반품안심케어
        "비대상",                                          # 멤버십N배송
        po.get("productOption", ""),                       # 옵션정보
        "",                                                # 옵션관리코드
        po.get("quantity", 0),                             # 수량
        _won(po.get("unitPrice", 0) or po.get("productPrice", 0)),  # 상품가격
        _won(po.get("optionPrice", 0)),                    # 옵션가격
        _won(po.get("productDiscountAmount", 0)),          # 최종 상품별 할인액
        _won(po.get("initialProductDiscountAmount", 0) or po.get("productDiscountAmount", 0)),  # 최초 상품별 할인액
        _won(po.get("sellerBurdenDiscountAmount", 0)),     # 판매자 부담 할인액
        _won(po.get("initialPaymentAmount", 0) or po.get("totalPaymentAmount", 0)),  # 최초 상품별 총 주문금액
        _won(po.get("totalPaymentAmount", 0)),             # 최종 상품별 총 주문금액
        po.get("sellerProductCode", ""),                   # 판매자 상품코드
        "", "",                                             # 내부코드1, 2
        po.get("deliveryFeeGroupId", "") or "",            # 배송비 묶음번호
        "선결제",                                          # 배송비 형태
        "조건부무료",                                       # 배송비 유형
        _won(po.get("deliveryFeeAmount", 0)),              # 배송비 합계
        _won(po.get("remoteAreaDeliveryFee", 0)),          # 제주/도서 추가배송비
        _won(po.get("deliveryFeeDiscountAmount", 0)),      # 배송비 할인액
        _iso_to_sheet(order.get("paymentDate", "")),       # 결제일 (order에 위치)
        order.get("paymentMeans", "") or "",               # 결제수단 (order에 위치)
        order.get("payLocationType", "") or "",            # 결제위치 (order.payLocationType)
        _won(po.get("commissionRatePayCost", 0) or 0),     # 네이버페이 주문관리 수수료
        _won(po.get("commissionFee", 0) or po.get("salesChannelPayCommission", 0) or 0),  # 매출연동 수수료
        _won(po.get("expectedSettlementAmount", 0)),       # 정산예정금액
        "",                                                # 판매옵션정보
    ]
    # 46개 보장
    assert len(row) == len(SS_COLUMNS), f"SS row 컬럼 수 불일치: {len(row)} vs {len(SS_COLUMNS)}"
    return row


def sync_smartstore(spreadsheet, days: int = BACKFILL_DAYS) -> int:
    """스마트스토어 sync — 결제·발송·배송·구매확정 상태 모두 포함.

    24시간 윈도우 한계 우회를 위해 1일씩 잘라 호출하고 productOrderId로 dedupe.
    cutoff는 구매확정일(있으면) 또는 결제일(없으면) 기준으로 비교.
    """
    import time as _time
    ws = _find_tab(spreadsheet, SS_HEADER_FIRST)
    if ws is None:
        raise RuntimeError("스마트스토어 원본 탭을 찾지 못했습니다")
    _log(f"스마트스토어 탭: {ws.title}")

    # 구매확정 + 결제완료 + 발송처리 + 배송중 + 배송완료 모두 수집
    # (CANCELED/RETURNED는 자연스럽게 제외)
    statuses = ["PURCHASE_DECIDED", "PAYED", "DISPATCHED", "DELIVERING", "DELIVERED"]
    token = naver_client.get_access_token()
    seen: dict = {}

    for status in statuses:
        # 1일씩 잘라서 호출 (한 번에 24h 한계 + RATE_LIMIT 회피)
        for d in range(1, days + 1):
            try:
                changes = naver_client.get_changed_product_orders(
                    token, status, hours_back=d * 24
                )
            except Exception as e:
                msg = str(e)
                if "RATE_LIMIT" in msg or "429" in msg:
                    _time.sleep(5)
                    try:
                        changes = naver_client.get_changed_product_orders(
                            token, status, hours_back=d * 24
                        )
                    except Exception:
                        continue
                else:
                    continue
            for c in changes:
                pid = c.get("productOrderId")
                if pid:
                    seen[pid] = c
            _time.sleep(1.2)
        _log(f"  status={status} 누적 unique: {len(seen)}건")

    # 상세 조회 (300개씩 배치)
    ids = list(seen.keys())
    orders = naver_client.get_order_details(token, ids)
    _log(f"  SS API 상세 {len(orders)}건 수신 (최근 {days}일, 5개 상태)")

    new_rows: list[list] = []
    for w in orders:
        row = _ss_wrap_to_row(w)
        if row is not None:
            new_rows.append(row)
    _log(f"  변환된 행: {len(new_rows)}")

    # cutoff: 구매확정일(col 2) 또는 결제일(col 39) 둘 중 하나라도 cutoff 이후면 제거
    cutoff = (datetime.now(KST) - timedelta(days=days)).strftime("%Y-%m-%d")
    all_rows = ws.get_all_values()
    keep: list[list] = [all_rows[0]] if all_rows else []
    delete_count = 0
    for r in all_rows[1:]:
        decision = r[2][:10] if len(r) > 2 and r[2] else ""
        payment = r[39][:10] if len(r) > 39 and r[39] else ""
        latest = max(decision, payment)
        if latest and latest >= cutoff:
            delete_count += 1
            continue
        keep.append(r)
    _log(f"  {cutoff} 이후 기존 행 제거: {delete_count}")

    keep.extend(new_rows)

    # ⚠️ ISSUE-3 (Codex C3: medium) — 빈 pid 누적. pid="" 일 때 inner if `if pid` = False 라
    # continue 안 됨 → 매일 sync 때마다 빈 pid 행 살아남음 → 매출 이중 카운트 위험.
    # FIX: 빈 pid 행은 dedupe 전에 격리 + ops 알림 + 빈 pid 카운트 메트릭 추적.
    # productOrderId 기준 dedupe — 신규(new_rows)가 뒤에 있으니
    # 같은 pid가 있으면 *나중 행(새 정보)*을 유지
    seen_pid = set()
    deduped = []
    if keep:
        deduped.append(keep[0])  # 헤더
    for r in reversed(keep[1:]):
        pid = r[0] if r else ""
        if not pid or pid in seen_pid:
            if pid:
                continue
        seen_pid.add(pid)
        deduped.append(r)
    # reversed 순회했으니 다시 뒤집어 시간 순 복원
    deduped = [deduped[0]] + list(reversed(deduped[1:]))
    removed_dup = len(keep) - len(deduped)
    if removed_dup > 0:
        _log(f"  productOrderId 중복 제거: {removed_dup}행")

    ws.clear()
    if deduped:
        ws.update(values=deduped, range_name="A1", value_input_option="USER_ENTERED")
    _log(f"  최종 SS 시트 행 수: {len(deduped)-1}")
    return len(new_rows)


# ============================================================
# main
# ============================================================

def run() -> dict:
    _log("=== 재구매 시트 이관 시작 ===")
    ss = _open_sheet()
    _log(f"스프레드시트: {ss.title}")

    result = {"cafe24": 0, "smartstore": 0, "errors": []}

    try:
        result["cafe24"] = sync_cafe24(ss)
    except Exception as e:
        _log(f"카페24 실패: {e}")
        result["errors"].append(f"cafe24: {e}")

    try:
        result["smartstore"] = sync_smartstore(ss)
    except Exception as e:
        _log(f"스마트스토어 실패: {e}")
        result["errors"].append(f"smartstore: {e}")

    _log(f"=== 완료: 카페24 {result['cafe24']}행, SS {result['smartstore']}행 ===")
    return result


if __name__ == "__main__":
    import json
    try:
        r = run()
        print(json.dumps(r, ensure_ascii=False, indent=2))
        sys.exit(0 if not r["errors"] else 1)
    except Exception as e:
        _log(f"치명적 오류: {e}")
        sys.exit(2)
```

---

### 5.3 `lib/historical_data.py` (168 줄)

```python
"""누적 ground_truth 분석 — 시계열·WoW·YoY·이상치.

repurchase_report.py가 매일 logs/gt_YYYY-MM-DD.json에 ground_truth를 저장.
이 모듈은 그걸 읽어 비교·이상치 감지 데이터를 추가 주입한다.

원칙:
- Claude API 호출 X (모두 Python 계산)
- 실패해도 빈 dict 반환 (메인 리포트가 죽지 않게)
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
LOG_DIR = Path(__file__).parent.parent / "logs"


def load_recent_gt(days: int = 7) -> list[dict]:
    """최근 N일치 gt_*.json을 날짜 오름차순으로 반환."""
    if not LOG_DIR.exists():
        return []
    today = datetime.now(KST).date()
    out = []
    for i in range(days, 0, -1):
        d = today - timedelta(days=i)
        f = LOG_DIR / f"gt_{d.strftime('%Y-%m-%d')}.json"
        if f.exists():
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                continue
    return out


def _safe_pct(cur, prev) -> float | None:
    if cur is None or prev in (None, 0):
        return None
    try:
        return round((float(cur) - float(prev)) / float(prev) * 100, 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def compute_wow(gt: dict, history: list[dict]) -> dict:
    """이번 주 vs 지난 주 핵심 지표 비교.

    history: 최근 7일 gt 리스트.
    오늘 gt와 7일 전 gt를 비교.
    """
    if not history:
        return {}

    # 7일 전(history[0])과 오늘(gt) 비교
    prev = history[0]

    cur_inm = gt.get("월별_재구매_매출", {}).get("통합", {}).get("당월", {}) or {}
    prev_inm = prev.get("월별_재구매_매출", {}).get("통합", {}).get("당월", {}) or {}

    cur_stage = gt.get("단계별_전환율_현재", {}).get("통합") or []
    prev_stage = prev.get("단계별_전환율_현재", {}).get("통합") or []

    def _stage_rate(stages, key="1→2"):
        for s in stages:
            if s.get("단계") == key:
                return s.get("전환율")
        return None

    return {
        "기준일": prev.get("리포트_날짜"),
        "당월_매출_WoW_pct": _safe_pct(cur_inm.get("매출"), prev_inm.get("매출")),
        "재구매자수_WoW_pct": _safe_pct(cur_inm.get("재구매자수"), prev_inm.get("재구매자수")),
        "1→2전환율_WoW_pp": _delta_pp(_stage_rate(cur_stage, "1→2"), _stage_rate(prev_stage, "1→2")),
        "2→3전환율_WoW_pp": _delta_pp(_stage_rate(cur_stage, "2→3"), _stage_rate(prev_stage, "2→3")),
    }


def _delta_pp(cur, prev) -> float | None:
    if cur is None or prev is None:
        return None
    try:
        return round(float(cur) - float(prev), 2)
    except (TypeError, ValueError):
        return None


def flag_anomalies(gt: dict, history: list[dict]) -> list[dict]:
    """7일 평균 ±2σ 벗어난 지표 자동 플래그.

    history < 5개면 신뢰성 낮아 빈 리스트 반환.
    """
    if len(history) < 5:
        return []

    flags = []

    # 당월 매출 시계열
    series = []
    for h in history:
        v = h.get("월별_재구매_매출", {}).get("통합", {}).get("당월", {}).get("매출")
        if isinstance(v, (int, float)):
            series.append(float(v))
    if len(series) >= 5:
        mean = statistics.mean(series)
        sd = statistics.stdev(series) if len(series) > 1 else 0
        cur = gt.get("월별_재구매_매출", {}).get("통합", {}).get("당월", {}).get("매출")
        if isinstance(cur, (int, float)) and sd > 0:
            z = (float(cur) - mean) / sd
            if abs(z) >= 2:
                flags.append({
                    "지표": "당월 재구매 매출",
                    "현재값": cur,
                    "7일평균": round(mean, 0),
                    "z_score": round(z, 2),
                    "방향": "급등" if z > 0 else "급락",
                })

    # 1→2 전환율
    series = []
    for h in history:
        stages = h.get("단계별_전환율_현재", {}).get("통합") or []
        for s in stages:
            if s.get("단계") == "1→2" and isinstance(s.get("전환율"), (int, float)):
                series.append(float(s["전환율"]))
                break
    if len(series) >= 5:
        mean = statistics.mean(series)
        sd = statistics.stdev(series) if len(series) > 1 else 0
        cur_stages = gt.get("단계별_전환율_현재", {}).get("통합") or []
        cur = next((s.get("전환율") for s in cur_stages if s.get("단계") == "1→2"), None)
        if isinstance(cur, (int, float)) and sd > 0:
            z = (float(cur) - mean) / sd
            if abs(z) >= 2:
                flags.append({
                    "지표": "1→2 전환율",
                    "현재값": cur,
                    "7일평균": round(mean, 2),
                    "z_score": round(z, 2),
                    "방향": "개선" if z > 0 else "악화",
                })

    return flags


def enrich(gt: dict) -> dict:
    """gt를 받아 history·WoW·anomalies 추가한 enriched dict 반환.

    실패해도 원본 gt 보존하며 추가 키만 비울 수 있게.
    """
    try:
        history = load_recent_gt(days=7)
    except Exception:
        history = []

    enriched = dict(gt)
    enriched["_history_count"] = len(history)
    try:
        enriched["WoW_비교"] = compute_wow(gt, history)
    except Exception as e:
        enriched["WoW_비교"] = {"error": str(e)}
    try:
        enriched["이상치_플래그"] = flag_anomalies(gt, history)
    except Exception as e:
        enriched["이상치_플래그"] = []
    return enriched
```

---

### 5.4 `lib/kpi_cards.py` (127 줄)

```python
"""KPI 카드 HTML 생성 — 메일 본문 상단에 4지표 시각 카드.

휴대폰 첫 화면에 의사결정자가 가장 중요한 4지표를 시각적으로 한 번에 파악하도록.
"""
from __future__ import annotations


def _safe_num(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _format_money(v):
    if v is None:
        return "—"
    try:
        v = int(v)
    except (TypeError, ValueError):
        return "—"
    if v >= 100_000_000:
        return f"{v / 100_000_000:.2f}억"
    if v >= 10_000:
        return f"{v / 10_000:,.0f}만"
    return f"{v:,}원"


def _color_for(value, target: float, severity_pct: float = 20, lower_is_better: bool = False):
    """벤치 대비 색상 (배경, 보더, 글자, 라벨)."""
    if value is None:
        return ("#ecf0f1", "#95a5a6", "#7f8c8d", "—")
    diff = ((target - value) / target * 100) if not lower_is_better else ((value - target) / target * 100)
    if diff <= 0:
        return ("#eafaf1", "#27ae60", "#1e8449", "🟢")
    if diff < severity_pct:
        return ("#fef9e7", "#f39c12", "#9a7d0a", "🟡")
    return ("#fdedec", "#e74c3c", "#922b21", "🔴")


def _card(label: str, main: str, sub: str, bg: str, border: str, text: str, badge: str) -> str:
    return f"""<td style='background:{bg};border-left:4px solid {border};padding:12px;border-radius:6px;width:25%;vertical-align:top;'>
  <div style='font-size:11px;color:#666;letter-spacing:0.3px;'>{label}</div>
  <div style='font-size:18px;font-weight:bold;color:{text};margin:4px 0;'>{main} <span style='font-size:14px;'>{badge}</span></div>
  <div style='font-size:11px;color:#555;'>{sub}</div>
</td>"""


def build_kpi_cards_html(enriched: dict) -> str:
    """enriched ground truth → 4지표 KPI 카드 HTML 테이블."""
    inm = enriched.get("월별_재구매_매출", {}).get("통합", {}) or {}
    cur = inm.get("당월", {}) or {}
    mom = _safe_num(inm.get("MoM_변화_pct"))
    sales_val = _safe_num(cur.get("매출"))

    stages = enriched.get("단계별_전환율_현재", {}).get("통합") or []
    rate_1to2 = _safe_num(next((s.get("전환율") for s in stages if s.get("단계") == "1→2"), None))

    # ⚠️ ISSUE-1 (Codex C1: high) — 이메일 KPI 카드. mn[-1] = 진행 중 코호트일 가능성.
    # GT에 is_complete 메타 추가 후 완결 코호트만 [-1] 추출하도록 변경 필요.
    mn = enriched.get("M+N_리텐션_통합") or []
    m1 = _safe_num(mn[-1].get("M+1")) if mn else None

    interval = enriched.get("재구매_간격") or {}
    p50_raw = interval.get("P50") or interval.get("중앙값")
    # P50 — "15일" 같은 문자열이면 숫자만 추출
    p50_num = None
    if p50_raw:
        try:
            p50_num = float("".join(c for c in str(p50_raw) if c.isdigit() or c == "."))
        except ValueError:
            pass

    # 매출 카드 — MoM 기준 색
    if mom is None:
        sales_bg, sales_bd, sales_tx, sales_badge = "#ecf0f1", "#95a5a6", "#7f8c8d", "—"
    elif mom >= 0:
        sales_bg, sales_bd, sales_tx, sales_badge = "#eafaf1", "#27ae60", "#1e8449", "🟢"
    elif mom > -20:
        sales_bg, sales_bd, sales_tx, sales_badge = "#fef9e7", "#f39c12", "#9a7d0a", "🟡"
    else:
        sales_bg, sales_bd, sales_tx, sales_badge = "#fdedec", "#e74c3c", "#922b21", "🔴"

    sales_card = _card(
        "당월 매출",
        _format_money(sales_val),
        f"전월대비 {mom:+.2f}%" if mom is not None else "전월대비 —",
        sales_bg, sales_bd, sales_tx, sales_badge,
    )

    bg, bd, tx, badge = _color_for(rate_1to2, 30, severity_pct=15)
    conv_card = _card(
        "1→2 재구매",
        f"{rate_1to2:.2f}%" if rate_1to2 is not None else "—",
        "목표 30% (첫→두번째 구매)",
        bg, bd, tx, badge,
    )

    bg, bd, tx, badge = _color_for(m1, 20, severity_pct=15)
    m1_card = _card(
        "한달 재구매율",
        f"{m1:.2f}%" if m1 is not None else "—",
        "목표 20% (첫달 안 재구매)",
        bg, bd, tx, badge,
    )

    # P50 — 14~16일이 정상 (lower_is_better)
    if p50_num is None:
        bg, bd, tx, badge = "#ecf0f1", "#95a5a6", "#7f8c8d", "—"
    elif p50_num <= 18:
        bg, bd, tx, badge = "#eafaf1", "#27ae60", "#1e8449", "🟢"
    elif p50_num <= 25:
        bg, bd, tx, badge = "#fef9e7", "#f39c12", "#9a7d0a", "🟡"
    else:
        bg, bd, tx, badge = "#fdedec", "#e74c3c", "#922b21", "🔴"
    p50_card = _card(
        "재구매 간격",
        str(p50_raw) if p50_raw else "—",
        "절반 기준 10~16일",
        bg, bd, tx, badge,
    )

    return f"""<h2 style='color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:4px;font-size:15px;'>📌 KPI 한눈에</h2>
<table style='width:100%;border-collapse:separate;border-spacing:6px;margin:8px 0 16px 0;'>
  <tr>{sales_card}{conv_card}{m1_card}{p50_card}</tr>
</table>"""
```

---

### 5.5 `report_email_daily.py` (391 줄)

```python
"""매일 09:10 이메일 심층 분석 — 4역할 페르소나 1회 호출.

분석가 → 전략가 → 회의주의자 → 의사결정자 가 순차로 발화하는
단일 Claude 호출. 비용 효율(API 1회) + 다관점 효과.

Anthropic 401 시 fallback: 원시 숫자 표 + 안내문.
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
from lib.historical_data import enrich
from lib import recommendation_log
from lib.charts import generate_daily_charts
from lib.kpi_cards import build_kpi_cards_html
from lib.glossary import glossary_details_html

KST = timezone(timedelta(hours=9))
ENV_PATH = Path(__file__).parent / ".env"


SYSTEM_PROMPT = """당신은 HeavyLover(냉동 도시락 D2C) 재구매 지표를 분석하는 전문가다. 독자는 비전공자 창업자 1명이다.

독자 수준: 마케팅·통계 용어 모름. 숫자는 알지만 전문 해석은 낯섦.
목표: 5분 안에 읽고 오늘 뭘 해야 할지 바로 알 수 있게.

**응답은 반드시 아래 4개 블록 순서대로. 블록 사이 빈 줄 1개.**

---

## 📌 오늘의 핵심 1줄
가장 중요한 변화를 평어체 1문장으로. 숫자 포함. 전문 용어 없이.
예시: "이번 달 재구매 고객이 지난달보다 32% 줄었습니다 — 원인 확인이 필요합니다."

---

## 📊 숫자 현황
아래 4가지만, 표 없이 불릿으로 간결하게:
- 이번 달 재구매 매출: XXX만원 (지난달보다 +X% / -X%)
- 첫 구매 후 2번째 구매한 비율: X% (목표 30%)
- 첫 구매 후 한 달 안에 돌아온 고객 비율: X% (목표 20%)
- 평균 재구매 간격: X일

이상한 수치 있으면 ⚠️ 표시 후 한 줄 설명. 없으면 생략.

---

## 🤔 왜 이런 수치가 나왔을까?
이유 2~3가지를 쉬운 말로. 형식:
- **이유 1** (확실성: 높음/중간/낮음): 쉬운 설명 1~2문장. 근거 숫자 1개만.
- **이유 2** ...
마지막에 "아직 데이터가 없어서 확인 못 한 것: ..." 한 줄 추가.

---

## ✅ 오늘 할 일 1가지
구체적으로 딱 1가지. 형식:
**할 일**: (누가) (무엇을) (언제까지)
**기대 효과**: 잘 되면 어떤 숫자가 얼마나 바뀌는지
**확인 방법**: X주 후에 어떤 수치를 보면 됨
**안 되면**: 다음 대안

---

**절대 규칙**:
- 입력 JSON 숫자만 사용. 만들어내기 금지.
- 전문 용어 쓰면 즉시 괄호로 풀이. 예: 코호트(같은 달에 처음 산 고객 묶음)
- "~로 보입니다", "~일 수 있습니다", "살펴보겠습니다" 금지. 직접 말하기.
- 가설이면 "아직 확인 안 됨" 명시.
- 전체 800~1200자. 짧고 명확하게."""

USER_PROMPT_TEMPLATE = """오늘의 ground truth + 7일 누적 비교 + 이상치 플래그:

```json
{gt_json}
```

{recommendation_block}

위 4역할 형식대로 일일 심층 리포트 작성."""


def call_claude(enriched_gt: dict, rec_block: str = "") -> str | None:
    load_dotenv(ENV_PATH, override=True)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    client = Anthropic(api_key=api_key)
    gt_json = json.dumps(enriched_gt, ensure_ascii=False, indent=2, default=str)
    user = USER_PROMPT_TEMPLATE.format(gt_json=gt_json, recommendation_block=rec_block)

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=3500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"Claude API 오류: {e}")
        return None


def _md_to_html(md: str) -> str:
    """Markdown → HTML. 블록 헤더(## 📌/📊/🤔/✅)는 배경색 카드로 렌더링."""
    # 헤더별 색상
    BLOCK_COLORS = {
        "📌": ("#fff3cd", "#856404"),   # 노랑 — 핵심 1줄
        "📊": ("#e8f4f8", "#0c5460"),   # 파랑 — 숫자 현황
        "🤔": ("#f0f0f0", "#333"),       # 회색 — 이유
        "✅": ("#d4edda", "#155724"),   # 초록 — 할 일
    }
    lines = md.splitlines()
    out = []
    in_list = False
    in_table = False
    in_block = False

    def _close_block():
        nonlocal in_block
        if in_block:
            out.append("</div>")
            in_block = False

    def _bold(s):
        import re
        return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)

    for line in lines:
        s = line.rstrip()
        if s.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            if in_table:
                out.append("</table>")
                in_table = False
            _close_block()
            title = s[3:].strip()
            bg, fg = "#f8f9fa", "#2c3e50"
            for emoji, (b, f) in BLOCK_COLORS.items():
                if emoji in title:
                    bg, fg = b, f
                    break
            out.append(
                f"<div style='background:{bg};border-left:4px solid {fg};padding:14px 16px;"
                f"margin:16px 0 8px 0;border-radius:0 6px 6px 0;'>"
                f"<div style='font-size:15px;font-weight:bold;color:{fg};margin-bottom:8px;'>{title}</div>"
            )
            in_block = True
        elif s.startswith("- "):
            if not in_list:
                out.append("<ul style='margin:4px 0 4px 16px;padding:0;'>")
                in_list = True
            out.append(f"<li style='margin:4px 0;'>{_bold(s[2:].strip())}</li>")
        elif s.startswith("|") and s.endswith("|"):
            if in_list:
                out.append("</ul>")
                in_list = False
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set("-:| ") for c in cells):
                continue
            tag = "th" if not in_table else "td"
            if not in_table:
                out.append("<table style='border-collapse:collapse;margin:8px 0;width:100%;'>")
                in_table = True
            style = "border:1px solid #ddd;padding:7px 12px;background:#fff;" if tag == "td" \
                else "border:1px solid #ccc;padding:7px 12px;background:#f0f0f0;font-weight:bold;"
            cells_html = "".join(f"<{tag} style='{style}'>{c}</{tag}>" for c in cells)
            out.append(f"<tr>{cells_html}</tr>")
        elif s == "---":
            if in_list:
                out.append("</ul>")
                in_list = False
            if in_table:
                out.append("</table>")
                in_table = False
            _close_block()
        elif s == "":
            if in_list:
                out.append("</ul>")
                in_list = False
            if in_table:
                out.append("</table>")
                in_table = False
        else:
            out.append(f"<p style='margin:5px 0;'>{_bold(s)}</p>")

    if in_list:
        out.append("</ul>")
    if in_table:
        out.append("</table>")
    _close_block()
    return "\n".join(out)


def _render_charts_block(chart_cids: list[str]) -> str:
    """차트 cid 리스트를 받아 모바일/데스크톱 양쪽 호환 그리드 HTML 반환."""
    if not chart_cids:
        return ""
    cells = "".join(
        f"<td style='padding:6px;width:50%;vertical-align:top;'>"
        f"<img src='cid:{cid}' style='width:100%;max-width:380px;height:auto;display:block;border-radius:4px;'>"
        f"</td>"
        for cid in chart_cids
    )
    rows = []
    cells_per_row = 2
    chunks = [chart_cids[i:i + cells_per_row] for i in range(0, len(chart_cids), cells_per_row)]
    for chunk in chunks:
        row_cells = "".join(
            f"<td style='padding:6px;width:50%;vertical-align:top;'>"
            f"<img src='cid:{cid}' style='width:100%;max-width:380px;height:auto;display:block;border-radius:4px;'>"
            f"</td>"
            for cid in chunk
        )
        if len(chunk) < cells_per_row:
            row_cells += "<td style='width:50%;'></td>" * (cells_per_row - len(chunk))
        rows.append(f"<tr>{row_cells}</tr>")
    table = f"<table style='width:100%;border-collapse:collapse;margin:16px 0;'>{''.join(rows)}</table>"
    return f"<h2 style='color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:4px;'>📈 시각화 요약</h2>{table}"


def _wrap_html(body_html: str, gt: dict, chart_cids: list[str] | None = None) -> str:
    today = datetime.now(KST).strftime("%Y-%m-%d (%a)")
    charts_html = _render_charts_block(chart_cids or [])
    try:
        kpi_html = build_kpi_cards_html(gt)
    except Exception as e:
        print(f"KPI 카드 생성 실패: {e}")
        kpi_html = ""
    return f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'><title>HeavyLover 재구매 일일 리포트</title></head>
<body style='font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif;max-width:760px;margin:0 auto;padding:20px;color:#333;line-height:1.55;'>
<div style='background:#f8f9fa;padding:16px;border-radius:6px;margin-bottom:16px;'>
  <h1 style='margin:0 0 6px 0;color:#1a73e8;font-size:20px;'>📊 HeavyLover 재구매 일일 심층</h1>
  <div style='color:#666;font-size:13px;'>{today} · 6섹션 페르소나 분석</div>
</div>
{kpi_html}
{charts_html}
{body_html}
<hr style='margin-top:30px;'>
<div style='font-size:12px;color:#888;'>
  <p>자동 발송 · 시트: <a href='https://docs.google.com/spreadsheets/d/1DEEz2iSa_REKUsYetyZMSqZsVm6_LFbOAasrzXjYU5s'>재구매 분석시트</a></p>
  <p>리포트 위치: Vultr /root/heavylover-repurchase/ · 매일 09:10 자동</p>
</div>
</body></html>"""


def fallback_email_body(enriched_gt: dict, error_msg: str) -> tuple[str, str]:
    """Claude 401 등 실패 시 원시 숫자 표만 보내는 fallback."""
    inm = enriched_gt.get("월별_재구매_매출", {}).get("통합", {}) or {}
    cur = inm.get("당월", {}) or {}
    prev = inm.get("전월", {}) or {}
    stages = enriched_gt.get("단계별_전환율_현재", {}).get("통합") or []
    s_1to2 = next((s for s in stages if s.get("단계") == "1→2"), {})
    s_2to3 = next((s for s in stages if s.get("단계") == "2→3"), {})

    mn = enriched_gt.get("M+N_리텐션_통합") or []
    m1_recent = mn[-1].get("M+1") if mn else "—"

    flags = enriched_gt.get("이상치_플래그") or []

    text = f"""HeavyLover 재구매 일일 리포트 (fallback 모드)

⚠️ Claude 분석 실패 — 원시 숫자만 전달
{error_msg}

[당월 vs 전월]
- 당월 재구매 매출: {cur.get('매출')}
- 전월 재구매 매출: {prev.get('매출')}
- MoM: {inm.get('MoM_변화_pct')}%

[단계별 전환]
- 1→2: {s_1to2.get('전환율')}% ({s_1to2.get('해석', '')})
- 2→3: {s_2to3.get('전환율')}%

[코호트 잔존]
- 최신 M+1: {m1_recent}%

[이상치 플래그]
{json.dumps(flags, ensure_ascii=False, indent=2) if flags else "없음"}

Anthropic 결제 활성 후 자동으로 4역할 분석 재개됩니다.
"""
    html = _wrap_html(_md_to_html(text), enriched_gt)
    return text, html


def main(gt: dict | None = None) -> int:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    try:
        if gt is None:
            ss = _open_sheet()
            gt = build_ground_truth(ss)
        enriched = enrich(gt)
        rec_block = recommendation_log.format_for_prompt(days=7)

        analysis = call_claude(enriched, rec_block=rec_block)

        try:
            charts = generate_daily_charts(gt, enriched)
        except Exception as e:
            print(f"차트 생성 실패: {e}")
            charts = {}

        if analysis:
            html = _wrap_html(
                glossary_details_html() + _md_to_html(analysis),
                enriched,
                chart_cids=list(charts.keys()),
            )
            send_email(
                subject=f"📊 HeavyLover 재구매 일일 — {today}",
                text_body=analysis,
                html_body=html,
                inline_images=charts,
            )
            # 의사결정자 액션을 추출해 recommendations.jsonl에 저장
            # (간단 휴리스틱: "## 4. 의사결정자" 섹션 텍스트)
            action = ""
            if "의사결정자" in analysis:
                parts = analysis.split("의사결정자")
                if len(parts) >= 2:
                    section = parts[1].split("##")[0].strip()
                    action = section[:300]
            if action:
                recommendation_log.append(today, "daily", action)
            print(f"일일 이메일 발송 완료 ({today})")
            return 0
        else:
            # 크레딧 부족이면 ops 채널 즉시 알림
            try:
                from telegram_client import send_message as _tg
                _tg(
                    f"🚨 Anthropic 크레딧 부족 — 재구매 분석 실패\n"
                    f"console.anthropic.com → Plans & Billing → Add credits",
                    channel="ops",
                )
            except Exception:
                pass
            text, html = fallback_email_body(enriched, "Anthropic API 크레딧 부족 또는 호출 실패")
            html_with_charts = _wrap_html(
                glossary_details_html() + _md_to_html(text),
                enriched,
                chart_cids=list(charts.keys()),
            )
            send_email(
                subject=f"⚠️ HeavyLover 재구매 일일 (fallback) — {today}",
                text_body=text,
                html_body=html_with_charts,
                inline_images=charts,
            )
            print(f"일일 이메일 fallback 발송 ({today})")
            return 0
    except Exception as e:
        err = f"일일 이메일 치명적 오류: {e}"
        print(err)
        try:
            send_email(
                subject=f"🚨 HeavyLover 일일 리포트 오류 — {today}",
                text_body=err,
            )
        except Exception:
            pass
        return 2


if __name__ == "__main__":
    sys.exit(main())
```

---

## 6. 다음 코드 수정 작업 가이드

ISSUE 우선순위대로 수정 시 다음 함수·라인을 순서대로 변경 (각 단계마다 git commit 분리 권장):

### Step 1 — GT 완결 메타데이터 도입 (ISSUE-1, ISSUE-2 공통 기반)
**파일**: `repurchase_report.py`
- `build_ground_truth()` line 282-426
  → 모듈 상수 `DATA_LAG_DAYS = 7` 추가
  → 헬퍼 `_last_day_of_month()`, `_m1_completion()`, `_is_complete_30d()`, `_is_complete_60d()` 추가
- `_extract_mn()` line 209-230
  → 반환 dict에 `is_complete`, `window_end`, `observed_days` 필드 포함

### Step 2 — M+1 KPI 소비처 4곳 일괄 수정 (ISSUE-1)
모두 `mn_recent[-1]` / `mn_list[-1]` / `mn[-1]` 패턴 → `is_complete` 필터로 교체:
- `repurchase_report.py:write_marts() → mart_summary` line 556-573
- `repurchase_report.py:write_dashboard()` line 736 부근
- `repurchase_report.py:_build_action_points()` line 893-951 (m1_recent 인자 받는 곳)
- `lib/kpi_cards.py:build_kpi_cards_html()` line 62

### Step 3 — 1→2 전환율 완결 게이트 (ISSUE-2)
**파일**: `repurchase_report.py`
- `_extract_stage_flat()` line 260-279
  → 30일·60일 분리. 각각 `_is_complete_30d` / `_is_complete_60d` 게이트
  → 평균은 완결 코호트만. 미완결은 별도 "in-progress" 트렌드 표
- 영향받는 다운스트림: `mart_stage`, `write_dashboard()` 코호트 전환율 테이블, `_build_action_points()` 의 `conv_rate`

### Step 4 — SS 빈 pid 격리 (ISSUE-3)
**파일**: `sheets_sync.py`
- `sync_smartstore()` line 422-437
  → dedupe 전에 빈 pid 행 격리 + ops 알림 (sample 5행)
  → 빈 pid 카운트 메트릭으로 추적 (`logs/ss_blank_pid_count.jsonl`)

### Step 5 — validate() 동적 키워드 + fallback 로깅 (ISSUE-4)
**파일**: `repurchase_report.py`
- `validate()` line 1258-1294
  → `_required_keywords(gt)` 헬퍼 추가, GT 데이터 유무 기반 동적 키워드
  → `_log_fallback()` 로 검증 실패와 API 오류 분리 로깅 (`logs/validation_fallback.jsonl`)
- `report_email_daily.py:main()` line 310-386
  → fallback 시 이메일 제목 분리: `(검증 실패)` vs `(API 오류)`

### Step 6 — 테스트 케이스 추가
- `tests/test_completion_metadata.py` (신규)
  → 2026-05-01, 2026-05-31, 2026-06-01 KST + DATA_LAG_DAYS 경계 케이스
- `tests/test_ss_blank_pid.py` (신규)
  → 빈 productOrderId fixture → 격리 동작 검증

---

**EOF**
