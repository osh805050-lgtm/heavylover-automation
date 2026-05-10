---
description: 헤비로버 사업계획서를 PSST 4P + 7역할 2라운드 토론으로 작성. 사용법 /proposal {사업명} (예: /proposal 초기창업패키지)
argument-hint: <사업명>
---

# 사업계획서 7역할 2라운드 빌드업

사용자가 입력한 사업명: **$ARGUMENTS**

너는 7역할 토론 오케스트레이터다. 아래 순서를 정확히 따른다.

## 사전 점검 (시작 전 필수)

0. **재실행 차단**: `proposals/outputs/{사업명}-*-final.md` 또는 `*-v3.md` 등 최종 산출물 파일 있으면 즉시 중단 후 사용자에게 "{사업명} 사업계획서 산출물이 이미 있습니다. 재실행 시 60~106분 + 수만 토큰 소모됩니다. 새 라운드 진행하시겠습니까? (예/아니오/이어쓰기)" 묻고 명시 승인 시에만 진행.
1. `proposals/knowledge/psst-rubric.json` 읽고 `programs.{사업명}` 블록 존재 확인. 없으면 → **`proposal-rubric-extractor` 자동 호출** (공고문 PDF/URL 입력 받아 자동 등재). 등재 완료 후 본 흐름 진입.
2. `proposals/knowledge/heavylover-skeleton.md` 갱신일 확인. 30일 초과 시 사용자에게 "skeleton 갱신부터 권고" 알림.
3. `proposals/outputs/` 디렉토리 존재 확인.
4. 사용자에게 1줄 안내: "$ARGUMENTS 사업계획서 7역할 빌드업을 시작합니다. 60~106분 소요 (인터뷰 + 공격 루프 포함). 각 단계 산출물은 proposals/outputs/에 저장됩니다."

## Round -1 — 인터뷰 (★ 신규, drafter 호출 전 필수)

`proposal-interviewer` 에이전트 호출.
- 입력: 사업명 = $ARGUMENTS
- 처리: psst-rubric.json의 `programs.{사업명}.interview_questions` 5~7개를 AskUserQuestion으로 사용자에게 묻고 답변 박제
- 출력: `proposals/outputs/{사업명}-{YYYY-MM-DD}-interview.yaml`
- 완료 후 사용자에게 인터뷰 통계 보고 (자세히 답변 N개, 간단 답변 N개, 미응답 N개)

**★ ABORT_FLOW 감지 (필수)**: interview.yaml 첫 줄을 Read로 확인. `ABORT_FLOW: rubric_missing` 또는 `ABORT_FLOW: save_failed` 토큰 발견 시 **즉시 전체 흐름 중단**. 사용자에게 1줄 알림 후 종료. Round 0 진입 금지.
`ABORT_FLOW: all_skipped` 발견 시 사용자에게 "인터뷰 답변이 모두 비어있어 산출물 품질이 70% 수준으로 떨어집니다. 그래도 진행하시겠습니까?" AskUserQuestion 1회. 거부 시 종료.

**중요**: 이 단계가 PDF v4 수준 산출의 핵심. 사용자가 모든 질문에 "답변 안 함" 선택해도 진행은 가능하나, 그 경우 산출물 품질이 70% 수준으로 떨어짐.

## Round 0 — Draft (단독)

`proposal-drafter` 에이전트 호출.
- 입력: 사업명 = $ARGUMENTS + **interview.yaml (1순위 입력)**
- 출력: `proposals/outputs/{사업명}-{YYYY-MM-DD}-v0.md`
- v0 yaml 헤더에 `redefinition_candidates` 3개 박제 확인
- 완료 후 사용자에게 v0 경로 보고 + 자가 점검표 통과 여부 1줄.

## Round 0.5 — 재정의 문장 선택 (★ 신규 AskUserQuestion 1회)

v0의 `redefinition_candidates` 3개를 사용자에게 보여주고 1개 선택 받음.
- AskUserQuestion 1회 (60초 timeout)
- timeout 시 첫 후보 자동 선택
- 선택 결과를 `proposals/outputs/{사업명}-{YYYY-MM-DD}-redefinition.txt`에 박제 → 이후 final-revisor가 본문 핵심 위치에 박음

## Round 1 — 검증 (3개 병렬)

v0 산출 후, 다음 3개 에이전트를 **단일 메시지에서 동시 호출** (병렬):

1. `proposal-rubric-mapper` — `proposals/outputs/{사업명}-{YYYY-MM-DD}-rubric-map.md` 출력
2. `proposal-consistency` — `...-consistency.md` 출력
3. `proposal-budget-auditor` — `...-budget-audit.md` 출력

3개 보고서 수신 후, **drafter를 다시 호출**해 v0 → v1 보강:
- 입력: v0 + 3개 보고서
- 보강 지시: rubric-map의 ❌ Remove 문장 제거 + ⚠️ Boost 문장 강화. consistency의 🔴 모순 모두 해소. budget-audit의 단가·수량·시점 누락 채움.
- 출력: `proposals/outputs/{사업명}-{YYYY-MM-DD}-v1.md`

사용자에게 R1 완료 1줄 보고 + 핵심 보강점 3가지 요약.

## Round 2 — 적대·강화 (순차)

v1 산출 후, 순서대로:

### Step 2-1: `proposal-competitor` 호출
- 입력: v1
- 출력: `...-competitor.md`
- 사용자 1줄 보고: "경쟁사 비교표 N개 항목 추출 완료"

### Step 2-2: drafter를 다시 호출해 v1 → v2-draft 보강
- 입력: v1 + competitor 보고서
- 보강 지시: S섹션에 비교표 삽입 + 포지셔닝 1줄 반영
- 출력: `proposals/outputs/{사업명}-{YYYY-MM-DD}-v2-draft.md`

### Step 2-3: `proposal-fact-checker` 호출
- 입력: v2-draft
- 출력: `...-fact-check.md`

### Step 2-4: drafter가 fact-check 보고서 받아 v2-draft → v2 보강
- 보강 지시: ❌ 환각 인용 제거. ⚠️ 출처 약함 보강.
- 출력: `proposals/outputs/{사업명}-{YYYY-MM-DD}-v2.md`

### Step 2-5: `proposal-devil` 호출 (R2 — 1회차)
- 입력: `proposals/outputs/{사업명}-{YYYY-MM-DD}-v2.md` (★ Step 2-4에서 drafter가 생성한 fact-check 정정본 — `v2-draft.md` 아님 절대 주의)
- 출력: `...-devil-attack.md`
- 이 단계에서는 종합 판정과 무관하게 **반드시 Round 3으로 진입** (v2 → final-revisor가 v3 강제 재작성)

## Round 3 — Final-revisor 강제 재작성 + 공격 루프 (★ 신규)

### Step 3-1: `proposal-final-revisor` 호출 (1회차)
- 입력: v2 + interview.yaml + fact-check.md + devil-attack.md + competitor.md + budget-audit.md + consistency.md + redefinition.txt + reference-criteria.md
- 처리: fact-check ❌ 100% 강제 정정 (recommended 자동 적용) + devil 🔴/🟡 모두 반영 + 4축 톤 규칙 적용 + 인터뷰 답변 박제 + 부록 A/B 자동 분리
- 출력: `proposals/outputs/{사업명}-{YYYY-MM-DD}-v3.md` + `appendix-A-evaluator.md` + `appendix-B-pending.md` + `submit-checklist.md`

### Step 3-2: `brand-voice-reviewer` 가드레일 호출 (1회만)
- ★ 에이전트 위치: `.claude/agents/brand-voice-reviewer.md` (proposal/ 하위 아닌 .claude/agents/ 직속)
- 입력: v3.md
- 처리: 18개 언어 규칙 위반 검출 (Tier 1 강제, Tier 2 권고, Tier 3 카운트, Tier 4 권고)
- 출력: `proposals/outputs/{사업명}-{YYYY-MM-DD}-voice-guardrail.md`
- 분기:
  - 🟢/🟡 통과 → Step 3-3 진입
  - 🔴 (Tier 1 위반 ≥ 1건) → final-revisor 1회만 재호출 → v3 재생성 → 다시 Step 3-2 통과 확인 → Step 3-3 진입

### Step 3-3: 공격 루프 (devil ↔ final-revisor 최대 2회)

**1회차 공격**:
- `proposal-devil` 호출 (공격 루프 모드) — **devil 호출 카운터 = 1**
- 입력: v3.md + 이전 devil-attack.md (같은 문장 중복 공격 금지용)
- 출력: `proposals/outputs/{사업명}-{YYYY-MM-DD}-devil-attack-r1.md`
- L1 자랑 검출 + L2 가짜 디테일 + L3 섹션 단절 + L4 공감 부재 + 기존 7대 패턴 모두 적용

**1회차 판정**:
- 🟢 통과 (🔴 0개 + 🟡 2개 이하) → v3 그대로 final 승격, **공격 루프 종료**
- 🟡 재작성 필요 → `proposal-final-revisor` 재호출 (v3.1 생성) → 2회차 공격 진입
- 🔴 다수 위반 → `proposal-final-revisor` 재호출 (v3.1 생성) → 2회차 공격 진입

**2회차 공격** (1회차 미통과 시):
- `proposal-devil` 호출 (입력: v3.1 + 이전 회차 devil-attack-r1.md) — **devil 호출 카운터 = 2 (절대 상한)**
- 출력: `devil-attack-r2.md`

**2회차 판정**:
- 🟢 통과 → v3.1 final 승격, **공격 루프 종료**
- 🟡/🔴 미통과 → `proposal-final-revisor` 재호출 (v3.2 생성) → **루프 종료. v3.2는 `proposals/outputs/{사업명}-{YYYY-MM-DD}-v3.2.md`로만 저장하고 final.md 자동 승격 차단** (Codex review 2026-05-10: 알려진 결함 박힌 채 제출되는 것 방지)

**🔴/🟡 미통과 시 사용자 보고 (final.md 자동 생성 안 함)**:
> ⚠️ 공격 루프 2회 후에도 잔여 약점 🔴 {N}건 / 🟡 {M}건 남음. v3.2 저장됨: `{사업명}-{YYYY-MM-DD}-v3.2.md`
>
> **자동 final.md 승격이 차단됨**. 다음 중 하나로 진행하세요:
> 1. **항목별 검토 후 수동 승격**: v3.2 + devil-attack-r2.md 직접 검토, 잔여 약점 각각에 대해 (a) v3.2를 직접 수정하거나 (b) waiver 사유를 `appendix-B-pending.md`에 박제 → `cp v3.2.md final.md`
> 2. **명시적 강제 승격**: `/proposal {사업명} --force-promote` 재실행 (waiver 검토를 사용자가 책임진다는 명시 동의)
>
> Final 단계의 폴더 셋업·Word 변환·체크리스트 생성은 final.md 존재 시에만 실행됩니다.

**`--force-promote` 처리 (H-7 구현)**:

`$ARGUMENTS`에 `--force-promote` 토큰이 포함된 경우 오케스트레이터가 아래를 실행:

1. `proposals/outputs/{사업명}-*-v3.2.md` 최신 파일 확인. 없으면 "강제 승격할 v3.2 파일이 없습니다" 안내 후 종료.
2. `proposals/outputs/{사업명}-*-devil-attack-r2.md` 읽어 잔여 🔴/🟡 항목 목록 추출.
3. `appendix-B-pending.md` 에 waiver 섹션 자동 append:
   ```
   ## --force-promote waiver ({날짜})
   사용자가 잔여 약점을 인지하고 강제 승격을 명시 동의함.
   잔여 🔴 {N}건 / 🟡 {M}건:
   {항목 목록}
   ```
4. v3.2 → final.md 복사 (`proposals/outputs/{사업명}-{날짜}-final.md`).
5. 사용자에게 1줄 보고: "강제 승격 완료. waiver 기록됨: appendix-B-pending.md. Final 단계로 진입합니다."
6. Final 단계(F-1~F-3) 계속 실행.

**무한 루프 방지 (★ 절대 상한)**: 공격 루프는 최대 2회 (즉 v3.2까지). 오케스트레이터가 devil 호출 횟수를 카운터로 추적. 2회 도달 시 devil 자체 판정(🔴/🟡)과 무관하게 **강제 종료**. **v3.3 이상 절대 생성 금지**.

## Final 단계

공격 루프 종료 후:
1. 통과한 v3.x (v3 / v3.1 / v3.2)를 `final.md`로 복사
2. 부록 A·B + submit-checklist는 그대로 유지

### Step F-1: 사이클 회고 보고서 자동 생성 (학습 루프)

`proposal-drafter`를 마지막으로 한 번 더 호출. 입력: 이번 사이클의 모든 산출물 (v0~final, rubric-map, consistency, budget-audit, competitor, fact-check, devil-attack).
출력: `proposals/lessons/cycle-{사업명}-{YYYY-MM-DD}.md`

회고 보고서 표준 항목:
- **이번 사이클 메타**: 사업명, 시작~종료 시간, 최종 판정, 라운드별 보강 횟수
- **잘 작동한 표현 Top 5**: rubric-mapper에서 ✅ Keep + 평가항목 직접 매칭 + fact-checker ✅ 동시 만족 문장
- **새로 발견된 약점 패턴**: devil이 처음 검출한 패턴 (universal·기존 1~7번에 없던 것) — 다음 사이클 universal에 추가 후보
- **rubric 미커버 항목**: rubric-mapper 요약 통계의 미커버 key_points 목록 — 다음 skeleton 갱신 후보
- **분량 통계**: 섹션별 단어 수·skeleton 직접 인용 비율(목표 70~80%)
- **다음 사이클 권고**: skeleton 보강 항목 1~3개, drafter 가이드 강화 1~3개

### Step F-2: submissions-log stub 자동 생성 (외부 결과 입력 대기 상태)

`proposal-drafter`를 호출. AI가 알 수 있는 7개 칸은 자동 채움, 결과·점수·reviewer 코멘트 4개 칸은 빈칸으로 둔다.

출력: `proposals/knowledge/submissions-log/{사업명}-{YYYY-MM-DD}.md`

**자동 채움 항목 (7개)**:
- 사업명 ($ARGUMENTS)
- 신청일 (오늘 날짜)
- 발표 예정일 (`psst-rubric.json` `programs.{사업명}.expected_announcement` — 없으면 "미정")
- 신청 금액 (`psst-rubric.json` `programs.{사업명}.max_funding`)
- 최종 제출본 경로 (`proposals/outputs/{사업명}-{날짜}-final.md`)
- 사이클 회고 경로 (`proposals/lessons/cycle-{사업명}-{날짜}.md`)
- 산출물 12종 경로 인덱스 (v0~final, rubric-map·consistency·budget-audit·competitor·fact-check·devil-attack)

**빈칸 유지 항목 (4개 — 사용자가 결과 통지 후 작성)**:
- 결과 (합격/탈락/보류)
- 평가표 점수
- reviewer_comments
- 회고 (잘된 점·약점·다음 교훈)

stub 생성 후 사용자에게 1줄 안내: "submissions-log stub 생성 완료. 결과 통지 받으면 4개 빈칸만 채워주세요. 경로: ..."

### Step F-3: 자동 폴더·서류 셋업 + 양식 섹션 분리 실행
   ```
   python tools/setup_proposal_folder.py $ARGUMENTS {YYYY-MM-DD}
   python tools/generate_submission_sections.py $ARGUMENTS {YYYY-MM-DD}
   ```
   첫 번째 스크립트가 자동으로:
   - `~/OneDrive/헤비로버_제출/{날짜} {사업명}/` 폴더 생성 (제출서류·심사자료·산출물_md 하위 폴더 포함)
     (`TARGET_BASE` = `~/OneDrive/헤비로버_제출` — `tools/setup_proposal_folder.py` 내 상수)
   - final.md → Word 파일 변환 후 폴더에 저장
   - 모든 md 산출물 → 산출물_md 폴더에 복사
   - `proposals/knowledge/submission-manifest.json` 기반으로 필요 서류 자동 탐색 후 제출서류 폴더에 복사
   - 제출_체크리스트.md 생성 (구비된 서류 ✅ / 직접 준비 필요 ⚠️ 구분)

   두 번째 스크립트가 자동으로:
   - psst-rubric.json의 section_mapping 참조
   - final.md를 P/S_solution/S_scale/T 섹션으로 분리
   - 사업별 양식 섹션명에 맞게 매핑하여 `복붙용_섹션분리.txt` 생성
   - HWP/Word 양식 열고 섹션별로 붙여넣기만 하면 됨

3. 사용자에게 최종 보고:

```markdown
## $ARGUMENTS 사업계획서 빌드업 완료

**소요 시간**: {분}
**최종본**: proposals/outputs/{사업명}-{YYYY-MM-DD}-final.md
**지원사업 폴더**: 사업/지원사업/{날짜} {사업명}/
**Word 파일**: {사업명}_사업계획서_{날짜}.docx
**복붙용 섹션 분리본**: 사업/지원사업/{날짜} {사업명}/복붙용_섹션분리.txt

### 생성된 모든 산출물 (감사 추적용)
- v0.md → v1.md → v2-draft.md → v2.md → [v3.md] → final.md
- rubric-map.md / consistency.md / budget-audit.md (R1 검증)
- competitor.md / fact-check.md / devil-attack.md (R2 검증)

### 지원사업 폴더 구성
- 📄 {사업명}_사업계획서_{날짜}.docx — Word 수정 가능 최종본
- 📄 복붙용_섹션분리.txt — HWP/Word 양식 섹션별 붙여넣기용
- 📁 제출서류/ — 자동 구비된 서류 + 직접 준비 필요 목록
- 📁 산출물_md/ — 전체 md 파일 (감사 추적)
- ✅ 제출_체크리스트.md — 구비 현황 + 직접 준비 필요 항목

### 양식 제출 방법 (복붙용_섹션분리.txt 사용)
1. 복붙용_섹션분리.txt 열기
2. 【양식 섹션】 헤더 아래 내용을 복사
3. HWP/Word 양식의 해당 칸에 붙여넣기
4. 글자 수 제한·양식 지침에 맞게 최종 편집

### 사용자 직접 액션 필수
1. 제출_체크리스트.md 열어서 ⚠️ 항목 직접 준비
2. fact-check.md의 ✅ 출처 URL 본인이 1회 클릭 확인
3. devil-attack.md Q&A 10개 답변 연습
4. 신청 후 결과 → `proposals/knowledge/submissions-log/{사업명}-{날짜}.md` 작성

### 합격률 추정
- 시스템 첫 사이클: +20% (J커브 학습효과 미실현)
- 5건 누적 후: +30~50%
```

## 안전 규칙

- 모든 에이전트 호출은 **proposal-** 접두사 9개 중에서만 (drafter, rubric-mapper, consistency, budget-auditor, competitor, fact-checker, devil, **interviewer**, **final-revisor**, **rubric-extractor**) + 가드레일은 **brand-voice-reviewer** 1회만 허용.
- 산출물 저장 전 `proposals/outputs/` 디렉토리 실재 확인.
- 사용자가 도중 중단하면 마지막 산출물 경로 알려주고 종료.
- 토론 중 환각·창작 의심 시 즉시 중단하고 사용자에게 보고.

## 미지원 사업명 처리 (★ 자동화)

`psst-rubric.json`의 `programs`에 없는 사업명 입력 시:
1. **사용자에게 1줄 안내**: "{사업명} 평가 기준이 시스템에 없습니다. proposal-rubric-extractor를 호출해 공고문에서 자동 추출하겠습니다."
2. `proposal-rubric-extractor` 호출 (Haiku, ~$0.05, 5분)
3. extractor가 사용자에게 공고문 PDF/URL + 사업 성격 입력 받아 평가표·special_focus·interview_questions 자동 생성
4. 사용자 승인 후 psst-rubric.json append
5. 등재 완료 후 본 흐름 진입 (Round -1 인터뷰부터)

## 작업 시작

위 흐름을 그대로 실행:
1. 사전 점검 (재실행 차단, 사업 등재 여부 확인)
2. **Round -1**: `proposal-interviewer` 호출 (★ 신규, 5~7개 인터뷰 질문)
3. **Round 0**: `proposal-drafter` 호출 (interview.yaml 1순위 입력)
4. **Round 0.5**: 재정의 문장 후보 3개 중 사용자 선택 (AskUserQuestion 1회)
5. **Round 1**: rubric-mapper + consistency + budget-auditor 병렬 → drafter v1
6. **Round 2**: competitor → drafter v2-draft → fact-checker → drafter v2 → devil
7. **Round 3**: final-revisor → brand-voice-reviewer 가드레일 → 공격 루프 (devil ↔ final-revisor 최대 2회)
8. **Final**: 통과한 v3.x를 final로 승격 + 회고 + submissions-log + 폴더 셋업
