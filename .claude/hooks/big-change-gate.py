#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stop hook: Claude 작업 완료 직전 자동 품질 게이트.

발동 조건:
  - git diff (staged + unstaged) 총 변경 라인 50줄+ OR
  - 변경 파일에 cron / .env / .github/workflows / tracking_ / repurchase_ / api / oauth 키워드

발동 시:
  - python -m pytest 실행 (실패 시 차단)
  - python -m ruff check {변경된 .py 파일만} (실패 시 차단)

통과 시:
  - 큰 변경: systemMessage로 Codex 리뷰 권장
  - 작은 변경: silent exit

차단 시: stdout에 {"decision": "block", "reason": "..."} JSON

오류 시 무조건 exit 0 (Claude 작업을 막지 않는다 — fail-open).
"""
import io
import json
import re
import subprocess
import sys
from pathlib import Path

# UTF-8 안전 출력
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

TRIGGER_PATTERNS = [
    r"cron",
    r"\.env",
    r"\.github[/\\]workflows",
    r"tracking_",
    r"repurchase_",
    r"_api\.py$",
    r"/api/",
    r"oauth",
]

LINE_THRESHOLD = 50


def run(cmd: list[str], cwd: str | None = None, timeout: int = 60) -> tuple[int, str]:
    """subprocess wrapper. UTF-8 safe. timeout 시 (124, output)."""
    try:
        p = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired as e:
        return 124, f"timeout after {timeout}s: {e}"
    except Exception as e:
        return -1, f"subprocess error: {e}"


def parse_diff_stat(stat_out: str) -> tuple[int, list[str]]:
    """git diff --stat 출력 파싱 → (총 라인 수, 변경 파일 리스트)."""
    total = 0
    files: list[str] = []
    pattern = re.compile(r"^\s*(\S.*?)\s+\|\s+(\d+)")
    for line in stat_out.split("\n"):
        m = pattern.match(line)
        if m:
            files.append(m.group(1).strip())
            total += int(m.group(2))
    return total, files


def has_keyword_match(files: list[str]) -> list[str]:
    """변경 파일 중 키워드 매치되는 것 반환."""
    matched: list[str] = []
    for f in files:
        for pat in TRIGGER_PATTERNS:
            if re.search(pat, f, re.IGNORECASE):
                matched.append(f)
                break
    return matched


def emit(payload: dict) -> None:
    """JSON output to stdout."""
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.flush()


def main() -> int:
    # stdin payload (현재 미사용)
    try:
        sys.stdin.read()
    except Exception:
        pass

    # 1) git root
    rc, out = run(["git", "rev-parse", "--show-toplevel"])
    if rc != 0:
        return 0  # not in git repo, skip
    git_root = out.strip().split("\n")[0]

    # 2) git diff --stat
    rc, diff_out = run(["git", "diff", "HEAD", "--stat"], cwd=git_root)
    if rc != 0:
        return 0  # no diff or git error, skip
    total_lines, changed_files = parse_diff_stat(diff_out)

    # 3) 키워드 매치
    matched_files = has_keyword_match(changed_files)

    # 4) 발동 조건
    big_change = total_lines >= LINE_THRESHOLD or bool(matched_files)
    if not big_change:
        return 0

    # 5) pytest 실행 (전체)
    pytest_rc, pytest_out = run(
        [sys.executable, "-m", "pytest"], cwd=git_root, timeout=120
    )

    # 6) ruff: 변경된 .py 파일에만 적용
    changed_py = [f for f in changed_files if f.endswith(".py")]
    ruff_rc = 0
    ruff_out = ""
    if changed_py:
        ruff_rc, ruff_out = run(
            [sys.executable, "-m", "ruff", "check"] + changed_py,
            cwd=git_root,
            timeout=30,
        )

    # 7) 결과 평가
    reasons: list[str] = []
    if pytest_rc != 0:
        tail = "\n".join(pytest_out.split("\n")[-30:])
        reasons.append(f"[pytest 실패] exit={pytest_rc}\n{tail}")
    if ruff_rc != 0:
        tail = "\n".join(ruff_out.split("\n")[-30:])
        reasons.append(f"[ruff 실패 — 변경 파일만] exit={ruff_rc}\n{tail}")

    trigger_info = f"변경 라인 {total_lines}"
    if matched_files:
        trigger_info += f" | 키워드 매치: {', '.join(matched_files)}"

    if reasons:
        reason_text = (
            f"큰 변경 자동 게이트 발동 ({trigger_info})\n\n"
            + "\n\n---\n\n".join(reasons)
            + "\n\n조치:\n"
            "1. systematic-debugging 스킬 호출해 원인 분석\n"
            "2. /codex:rescue 호출해 cross-review\n"
            "3. 수정 후 다시 응답 진행"
        )
        emit({"decision": "block", "reason": reason_text})
    else:
        msg = (
            f"큰 변경 감지 ({trigger_info}). pytest+ruff 통과. "
            f"권장: /codex:rescue 호출해 cross-review."
        )
        emit({"systemMessage": msg})

    return 0


if __name__ == "__main__":
    sys.exit(main())
