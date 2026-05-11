# 메타 광고 자동화 + 재구매 cron 통합 수리 플랜 v2

**작성일**: 2026-05-11 → 2026-05-12 (v1 → v2: codex adversarial 점검 결과 반영)
**대상 저장소**: `c:\Users\osh80\OneDrive\바탕 화면\heavylover-automation`
**원본 위치**: `C:\Users\osh80\.claude\plans\drifting-jingling-rocket.md`

---

## 회피 규칙(patterns.md)이란

CLAUDE.md §0에 박힌 운영 원칙입니다. 핵심 구조:

- **`docs/lessons/failures.md`** — 과거 실수 시간순 로그 (1회 실수 = 1줄 박제)
- **`docs/lessons/patterns.md`** — 같은 실수 재발 방지용 **작업 종류별 회피 규칙**

`patterns.md`는 10개 카테고리(§자동화점검, §외부API다루기, §시간중복처리, §환경컨텍스트, …)로 나뉘어 있고, 작업 시작 전 매칭표로 해당 카테고리를 먼저 읽어 사고를 차단합니다.

**이번 사건과 직접 연관된 카테고리**:
- §외부API다루기 8번 규칙 (이미 박제됨): *"외부 API 첫 응답에서 통화·시간대·단위 즉시 확인. KRW 외 계정이면 환산 함수를 단가성 필드에 일관 적용 — 환율은 변동값 안 쓰고 고정 상수(`CURRENCY_KRW_PER_USD`)로 단일 출처 관리."*
- §자동화점검 4번 규칙 (이미 박제됨): *"배포 상태는 문서가 아니라 실측. `crontab -l`로 1차 검증."*

→ 규칙은 이미 있었는데 **weekly 리포트 작성 시 follow가 안 됐다**. v2에선 규칙을 모듈 단위로 강제(공용 모듈로 환산 단일 출처 고정 + pytest로 단위 고정)합니다.

---

## Context (왜 변경하는가)

승현님이 2026-05-11 신고한 자동화 장애 3건을 v1 플랜으로 묶었지만, codex adversarial 점검에서 **P0 3건 + P1 5건**이 발견됨.

### codex 발견 핵심 결함 (v2에서 모두 차단)

| 결함 | 위험도 | v1의 문제 | v2 차단 방식 |
|---|---|---|---|
| `meta_ads_weekly_report.py` ↔ `meta_ads_report.py` 순환 import | **P0** | v1: weekly에서 report를 import. 그런데 report:38이 이미 weekly를 import 중 → 추가 시 즉시 죽음 | 공용 모듈 `lib/meta_currency.py` 신설, 양쪽이 거기서 import |
| 환산 이중 적용 → ×1450² 폭주 | **P0** | v1: `summarize_row` + `aggregate_totals` 양쪽에 환산 추가 | 환산 책임을 `summarize_row` **단일 진입점**으로 고정. `aggregate_totals(rows_summary)`는 합산만 (이미 그렇게 설계됨 — 라인 392-402 확인) |
| dry-run이 실제 메일 발송 | **P0** | v1: `SEND_EMAIL=0` 설정만 안내. 코드는 해당 분기 없음 (line 648에서 직접 호출) | **코드부터** `SEND_EMAIL=0` / `--dry-run` 분기 구현 후 검증 |
| current/previous 비대칭 환산 | P1 | v1: 환산 위치 모호 | `summarize_row` 단일 적용 시 `build_comparison`이 이미 summarize 결과를 받음(602-605) → 자동 대칭 |
| daily helper(`_build_kpi_cards`) ctx 시그니처 불일치 | P1 | v1: 그대로 import 가정 | weekly 전용 어댑터 함수로 ctx 재조립 (`metrics`, `static_benchmark_2026_kr_food`, `auto_flags`, `funnel_today` 키 맞춤) |
| patterns.md 보강 누락 | P1 | v1: failures.md만 박제 | §외부API다루기 + §자동화점검에 weekly 환산 회피 규칙 명시 추가 |
| 단위 테스트 부재 | P1 | v1: 수동 dry-run만 | `tests/test_meta_ads_weekly_report.py` 신설 |
| rollback 절차 부재 | P1 | v1: 없음 | git revert + 이전 SHA workflow_dispatch 재배포 절차 명시 |

---

## 변경 범위 (6단계)

### Step 0 — 공용 모듈 신설 (선결조건, 순환 import 차단)

**신규 파일**: `lib/meta_currency.py`

이전 대상 함수 (모두 `meta_ads_report.py`에서 이동):
- `CURRENCY_KRW_PER_USD` 상수 (line 68)
- `CURRENCY_FIELDS_USD` 상수 (line 69)
- `_check_account_currency()` (line 79-87)
- `_to_krw()` (line 90-99)
- `convert_metrics_to_krw()` (line 102-108)
- `_compare()` (line 145-168)

**이전 후**:
- `meta_ads_report.py`: `from lib.meta_currency import _to_krw, ...`
- `meta_ads_weekly_report.py`: 같은 import 추가
- `meta_ads_yearly_backfill.py:37-70`도 같은 패턴 → import 경로 교체

→ 순환 import 차단 + 환산 단일 출처 확정.

### Step 1 — dry-run 분기 코드 먼저 구현 (검증 안전장치)

**파일**: `meta_ads_weekly_report.py`

- `run()` 함수 (586라인) 상단:
  ```python
  DRY_RUN = os.getenv("META_WEEKLY_DRY_RUN") == "1"
  ```
- 648라인 `email_sender.send_email(...)` 직전:
  ```python
  if DRY_RUN:
      Path("dry_run_weekly.html").write_text(html, encoding="utf-8")
      print("[DRY RUN] HTML 저장: dry_run_weekly.html")
      return
  ```

### Step 2 — 환산 단일 진입점 적용 (P0 이중환산 차단)

**파일**: `meta_ads_weekly_report.py` `summarize_row()` (66-99라인)

- `_check_account_currency()` 모듈 상단 호출 (run 진입 시 1회)
- `summarize_row()` 진입 직후 raw에서 spend, purchase_value 추출 → `_to_krw()` 적용 → 그 환산값으로 CPA·ROAS 재계산

**건드리지 말 것**:
- `aggregate_totals()` (392-413라인) — summarize_row 결과 합산만. 환산 추가 금지.
- `build_comparison()` (122-158라인) — summarize_row 결과 받음. 자동 대칭.

### Step 3 — 주간 리포트 섹션 보강 (weekly 어댑터 방식)

**파일**: `meta_ads_weekly_report.py` `render_html()` (179-337라인)

daily helper를 **직접 import 하지 않고** weekly 전용 어댑터 함수로 ctx 재조립:

```python
def _build_weekly_ctx(totals, comparison, campaigns):
    return {
        "metrics": totals["current"],
        "static_benchmark_2026_kr_food": {...},
        "auto_flags": _build_weekly_flags(totals),
        "funnel_today": None,
        "campaigns_today": campaigns,
        "self_benchmark_30d": None,
    }
```

추가 섹션:
- **KPI 카드 4종** (지출/구매/ROAS/CPA)
- **자동 플래그 박스** (ROAS<2.8, CPA>30000, freq>4)
- **벤치마크 판정 열** (캠페인 표에 `_compare()` 결과)
- **절대값 + 변동률 듀얼 표시** ("이전 28,400원 → 이번 26,100원 (-8.1%)")

차트 PNG: **out of scope** (후속 작업).

### Step 4 — workflow에서 토큰 갱신 step 삭제

**파일 1**: `.github/workflows/meta-ads-weekly.yml` 59-70라인 step 삭제.
**파일 2**: `refresh_meta_token.py` docstring 1줄 추가:
```python
"""⚠️ 2026-05-11 비활성: System User Token(무기한) 사용 중. 정책 변경으로 만료 토큰 복귀 시만 재활성."""
```

### Step 5 — 학습 박제

**파일 1**: `docs/lessons/failures.md` 상단 3줄 (주간 환산 누락 / 토큰 step 미제거 / cron 중복).
**파일 2**: `docs/lessons/patterns.md`:
- §외부API다루기 9번: 신규 리포트 작성 시 `lib.meta_currency`에서 import. 자체 구현 금지.
- §자동화점검 5번: 인증 메커니즘 변경 시 갱신 cron·workflow step 동시 제거.

### Step 6 — 단위 테스트 신설

**신규 파일**: `tests/test_meta_ads_weekly_report.py` (4 케이스)

1. `summarize_row` USD 샘플 → spend ×1450, purchase_value ×1450, ROAS 불변
2. `aggregate_totals` 합산만 — 이중 환산 없음 fixture 검증
3. `build_comparison` 대칭성 — 동일 USD raw → 변동률 0%
4. `_build_weekly_ctx` 어댑터 — 키 6개 존재, `funnel_today=None` silent failure 없음

---

## 변경할 파일 일람

| 파일 | 변경 유형 | 단계 |
|---|---|---|
| `lib/meta_currency.py` | 신규 | Step 0 |
| `meta_ads_report.py` | import 경로 교체, 함수 삭제 | Step 0 |
| `meta_ads_yearly_backfill.py` | import 경로 교체 | Step 0 |
| `meta_ads_weekly_report.py` | dry-run + 환산 + 어댑터 + 섹션 | Step 1~3 |
| `.github/workflows/meta-ads-weekly.yml` | step 삭제 | Step 4 |
| `refresh_meta_token.py` | docstring 1줄 | Step 4 |
| `docs/lessons/failures.md` | 3줄 박제 | Step 5 |
| `docs/lessons/patterns.md` | 카테고리 2건 보강 | Step 5 |
| `tests/test_meta_ads_weekly_report.py` | 신규 4 케이스 | Step 6 |

---

## 재사용 코드 (새로 만들지 말 것)

- 환산 패턴: `meta_ads_yearly_backfill.py:37-70`
- 통화 가드 호출: `meta_ads_report.py:104`
- 비교 출력: `meta_ads_report.py:145-168` `_compare()`
- `_to_float`: `meta_ads_weekly_report.py` 기존 export

---

## 검증 절차

1. **단위 테스트**: `python -m pytest tests/test_meta_ads_weekly_report.py -v` → 4 PASS
2. **로컬 dry-run**: `$env:META_WEEKLY_DRY_RUN="1"; python meta_ads_weekly_report.py` → `dry_run_weekly.html` 시각 검증
3. **API 통화 실측**: spend × Meta 비즈니스 관리자 지출 1450배 차이 확인
4. **workflow_dispatch**: Actions Manual trigger → refresh step 부재 + artifact 검증
5. **재구매 cron**: 승현님 SSH 출력 공유 → 중복 줄 지목 → 백업 후 dedupe

---

## Rollback 절차

1. Actions에서 `meta-ads-weekly.yml` disable
2. `git revert <merge-commit>` → main push
3. 이전 SHA workflow_dispatch 재실행
4. 필요 시 v1 코드로 수동 발송
5. failures.md 1줄 박제

---

## 머지 정책

- main 직접 push 금지. PR 생성.
- 자동 배포: `deploy-vultr.yml`이 `*.py` push에 반응. weekly는 Actions 직접 실행이라 deploy 불필요.
- 다음 cron 자동 실행: 2026-05-17(일) 23:00 UTC = 2026-05-18(월) 08:00 KST. 그 전 workflow_dispatch로 검증 완료.

---

## 실행 순서 — 병렬 처리 맵

### Wave 1 (병렬 3 jobs) — 상호 독립

| Job | 작업 | 변경 파일 |
|---|---|---|
| **W1-A** | 공용 환산 모듈 신설 | `lib/meta_currency.py` (신규) |
| **W1-B** | workflow 토큰 step 삭제 + docstring | `.github/workflows/meta-ads-weekly.yml`, `refresh_meta_token.py` |
| **W1-C** | 학습 박제 | `docs/lessons/failures.md`, `docs/lessons/patterns.md` |

### Wave 2 (병렬 3 jobs) — Wave 1-A 완료 후

| Job | 작업 | 변경 파일 |
|---|---|---|
| **W2-D** | import 경로 교체 | `meta_ads_report.py`, `meta_ads_yearly_backfill.py` |
| **W2-E** | weekly 본체 수정 | `meta_ads_weekly_report.py` |
| **W2-F** | 단위 테스트 신설 | `tests/test_meta_ads_weekly_report.py` (신규) |

### Wave 3 (직렬) — 통합 검증
pytest → dry-run → API 통화 가드

### Wave 4 (직렬) — PR + 원격 검증
git commit/push → PR → workflow_dispatch → artifact 검증

### Wave 5 (필수) — 최종 codex adversarial
PR diff 전체 + 신규 파일 + 테스트 codex로 재점검. P0/P1 신규 시 머지 보류.

### Wave 6 (별도) — 재구매 cron 정리
승현님 SSH 즉시 진행.

---

## 소요 추정 / 정지 조건

총 90분 (병렬화로 v1 대비 40% 단축).

정지 조건:
- 다른 모듈에서 `meta_ads_report._to_krw` 직접 import 발견
- summarize_row 환산이 `_to_float` 흐름과 충돌
- dry-run KRW 결과가 Meta 실측과 ±5% 이상 괴리
- workflow_dispatch artifact 미생성
- Wave 5 codex P0/P1 신규 지적 → v3 수립
- codex 점검 중 응답 멈춤 → 즉시 보고
