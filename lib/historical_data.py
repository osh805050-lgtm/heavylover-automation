"""누적 ground_truth 분석 — 시계열·WoW·YoY·이상치.

repurchase_report.py가 매일 logs/gt_YYYY-MM-DD.json에 ground_truth를 저장.
이 모듈은 그걸 읽어 비교·이상치 감지 데이터를 추가 주입한다.

원칙:
- Claude API 호출 X (모두 Python 계산)
- 실패해도 빈 dict 반환 (메인 리포트가 죽지 않게)
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
LOG_DIR = Path(__file__).parent.parent / "logs"


def load_recent_gt(days: int = 7) -> list[dict]:
    """최근 N일치 gt_*.json을 날짜 오름차순으로 반환."""
    if not LOG_DIR.exists():
        return []
    today = datetime.now(KST).date()
    out = []
    for i in range(days, 0, -1):
        d = today - timedelta(days=i)
        f = LOG_DIR / f"gt_{d.strftime('%Y-%m-%d')}.json"
        if f.exists():
            try:
                out.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                continue
    return out


def _safe_pct(cur, prev) -> float | None:
    if cur is None or prev in (None, 0):
        return None
    try:
        return round((float(cur) - float(prev)) / float(prev) * 100, 1)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def compute_wow(gt: dict, history: list[dict]) -> dict:
    """이번 주 vs 지난 주 핵심 지표 비교.

    history: 최근 7일 gt 리스트.
    오늘 gt와 7일 전 gt를 비교.
    """
    if not history:
        return {}

    # 7일 전(history[0])과 오늘(gt) 비교
    prev = history[0]

    cur_inm = gt.get("월별_재구매_매출", {}).get("통합", {}).get("당월", {}) or {}
    prev_inm = prev.get("월별_재구매_매출", {}).get("통합", {}).get("당월", {}) or {}

    cur_stage = gt.get("단계별_전환율_현재", {}).get("통합") or []
    prev_stage = prev.get("단계별_전환율_현재", {}).get("통합") or []

    def _stage_rate(stages, key="1→2"):
        for s in stages:
            if s.get("단계") == key:
                return s.get("전환율")
        return None

    return {
        "기준일": prev.get("리포트_날짜"),
        "당월_매출_WoW_pct": _safe_pct(cur_inm.get("매출"), prev_inm.get("매출")),
        "재구매자수_WoW_pct": _safe_pct(cur_inm.get("재구매자수"), prev_inm.get("재구매자수")),
        "1→2전환율_WoW_pp": _delta_pp(_stage_rate(cur_stage, "1→2"), _stage_rate(prev_stage, "1→2")),
        "2→3전환율_WoW_pp": _delta_pp(_stage_rate(cur_stage, "2→3"), _stage_rate(prev_stage, "2→3")),
    }


def _delta_pp(cur, prev) -> float | None:
    if cur is None or prev is None:
        return None
    try:
        return round(float(cur) - float(prev), 2)
    except (TypeError, ValueError):
        return None


def flag_anomalies(gt: dict, history: list[dict]) -> list[dict]:
    """7일 평균 ±2σ 벗어난 지표 자동 플래그.

    history < 5개면 신뢰성 낮아 빈 리스트 반환.
    """
    if len(history) < 5:
        return []

    flags = []

    # 당월 매출 시계열
    series = []
    for h in history:
        v = h.get("월별_재구매_매출", {}).get("통합", {}).get("당월", {}).get("매출")
        if isinstance(v, (int, float)):
            series.append(float(v))
    if len(series) >= 5:
        mean = statistics.mean(series)
        sd = statistics.stdev(series) if len(series) > 1 else 0
        cur = gt.get("월별_재구매_매출", {}).get("통합", {}).get("당월", {}).get("매출")
        if isinstance(cur, (int, float)) and sd > 0:
            z = (float(cur) - mean) / sd
            if abs(z) >= 2:
                flags.append({
                    "지표": "당월 재구매 매출",
                    "현재값": cur,
                    "7일평균": round(mean, 0),
                    "z_score": round(z, 2),
                    "방향": "급등" if z > 0 else "급락",
                })

    # 1→2 전환율
    series = []
    for h in history:
        stages = h.get("단계별_전환율_현재", {}).get("통합") or []
        for s in stages:
            if s.get("단계") == "1→2" and isinstance(s.get("전환율"), (int, float)):
                series.append(float(s["전환율"]))
                break
    if len(series) >= 5:
        mean = statistics.mean(series)
        sd = statistics.stdev(series) if len(series) > 1 else 0
        cur_stages = gt.get("단계별_전환율_현재", {}).get("통합") or []
        cur = next((s.get("전환율") for s in cur_stages if s.get("단계") == "1→2"), None)
        if isinstance(cur, (int, float)) and sd > 0:
            z = (float(cur) - mean) / sd
            if abs(z) >= 2:
                flags.append({
                    "지표": "1→2 전환율",
                    "현재값": cur,
                    "7일평균": round(mean, 2),
                    "z_score": round(z, 2),
                    "방향": "개선" if z > 0 else "악화",
                })

    return flags


def enrich(gt: dict) -> dict:
    """gt를 받아 history·WoW·anomalies 추가한 enriched dict 반환.

    실패해도 원본 gt 보존하며 추가 키만 비울 수 있게.
    """
    try:
        history = load_recent_gt(days=7)
    except Exception:
        history = []

    enriched = dict(gt)
    enriched["_history_count"] = len(history)
    try:
        enriched["WoW_비교"] = compute_wow(gt, history)
    except Exception as e:
        enriched["WoW_비교"] = {"error": str(e)}
    try:
        enriched["이상치_플래그"] = flag_anomalies(gt, history)
    except Exception as e:
        enriched["이상치_플래그"] = []
    return enriched
