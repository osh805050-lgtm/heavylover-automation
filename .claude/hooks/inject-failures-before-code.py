#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
코드 작업 전 failures.md 강제 주입 hook (UserPromptSubmit)

작동 방식:
1. 사용자 프롬프트에 코드 작업 키워드 감지
2. failures.md 최근 15건 자동 추출
3. system context로 강제 주입 — Claude가 Read를 안 해도 내용이 컨텍스트에 들어감

목적: "failures.md 읽는 것을 깜빡함" 패턴 구조적 제거.
     Claude의 의지에 의존하지 않고 시스템이 강제로 주입.

오류 시 무조건 exit 0 (Claude 작업을 막지 않는다 — fail-open).
"""
import json
import sys
import io
import re
from pathlib import Path

# Windows cp949 환경에서도 UTF-8로 안전하게 출력
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

# 코드 작업 키워드 — 이 단어가 프롬프트에 있으면 failures.md 주입
CODE_WORK_PATTERN = (
    r"함수|구현|리팩|TDD|pytest|ruff|디버깅|debug|단위.?테스트|unit\s*test"
    r"|코드\s*작성|짜줘|작성해줘|수정해줘|고쳐줘|버그|오류 수정"
    r"|\.py|Edit|Write|hook|cron|자동화|배포|workflow"
    r"|repurchase|재구매|cohort|코호트|compare|shadow"
)

FAILURES_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "lessons" / "failures.md"

MAX_ENTRIES = 15  # 최근 N건


def extract_recent_failures(content: str, n: int) -> str:
    """failures.md에서 최근 N건 항목 추출 (- **날짜** 형식 라인)."""
    lines = content.split("\n")
    entries = []
    current: list[str] = []

    for line in lines:
        if re.match(r"^- \*\*\d{4}-\d{2}-\d{2}\*\*", line):
            if current:
                entries.append("\n".join(current))
            current = [line]
        elif current:
            # 빈 줄이 2개 연속이면 항목 종료
            if line.strip() == "" and current and current[-1].strip() == "":
                entries.append("\n".join(current))
                current = []
            else:
                current.append(line)

    if current:
        entries.append("\n".join(current))

    recent = entries[:n]  # 이미 시간 역순 (파일 상단이 최신)
    return "\n\n".join(recent)


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        data = json.loads(raw)
    except Exception:
        sys.exit(0)

    prompt = data.get("prompt", "") or ""
    if not prompt:
        sys.exit(0)

    # 코드 작업 키워드 없으면 주입 안 함
    if not re.search(CODE_WORK_PATTERN, prompt, re.IGNORECASE):
        sys.exit(0)

    if not FAILURES_PATH.exists():
        sys.exit(0)

    try:
        content = FAILURES_PATH.read_text(encoding="utf-8")
    except Exception:
        sys.exit(0)

    recent = extract_recent_failures(content, MAX_ENTRIES)
    if not recent:
        sys.exit(0)

    inject = (
        "## ⛔ 코드 작업 전 강제 주입 — failures.md 최근 {n}건\n\n"
        "이 내용은 Claude가 Read 도구를 호출하지 않아도 자동 주입됩니다.\n"
        "**코드 첫 줄 전에 아래 항목을 확인하고 위반 패턴 없는지 점검하라.**\n\n"
        "{entries}\n\n"
        "---\n"
        "**체크리스트 (코드 작성 전 확인):**\n"
        "- [ ] 위 실패 중 지금 작업과 겹치는 패턴 없는가?\n"
        "- [ ] systematic-debugging 스킬이 필요한 진단 작업 아닌가?\n"
        "- [ ] writing-plans 스킬이 필요한 10줄+ 변경 아닌가?\n"
        "- [ ] 완료 선언 전 verification-before-completion 스킬 호출 예정인가?\n"
    ).format(n=MAX_ENTRIES, entries=recent)

    out = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": inject,
        }
    }
    json.dump(out, sys.stdout, ensure_ascii=False)
    sys.exit(0)


if __name__ == "__main__":
    main()
