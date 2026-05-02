"""
file-history의 모든 세션 디렉토리를 스캔해서 누락 파일 복원.
첫 줄 또는 frontmatter 정확 매칭 + 가장 최신 mtime + 가장 큰 파일 우선.
"""
import os, re, shutil
from pathlib import Path

FH_ROOT = Path("c:/Users/osh80/.claude/file-history")
ROOT    = Path("c:/Users/osh80/OneDrive/바탕 화면/heavylover-automation")

# (식별 패턴, 패턴 적용 위치(head/full), 복원 위치)
TARGETS = [
    # proposals/knowledge 핵심 2개
    (r'"purpose":\s*"PSST 4P', "head", "proposals/knowledge/psst-rubric.json"),
    (r"^# 헤비로버 공통 뼈대", "head", "proposals/knowledge/heavylover-skeleton.md"),

    # proposal 에이전트 7개 (frontmatter name 매칭)
    (r"^name:\s*proposal-drafter\b",        "head", ".claude/agents/proposal/proposal-drafter.md"),
    (r"^name:\s*proposal-rubric-mapper\b",  "head", ".claude/agents/proposal/proposal-rubric-mapper.md"),
    (r"^name:\s*proposal-consistency\b",    "head", ".claude/agents/proposal/proposal-consistency.md"),
    (r"^name:\s*proposal-budget-auditor\b", "head", ".claude/agents/proposal/proposal-budget-auditor.md"),
    (r"^name:\s*proposal-competitor\b",     "head", ".claude/agents/proposal/proposal-competitor.md"),
    (r"^name:\s*proposal-fact-checker\b",   "head", ".claude/agents/proposal/proposal-fact-checker.md"),
    (r"^name:\s*proposal-devil\b",          "head", ".claude/agents/proposal/proposal-devil.md"),

    # expansion domain 12개
    (r"^name:\s*domain-a-creative-proposer\b",   "head", ".claude/agents/expansion/domain-a-creative-proposer.md"),
    (r"^name:\s*domain-a-creative-challenger\b", "head", ".claude/agents/expansion/domain-a-creative-challenger.md"),
    (r"^name:\s*domain-b-crm-proposer\b",        "head", ".claude/agents/expansion/domain-b-crm-proposer.md"),
    (r"^name:\s*domain-b-crm-challenger\b",      "head", ".claude/agents/expansion/domain-b-crm-challenger.md"),
    (r"^name:\s*domain-c-channel-proposer\b",    "head", ".claude/agents/expansion/domain-c-channel-proposer.md"),
    (r"^name:\s*domain-c-channel-challenger\b",  "head", ".claude/agents/expansion/domain-c-channel-challenger.md"),
    (r"^name:\s*domain-d-pricing-proposer\b",    "head", ".claude/agents/expansion/domain-d-pricing-proposer.md"),
    (r"^name:\s*domain-d-pricing-challenger\b",  "head", ".claude/agents/expansion/domain-d-pricing-challenger.md"),
    (r"^name:\s*domain-e-content-proposer\b",    "head", ".claude/agents/expansion/domain-e-content-proposer.md"),
    (r"^name:\s*domain-e-content-challenger\b",  "head", ".claude/agents/expansion/domain-e-content-challenger.md"),
    (r"^name:\s*domain-f-b2b-proposer\b",        "head", ".claude/agents/expansion/domain-f-b2b-proposer.md"),
    (r"^name:\s*domain-f-b2b-challenger\b",      "head", ".claude/agents/expansion/domain-f-b2b-challenger.md"),
]


def scan_all_filehistory():
    """모든 세션의 모든 @vN 파일을 한 번 읽어 캐시"""
    cache = []
    for session_dir in FH_ROOT.iterdir():
        if not session_dir.is_dir():
            continue
        for f in session_dir.iterdir():
            if not f.is_file():
                continue
            m = re.match(r"([a-f0-9]+)@v(\d+)$", f.name)
            if not m:
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            head = content[:2000]
            cache.append({
                "path": f,
                "version": int(m.group(2)),
                "mtime": f.stat().st_mtime,
                "size": f.stat().st_size,
                "head": head,
                "full": content,  # 작은 메모리 부담 OK
            })
    return cache


def restore(cache, pattern, where, dest_rel):
    dest = ROOT / dest_rel
    if dest.exists():
        return f"이미 존재: {dest_rel}"

    candidates = []
    for entry in cache:
        text = entry[where]
        if re.search(pattern, text, re.MULTILINE):
            candidates.append(entry)

    if not candidates:
        return f"백업 없음: {dest_rel}"

    # 가장 최신 mtime + 큰 파일
    candidates.sort(key=lambda e: (e["mtime"], e["size"]), reverse=True)
    best = candidates[0]

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(best["path"]), str(dest))
    return f"복원: {dest_rel} ← {best['path'].parent.name[:8]}/{best['path'].name} ({best['size']:,}b)"


def main():
    print("[스캔 중] 모든 file-history 세션...")
    cache = scan_all_filehistory()
    print(f"[스캔 완료] {len(cache)}개 파일 인덱싱")
    print()

    restored, skipped, missing = [], [], []
    for pattern, where, dest_rel in TARGETS:
        result = restore(cache, pattern, where, dest_rel)
        if result.startswith("복원:"):
            restored.append(result)
        elif result.startswith("이미"):
            skipped.append(result)
        else:
            missing.append(result)

    print(f"[복원 완료] {len(restored)}개")
    for r in restored:
        print(f"  + {r}")
    print()
    if skipped:
        print(f"[건너뜀] {len(skipped)}개")
        for s in skipped:
            print(f"  = {s}")
        print()
    if missing:
        print(f"[백업 없음] {len(missing)}개")
        for m in missing:
            print(f"  - {m}")


if __name__ == "__main__":
    main()
