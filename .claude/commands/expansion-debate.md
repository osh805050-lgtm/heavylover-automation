# /expansion-debate

헤비로버 확장·마케팅 방안 Proposer+Challenger 토론 실행.
6개 도메인 순차 진행 → 생존/보류/탈락 판정 → synthesis 자동 생성.

## 실행 순서

### Step 0: 사전 점검
- `docs/strategy/outputs/` 디렉토리에서 최신 `*-08_6m_roadmap.md` 파일 존재 확인 (날짜 무관, 가장 최근 것 사용)
- `data/analysis_10b/unit_economics.json` 존재 확인
- `docs/expansion/outputs/` 디렉토리 존재 확인 (없으면 생성)
- 오늘 날짜 설정: TODAY=2026-04-29

사용자에게 안내:
"헤비로버 확장 토론을 시작합니다. 6개 도메인 × Proposer+Challenger = 12회 토론. 약 40~60분 소요. 결과는 docs/expansion/outputs/에 저장됩니다."

### Step 1: Domain A — 크리에이티브 최적화

공통 데이터 주입:
- ROAS: last30 3.51, 위너 8.58, 최하위 2.33
- last30 AOV: 59,964 (5개월 평균 67,420 대비 -11%)
- Kill Criteria K1: ROAS < 2.8 → 광고비 -30%

`domain-a-creative-proposer` 에이전트 호출:
- `data/meta_ads/daily_campaign.csv` 읽기
- 제안 A-1, A-2, A-3 생성
- 출력: 핵심 제안 + 수치 근거 + Challenger에게 질문

`domain-a-creative-challenger` 에이전트 호출 (Proposer 출력 첨부):
- Proposer 제안 3개에 반박
- 조건부 수용 항목 명시

오케스트레이터 판정:
- 생존/보류/탈락 + 이유 + 조건
- 저장: `docs/expansion/outputs/2026-04-29-domain-a-creative.md`

### Step 2: Domain B — CRM / 재구매 트리거

공통 데이터 주입:
- M+1: 14%, P50: 10일, 카페24 정착 시 3.4회
- Kill Criteria K2: M+1 < 12% 3개월 연속 → 신규 획득 정지 검토

`domain-b-crm-proposer` 에이전트 호출:
- `data/analysis_10b/sheets/mart_cohort.csv` 읽기
- 제안 B-1(H4 즉시), B-2(시퀀스), B-3(태깅 인프라)

`domain-b-crm-challenger` 에이전트 호출 (Proposer 출력 첨부):
- H4 원인 불명, 카페24 트리거 기능 불명, 측정 순서 공격

오케스트레이터 판정 후 저장: `2026-04-29-domain-b-crm.md`

### Step 3: Domain C — 채널 확장

공통 데이터 주입:
- SS 오가닉 재구매 30~46%
- 카페24: 100% Meta 광고 의존
- 월매출 3,800만, 흑자선 5,000만

`domain-c-channel-proposer` → `domain-c-channel-challenger`
저장: `2026-04-29-domain-c-channel.md`

### Step 4: Domain D — 가격·패키지 최적화

공통 데이터 주입:
- 신규 AOV 67,420 / 재구매 AOV 86,529
- 결제→구매 전환율 49.85%
- Kill Criteria K6: AOV < 58,000 2개월 연속

`domain-d-pricing-proposer` → `domain-d-pricing-challenger`
저장: `2026-04-29-domain-d-pricing.md`

### Step 5: Domain E — 콘텐츠 / SEO

공통 데이터 주입:
- 브랜드 검색량 월 260
- CAC 17,932원 (Meta 광고)
- 현재 블로그 전환 추적 없음

`domain-e-content-proposer` → `domain-e-content-challenger`
저장: `2026-04-29-domain-e-content.md`

### Step 6: Domain F — B2B / 오프라인 접점

공통 데이터 주입:
- ACT-01 상태: 박재영 역할 명세 미완료 (기한 05-06)
- CAC 17,932원 (B2B 파일럿 비교 기준)
- CLAUDE.md: B2B 단순 전환 재논의 금지 (헬스장 채널은 열린 사안)

`domain-f-b2b-proposer` → `domain-f-b2b-challenger`
저장: `2026-04-29-domain-f-b2b.md`

### Step 6.5: 도메인 간 의존성 체크 (Synthesis 전 필수)

6개 output 파일 읽기 후 다음을 체크:

| 도메인 생존 조건 | 연쇄 영향 |
|---|---|
| A(크리에이티브) 생존 | B(CRM)에 "신규 코호트 증가" 트리거 전달 |
| B(CRM) 생존 | D(가격) 업셀 타이밍 전제로 사용 가능 |
| C(채널) 생존 | E(콘텐츠) SEO 키워드 우선순위 조정 필요 |
| D(가격) 생존 | A(크리에이티브) 소재 메시지 변경 연동 필요 |
| F(B2B) 생존 | ACT-01 박재영 역할 명세가 전제 |

의존성으로 인해 "도메인 단독 생존이 불가능한 경우" → synthesis에서 묶음 실행으로 표기.

### Step 7: Synthesis 자동 생성

6개 output 파일 + Step 6.5 의존성 체크 결과 읽기 후 `{TODAY}-expansion-synthesis.md` 생성:

```
# 헤비로버 확장 토론 종합 — 2026-04-29

## 생존 제안 (즉시 실행 가능)
| 제안 | 도메인 | 담당 | 기한 | KPI |
|---|---|---|---|---|

## 보류 제안 (트리거 조건)
| 제안 | 도메인 | 트리거 조건 | Kill Criteria 연동 |
|---|---|---|---|

## 탈락 제안 (이유)
| 제안 | 도메인 | 탈락 이유 |
|---|---|---|

## 비직관 발견 TOP 3
1. 
2. 
3. 

## 공통 선결 조건 (모든 도메인에서 반복 등장)
- ACT-01: 박재영 역할 명세 (X개 도메인에서 블로커로 등장)
- 측정 인프라: UTM + 그룹 태깅
- 결제 퍼널 49.85% 병목 (A/B/D/E 도메인 공통 언급)
```

사용자 최종 보고:
"확장 토론 완료. 생존 N개, 보류 M개, 탈락 K개. 비직관 발견 3개. 결과: docs/expansion/outputs/2026-04-29-expansion-synthesis.md"
