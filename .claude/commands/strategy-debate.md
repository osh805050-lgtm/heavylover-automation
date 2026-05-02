---
description: 헤비로버 성장전략 5 에이전트 갑론을박 → 6개월 실행 로드맵 auto-generate. 5라운드 순차 진행, 뻔한 결론 자동 차단, 합의/불합의 분리 박제.
---

# 헤비로버 성장전략 갑론을박

너는 `strategy-orchestrator` 에이전트다. 아래 순서를 정확히 따른다.

## 사전 점검

1. `docs/analysis_10b/_master.md` 존재 확인. 없으면: "분석 리포트가 없습니다. 먼저 IC 진단 리포트를 완성해주세요." 중단.
2. `data/analysis_10b/unit_economics.json` 존재 확인.
3. `docs/strategy/outputs/` 디렉토리 확인. 없으면 생성.
4. 오늘 날짜 확인 → `TODAY=YYYY-MM-DD` 모든 파일 접두어.
5. 사용자에게 안내: "헤비로버 성장전략 5 에이전트 갑론을박을 시작합니다. 5라운드 순차 진행, 약 30~50분 소요. 결과는 docs/strategy/outputs/에 저장됩니다."

## Round 0: 공통 데이터 로드

5명이 공유할 핵심 숫자 확인 (읽기만):
- `data/analysis_10b/unit_economics.json` → CAC, LTV, ROAS, AOV
- `data/analysis_10b/sheets/mart_summary.csv` → M+1, 재구매율
- `data/analysis_10b/sheets/mart_monthly.csv` → 월별 신규·재구매
- `data/meta_ads/daily.csv` → last30 ROAS, AOV

## Round 1: 현재 진단 — "지금 가장 큰 병목이 뭔가?"

강제 비직관 질문: **"광고를 완전히 끄면 어떻게 되나?"**

오케스트레이터가 먼저 계산:
- 광고 중단 시 추정 월매출 산출 (오가닉+재구매만)
- 이 숫자를 라운드 시작 시 공유

5명 순차 호출 (A→B→C→D→E), 각자 직전 발언 읽고 반박:
1. `strategy-margin-fundamentalist` 에이전트 호출
2. `strategy-acquisition-maximalist` 에이전트 호출 (A 발언 포함)
3. `strategy-structural-pessimist` 에이전트 호출 (A+B 발언 포함)
4. `strategy-capital-allocator` 에이전트 호출 (A+B+C 발언 포함)
5. `strategy-identity-challenger` 에이전트 호출 (A+B+C+D 발언 포함)

결과 저장: `docs/strategy/outputs/$TODAY-round1-diagnosis.md`
사용자 보고: "Round 1 완료. 5명 포지션 저장됨. 주요 충돌 포인트: [1줄]"

## Round 2: 10억 경로 — "어떻게 가야 하나?"

강제 비직관 질문: **"시리얼을 취소하면 어떻게 되나?"**

Round 1 결과 읽은 후 5명 순차 호출.
결과 저장: `docs/strategy/outputs/$TODAY-round2-path.md`

## Round 3: 자본 배분 — "1억이 생기면 어디에?"

강제 비직관 질문: **"박재영이 없으면 어떻게 되나?"**

Round 2 결과 읽은 후 5명 순차 호출.
결과 저장: `docs/strategy/outputs/$TODAY-round3-capital.md`

## Round 4: 위험 시나리오 — "어디서 망하나?"

강제 비직관 질문: **"카페24를 없애면 어떻게 되나?"**

Round 3 결과 읽은 후 5명 순차 호출.
결과 저장: `docs/strategy/outputs/$TODAY-round4-risk.md`

## Round 5: Kill Criteria 합의

강제 비직관 질문: **"10억 목표를 6억으로 낮추면 어떻게 되나?"**

Round 4 결과 읽은 후 5명 순차 호출.
오케스트레이터가 합의 항목 (3명 이상 동의) vs 불합의 항목 분리.
결과 저장: `docs/strategy/outputs/$TODAY-round5-kill-criteria.md`

## 최종: 6개월 로드맵 Auto-Generate

5개 라운드 파일 모두 읽기 → `08_6m_roadmap.md` 작성.

구조:
- 합의된 확정 액션 (담당·기한·측정 지표·Kill Criteria)
- 합의 안 된 실험 후보 (트리거 조건 명시)
- 5라운드 통해 나온 비직관 발견 TOP 3
- 월별 매출 목표 M+1~M+6
- Kill Criteria 8개
- 합의 불가 항목 (영구 박제)

저장: `docs/strategy/outputs/$TODAY-08_6m_roadmap.md`
(선택) 요약 300자 텔레그램 발송 (`TELEGRAM_BOT_TOKEN_REPORT`)

사용자 최종 보고:
"갑론을박 완료. 확정 액션 N개, 실험 후보 M개, 합의 불가 K개. 로드맵 저장: docs/strategy/outputs/$TODAY-08_6m_roadmap.md"
