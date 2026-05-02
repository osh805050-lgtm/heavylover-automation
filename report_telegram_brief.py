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
    headline = _build_headline(cur.get("매출"), mom, m1, rate_1to2, flags)

    # 색상 플래그
    flag_sales = "🔴" if (mom is not None and mom < -30) else ("🟡" if (mom is not None and mom < 0) else "🟢")
    flag_1to2 = _flag_emoji(rate_1to2, 30, severity_pct=15)
    flag_m1 = _flag_emoji(m1, 20, severity_pct=15)
    flag_p50 = "🟢"  # 정상 범위 14~16일

    # 포맷 통일
    mom_str = f"{mom:+.2f}%" if mom is not None else "—"
    wow_str = f"{matrix_wow:+.2f}%" if matrix_wow is not None else None
    rate_str = f"{rate_1to2:.2f}%" if rate_1to2 is not None else "—"
    m1_str = f"{m1:.2f}%" if m1 is not None else "—"

    lines = [
        f"📊 헤비로버 재구매 {today}",
        "",
        f"핵심: {headline}",
        "",
        "━━━ 주요 지표 ━━━",
        f"{flag_sales} 당월 재구매 매출",
        f"   {_format_kr_money(cur.get('매출'))}",
        f"   전월대비 {mom_str} {_delta_arrow(mom)}" if mom is not None else "   전월대비 —",
    ]
    if wow_str is not None:
        lines.append(f"   전주대비 {wow_str} {_delta_arrow(matrix_wow)}")
    lines.append("")

    lines.extend([
        f"{flag_1to2} 1→2번째 구매 전환율",
        f"   {rate_str} (목표 30%)",
        "",
        f"{flag_m1} 첫 구매 후 한달 재구매율",
        f"   {m1_str} (목표 20%)",
        "",
        f"{flag_p50} 재구매 간격 중앙값",
        f"   {p50}  (고객 절반이 이 기간 안에 다시 구매)",
        "",
    ])

    if flags:
        lines.append("⚠️ 이상한 움직임 감지 (평균 대비 크게 벗어남):")
        for f in flags[:3]:
            direction = "급등" if f.get("방향") in ("급등", "개선") else "급락"
            lines.append(f"  • {f.get('지표')} {direction}")
    else:
        lines.append("✓ 특이 이상치 없음")

    lines.append("")
    lines.append("📧 심층 분석 → 메일 확인")

    return "\n".join(lines)


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
