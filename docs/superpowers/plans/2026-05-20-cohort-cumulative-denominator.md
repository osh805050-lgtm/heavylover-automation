# 재구매 코호트 분모 통일 (eligible → cumulative) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `_extract_stage_flat()` 평균 산식을 eligible-mean에서 cumulative pooled(전환수 합 / 첫구매자수 합)로 변경하고, 액션 포인트 메시지에 분모 정의를 라벨로 박제한다. 동일 cron 동작 유지 + 기존 버그(60일 base 오용) 동시 수정.

**Architecture:**
- `_extract_stage_flat()` — 30일·60일 평균을 pooled cumulative `sum(전환수) / sum(첫구매자수) * 100`로 변경. 60일 entry용 `base_60` 분리.
- `_build_action_points()` — conv_rate 출처 메시지에 "(완결 코호트 누적)" 박제 (failures.md ㊻ "라벨에 정의 명시" 회피 규칙).
- `tests/test_repurchase_report.py` — 신규 생성. `_extract_cohort_stage` mock으로 형식 검증, date 의존성은 충분히 오래된 코호트(2024)로 우회.

**Tech Stack:** Python 3.11+, pytest, unittest.mock

**Why this change (요약):**
- 현재 eligible mean: 분모(첫구매자수 - 30일 미경과 1회 구매자)가 매일 바뀜 → 같은 코호트가 시간 따라 비율 변동 → 시계열 비교·박제 불가.
- 변경 후 pooled cumulative: 분모(첫구매자수 총합) 고정 → "최근 3개월 완결 코호트 누적 전환율" 단일 정의.
- 시트 자체(코호트_*_전환율 탭)는 GAS 산출이라 변경 없음(eligible 그대로 진행 중 모니터링). Python이 만드는 액션 포인트·mart 탭·KPI 카드만 cumulative 통일.

**Out of scope (이번 plan에서 안 함):**
- 채널 대시보드 "30일/60일 내 재구매율" 표 컬럼 (시트값 그대로 표시 중 — 표는 진행중 모니터링용으로 eligible 유지)
- GAS `repurchase_v5_1.gs` 수정 (시트 자체 산식)
- M+1 코호트 시트(`코호트_월별잔존율`) 산식 (별도 정의 — 이번 작업과 무관)

---

## 변경 파일 매핑

| 파일 | 변경 | 라인 |
|---|---|---|
| `repurchase_report.py` | `_extract_stage_flat` 산식 변경 + `base_60` 분리 | 411-439 |
| `repurchase_report.py` | `_build_action_points` 라벨 박제 | 1338-1357 |
| `tests/test_repurchase_report.py` | 신규 생성 (mock 기반 단위 테스트) | 전체 |

---

## Task 1: 테스트 파일 신규 생성

**Files:**
- Create: `tests/test_repurchase_report.py`

- [ ] **Step 1: 파일 신규 작성**

```python
"""repurchase_report.py 단위 테스트 — 분모 통일(cumulative) 검증."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from repurchase_report import _extract_stage_flat, _build_action_points


# ── 공통 fixture: 충분히 오래된 코호트 (2024) — date.today() 무관하게 gate 통과 ─

def _mock_rows():
    """3개 코호트 — 30일·60일 합산 cumulative 비교용 mock 데이터.

    cumulative 30일 = (20 + 30 + 10) / (100 + 200 + 100) * 100 = 60/400 = 15.0%
    eligible-mean 30일 = (25.0 + 18.0 + 12.5) / 3 = 18.5% (기존 산식)
    → 두 값이 명확히 다름 = 산식 변경이 적용됐는지 검증 가능.

    cumulative 60일 = (30 + 40 + 30) / (100 + 200 + 100) * 100 = 100/400 = 25.0%
    eligible-mean 60일 = (35.0 + 25.0 + 40.0) / 3 = 33.33% (기존 산식)
    """
    return [
        {"코호트월": "2024-01", "첫구매자수": 100,
         "30일_전환수": 20, "30일_전환율": 25.0,
         "60일_전환수": 30, "60일_전환율": 35.0,
         "1→2_전환율": 35.0, "2→3_전환율": None},
        {"코호트월": "2024-02", "첫구매자수": 200,
         "30일_전환수": 30, "30일_전환율": 18.0,
         "60일_전환수": 40, "60일_전환율": 25.0,
         "1→2_전환율": 25.0, "2→3_전환율": None},
        {"코호트월": "2024-03", "첫구매자수": 100,
         "30일_전환수": 10, "30일_전환율": 12.5,
         "60일_전환수": 30, "60일_전환율": 40.0,
         "1→2_전환율": 40.0, "2→3_전환율": None},
    ]


# ── _extract_stage_flat cumulative 산식 검증 ────────────────────

def test_stage_flat_30day_cumulative():
    """30일 평균이 cumulative (sum/sum)이어야 한다."""
    with patch('repurchase_report._extract_cohort_stage', return_value=_mock_rows()):
        result = _extract_stage_flat(None)
    s30 = next(s for s in result if s["단계"] == "1→2_30일")
    assert s30["전환율"] == 15.0, f"expected 15.0%, got {s30['전환율']}"
    assert s30["기준고객수"] == 400
    assert s30["전환고객수"] == 60


def test_stage_flat_60day_cumulative():
    """60일 평균이 cumulative여야 한다. base_60도 last3_60 기준이어야 한다."""
    with patch('repurchase_report._extract_cohort_stage', return_value=_mock_rows()):
        result = _extract_stage_flat(None)
    s60 = next(s for s in result if s["단계"] == "1→2")
    assert s60["전환율"] == 25.0, f"expected 25.0%, got {s60['전환율']}"
    assert s60["기준고객수"] == 400
    assert s60["전환고객수"] == 100


def test_stage_flat_empty_input():
    """빈 시트 입력 시 빈 리스트 반환."""
    with patch('repurchase_report._extract_cohort_stage', return_value=[]):
        assert _extract_stage_flat(None) == []


def test_stage_flat_small_sample_excluded():
    """첫구매자수 < 5 코호트는 분모에서 제외."""
    rows = [
        {"코호트월": "2024-01", "첫구매자수": 3,  # < 5 제외
         "30일_전환수": 99, "30일_전환율": 99.0,
         "60일_전환수": 99, "60일_전환율": 99.0,
         "1→2_전환율": 99.0, "2→3_전환율": None},
        {"코호트월": "2024-02", "첫구매자수": 100,
         "30일_전환수": 20, "30일_전환율": 20.0,
         "60일_전환수": 30, "60일_전환율": 30.0,
         "1→2_전환율": 30.0, "2→3_전환율": None},
    ]
    with patch('repurchase_report._extract_cohort_stage', return_value=rows):
        result = _extract_stage_flat(None)
    s30 = next(s for s in result if s["단계"] == "1→2_30일")
    # 99% 코호트가 평균에 들어가면 cumulative ≥ 59%. 제외되면 20.0%.
    assert s30["전환율"] == 20.0


# ── _build_action_points 라벨 검증 ──────────────────────────────

def test_action_point_conv_rate_label():
    """60일 재구매율 메시지에 '(완결 코호트 누적)' 라벨이 박제돼야 한다."""
    points = _build_action_points(
        conv_rate=25.0, m1_recent=None, p50_num=None,
        mom_pct=None,
        cohort_trend={"최근3개월_평균": 25.0, "이전3개월_평균": 22.0},
    )
    msg = next((p for p in points if "60일" in p), "")
    assert "(완결 코호트 누적)" in msg, f"라벨 누락: {msg}"


def test_action_point_conv_rate_label_low():
    """conv_rate < 20% (🔴 케이스)에도 라벨 박제."""
    points = _build_action_points(
        conv_rate=15.0, m1_recent=None, p50_num=None,
        mom_pct=None, cohort_trend={},
    )
    msg = next((p for p in points if "60일" in p), "")
    assert "(완결 코호트 누적)" in msg


def test_action_point_m1_label_separate():
    """M+1 메시지와 60일 메시지는 분모가 다르므로 라벨로 구분돼야 한다."""
    points = _build_action_points(
        conv_rate=25.0, m1_recent=10.0, p50_num=None,
        mom_pct=None, cohort_trend={},
    )
    # M+1 메시지: '한 달 안' 포함, 라벨은 (M+1 코호트)
    m1_msg = next((p for p in points if "한 달 안" in p), "")
    assert "(M+1 코호트)" in m1_msg, f"M+1 라벨 누락: {m1_msg}"
    # 60일 메시지: '60일' 포함, 라벨은 (완결 코호트 누적)
    conv_msg = next((p for p in points if "60일" in p), "")
    assert "(완결 코호트 누적)" in conv_msg
```

- [ ] **Step 2: 테스트 실행하여 모두 실패 확인 (Red)**

Run:
```bash
python -m pytest tests/test_repurchase_report.py -v
```

Expected: 7개 모두 FAIL
- test_stage_flat_30day_cumulative: AssertionError (현재 18.5 반환)
- test_stage_flat_60day_cumulative: AssertionError (현재 33.33 반환)
- test_stage_flat_empty_input: PASS (이미 빈 리스트 반환)
- test_stage_flat_small_sample_excluded: 통과할 수도 있음 (현재도 ≥5 필터 있음)
- test_action_point_conv_rate_label: AssertionError (라벨 없음)
- test_action_point_conv_rate_label_low: AssertionError
- test_action_point_m1_label_separate: AssertionError

이 시점에선 일부 PASS도 정상 — 신규 검증 항목이 실패하는지가 핵심.

---

## Task 2: `_extract_stage_flat` cumulative 산식 적용

**Files:**
- Modify: `repurchase_report.py:411-439`

- [ ] **Step 1: 함수 전체 교체**

기존 코드 (411-439):
```python
    gate_30 = 30 + DATA_LAG_DAYS
    gate_60 = 60 + DATA_LAG_DAYS

    completed_30 = [r for r in rows
                    if r["30일_전환율"] is not None and r["첫구매자수"] >= 5
                    and _days_elapsed(r["코호트월"]) >= gate_30]
    completed_60 = [r for r in rows
                    if r["60일_전환율"] is not None and r["첫구매자수"] >= 5
                    and _days_elapsed(r["코호트월"]) >= gate_60]

    if not completed_30:
        return []

    last3_30 = completed_30[-3:]
    avg30 = round(sum(r["30일_전환율"] or 0 for r in last3_30) / len(last3_30), 2)
    base = sum(r["첫구매자수"] for r in last3_30)
    conv30 = sum(r["30일_전환수"] for r in last3_30)

    result = [
        {"단계": "1→2_30일", "기준고객수": base, "전환고객수": conv30, "전환율": avg30,
         "해석": f"30일 빠른 전환, 최근 3개월({last3_30[0]['코호트월']}~{last3_30[-1]['코호트월']}) 평균"},
    ]
    if completed_60:
        last3_60 = completed_60[-3:]
        avg60 = round(sum(r["60일_전환율"] or 0 for r in last3_60) / len(last3_60), 2)
        conv60 = sum(r["60일_전환수"] for r in last3_60)
        result.insert(0, {"단계": "1→2", "기준고객수": base, "전환고객수": conv60, "전환율": avg60,
                          "해석": f"60일 누적, 최근 3개월({last3_60[0]['코호트월']}~{last3_60[-1]['코호트월']}) 평균"})
    return result
```

신규 코드:
```python
    gate_30 = 30 + DATA_LAG_DAYS
    gate_60 = 60 + DATA_LAG_DAYS

    completed_30 = [r for r in rows
                    if r["30일_전환율"] is not None and r["첫구매자수"] >= 5
                    and _days_elapsed(r["코호트월"]) >= gate_30]
    completed_60 = [r for r in rows
                    if r["60일_전환율"] is not None and r["첫구매자수"] >= 5
                    and _days_elapsed(r["코호트월"]) >= gate_60]

    if not completed_30:
        return []

    # [2026-05-20] cumulative pooled — 분모 통일 (eligible → 첫구매자수 합).
    # 이유: eligible mean은 분모가 매일 바뀌어 시계열 비교·박제 불가.
    # pooled는 "최근 3개월 완결 코호트 누적 전환율" 단일 정의로 고정.
    last3_30 = completed_30[-3:]
    base_30 = sum(r["첫구매자수"] for r in last3_30)
    conv30 = sum(r["30일_전환수"] for r in last3_30)
    avg30 = round(conv30 / base_30 * 100, 2) if base_30 > 0 else 0

    result = [
        {"단계": "1→2_30일", "기준고객수": base_30, "전환고객수": conv30, "전환율": avg30,
         "해석": f"30일 누적(완결 코호트), 최근 3개월({last3_30[0]['코호트월']}~{last3_30[-1]['코호트월']})"},
    ]
    if completed_60:
        last3_60 = completed_60[-3:]
        base_60 = sum(r["첫구매자수"] for r in last3_60)
        conv60 = sum(r["60일_전환수"] for r in last3_60)
        avg60 = round(conv60 / base_60 * 100, 2) if base_60 > 0 else 0
        result.insert(0, {"단계": "1→2", "기준고객수": base_60, "전환고객수": conv60, "전환율": avg60,
                          "해석": f"60일 누적(완결 코호트), 최근 3개월({last3_60[0]['코호트월']}~{last3_60[-1]['코호트월']})"})
    return result
```

변경 요점:
- `avg30/avg60` 산식 → pooled cumulative
- `base` → `base_30`, 60일 entry에 `base_60` 분리 (기존 버그 수정)
- 해석 문자열에 "누적(완결 코호트)" 박제

- [ ] **Step 2: stage_flat 테스트 통과 확인**

Run:
```bash
python -m pytest tests/test_repurchase_report.py::test_stage_flat_30day_cumulative tests/test_repurchase_report.py::test_stage_flat_60day_cumulative tests/test_repurchase_report.py::test_stage_flat_empty_input tests/test_repurchase_report.py::test_stage_flat_small_sample_excluded -v
```

Expected: 4개 모두 PASS

---

## Task 3: `_build_action_points` 라벨 박제

**Files:**
- Modify: `repurchase_report.py:1326-1357`

- [ ] **Step 1: M+1 메시지에 라벨 추가 (line 1330-1334)**

기존:
```python
            if v < 14:
                points.append(f"🔴 첫 구매 후 한 달 안에 재구매하는 비율이 {v}%입니다. 목표(20%)에 크게 못 미칩니다. 구매 3일·10일·17일 후 리마인드 메일 검토 필요.")
            elif v < 20:
                points.append(f"🟡 첫 구매 후 한 달 안에 재구매하는 비율이 {v}%입니다. 목표(20%)에 조금 못 미칩니다. CRM 재구매 유도 메시지 강화를 검토하세요.")
            else:
                points.append(f"🟢 첫 구매 후 한 달 안에 재구매하는 비율이 {v}%로 목표(20%) 충족입니다.")
```

신규:
```python
            if v < 14:
                points.append(f"🔴 첫 구매 후 한 달 안에 재구매하는 비율이 {v}%입니다 (M+1 코호트). 목표(20%)에 크게 못 미칩니다. 구매 3일·10일·17일 후 리마인드 메일 검토 필요.")
            elif v < 20:
                points.append(f"🟡 첫 구매 후 한 달 안에 재구매하는 비율이 {v}%입니다 (M+1 코호트). 목표(20%)에 조금 못 미칩니다. CRM 재구매 유도 메시지 강화를 검토하세요.")
            else:
                points.append(f"🟢 첫 구매 후 한 달 안에 재구매하는 비율이 {v}%로 목표(20%) 충족입니다 (M+1 코호트).")
```

- [ ] **Step 2: 60일 메시지에 라벨 추가 (line 1350-1355)**

기존:
```python
            if v < 20:
                points.append(f"🔴 첫 구매 후 60일 내 재구매율이 {v}%입니다{trend_str}. 상세페이지·구매 경험을 점검하세요.")
            elif v < 30:
                points.append(f"🟡 첫 구매 후 60일 내 재구매율이 {v}%입니다{trend_str}. 개선 여지가 있습니다.")
            else:
                points.append(f"🟢 첫 구매 후 60일 내 재구매율이 {v}%입니다{trend_str}. 양호합니다.")
```

신규:
```python
            if v < 20:
                points.append(f"🔴 첫 구매 후 60일 내 재구매율이 {v}%입니다 (완결 코호트 누적){trend_str}. 상세페이지·구매 경험을 점검하세요.")
            elif v < 30:
                points.append(f"🟡 첫 구매 후 60일 내 재구매율이 {v}%입니다 (완결 코호트 누적){trend_str}. 개선 여지가 있습니다.")
            else:
                points.append(f"🟢 첫 구매 후 60일 내 재구매율이 {v}%입니다 (완결 코호트 누적){trend_str}. 양호합니다.")
```

- [ ] **Step 3: action point 테스트 통과 확인**

Run:
```bash
python -m pytest tests/test_repurchase_report.py::test_action_point_conv_rate_label tests/test_repurchase_report.py::test_action_point_conv_rate_label_low tests/test_repurchase_report.py::test_action_point_m1_label_separate -v
```

Expected: 3개 모두 PASS

---

## Task 4: 전체 회귀 검증

- [ ] **Step 1: 신규 + 기존 테스트 전체 실행**

Run:
```bash
python -m pytest tests/test_repurchase_report.py tests/test_repurchase_analysis.py -v
```

Expected:
- tests/test_repurchase_report.py: 7개 PASS
- tests/test_repurchase_analysis.py: 기존 통과 개수 그대로 (회귀 없음)

- [ ] **Step 2: ruff lint 통과 확인**

Run:
```bash
python -m ruff check repurchase_report.py tests/test_repurchase_report.py
```

Expected: "All checks passed!" 또는 변경 라인에 새 경고 없음

- [ ] **Step 3: 함수 단독 실행으로 실제 동작 점검 (선택)**

샘플 mock으로 실제 함수 호출:
```bash
python -c "
import sys
sys.path.insert(0, '.')
from unittest.mock import patch
from repurchase_report import _extract_stage_flat
mock_rows = [
    {'코호트월': '2024-01', '첫구매자수': 100, '30일_전환수': 20, '30일_전환율': 25.0, '60일_전환수': 30, '60일_전환율': 35.0, '1→2_전환율': 35.0, '2→3_전환율': None},
    {'코호트월': '2024-02', '첫구매자수': 200, '30일_전환수': 30, '30일_전환율': 18.0, '60일_전환수': 40, '60일_전환율': 25.0, '1→2_전환율': 25.0, '2→3_전환율': None},
    {'코호트월': '2024-03', '첫구매자수': 100, '30일_전환수': 10, '30일_전환율': 12.5, '60일_전환수': 30, '60일_전환율': 40.0, '1→2_전환율': 40.0, '2→3_전환율': None},
]
with patch('repurchase_report._extract_cohort_stage', return_value=mock_rows):
    print(_extract_stage_flat(None))
"
```

Expected output (요약):
- `[{'단계': '1→2', ..., '전환율': 25.0, ...}, {'단계': '1→2_30일', ..., '전환율': 15.0, ...}]`

---

## Task 5: 커밋

- [ ] **Step 1: git status 확인**

Run: `git status`

변경 파일:
- `repurchase_report.py`
- `tests/test_repurchase_report.py`
- `docs/superpowers/plans/2026-05-20-cohort-cumulative-denominator.md`

- [ ] **Step 2: 커밋 메시지 작성 + 커밋**

```bash
git add repurchase_report.py tests/test_repurchase_report.py docs/superpowers/plans/2026-05-20-cohort-cumulative-denominator.md
git commit -m "$(cat <<'EOF'
fix(repurchase): 30/60일 전환율 분모 통일 — eligible mean → cumulative pooled

문제: _extract_stage_flat() 평균이 시트의 eligible-rate(분모=total-observing)
산술평균이라 매일 분모가 바뀜 → 같은 코호트가 시간 따라 비율 변동 →
시계열 비교·박제 불가능. 2026-04 코호트 30.17%/2026-02 38.6% 등 모순 발생.

수정:
- avg30/avg60 = sum(전환수) / sum(첫구매자수) * 100 (pooled cumulative)
- base_60 분리 (기존 base가 last3_30 기준이어서 60일 entry에 불일치)
- 액션 포인트 메시지에 분모 정의 라벨 박제: "(M+1 코호트)" / "(완결 코호트 누적)"
- 해석 문자열에 "누적(완결 코호트)" 박제

영향: 통합·카페24·SS 액션 포인트, mart_stage 탭, mart_summary 탭,
채널 대시보드 KPI 카드의 전환율 값이 cumulative로 통일됨. 시트
(코호트_*_전환율 탭, GAS 산출)는 변경 없음 — eligible 그대로 진행중 모니터링.

failures.md ㊻ "라벨에 정의 명시" 회피 규칙 적용.
EOF
)"
```

- [ ] **Step 3: 커밋 성공 확인**

Run: `git log -1 --stat`

Expected: 위 커밋 단일, 변경 파일 3개

---

## Self-Review 체크리스트

### 1. Spec coverage
- [x] `_extract_stage_flat` 산식 변경 → Task 2
- [x] `_build_action_points` 라벨 박제 → Task 3
- [x] 기존 60일 base 버그 수정 → Task 2 (base_60 분리)
- [x] 회귀 없음 검증 → Task 4
- [x] 단위 테스트 → Task 1

### 2. Placeholder scan
- 모든 코드 블록 완전 (실제 코드)
- 모든 명령 실행 가능
- "TBD" / "TODO" 없음

### 3. Type consistency
- `base_30` / `base_60` 일관 사용
- `conv30` / `conv60` 일관 사용
- mock fixture key명이 `_extract_cohort_stage` 반환 형식과 일치

---

## 실행 후 후속 작업 제안 (이번 plan 범위 밖)

다음 항목은 이번 작업 완료 후 별도 plan으로 검토 가능:

1. **채널 대시보드 코호트 표 (line 1272-1281)** — `r.get("30일_전환율")` 시트값 그대로 표시 중. 컬럼 라벨에 "(변동중, 진행 코호트 포함)" 추가하면 사용자 혼동 줄어듦.
2. **GAS 시트 라벨** — `코호트_통합_전환율` 탭 헤더의 "30일 전환율(eligible)" 옆에 cumulative 컬럼 추가 검토.
3. **Looker Studio 차트 라벨** — mart_stage 변경 후 대시보드 차트 제목 점검.
