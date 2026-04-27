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


def _trend_icon(pp_or_pct, higher_is_better=True) -> str:
    if pp_or_pct is None:
        return ""
    try:
        v = float(pp_or_pct)
    except (ValueError, TypeError):
        return ""
    if v > 0:
        return "↑" if higher_is_better else "↓⚠️"
    if v < 0:
        return "↓⚠️" if higher_is_better else "↑"
    return "—"


def build_brief(gt: dict) -> str:
    enriched = enrich(gt)
    inm = gt.get("월별_재구매_매출", {}).get("통합", {}) or {}
    cur = inm.get("당월", {}) or {}
    mom = inm.get("MoM_변화_pct")

    stages = gt.get("단계별_전환율_현재", {}).get("통합") or []
    stage_1to2 = next((s for s in stages if s.get("단계") == "1→2"), {}) or {}

    mn = gt.get("M+N_리텐션_통합") or []
    m1 = mn[-1].get("M+1") if mn else None

    interval = gt.get("재구매_간격") or {}
    p50 = interval.get("P50") or interval.get("중앙값") or "?"

    wow = enriched.get("WoW_비교") or {}
    matrix_wow = wow.get("당월_매출_WoW_pct")

    flags = enriched.get("이상치_플래그") or []

    today = datetime.now(KST).strftime("%Y-%m-%d")
    lines = [
        f"📊 재구매 요약 {today}",
        "",
        f"당월 매출: {_format_kr_money(cur.get('매출'))} (MoM {mom}% {_trend_icon(mom)})",
    ]
    if matrix_wow is not None:
        lines.append(f"WoW(7일전 대비): {matrix_wow}% {_trend_icon(matrix_wow)}")

    rate_1to2 = stage_1to2.get("전환율")
    rate_str = f"{rate_1to2}%" if rate_1to2 is not None else "—"
    lines.append(f"1→2 전환: {rate_str} (목표 30%)")

    if m1 is not None:
        lines.append(f"M+1 리텐션: {m1}% (벤치 20%)")

    p50_str = p50 if p50 else "—"
    lines.append(f"재구매 간격 P50: {p50_str}")

    if flags:
        lines.append("")
        lines.append("⚠️ 이상치:")
        for f in flags[:3]:
            lines.append(f"  - {f.get('지표')} {f.get('방향')} (z={f.get('z_score')})")

    lines.append("")
    lines.append("상세 분석은 이메일 확인.")

    return "\n".join(lines)


def main() -> int:
    try:
        ss = _open_sheet()
        gt = build_ground_truth(ss)
        msg = build_brief(gt)
        send_message(msg)
        print(f"[{datetime.now(KST).strftime('%H:%M:%S')}] 텔레그램 요약 발송 완료")
        return 0
    except Exception as e:
        err = f"🚨 텔레그램 요약 실패: {e}"
        print(err)
        try:
            send_message(err)
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
