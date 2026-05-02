"""
2차 복원 — 1차에서 빠진 strategy/expansion outputs, data/analysis_10b/*, _master.md, commands 전체.
모든 file-history 세션 스캔 + 패턴 매칭 + 가장 최신·큰 파일 우선.
"""
import os, re, shutil
from pathlib import Path

FH_ROOT = Path("c:/Users/osh80/.claude/file-history")
ROOT    = Path("c:/Users/osh80/OneDrive/바탕 화면/heavylover-automation")

# (식별 패턴, 적용 위치(head/full), 복원 위치)
TARGETS = [
    # strategy outputs (라운드별 헤더로 식별)
    (r"# Round 1: 현재 진단",               "head", "docs/strategy/outputs/2026-04-29-round1-diagnosis.md"),
    (r"# Round 2: 10억 경로",                "head", "docs/strategy/outputs/2026-04-29-round2-path.md"),
    (r"# Round 3: 자본 배분",                "head", "docs/strategy/outputs/2026-04-29-round3-capital.md"),
    (r"# Round 4: 위험 시나리오",            "head", "docs/strategy/outputs/2026-04-29-round4-risk.md"),
    (r"# Round 5: Kill Criteria",            "head", "docs/strategy/outputs/2026-04-29-round5-kill-criteria.md"),
    (r"# 6개월 로드맵",                      "head", "docs/strategy/outputs/2026-04-29-08_6m_roadmap.md"),

    # expansion outputs (도메인별)
    (r"# Domain A.*크리에이티브",            "head", "docs/expansion/outputs/domain-a-creative.md"),
    (r"# Domain B.*CRM",                     "head", "docs/expansion/outputs/domain-b-crm.md"),
    (r"# Domain C.*채널",                    "head", "docs/expansion/outputs/domain-c-channel.md"),
    (r"# Domain D.*가격",                    "head", "docs/expansion/outputs/domain-d-pricing.md"),
    (r"# Domain E.*콘텐츠",                  "head", "docs/expansion/outputs/domain-e-content.md"),
    (r"# Domain F.*B2B",                     "head", "docs/expansion/outputs/domain-f-b2b.md"),
    (r"# expansion-synthesis",               "head", "docs/expansion/outputs/expansion-synthesis.md"),

    # 분석 IC 리포트
    (r"^# 10억 달성 IC 진단 리포트",         "head", "docs/analysis_10b/_master.md"),
    (r"# 2026-02 코호트.*원인",              "head", "docs/analysis_10b/cohort_funnel_diagnosis.md"),

    # 데이터 (JSON 첫 키로 식별)
    (r'"unit_economics"|"LTV":\s*\d|"CAC":\s*\d', "head", "data/analysis_10b/unit_economics.json"),
    (r'"bridge_scenarios"|"bear":|"base":|"bull":',"head", "data/analysis_10b/bridge_10b.json"),

    # commands
    (r"^# 헤비로버 성장전략 갑론을박",       "head", ".claude/commands/strategy-debate.md"),
    (r"^# /expansion-debate",                "head", ".claude/commands/expansion-debate.md"),
    (r"^# /analysis-10b",                    "head", ".claude/commands/analysis-10b.md"),
]


def scan_all_filehistory():
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
            cache.append({
                "path": f,
                "version": int(m.group(2)),
                "mtime": f.stat().st_mtime,
                "size": f.stat().st_size,
                "head": content[:3000],
                "full": content,
            })
    return cache


def restore(cache, pattern, where, dest_rel):
    dest = ROOT / dest_rel
    if dest.exists() and dest.stat().st_size > 0:
        return f"이미 존재: {dest_rel}"

    candidates = []
    for entry in cache:
        text = entry[where]
        if re.search(pattern, text, re.MULTILINE):
            candidates.append(entry)

    if not candidates:
        return f"백업 없음: {dest_rel}"

    candidates.sort(key=lambda e: (e["mtime"], e["size"]), reverse=True)
    best = candidates[0]

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(best["path"]), str(dest))
    return f"복원: {dest_rel} ← {best['path'].parent.name[:8]}/{best['path'].name} ({best['size']:,}b, {len(candidates)}개 후보)"


def main():
    print("[스캔 중] 모든 file-history 세션...")
    cache = scan_all_filehistory()
    print(f"[스캔 완료] {len(cache)}개 파일 인덱싱\n")

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
    if skipped:
        print(f"\n[건너뜀] {len(skipped)}개")
        for s in skipped:
            print(f"  = {s}")
    if missing:
        print(f"\n[백업 없음] {len(missing)}개")
        for m in missing:
            print(f"  - {m}")


if __name__ == "__main__":
    main()
