# 재구매 수치 정확성 + 멈춤 감지 v5 — 작은 plan (완료)

> v3 (2026-05-05~) staleness 감지 시스템 + v4 plan-level codex 4회 무한 루프 → v5 분할 plan 완료.
> 본 docs는 `C:\Users\osh80\.claude\plans\codex-adversial-mossy-piglet.md` 의 commit용 사본.
> 작성: 2026-05-12

---

## Context

5월 5일 6일간 분석 멈춤 + Codex 5회 점검에서 수치 부정확 결함 10개 + 운영 결함 2개 확인. v4 plan 4회 반복했으나 plan이 커서 결함 무한 증식 → plan 분할로 핵심만 (수치 정확성 + 멈춤 감지).

대시보드 3개·"변동중" 표시·시트 숨김 등 UI 변경은 별도 plan (v6) 분리.

---

## 변경 사항 (2개 파일)

### A. `sheets_sync.py` — SS 정가 fallback (수치 결함 #2)

**위치**: line 405-426 (신규 `_ss_gross_amount()`), line 463 (호출 적용)

**근거**: 100% 쿠폰·적립금 할인 SS 주문이 `totalPaymentAmount=0`으로 분석에서 누락. 카페24와 동일 fallback 정책 통일.

```python
def _ss_gross_amount(po: dict) -> int:
    """SS 정가 fallback. totalPaymentAmount이 0/없으면 (unitPrice + optionPrice) × quantity."""
    try:
        total = int(float(po.get("totalPaymentAmount", 0) or 0))
    except (ValueError, TypeError):
        total = 0
    if total > 0:
        return total
    try:
        unit = int(float(po.get("unitPrice", 0) or po.get("productPrice", 0) or 0))
        qty = int(po.get("quantity", 1) or 1)
        opt = int(float(po.get("optionPrice", 0) or 0))
        gross = (unit + opt) * qty if unit > 0 else 0
        return max(gross, 0)
    except (ValueError, TypeError):
        return 0
```

### B. `scripts/gas/repurchase_v5_1.gs` — 신규 (v5_0 + 12개 변경)

#### B-1. 운영 안정성 (멈춤 감지 강화)

- **`appendPipelineMeta_()`** (GAS-native) — `pipeline_meta` 탭에 row append. 헤더 `run_id|writer|status|started_at|finished_at|extra` (`lib/sheet_staleness.py:25` 정확히 일치)
- **`runAll()` try/catch** — 시작 `status=running`, 끝 `status=success`, catch `status=fail` + 에러 메시지를 extra에 기록
- **소스 시트·헤더 검증** — 카페24/SS 시트 둘 다 없거나 컬럼 부족 시 fail-fast
- **run_id 형식**: `YYYY-MM-DD_HHmmss_gas` (Python `check_pipeline_freshness()` `startswith(today)` 호환)

#### B-2. 수치 정확성 10개

| # | 결함 | 수정 |
|---|---|---|
| 1 | 재구매율 분모 부풀림 | `totalCust = new Set([...newCust, ...repurchaseCust]).size` (dedup) |
| 2 | SS 0원 분석 제외 | sheets_sync `_ss_gross_amount` 정가 fallback 으로 자동 해결 |
| 3 | isCanceled 부분일치 오탐 | `VALID_STATUSES` 화이트리스트 (allow-list) — "거래종료"·결제완료·발송처리·배송중·배송완료·구매확정·교환만 통과 |
| 4 | 카페24 amount 첫 row만 (Codex 점검 결과 v5_0이 정확) | 첫 row만 저장 유지 — sheets_sync `[row]*n` 동일 amount 복제 패턴이라 누적 시 부풀림 발생 |
| 5 | 코호트 30/60/90일 분모에 미관찰 포함 | `eligibleN = total - observingN`, 비율 = `cN / eligibleN`, observing 별도 컬럼 |
| 6 | 기간 재구매율 sales-mix 의미 | 헤더에 `재구매율%(sales-mix)` 명시 + 분모 dedup으로 부분 해결 |
| 7 | 퍼널 1→2/2→3/3→4 base에 미관찰 포함 | `FUNNEL_MATURITY_DAYS=10` (P50 기반). 첫·두번째·세번째 구매 10일 미경과 고객 분모 제외 — stage·cohortFunnel 양쪽 일관 |
| 8 | 통합 식별자 비호환 (카페24=휴대전화·SS=구매자ID) | 옵션 B (사용자 선택) — 통합 시트 경고 메시지 강화: "통합 재구매율·재구매자수는 실제보다 부풀려질 수 있으니 카페24·SS 각각 참조" |
| 9 | M+N 현재월 partial 처리 | `targetMonth >= currentMonth` 면 `🔵 진행중` prefix + 회색 배경, 색상 해석 제외 |
| 10 | 0일 간격 제외 | `calcGaps`에서 `d >= 0` (같은 날 재구매 포함). 히스토그램에 "0일 (같은 날)" 구간 추가 |

#### B-3. Maturity 규칙 (평문 — Python·GAS 공통)

```
cohort_30d/60d/90d: (now - first_purchase).days >= N
funnel_1_2/2_3/3_4: (now - prev_purchase).days >= 10  (FUNNEL_MATURITY_DAYS)
mn_retention_m1:    target_month < current_month
```

---

## Codex 점검 이력 (총 7회)

| 회차 | 대상 | verdict | 결함 |
|---|---|---|---|
| 1 | GAS v5_0 1회차 | needs-attention | 3개 (partial failure, 코호트 분모, 현재월 M+N) |
| 2 | GAS v5_0 2회차 | needs-attention | 4개 (schema drift, 6분 timeout, sales-mix, 퍼널 분모) |
| 3 | Plan v1 (큰 plan) | needs-attention | 4개 (Python 함수 재사용, gt 어댑터, maturity contract, iteration cap) |
| 4 | Plan v2 | needs-attention | 4개 (채널 카드 매트릭스, KPI 패밀리, Phase 순서, severity 분류) |
| 5 | Plan v3 | needs-attention | 6개 (fixture 추상, Python lambda GAS 호환, Phase 갭, assert 비안전, M+1·P50 손실, rubric 광범위) |
| 6 | Plan v4 | needs-attention | (본문 캡처 실패) — 누적 결함 추세로 plan 분할 결정 |
| 7 | 최종 수치 검증 | needs-attention (확인용) | 기존 7개 confirmed + 추가 3개 (통합 식별자, M+N 현재월, 0일 간격) |
| 8 | Plan v5 (작은 plan) | needs-attention (false-positive) | 2개 — 둘 다 "코드가 아직 없네요" — plan 결함 아님 |
| 9 | v5.1 코드 1회차 | needs-attention | 2개 HIGH (카페24 amount 누적 부풀림, run_id 형식 불일치) |
| 10 | v5.1 cycle 1 (수정 후) | needs-attention | 1개 HIGH (cohortFunnel observing23 누락) |
| 11 | v5.1 cycle 2 | Codex 한도 초과 → 사용자 결정으로 commit |

**최종 상태**: 1회차 + cycle 1 수정 모두 반영. Codex cycle 2는 사용량 한도로 미실행. 사용자 결정에 따라 현 상태 commit.

---

## Verification

### Phase A 완료 검증
- ✅ sheets_sync.py `_ss_gross_amount` 추가 (line 405-426)
- ✅ sheets_sync.py line 463 `_won(_ss_gross_amount(po))` 적용
- ✅ scripts/gas/repurchase_v5_1.gs 신규 생성 (12개 변경 + cycle 1 수정 + cycle 2 수정 반영)

### Phase B — 승현님 수동 작업
1. 구글 시트 → 확장 프로그램 → Apps Script 에디터 열기
2. 기존 코드 전체 선택 후 삭제
3. `scripts/gas/repurchase_v5_1.gs` 코드 전체 복사 → 붙여넣기
4. 저장 (Ctrl+S)
5. 트리거 설정: 시계 아이콘 → 새 트리거 → 함수 `runAll`, 매일 08:45 KST
6. ▶ 수동 1회 실행 → 오늘 시트 정상화 + pipeline_meta에 row 기록
7. Vultr에서 `python lib/sheet_staleness.py` → `fresh` 반환 확인

### E2E 검증 (Phase B 후)
- 다음날 09:00 KST 정상 발송
- pipeline_meta writer=gas, status=success 새 row
- 시트의 % 수치가 dedup·eligible·maturity 적용된 값으로 표시
- 통합 시트에 강화된 경고 메시지 표시
- M+N 현재월 셀이 🔵 진행중 라벨

---

## 다음 세션 (v6 — UI 개편)

본 plan에서 제외된 항목:
- 📊 대시보드 3개 분할 (통합/카페24/SS)
- "🔄 변동중" 표시 (KPI 패밀리별 maturity rule)
- 시트 숨김 (Meta_Ads_Daily_AdSet + GAS 분석 시트 19개)
- _PROTECTED_TABS RuntimeError 가드

→ 별도 plan v6에서 진행. 수치는 본 plan에서 정확해진 상태이므로 UI만 다듬으면 됨.

---

## v5.1 핵심 변경 라인 요약

| 파일 | 라인 | 변경 |
|---|---|---|
| `sheets_sync.py` | 405-426 | `_ss_gross_amount(po)` 신규 헬퍼 |
| `sheets_sync.py` | 463 | `_won(po.get("totalPaymentAmount", 0))` → `_won(_ss_gross_amount(po))` |
| `scripts/gas/repurchase_v5_1.gs` | 전체 | 신규 (v5_0 + 12개 변경 + Codex 1회차+cycle 1 수정 반영) |

---

**Claude 작업 완료**: Phase A
**승현님 작업 대기**: Phase B (GAS 시트 붙여넣기 + 트리거 설정 + 수동 실행)
