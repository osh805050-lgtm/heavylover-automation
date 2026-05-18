---
name: block-code-without-superpowers
description: 코드 작업(Edit/Write) 전 superpowers writing-plans 스킬 미사용 시 경고 차단
trigger: stop
---

# 규칙: 코드 작업 전 superpowers 사전점검 강제

## 감지 패턴
응답에 다음이 포함되면서 superpowers 스킬 호출 흔적이 없을 때:
- "수정했습니다" / "완료됐습니다" / "코드를 작성했습니다"
- Edit / Write 툴 사용 직후

## 차단 조건
코드 신규 작성 또는 기존 로직 변경 후 "완료" 보고 시,
대화 내에 `use_skill` 호출(writing-plans / verification-before-completion) 흔적 없으면 차단.

## 대체 행동
1. superpowers `use_skill('verification-before-completion')` 먼저 호출
2. 실행 결과 확인 후 "완료" 보고
