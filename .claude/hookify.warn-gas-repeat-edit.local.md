---
name: warn-gas-repeat-edit
enabled: true
event: file
conditions:
  - field: file_path
    operator: regex_match
    pattern: scripts/gas/.*\.gs$
---

⚠️ **GAS 파일 수정 감지 — 사용자 수동 작업 발생**

이번 세션 학습 (2026-05-13 v5.1):
- 같은 GAS 파일에 5회 수정 (v5.1 → patch → patch v2 → 시트 위치 → partial 완화)
- 매번 사용자가 구글 시트 Apps Script에 다시 붙여넣고 runAll 실행 필요
- 사용자 부담: 한 번에 묶어서 변경했어야 함

**규칙 (GAS 파일 수정 시)**:
1. **같은 세션에서 이미 GAS 수정한 적 있는가** 자체 점검
2. 있으면: 이전 수정과 묶어서 한 번에 진행 권고
3. **이번 수정 후 사용자 수동 작업 발생** 인지하고 명시
4. 작은 수정 2~3개를 모아서 한 번의 commit + 한 번의 사용자 붙여넣기로 통합
5. 진짜 긴급한 결함(metric corruption, 데이터 손실)만 즉시 수정. 나머지는 batch.

**자동 동기화 옵션**: clasp 셋업하면 자동 push 가능. 다만 90일 토큰 갱신 부담.
**근본 해결**: Phase 3 (Python으로 GAS 완전 이관)이 답.
