#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patterns.md 키워드 기반 자동 주입 hook (UserPromptSubmit)

작동 방식:
1. Claude Code가 사용자 프롬프트를 받기 직전에 이 스크립트를 실행
2. stdin으로 hook payload(JSON) 수신 → 'prompt' 필드 추출
3. 8개 카테고리 키워드 정규식과 매칭
4. 매칭된 카테고리만 docs/lessons/patterns.md에서 추출해 system context로 주입
5. 매칭 0건이면 아무것도 주입 안 함 (토큰 낭비 X)

오류 시 무조건 exit 0 (Claude 작업을 막지 않는다).
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

KEYWORDS = {
    "§자동화점검": r"자동화|automation|cron|vultr|pluscl|배포|crontab|\.env|발주|송장|텔레그램|telegram",
    "§외부API다루기": r"\bAPI\b|api|cafe24|카페24|naver|네이버|meta|메타|oauth|토큰|anthropic|스마트스토어|productorder|webhook",
    "§시간중복처리": r"중복|dedup|윈도우|hours_back|days_back|cutoff|동기화|\bsync\b|paymentdate|결제일",
    # "분석" 단독 매칭 오주입 방지 — mart_/cohort/repurchase 등 구체적 맥락 동반 시만 매칭
    "§데이터범위와분석분리": r"mart_|cohort|코호트|repurchase|재구매.*분석|분석.*재구매|리포트.*시트|시트.*리포트",
    "§엑셀편집": r"엑셀|excel|openpyxl|xlsx|freeze|숨김|발주.?양식|디자인.*시트",
    "§출력관리": r"장문|5000자|분할|토큰.*초과|출력.*길이",
    "§지역자격필터": r"지역|region|경기|용인|소재지|govt.?radar|정부지원|지원사업|시·군|시군",
    "§환경컨텍스트": r"메일|gmail|naver.*메일|imap|smtp|claude\s*-[cr]|wsl|powershell",
}

# 다중 섹션 매칭 시 최대 개수 (토큰 절약)
MAX_SECTIONS = 2

PATTERNS_PATH = Path(__file__).resolve().parent.parent.parent / "docs" / "lessons" / "patterns.md"


def extract_section(content: str, header: str) -> str:
    """patterns.md에서 '## §카테고리' 섹션 본문 추출 (다음 ## 또는 EOF까지)."""
    pattern = rf"^## {re.escape(header)}.*?(?=^## §|\Z)"
    m = re.search(pattern, content, re.MULTILINE | re.DOTALL)
    return m.group(0).strip() if m else ""


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

    if not PATTERNS_PATH.exists():
        sys.exit(0)

    matched = []
    for header, regex in KEYWORDS.items():
        try:
            if re.search(regex, prompt, re.IGNORECASE):
                matched.append(header)
        except re.error:
            continue

    if not matched:
        sys.exit(0)

    try:
        content = PATTERNS_PATH.read_text(encoding="utf-8")
    except Exception:
        sys.exit(0)

    # 최대 MAX_SECTIONS개 섹션만 주입 (중요도 순: 먼저 매칭된 것 우선)
    sections = []
    for h in matched[:MAX_SECTIONS]:
        s = extract_section(content, h)
        if s:
            sections.append(s)

    if not sections:
        sys.exit(0)

    inject = (
        "## 작업 자동 매칭 패턴 (docs/lessons/patterns.md)\n\n"
        f"감지된 카테고리: {', '.join(matched)}\n\n"
        + "\n\n---\n\n".join(sections)
        + "\n\n**위 회피 규칙을 반영해 작업하라. 사용자 요청이 위반이면 즉시 거부 + 이유 보고. "
        "신규 실수 발생 시 docs/lessons/failures.md 상단에 한 줄 추가.**"
    )

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
