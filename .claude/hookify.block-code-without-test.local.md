---
name: block-code-without-test
description: 신규 함수·로직 추가 시 같은 응답 안에 test_*.py 작성 흔적 없으면 차단 (TDD Red-Green-Refactor 강제)
trigger: stop
---

# 규칙: 신규 함수·로직 추가 전 테스트 먼저 작성 (TDD)

## 감지 패턴
응답에 다음이 포함되면서 같은 응답 안에 `tests/test_*.py` Write 또는 Edit 흔적이 없을 때:
- "함수를 추가했습니다" / "함수를 작성했습니다" / "함수 신설" / "구현 완료"
- `def {함수명}` 또는 `class {클래스명}` 신규 정의가 Edit/Write에서 발견
- "로직을 추가했습니다" / "분기를 추가했습니다"

## 면제 패턴 (logic-neutral, 차단 대상 아님)
- 변수명 변경, 주석/docstring 추가, log/print 메시지 수정
- import 정렬, 줄바꿈, 들여쓰기 수정
- 설정 파일 수정: `.ini`, `.json`, `.yml`, `.yaml`, `.toml`, `.env`, `.cfg`
- 문서 파일 수정: `.md`, `.txt`, `.rst`
- `.claude/` 안의 hookify/agent/command 정의 파일
- `.github/workflows/*.yml` 워크플로우 정의
- 데이터 파일: `.csv`, `.jsonl`, `data/` 안 파일

## 차단 조건
**신규 함수 정의 또는 로직 분기 추가** + 같은 응답에 `tests/test_*.py` Write/Edit 흔적 없음 → 차단

## 대체 행동
1. 먼저 `tests/test_{모듈명}.py`에 실패하는 테스트 작성 (**Red 단계**)
2. 테스트 실행해 실패 확인: `python -m pytest tests/test_{모듈명}.py -v`
3. 그 다음 구현 추가 (**Green 단계**)
4. 테스트 통과 확인 후 리팩토링 (**Refactor 단계**)
5. 완료 전 `use_skill('verification-before-completion')` 호출

## 비전공자 안내 (차단 시 표시)
"구현 코드를 먼저 쓰지 마세요. `tests/test_{함수명}.py`에 '이 함수가 이런 입력을 받으면 이런 결과를 내야 한다'는 검증 코드를 먼저 만들어야 합니다. 그게 TDD입니다."
