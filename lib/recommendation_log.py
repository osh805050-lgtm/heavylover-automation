"""권고 추적 — 매일/주간 리포트의 액션 권고를 누적 저장하고 추적.

logs/recommendations.jsonl (JSON Lines, 1일 1줄):
{"date": "2026-04-29", "agent": "daily", "action": "...", "target": "M+1", "target_value": 16}

다음 리포트가 1주일 전 권고를 조회해 "실행됐나? 효과 있었나?" 자동 평가.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
LOG_PATH = Path(__file__).parent.parent / "logs" / "recommendations.jsonl"


def append(date: str, agent: str, action: str, target_metric: str = "", target_value=None) -> None:
    """권고 1줄 append. 실패해도 메인 리포트가 죽지 않게 silent."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        rec = {
            "date": date,
            "agent": agent,
            "action": action,
            "target_metric": target_metric,
            "target_value": target_value,
        }
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def load_recent(days: int = 14) -> list[dict]:
    """최근 N일 권고를 시간 오름차순으로 반환."""
    if not LOG_PATH.exists():
        return []
    cutoff = (datetime.now(KST).date() - timedelta(days=days)).isoformat()
    out = []
    try:
        for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("date", "") >= cutoff:
                out.append(rec)
    except Exception:
        return []
    return out


def format_for_prompt(days: int = 7) -> str:
    """프롬프트에 주입할 텍스트 (최근 권고 + 평가 안내)."""
    recent = load_recent(days=days)
    if not recent:
        return "지난 권고 없음 (첫 리포트)."

    lines = ["**지난 권고 추적 (오래된 것부터)**:"]
    for r in recent:
        action = r.get("action", "")[:120]
        lines.append(f"- {r.get('date')} [{r.get('agent')}] {action}")
    lines.append("")
    lines.append("위 권고가 이번 주 데이터에 반영됐는지 평가하고, 그 결과를 다음 권고에 반영하라.")
    return "\n".join(lines)
