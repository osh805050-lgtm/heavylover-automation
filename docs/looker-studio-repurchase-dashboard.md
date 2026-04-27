# 재구매 대시보드 (Looker Studio) 연결 가이드

매일 09:00 `repurchase_report.py`가 시트에 마트 4종을 자동 갱신한다. Looker Studio는 이 마트 탭만 바라보면 된다.

## 마트 탭 (시트 자동 생성·갱신)

| 탭 | 용도 | Looker 차트 |
|---|---|---|
| `mart_summary` | KPI 1줄 요약 (지표/값/벤치/상태) | 스코어카드 4~6장 |
| `mart_monthly` | 연월·채널별 월별 KPI long format | 라인차트, 채널 필터 |
| `mart_cohort` | 코호트월·채널별 M+1~M+6 long format | 피벗 테이블 (히트맵) |
| `mart_stage` | 채널·단계별 전환율 | 막대그래프 |

각 탭 헤더 뒷열 `갱신시각`에 `YYYY-MM-DD HH:MM KST` 자동 기록.

## Looker Studio 만들기 (10분)

1. https://lookerstudio.google.com → 빈 보고서
2. 데이터 추가 → Google Sheets → 재구매 시트 선택
3. 워크시트는 `mart_summary` 먼저 연결, 옵션 4개 모두 추가하려면 데이터 추가를 4번 반복
4. 페이지 3장 구성:

### 페이지 1 — 요약
- `mart_summary` 사용
- 스코어카드 6개: MoM 변화율, 1→2 전환율, 2→3 전환율, M+1 리텐션, P50, P90
- 표 1개: 지표·값·벤치마크·상태 그대로

### 페이지 2 — 월별 추이
- `mart_monthly` 사용
- 라인차트: X=연월, Y=재구매율 / 두 번째 라인차트: Y=재구매매출
- 필터: 채널 (통합/카페24/스마트스토어)

### 페이지 3 — 코호트 히트맵
- `mart_cohort` 사용
- 피벗: 행=코호트월, 열=M+1~M+6, 값=리텐션%
- 조건부 색상: 0% (빨강) → 30% (초록)

## 자동 새로고침

기본 12시간 캐시. 수동 새로고침은 우상단 새로고침 버튼.

## 모바일 즐겨찾기

URL을 카카오톡 "나에게 보내기" → 즐겨찾기 고정. 노트북 없이도 출퇴근길 확인.

## 검증 (1주일)

- `mart_monthly` 통합 합계 = 기존 `통합 월별 재구매` 탭
- `mart_cohort` M+1 = 기존 `mn_retention` 탭
- 텔레그램 09:00 리포트 수치 = `mart_summary` 값
- 편차 0이면 기존 19개 탭 정리 검토

## 롤백

`repurchase_report.py`의 `run()` 안에서 `write_marts(...)` 호출 줄을 주석 처리하면 끝. 마트 탭은 마지막 갱신 상태로 멈춤(파괴 없음).
