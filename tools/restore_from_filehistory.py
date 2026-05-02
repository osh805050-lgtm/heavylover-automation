"""
Claude file-history에서 사라진 .md 파일을 자동 복원
- file-history의 모든 @vN 파일에서 첫 줄(헤더) 읽고 위치 매칭
- 가장 최신 mtime 버전을 선택
"""
import os
import re
import shutil
from pathlib import Path

FH_DIR = Path("c:/Users/osh80/.claude/file-history/0941ed83-b2bd-4bf7-9921-1b9253974e0c")
ROOT   = Path("c:/Users/osh80/OneDrive/바탕 화면/heavylover-automation")

# 헤더(첫 줄) 패턴 → 복원 위치 매핑
TARGETS = [
    # (헤더 정규식, 복원 위치)
    (r"^# Round 1: 독립 분석",        "docs/analysis_10b/rounds/round-01-independent.md"),
    (r"^# Round 2: 상호 검토",         "docs/analysis_10b/rounds/round-02-crosscheck.md"),
    (r"^# Round 3: 비판",              "docs/analysis_10b/rounds/round-03-critic-1.md"),
    (r"^# Round 4: 외부",              "docs/analysis_10b/rounds/round-04-external-cases.md"),
    (r"^# Round 5: 스트레스",          "docs/analysis_10b/rounds/round-05-stress-test.md"),
    (r"^# Round 6: 가정",              "docs/analysis_10b/rounds/round-06-assumption-flip.md"),
    (r"^# Round 7: 시간",              "docs/analysis_10b/rounds/round-07-time-pressure.md"),
    (r"^# Round 8: 우선순위",          "docs/analysis_10b/rounds/round-08-tournament.md"),
    (r"^# Round 9:",                   "docs/analysis_10b/rounds/round-09-critic-2.md"),
    (r"^# Round 10: 최종 통합",         "docs/analysis_10b/rounds/round-10-synthesis.md"),
    (r"^# 현금흐름 시뮬레이션",         "docs/analysis_10b/cashflow_simulation.md"),
]

# proposal 에이전트들 (헤더로 식별)
PROPOSAL_AGENTS = [
    (r"name:\s*proposal-drafter",        ".claude/agents/proposal/proposal-drafter.md"),
    (r"name:\s*proposal-rubric-mapper",  ".claude/agents/proposal/proposal-rubric-mapper.md"),
    (r"name:\s*proposal-consistency",    ".claude/agents/proposal/proposal-consistency.md"),
    (r"name:\s*proposal-budget-auditor", ".claude/agents/proposal/proposal-budget-auditor.md"),
    (r"name:\s*proposal-competitor",     ".claude/agents/proposal/proposal-competitor.md"),
    (r"name:\s*proposal-fact-checker",   ".claude/agents/proposal/proposal-fact-checker.md"),
    (r"name:\s*proposal-devil",          ".claude/agents/proposal/proposal-devil.md"),
]

# strategy / expansion / analysis 에이전트
OTHER_AGENTS = [
    (r"name:\s*strategy-orchestrator",    ".claude/agents/strategy/strategy-orchestrator.md"),
    (r"name:\s*strategy-margin",          ".claude/agents/strategy/strategy-margin-fundamentalist.md"),
    (r"name:\s*strategy-acquisition",     ".claude/agents/strategy/strategy-acquisition-maximalist.md"),
    (r"name:\s*strategy-structural",      ".claude/agents/strategy/strategy-structural-pessimist.md"),
    (r"name:\s*strategy-capital",         ".claude/agents/strategy/strategy-capital-allocator.md"),
    (r"name:\s*strategy-identity",        ".claude/agents/strategy/strategy-identity-challenger.md"),
    (r"name:\s*analysis-orchestrator",    ".claude/agents/analysis/analysis-orchestrator.md"),
    (r"name:\s*agent-cfo",                ".claude/agents/analysis/agent-cfo.md"),
    (r"name:\s*agent-cmo",                ".claude/agents/analysis/agent-cmo.md"),
    (r"name:\s*agent-coo",                ".claude/agents/analysis/agent-coo.md"),
    (r"name:\s*agent-customer",           ".claude/agents/analysis/agent-customer.md"),
    (r"name:\s*agent-competitor",         ".claude/agents/analysis/agent-competitor.md"),
    (r"name:\s*agent-growth",             ".claude/agents/analysis/agent-growth.md"),
    (r"name:\s*agent-critic",             ".claude/agents/analysis/agent-critic.md"),
    (r"name:\s*expansion-orchestrator",   ".claude/agents/expansion/expansion-orchestrator.md"),
    (r"name:\s*domain-[a-f]-",            None),  # 동적 매칭
]


def scan_filehistory():
    """모든 file-history 파일 → {hash: [(path, mtime, content_first_500)]}"""
    files_by_hash = {}
    for f in FH_DIR.iterdir():
        if not f.is_file():
            continue
        # hash@vN 형식
        m = re.match(r"([a-f0-9]+)@v(\d+)$", f.name)
        if not m:
            continue
        hash_id = m.group(1)
        version = int(m.group(2))
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")[:1000]
        except Exception:
            continue
        files_by_hash.setdefault(hash_id, []).append((f, version, f.stat().st_mtime, content))
    # 각 hash별로 최신 버전만
    latest = {}
    for h, vs in files_by_hash.items():
        vs.sort(key=lambda x: (x[1], x[2]), reverse=True)  # 버전 → mtime 내림차순
        latest[h] = vs[0]
    return latest


def restore():
    latest = scan_filehistory()
    print(f"[스캔] file-history {len(latest)}개 hash")

    all_targets = TARGETS + PROPOSAL_AGENTS + OTHER_AGENTS
    restored = []
    skipped = []

    for pattern, dest_rel in all_targets:
        if dest_rel is None:
            continue
        dest = ROOT / dest_rel
        if dest.exists():
            skipped.append(f"이미 존재: {dest_rel}")
            continue

        # file-history에서 패턴 매칭
        candidates = []
        for h, (path, version, mtime, content) in latest.items():
            if re.search(pattern, content, re.MULTILINE):
                candidates.append((path, mtime, len(content)))

        if not candidates:
            skipped.append(f"백업 없음: {dest_rel}")
            continue

        # 가장 최신 mtime + 가장 큰 파일 선택
        candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)
        src = candidates[0][0]

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dest))
        restored.append(f"{dest_rel} ← {src.name}")

    print(f"\n[복원 완료] {len(restored)}개")
    for r in restored:
        print(f"  + {r}")

    print(f"\n[건너뜀] {len(skipped)}개")
    for s in skipped:
        print(f"  - {s}")


if __name__ == "__main__":
    restore()
