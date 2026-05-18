---
name: warn-jargon-without-analogy
enabled: true
event: stop
action: warn
pattern: (API|cron|regex|gspread|quota|atomic|race condition|timeout|exception|webhook|OAuth|payload|schema|race|stale|fresh|coverage|stack trace|lookahead|lookbehind|negative\s+(lookahead|lookbehind)|f-string|placeholder|escape|hashtag|namespace|polling|debounce|throttle)
---

⚠️ **전문 용어 사용 — 비유/일상 단어 번역 동반 확인**

CLAUDE.md §0: "전문 용어 사용 시 같은 문장 또는 직후 1줄에 비유 또는 일상 단어 번역 동반 필수"

## 자체 검토

응답에 위 전문 용어가 등장했다면 같은 응답 안에 다음 중 **하나라도** 있는지 확인:

1. **비유**: "X = 청소부", "Y = 검문소" 같은 일상 사물 빗댐
2. **일상 단어 번역**: "API = 다른 서비스와 데이터 주고받는 통로"
3. **표**: 전문 용어와 그 뜻을 좌우로 정리
4. **승현님이 이미 알고 있는 맥락**: 이전 응답에서 같은 용어를 비유로 설명한 적 있음

## 위반 시 대체 행동

응답 보내기 전 1줄 추가:
- "여기서 {전문용어} = {일상 단어} 또는 {비유}"

예시:
- ❌ "gspread quota 초과로 race condition 발생"
- ✅ "gspread(구글 시트 자동화 도구) quota(분당 호출 한도) 초과로 race condition(작업 순서 꼬임) 발생"

## 면제 케이스

- 같은 응답에 비유 또는 표가 이미 있음
- 승현님이 직접 그 용어를 먼저 사용함 (질문에 등장)
- 코드 블록 안 (코드는 그대로 둠)
