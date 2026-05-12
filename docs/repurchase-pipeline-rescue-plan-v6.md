# 재구매 시트 UI 개편 v6 (대시보드 3개 + 시트 숨김 + 변동중 표시)

> v5 (수치 정확성 + 멈춤 감지) 완료 후 분리됐던 UI 작업 3가지.
> GAS는 v5.1 그대로 사용 — 이번 plan은 Python(`repurchase_report.py` + 리포트 파일)만 수정.
> 작성: 2026-05-13
> v1 → v2: 어댑터 키·partial 60일 일관 (Codex 1회차 결함 반영)
> v2 → v3: KPI별 maturity 시그니처 분리 + pipeline_meta freshness 연동 (Codex 2회차 결함 반영)

---

## Context

**왜**:
- v5에서 의도적으로 분리 — plan 작게 만들어 codex 무한 루프 회피
- v5 작업으로 수치 정확성·멈춤 감지 잡힘
- 이번엔 시각적 정리만 — 같은 정확한 수치를 보기 편하게

**의도된 결과**:
- 시트 첫 화면 = 📊 대시보드 (통합·카페24·SS) 3개만 보임
- 나머지 분석 시트는 숨김
- 변동 가능한 수치는 시각적으로 구별 (📊 대시보드·텔레그램·이메일 모두)

**범위 외**:
- GAS 코드 수정 (v5.1 그대로 사용)
- KPI 패밀리별 maturity rule 도입 (v4에서 시도했다가 codex가 무한 루프 만들어 보류 — 단순 60일 기준만)

---

## 변경 사항 3개

### ④ 대시보드 3개 분할

**파일**: `repurchase_report.py:744+ write_dashboard()` → 함수 분할

**현재**: `📊 대시보드` 1개 (통합 데이터만)

**변경**:
```python
def _dashboard_source(gt: dict, channel: str) -> dict:
    """3개 채널 gt 구조 정규화. M+1·P50은 통합만 (채널 데이터 없음)."""
    if channel == "통합":
        return {
            "월매출": gt.get("월별_재구매_매출", {}).get("통합", {}),  # 당월/전월/MoM_변화_pct 포함
            "1_2": _stage_get(gt, "통합", "1→2"),
            "2_3": _stage_get(gt, "통합", "2→3"),
            "M1": _m1_recent(gt, "통합"),
            "P50": _p50(gt),
        }
    elif channel == "카페24":
        src = gt.get("월별_재구매_매출", {}).get("카페24", {})
        # [Codex v6 1회차] 채널 레벨은 매출·MoM_pct만 존재. 건수는 키 없음 → 제외
        return {
            "월매출": {
                "당월": {"매출": src.get("당월_매출")},
                "전월": {"매출": src.get("전월_매출")},
                "MoM_변화_pct": src.get("MoM_pct"),
            },
            "1_2": _stage_get(gt, "카페24", "1→2"),
            "2_3": _stage_get(gt, "카페24", "2→3"),
            "M1": None,   # 채널별 미계산 — "📌 통합 참조" 라벨
            "P50": None,
        }
    elif channel == "스마트스토어":
        src = gt.get("월별_재구매_매출", {}).get("스마트스토어", {})
        return {
            "월매출": {
                "당월": {"매출": src.get("당월_매출")},
                "전월": {"매출": src.get("전월_매출")},
                "MoM_변화_pct": src.get("MoM_pct"),
            },
            "1_2": _stage_get(gt, "스마트스토어", "1→2"),
            "2_3": _stage_get(gt, "스마트스토어", "2→3"),
            "M1": None,
            "P50": None,
        }

def write_dashboard_integrated(spreadsheet, source): ...
def write_dashboard_cafe24(spreadsheet, source): ...
def write_dashboard_ss(spreadsheet, source): ...
```

**3개 시트 맨 앞 배치**: index 0(통합), 1(카페24), 2(스마트스토어)

**채널별 카드 매트릭스** (Codex 1회차 결함 반영):

| 카드 | 통합 | 카페24 | SS |
|---|---|---|---|
| 재구매 매출 (당월/MoM) | ✅ | ✅ | ✅ |
| 1→2 전환율 | ✅ | ✅ | ✅ |
| M+1 리텐션 | ✅ | "📌 통합 참조" 라벨 | "📌 통합 참조" 라벨 |
| 재구매 평균 주기 (P50) | ✅ | "📌 통합 참조" 라벨 | "📌 통합 참조" 라벨 |

근거: 현재 `build_ground_truth`는 M+N·P50을 통합만 계산. 채널별 계산은 v7로 미룸.

**재사용**: `_dash_status()` (729), `_fmt_won/_fmt_pct/_fmt_delta` (799-828)

---

### ⑤ 시트 숨김 정리

**파일**: `repurchase_report.py:654-674 _REDUNDANT_TABS` 확장 + `_PROTECTED_TABS` 추가

**추가 숨김 대상**:
```python
_REDUNDANT_TABS = [
    # ... 기존 ...
    "Meta_Ads_Daily_AdSet",  # 신규 — 광고 adset 시계열, 재구매 분석 무관
    # GAS 분석 시트 19개 (📊 대시보드 3개로 충분)
    "재구매_통합_일별", "재구매_통합_주별",
    "재구매_카페24_일별", "재구매_카페24_주별",
    "재구매_SS_일별", "재구매_SS_주별",
    "코호트_통합_전환율",
    "구매횟수_퍼널_통합",  # 이미 있음
    "재구매_간격분석",
    "코호트_월별잔존율",
]
```

**보호 가드** (`assert` 대신 `RuntimeError` — Codex v4 결함 반영):
```python
_PROTECTED_TABS = {
    "pipeline_meta",
    "📊 대시보드",
    "📊 대시보드 (통합)",
    "📊 대시보드 (카페24)",
    "📊 대시보드 (스마트스토어)",
}

def hide_redundant_tabs(spreadsheet):
    overlap = _PROTECTED_TABS & set(_REDUNDANT_TABS + _MOVE_TO_BACK_TABS)
    if overlap:
        raise RuntimeError(f"보호 탭이 숨김 리스트에 포함됨: {overlap}")
    # ... 기존 로직 ...
```

---

### ⑥ "변동중" 표시 — KPI별 maturity 시그니처 분리

**🚨 Codex v6 2회차 결함 반영**: KPI마다 maturity 결정 방식이 다른데 단일 시그니처로 묶어 메타데이터 누락. KPI별 분리 + 메타데이터 명시.

**핵심 원칙**:
1. **모든 maturity 판정은 build_ground_truth가 미리 계산해서 gt에 포함**
2. 대시보드·리포트는 그저 `maturity_status` 필드만 읽음 (재계산 X)
3. 정보 부족하면 fail-closed: 보수적으로 `partial`

#### 5가지 KPI별 maturity 함수 (모두 `repurchase_report.py`)

```python
# 1) 월 매출 — pipeline_meta freshness 연동 (Codex 3회차 결함 반영: GAS freshness도 함께)
def _monthly_revenue_partial(kpi_month: str, freshness: dict) -> bool:
    """월 매출 확정 조건:
    - kpi_month < 현재월 (진행 중인 달 아님)
    - AND pipeline_meta에 kpi_month 마지막 날 + 2일 이후
          writer=sheets_sync 와 writer=gas 둘 다 success row 존재
    """
    now = datetime.now(KST)
    cur_month = now.strftime("%Y-%m")
    if kpi_month >= cur_month:
        return True  # 진행중
    required_after = _last_day_of(kpi_month) + timedelta(days=2)
    # raw 갱신 + GAS 분석 둘 다 confirmed 후 시점 이후여야 확정
    last_sync = freshness.get("sheets_sync_last_success")
    last_gas  = freshness.get("gas_last_success")
    if not last_sync or last_sync < required_after:
        return True
    if not last_gas or last_gas < required_after:
        return True
    return False

# 2) 코호트 전환율 (30/60/90일) — 코호트 첫구매월 1일 기준
def _cohort_conversion_partial(cohort_month: str, window_days: int) -> bool:
    """30/60/90일 윈도우가 다 지나야 확정."""
    now = datetime.now(KST)
    cohort_start = _first_day_of(cohort_month)  # 코호트월 1일
    cohort_end = _last_day_of(cohort_month)
    # 마지막 코호트 멤버(=cohort_end 첫구매)도 window_days 경과해야 확정
    return (now - cohort_end).days < window_days

# 3) M+1 리텐션 — 타겟 달이 진행중이면 partial
def _m1_retention_partial(cohort_month: str) -> bool:
    """M+1 = cohort_month 다음 달. 그 달이 종료 + 2일 지나야 확정."""
    now = datetime.now(KST)
    target_month = _add_months(cohort_month, 1)
    cur_month = now.strftime("%Y-%m")
    if target_month >= cur_month:
        return True  # 진행중 또는 미래
    required_after = _last_day_of(target_month) + timedelta(days=2)
    return now < required_after

# 4) P50 재구매 간격 — Codex 3회차 결함 반영: latest_sample_date 시트에 없음
#    P50 maturity 제외 (단순 처리). P50은 30일 표본 합산이라 변동성 작음.
#    sample_count < 30 일 때만 partial 표시 (간단 가드).
def _p50_partial(sample_count: int) -> bool:
    """P50 확정 조건: 표본 >= 30. latest_sample_date 시트에 없으므로 시간 기반 판정 보류."""
    return sample_count < 30

# 5) 단계별 전환율 (funnel stage) — aggregate stage는 row가 의존하는
#    가장 최근 코호트 기준. build_ground_truth가 이 메타데이터를 stage row에 embed.
def _stage_partial(latest_cohort_month: str) -> bool:
    """1→2/2→3/3→4 stage aggregate가 의존하는 최근 코호트가
    60일 안 지났으면 partial (재구매 기회 부족 코호트가 분모에 포함)."""
    now = datetime.now(KST)
    if not latest_cohort_month:
        return True  # 메타데이터 없으면 fail-closed
    cohort_end = _last_day_of(latest_cohort_month)
    return (now - cohort_end).days < 60
```

#### build_ground_truth 변경 (gt에 maturity_status 미리 포함)

```python
# build_ground_truth 내부에서 각 KPI에 maturity_status 계산해서 추가
gt["월별_재구매_매출"]["통합"]["당월"]["maturity_status"] = (
    "partial" if _monthly_revenue_partial(...) else "confirmed"
)
gt["단계별_전환율_현재"]["통합"][0]["maturity_status"] = (
    "partial" if _stage_partial(latest_cohort_month) else "confirmed"
)
gt["재구매_간격"]["maturity_status"] = (
    "partial" if _p50_partial(sample_count, latest_date) else "confirmed"
)
# ... M+1, 코호트 등 동일 패턴
```

#### pipeline_meta freshness 추출

```python
def _get_pipeline_freshness(spreadsheet) -> dict:
    """pipeline_meta 탭에서 writer=sheets_sync 최근 success row 가져옴.
    월 매출 확정 판정에 사용."""
    try:
        ws = spreadsheet.worksheet("pipeline_meta")
        rows = ws.get_all_values()[1:]  # 헤더 제외
        sync_success = [r for r in rows if r[1] == "sheets_sync" and r[2] == "success"]
        if not sync_success:
            return {}
        latest = sync_success[-1]
        return {"last_success_at": datetime.fromisoformat(latest[4])}  # finished_at
    except Exception:
        return {}
```

#### 대시보드 표시

- `maturity_status == "partial"` 셀에 `🔄 변동중` prefix + 회색 폰트
- 변동중 셀에는 setNumberFormat 적용 X (문자열 prefix 보존)

#### 리포트 적용

- `report_telegram_brief.py`: 변동중 수치 `[참고용]` prefix
- `report_email_daily.py`: 의사결정 권고 섹션 — `maturity_status == "confirmed"`만 사용. 그 외는 "확정 후 재평가" 코멘트 또는 제외

**대시보드 적용**:
- 변동 가능 셀에 `🔄 변동중` prefix
- 회색 폰트 (FormatRules 추가)

**리포트 적용**:
- `report_telegram_brief.py`: 변동중 수치는 `[참고용]` prefix
- `report_email_daily.py`: 의사결정 권고 섹션에서 변동중 수치 제외 또는 "확정 후 재평가" 명시

---

## 작업 순서 (병렬·순차 충돌 분석)

```
[Phase A — 병렬 OK, 충돌 없음]
  A1. ⑤ _REDUNDANT_TABS 확장 + _PROTECTED_TABS RuntimeError 가드
       (repurchase_report.py:654-720 영역만)
  A2. ⑥-1 텔레그램 변동중 표시
       (report_telegram_brief.py)
  A3. ⑥-2 이메일 변동중 표시 + 의사결정 제외
       (report_email_daily.py)

[Phase B — 순차 (같은 함수 영역)]
  B1. ④-1 _dashboard_source(gt, channel) 어댑터 추가
       (repurchase_report.py:744 직전)
  B2. ④-2 write_dashboard 3분할
       (B1 의존)
  B3. ⑥-3 대시보드 변동중 표시 추가
       (B2 의존)

[Phase C]
  C1. Codex adversarial 1회 점검
  C2. HIGH/CRITICAL 발견 시 수정 (cap 1회 — v5 무한 루프 학습)
  C3. 통과 후 commit
```

**병렬 충돌 분석**:
- A1 (line 654-720) vs B1-B3 (line 744+) — 같은 파일이지만 라인 영역 다름 → 병렬 안전
- A2·A3는 별도 파일 → 완전 독립

---

## 수정 파일

| 파일 | 변경 |
|---|---|
| `repurchase_report.py` | `_REDUNDANT_TABS` 확장, `_PROTECTED_TABS` RuntimeError, `_dashboard_source` 어댑터, `write_dashboard` 3분할, 변동중 prefix |
| `report_telegram_brief.py` | 변동중 수치 `[참고용]` prefix |
| `report_email_daily.py` | 변동중 수치 prefix + 의사결정 권고 섹션 제외 |
| `docs/repurchase-pipeline-rescue-plan-v6.md` | 본 plan (작성됨) |

---

## 재사용 기존 코드

| 패턴 | 위치 |
|---|---|
| `_dash_status()` | `repurchase_report.py:729` |
| `_fmt_won/_fmt_pct/_fmt_delta` | `repurchase_report.py:799-828` |
| `hide_redundant_tabs()` 로직 | `repurchase_report.py:683` — 리스트만 확장 |
| 시트 맨 앞 배치 batch_update | `repurchase_report.py:758-763` |
| GAS의 `⏳/✅/🔵` 컨벤션 | `repurchase_v5_1.gs` — 표시 일관성 유지 |

---

## Codex 점검 정책 (무한 루프 차단)

**iteration cap**: 1회 remediation (총 2회 점검)
**block 기준**: HIGH/CRITICAL만 — MEDIUM/LOW는 residual-risk로 진행
**자동 HIGH 카테고리**: schema drift / wrong denominator / metric corruption / irreversible damage / data loss
**cap 도달 시**: 사용자 결정 (수용 vs 추가 작업 분리)

---

## Verification

### Phase A·B acceptance
1. **시트 숨김**: 구글 시트 진입 시 `Meta_Ads_Daily_AdSet`·GAS 분석 시트 19개 숨김. 보이는 탭은 `📊 대시보드 (통합/카페24/SS)` + `pipeline_meta` + raw 시트(맨 뒤 숨김)
2. **`_PROTECTED_TABS` 가드**: 보호 탭이 숨김 리스트에 들어가면 RuntimeError 발생 (단위 검증)
3. **3개 대시보드**: index 0/1/2 순서 + 각 채널 데이터 정상 표시
4. **카페24/SS 대시보드의 M+1·P50 칸**: "📌 통합 대시보드 참조" 라벨 (None을 0으로 오인 X)
5. **변동중 표시**: 5월 매출·5월 코호트·4월 M+1이 `🔄 변동중` prefix + 회색 폰트
6. **텔레그램**: 변동중 수치에 `[참고용]` 표시
7. **이메일 의사결정 권고**: 변동중 수치 제외 또는 "확정 후 재평가"

### Codex
8. **HIGH/CRITICAL 0건** 통과

### E2E (commit 후)
9. GitHub push → Vultr 자동 배포 → 내일 09:00 cron 실행 시 대시보드 3개 + 변동중 표시 적용
10. `python repurchase_report.py` 수동 실행 시 즉시 확인 가능

---

## 사용자 작업 (이번엔 거의 없음)

- ❌ GAS 변경 없음 (v5.1 그대로 사용)
- ✅ Python은 GitHub push → Vultr 자동 배포 (사용자 무작업)
- ✅ 내일 09:00 cron 또는 사용자가 즉시 보고 싶으면 Vultr에서 `python repurchase_report.py`

---

**Claude 작업**: Phase A (병렬) + Phase B (순차) + Phase C (Codex 점검)
**승현님 작업**: 거의 없음 (자동 배포)
