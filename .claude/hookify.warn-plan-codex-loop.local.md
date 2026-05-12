---
name: warn-plan-codex-loop
enabled: true
event: bash
pattern: codex-companion.*adversarial-review.*(plan|docs/.*\.md|\.claude/plans)
---

⚠️ **Plan-level Codex adversarial review 감지**

이번 세션 학습 (2026-05-13 v5/v6):
- plan v5: 4회 점검 → 결함 17개 누적 (무한 루프)
- plan v6: 3회 점검 → 결함 7개 (또 반복)
- Codex는 adversarial 도구라 plan이 정밀해질수록 새 결함을 끝없이 찾음
- 같은 plan에 3회 이상 점검은 거의 항상 가치 감소

**규칙**:
1. 같은 plan에 codex review **최대 2회**까지만
2. 2회 후에도 needs-attention이면 → "plan 분할 또는 코드 진입" 결정
3. 결함이 줄지 않고 늘어나는 패턴 보이면 즉시 중단
4. 큰 plan(5개+ 변경)은 작은 plan으로 분할 후 점검

**관련 실패 노트**: `docs/lessons/failures.md` ㊲ (plan adversarial 무한 루프)
