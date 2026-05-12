---
name: warn-large-plan-split
enabled: true
event: file
conditions:
  - field: file_path
    operator: regex_match
    pattern: (docs/.*plan.*|\.claude/plans/.*)\.md$
  - field: new_text
    operator: regex_match
    pattern: 변경 사항\s*[5-9]개|변경 사항\s*1[0-9]개|##\s+\d{1,2}\.|###\s+[⑤⑥⑦⑧⑨⑩]
---

⚠️ **큰 plan 작성 감지 — 분할 권고**

이번 세션 학습 (2026-05-13):
- v4 plan (7개 변경) → Codex 4회 점검 → 결함 17개 누적
- v5 plan (2개 변경) → Codex 1~2회 점검 → 통과
- v6 plan (3개 변경) → Codex 3회 점검 → 결함 7개 (또 발생)
- 패턴: plan 변경 항목 5개 이상이면 Codex가 결함 끝없이 발견

**규칙**:
1. plan 변경 항목 **5개 이상**이면 → 2~3개씩 분할 검토
2. 핵심(멈춤 방지, 수치 정확성)만 먼저, UI·UX는 다음 plan
3. 큰 plan으로 진행 시 사용자에게 "분할 vs 통합" 옵션 명시 제시
4. iteration cap 2회 명시 (codex 3회+ 시 사용자 결정 받기)

**관련 실패 노트**: `docs/lessons/failures.md` ㊲

**의사결정 가이드**:
- 5개+ 변경 = 분할 (각 codex 1~2회면 충분)
- 2~3개 변경 = 단일 plan OK
- 의존성 강하면 순차, 독립이면 병렬 plan
