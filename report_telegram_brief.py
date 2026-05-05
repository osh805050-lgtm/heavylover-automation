"""매일 09:05 텔레그램 30초 요약.

이메일 심층 분석으로 가기 전 핵심 지표 + 이상치 플래그만.
Claude API 호출 없음 (비용 0).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Windows 콘솔 cp949 회피
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from sheets_sync import _open_sheet
from repurchase_report import build_ground_truth
from telegram_client import send_message
from lib.historical_data import enrich

KST = timezone(timedelta(hours=9))


def _format_kr_money(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{int(v):,}원"
    except (ValueError, TypeError):
        return "—"


def _flag_emoji(value, target: float, lower_is_better: bool = False, severity_pct: float = 20) -> str:
    """벤치 대비 색상 플래그. severity_pct 이상 차이는 🔴, 그 미만은 🟡, 충족은 🟢."""
    if value is None:
        return "—"
    try:
        v = float(value)
    except (ValueError, TypeError):
        return "—"
    diff_pct = ((target - v) / target * 100) if not lower_is_better else ((v - target) / target * 100)
    if diff_pct <= 0:
        return "🟢"
    if diff_pct < severity_pct:
        return "🟡"
    return "🔴"


def _delta_arrow(value, higher_is_better: bool = True) -> str:
    if value is None:
        return ""
    try:
        v = float(value)
    except (ValueError, TypeError):
        return ""
    if v > 0:
        return "↑" if higher_is_better else "↓"
    if v < 0:
        return "↓" if higher_is_better else "↑"
    return "→"


def _build_headline(cur_sales, mom, m1, rate_1to2, flags) -> str:
    """가장 큰 신호를 헤드라인 1줄로."""
    candidates = []
    if m1 is not None and m1 < 14:
        candidates.append((20 - m1, f"🔴 첫달 재구매율(M+1) {m1}% — 목표 20% 대비 {round(20-m1, 1)}%p 미달"))
    if rate_1to2 is not None and rate_1to2 < 20:
        candidates.append((30 - rate_1to2, f"🔴 1→2번째 구매 전환 {rate_1to2}% — 목표 30% 대비 {round(30-rate_1to2, 1)}%p 미달"))
    if mom is not None and mom < -30:
        candidates.append((abs(mom), f"🔴 당월 매출 전월대비 {mom}% — 큰 폭 하락 점검 필요"))
    if flags:
        f = flags[0]
        candidates.append((10, f"⚠️ 통계 이상치 — {f.get('지표')} {f.get('방향')} (z={f.get('z_score')})"))
    if not candidates:
        return "🟢 핵심 지표 정상 범위 — 큰 변화 없음"
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def build_brief(gt: dict) -> str:
    enriched = enrich(gt)
    inm = gt.get("월별_재구매_매출", {}).get("통합", {}) or {}
    cur = inm.get("당월", {}) or {}
    mom = inm.get("MoM_변화_pct")

    stages = gt.get("단계별_전환율_현재", {}).get("통합") or []
    stage_1to2 = next((s for s in stages if s.get("단계") == "1→2"), {}) or {}
    rate_1to2 = stage_1to2.get("전환율")

    mn = gt.get("M+N_리텐션_통합") or []
    m1 = mn[-1].get("M+1") if mn else None

    interval = gt.get("재구매_간격") or {}
    p50 = interval.get("P50") or interval.get("중앙값") or "—"

    wow = enriched.get("WoW_비교") or {}
    matrix_wow = wow.get("당월_매출_WoW_pct")
    flags = enriched.get("이상치_플래그") or []

    today = datetime.now(KST).strftime("%Y-%m-%d")

    # ── 주의/액션 항목 수집 ──────────────────────────────────
    alerts = []  # (우선순위, 항목명, 현재값, 이유, 액션)

    if mom is not None and mom < -30:
        alerts.append((
            3,
            "재구매 매출 급락",
            f"전월대비 {mom:+.1f}%",
            "한 달 사이 큰 폭 하락 — 광고 소재 피로 또는 계절 요인 가능성",
            "광고 ROAS 확인 후 위너 소재 재투입 검토",
        ))
    elif mom is not None and mom < 0:
        alerts.append((
            1,
            "재구매 매출 소폭 감소",
            f"전월대비 {mom:+.1f}%",
            "전월 대비 감소 — 5% 이내면 정상 변동 범위",
            "이달 말까지 추이 모니터링",
        ))

    if rate_1to2 is not None and rate_1to2 < 20:
        alerts.append((
            3,
            "1→2 전환율 위험",
            f"{rate_1to2:.1f}% (목표 30%)",
            f"첫 구매 후 재구매로 이어지는 비율이 목표 대비 {round(30 - rate_1to2, 1)}%p 부족",
            "구매 후 3일·10일 리마인드 메시지 발송 점검",
        ))
    elif rate_1to2 is not None and rate_1to2 < 25:
        alerts.append((
            2,
            "1→2 전환율 주의",
            f"{rate_1to2:.1f}% (목표 30%)",
            f"목표 대비 {round(30 - rate_1to2, 1)}%p 부족 — 개선 여지 있음",
            "재구매 유도 쿠폰 or 리마인드 타이밍 검토",
        ))

    if m1 is not None and m1 < 14:
        alerts.append((
            3,
            "M+1 리텐션 위험",
            f"{m1:.1f}% (목표 20%)",
            f"첫 구매 후 한 달 내 돌아오는 비율 목표 대비 {round(20 - m1, 1)}%p 미달",
            "첫 구매 고객 대상 Day 10 전후 쿠폰 발송 확인",
        ))
    elif m1 is not None and m1 < 17:
        alerts.append((
            1,
            "M+1 리텐션 주의",
            f"{m1:.1f}% (목표 20%)",
            f"목표 대비 {round(20 - m1, 1)}%p 부족",
            "CRM 시퀀스 발송 이력 확인",
        ))

    if matrix_wow is not None and abs(matrix_wow) > 20:
        direction = "급등" if matrix_wow > 0 else "급락"
        alerts.append((
            2,
            f"주간 매출 {direction}",
            f"전주대비 {matrix_wow:+.1f}%",
            "단기 급변 — 프로모션·광고 변화 여부 확인 필요",
            "광고 예산·소재 변경 이력 대조",
        ))

    for f in flags[:2]:
        direction = "급등" if f.get("방향") in ("급등", "개선") else "급락"
        alerts.append((
            1,
            f"이상치: {f.get('지표')} {direction}",
            f"z={f.get('z_score')}",
            "평균 대비 통계적으로 크게 벗어남",
            "메일 심층 분석 확인",
        ))

    alerts.sort(key=lambda x: x[0], reverse=True)

    # ── 메시지 조립 ───────────────────────────────────────────
    lines = [f"📊 헤비로버 재구매 {today}", ""]

    if not alerts:
        lines += [
            "🟢 오늘 특이사항 없음",
            "",
            f"재구매 매출 전월대비 {mom:+.1f}%" if mom is not None else "",
            f"1→2 전환율 {rate_1to2:.1f}%" if rate_1to2 is not None else "",
            f"M+1 리텐션 {m1:.1f}%" if m1 is not None else "",
        ]
    else:
        for _, name, val, reason, action in alerts:
            icon = "🔴" if _ == 3 else "🟡"
            lines += [
                f"{icon} {name} | {val}",
                f"   이유: {reason}",
                f"   액션: {action}",
                "",
            ]

    lines += ["📧 상세 → 메일 확인"]
    return "\n".join(l for l in lines if l is not None)


def main() -> int:
    try:
        ss = _open_sheet()
        gt = build_ground_truth(ss)
        msg = build_brief(gt)
        send_message(msg, channel="report")
        print(f"[{datetime.now(KST).strftime('%H:%M:%S')}] 텔레그램 요약 발송 완료")
        return 0
    except Exception as e:
        err = f"🚨 텔레그램 요약 실패: {e}"
        print(err)
        try:
            send_message(err, channel="ops")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
