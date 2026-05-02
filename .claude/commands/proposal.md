---
description: 헤비로버 사업계획서를 PSST 4P + 7역할 2라운드 토론으로 작성. 사용법 /proposal {사업명} (예: /proposal 초기창업패키지)
argument-hint: <사업명>
---

# 사업계획서 7역할 2라운드 빌드업

사용자가 입력한 사업명: **$ARGUMENTS**

너는 7역할 토론 오케스트레이터다. 아래 순서를 정확히 따른다.

## 사전 점검 (시작 전 필수)

1. `proposals/knowledge/psst-rubric.json` 읽고 `programs.{사업명}` 블록 존재 확인. 없으면 사용자에게 "공고문 URL 또는 평가표 알려주세요" 묻고 중단.
2. `proposals/knowledge/heavylover-skeleton.md` 갱신일 확인. 30일 초과 시 사용자에게 "skeleton 갱신부터 권고" 알림.
3. `proposals/outputs/` 디렉토리 존재 확인.
4. 사용자에게 1줄 안내: "$ARGUMENTS 사업계획서 7역할 2라운드 빌드업을 시작합니다. 30~60분 소요. 각 단계 산출물은 proposals/outputs/에 저장됩니다."

## Round 0 — Draft (단독)

`proposal-drafter` 에이전트 호출.
- 입력: 사업명 = $ARGUMENTS
- 출력: `proposals/outputs/{사업명}-{YYYY-MM-DD}-v0.md`
- 완료 후 사용자에게 v0 경로 보고 + 자가 점검표 통과 여부 1줄.

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

### Step 2-5: `proposal-devil` 호출
- 입력: v2
- 출력: `...-devil-attack.md`
- 종합 판정 분기:
  - 🟢 합격 후보 → final 단계로
  - 🟡 보강 필요 → drafter 호출해 v3 재작성 (devil-attack.md를 입력으로) → devil 재검증 1회 → 결과가 🟢/🟡이면 final, 🔴이면 중단
    - **무한 루프 방지**: v3 후 재검증은 1회만. 그 이후 🔴 나오면 자동 중단.
  - 🔴 재작성 필수 → drafter 호출해 v3-full 재작성 (v0 수준 재시작) → 단, 이 루프도 1회만. 재작성 후도 🔴이면 사용자에게 "구조적 문제 있음, 공고문 재검토 필요" 보고 후 중단.

## Final 단계

devil 🟢 판정 후:
1. v2 또는 최종 vN을 `final.md`로 복사
2. **자동 폴더·서류 셋업 실행**:
   ```
   python tools/setup_proposal_folder.py $ARGUMENTS {YYYY-MM-DD}
   ```
   이 스크립트가 자동으로:
   - `사업/지원사업/{날짜} {사업명}/` 폴더 생성 (제출서류·심사자료·산출물_md 하위 폴더 포함)
   - final.md → Word 파일 변환 후 폴더에 저장
   - 모든 md 산출물 → 산출물_md 폴더에 복사
   - 컴퓨터에서 필요 서류 자동 탐색 후 제출서류 폴더에 복사
   - 제출_체크리스트.md 생성 (구비된 서류 ✅ / 직접 준비 필요 ⚠️ 구분)

3. 사용자에게 최종 보고:

```markdown
## $ARGUMENTS 사업계획서 빌드업 완료

**소요 시간**: {분}
**최종본**: proposals/outputs/{사업명}-{YYYY-MM-DD}-final.md
**지원사업 폴더**: 사업/지원사업/{날짜} {사업명}/
**Word 파일**: {사업명}_사업계획서_{날짜}.docx

### 생성된 모든 산출물 (감사 추적용)
- v0.md → v1.md → v2-draft.md → v2.md → [v3.md] → final.md
- rubric-map.md / consistency.md / budget-audit.md (R1 검증)
- competitor.md / fact-check.md / devil-attack.md (R2 검증)

### 지원사업 폴더 구성
- 📄 {사업명}_사업계획서_{날짜}.docx — Word 수정 가능 최종본
- 📁 제출서류/ — 자동 구비된 서류 + 직접 준비 필요 목록
- 📁 산출물_md/ — 전체 md 파일 (감사 추적)
- ✅ 제출_체크리스트.md — 구비 현황 + 직접 준비 필요 항목

### 사용자 직접 액션 필수
1. 제출_체크리스트.md 열어서 ⚠️ 항목 직접 준비
2. fact-check.md의 ✅ 출처 URL 본인이 1회 클릭 확인
3. devil-attack.md Q&A 10개 답변 연습
4. 신청 후 결과 → `proposals/knowledge/submissions-log/{사업명}-{날짜}.json` 작성

### 합격률 추정
- 시스템 첫 사이클: +20% (J커브 학습효과 미실현)
- 5건 누적 후: +30~50%
```

## 안전 규칙

- 모든 에이전트 호출은 **proposal-** 접두사 7개 중에서만. 다른 에이전트(blog-writer 등) 호출 금지.
- 산출물 저장 전 `proposals/outputs/` 디렉토리 실재 확인.
- 사용자가 도중 중단하면 마지막 산출물 경로 알려주고 종료.
- 토론 중 환각·창작 의심 시 즉시 중단하고 사용자에게 보고.

## 미지원 사업명 처리

`psst-rubric.json`의 `programs`에 없는 사업명 입력 시:
1. WebSearch로 공고문 검색 권고
2. 공고문 URL 받으면 `psst-rubric.json`에 신규 블록 추가 후 재시작
3. 사용자가 양식 제공 시 PSST 매핑 어댑터 작성 후 재시작

## 작업 시작

위 흐름을 그대로 실행. 첫 단계: `proposal-drafter` 호출 (사업명 = $ARGUMENTS).
