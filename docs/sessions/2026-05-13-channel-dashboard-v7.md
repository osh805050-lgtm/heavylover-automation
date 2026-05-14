# 2026-05-13 세션 — 채널 대시보드 v7 + Codex 결함 수정 + P50 1→2 + 텔레그램 중복 차단

> 약 5시간 세션. 재구매 분석 시스템 4가지 사고 발견 → 모두 수정 + 박제.

---

## 작업 결과 요약

| 작업 | 커밋 | 상태 |
|---|---|---|
| v5.1.1 — GAS `VALID_STATUSES` 화이트리스트 silent drop 차단 (블랙리스트 회귀) | 3476a8b | ✅ |
| deploy-vultr.yml — /root/heavylover-repurchase 폴더 자동 pull 추가 | 9364338 | ✅ |
| v6 강제 deploy + Vultr Python 수동 실행 (대시보드 3개 + 시트 숨김) | (수동) | ✅ |
| v7 — 채널 대시보드 통합 4섹션 동일 구조 + Codex HIGH 2 + MED 1 | 8ae658e | ✅ |
| P50 1→2 첫 재구매 전용 지표 신설 + 라벨 명시 | dd6b658 | ✅ |
| 09:00 텔레그램 중복 발송 차단 (09:05 cron 단독) | ee3ac23 | ✅ |
| CLAUDE.md §0 §시트status분류 + §plan점검 안전규칙 추가 | f446fe2 | ✅ |
| patterns.md §시트status분류 신설 | f446fe2 | ✅ |
| failures.md ㊷ ㊸ ㊺ ㊻ ㊼ — 5건 박제 | (multiple) | ✅ |

---

## 사고 1: 카페24 첫구매자 99% silent drop (㊷)

**증상**: 2026-03 카페24 코호트 첫구매자 = 1명. raw 데이터는 200건+.

**원인**: GAS v5.1에서 `VALID_STATUSES` 화이트리스트로 바꿈. sheets_sync.py:244 코멘트가 "거래종료 고정"이라 명시했으나 실제 시트 raw 값은 "배송 완료"(공백 포함)·"배송중"·"취소 완료"·"입금전 취소 - 관리자". 화이트리스트와 불일치 → 99% silent drop.

**수정**: v5.1.1 — 블랙리스트 회귀 (`isCanceledStatus_` 정규화 + 취소/환불/반품 부분일치 제외).

**박제**: failures.md ㊷, patterns.md §시트status분류 신설.

---

## 사고 2: deploy-vultr.yml 폴더 미동기화 (㊸)

**증상**: GAS v5.1.1 + Python v6 push 후 09:00 cron이 옛 코드로 실행. 통합 대시보드 1개만 + 시트 숨김 안 됨.

**원인**: deploy-vultr.yml이 `/root/heavylover-automation`만 git pull. 재구매 분석은 `/root/heavylover-repurchase` 별도 폴더 → 자동 배포 대상 아니었음. 5/8 commit (94d4b11)에 멈춤.

**수정**: deploy-vultr.yml SSH script에 for 루프로 두 폴더 모두 fetch+reset.

**박제**: failures.md ㊸.

---

## 사고 3: v6 채널 대시보드 정보 빈약 (㊺)

**증상**: 카페24/SS 대시보드가 빈 행 4개 ("통합 대시보드 참조" 3 + "측정 예정" 1). 사용자 표현 "디자인 최악".

**원인**: v6 도입 시 채널별 M+N 리텐션·P50 데이터 미구축. 시각 검증 없이 commit.

**수정 (v7)**:
- 채널 대시보드 = 통합과 동일 4섹션 (KPI 3개 + 월별 추이 6개월 + 코호트 전환율 6개월 + M+N 3코호트)
- 판정 컬럼 제거 (채널만)
- 명시 픽셀 열 너비 (글씨 잘림 방지)
- GAS `writeMonthlyRetentionSheet` 채널별 3회 호출 → 신규 시트 3개 (`코호트_통합/카페24/SS_월별잔존율`)
- `markLegacyMonthlyRet_()` legacy 시트 데이터 보존 + DEPRECATED 라벨

**Plan adversarial review 2회 + Codex adversarial review 1회**:
- 1회차: CRITICAL 3 + HIGH 5 + MEDIUM 6
- 2회차: CRITICAL 2 + HIGH 3 + MEDIUM 4 (1회차 박제 사항 보강 + Out of Scope 확장)
- Codex: HIGH 2 + MED 1 → 모두 수정 (legacy clear() 제거, partial 마커 보존, KPI 색상 위치)

**박제**: failures.md ㊺.

---

## 사고 4: P50 라벨 정의 불명 (㊻)

**증상**: 통합 대시보드 "재구매 평균 주기 15일" — §4 박제 P50 10일과 다름.

**원인**: GAS `calcGaps`는 모든 인접 재구매 간격(1→2 + 2→3 + 3→4) mix. §4의 10일은 1→2 첫 재구매만. 같은 라벨인데 정의가 다름 → CRM 발송 타이밍 잡기 모호.

**수정**:
- GAS `calcFirstRepurchaseGaps()` 신규 — 1→2 첫 재구매만 추출
- `writeIntervalSheet` summaryRows 11행으로 확장 (1→2 전용 P50/P75/P90/샘플수 최상단 노란색 강조 + 기존 전체 인접 P50/P75/P90 참고용 유지)
- Python `_extract_interval_stats`에 `P50_1to2` 등 신규 키 추출
- 통합 대시보드 KPI 카드 P50 → `P50_1to2` 우선 사용, 라벨 "재구매 평균 주기 (1→2 첫 재구매)"

**실측 결과**: P50_1to2 = 15일, P50 전체 = 15일 (우연히 같음). §4 10일과 차이는 시점 차 (4/29 분석 → 5/13 +14일치 데이터).

**박제**: failures.md ㊻.

---

## 사고 5: 텔레그램 중복 발송 (㊼)

**증상**: 매일 똑같은 재구매 알림 2건씩 (5분 차).

**원인**:
- 09:00 `repurchase_report.py`가 `build_brief()` 호출 → 발송
- 09:05 `report_telegram_brief.py`도 `build_brief()` 호출 → 또 발송
- 같은 함수, 같은 내용

**수정**: repurchase_report.py main() 텔레그램 발송 블록 제거. 09:05 cron 단독.

**박제**: failures.md ㊼.

---

## CLAUDE.md / patterns.md 갱신

- §0 안전규칙: `§시트status분류`, `§plan점검`, `§비율지표분모` 3개 추가
- patterns.md `§시트status분류` 신설 — 시트 raw STATUS 분류 시 직접 sampling + 블랙리스트 선호 규칙
- patterns.md `§plan점검` 신설 — plan adversarial codex review 최대 2회 + 결함 늘면 즉시 중단
- patterns.md `§비율지표분모` 신설 — dedup·observing 제외·maturity window 3가지 필수

---

## 사용자 작업 (이번 세션 수동)

| 작업 | 횟수 | 비고 |
|---|---|---|
| GAS Apps Script 재붙여넣기 | 2회 | v5.1.1 1회 + v7 1회 (v7은 P50 1→2 포함) |
| SSH Python 수동 실행 허락 | 3회 | v6 적용 + v7 적용 + P50 1→2 적용 |
| Plan 승인 | 1회 | 채널 대시보드 v7 (2회 adversarial review 후) |
| Codex 점검 결정 | 1회 | HIGH 2 + MED 1 → 즉시 수정 후 commit |

---

## 다음 작업 (이번 세션 결정 외)

- ✅ 매일 자동 흐름은 변경 없음 (GAS 08:45 + Python 09:00)
- 🔄 ICP 분석: P50 1→2 추적이 매월 어떻게 변하는지 코호트별 추이 (별도 작업)
- 🔄 채널별 P50 (카페24 vs SS) — 별도 분석 (P50 채널별 미산출 상태)
- 🔄 GAS clasp 자동 sync — 사용자 GAS 수동 붙여넣기 부담 영구 해소 (별도 세션)
- 🔄 Phase 3: GAS 완전 Python 이관 — 장기 근본 해결

---

## 핵심 학습 (이번 세션 박제 가치)

1. **시트 raw 값 직접 검증 없이 화이트리스트 만들지 마라** — 다른 코드 코멘트만 보고 가정 금지
2. **새 폴더·서버 추가 시 deploy 워크플로우 즉시 동기화** — "git pull 자동"이라 가정 금지
3. **UI 산출물 commit 전 시각 검증 필수** — 빈 정보·"참조"·"미측정" 라벨 4개 이상이면 거부 가능성 큼
4. **지표 라벨에 정의 명시** — "재구매 평균 주기"는 모호. "재구매 평균 주기 (1→2 첫 재구매)"가 명확
5. **새 cron 추가 전 동일 작업 전체 검색** — Python import로 같은 함수 공유 가능
6. **Plan adversarial review 최대 2회** — 3회차는 결함이 새 영역으로 확장. 코드 진입이 답
