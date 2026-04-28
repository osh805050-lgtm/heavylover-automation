"""KPI 카드 HTML 생성 — 메일 본문 상단에 4지표 시각 카드.

휴대폰 첫 화면에 의사결정자가 가장 중요한 4지표를 시각적으로 한 번에 파악하도록.
"""
from __future__ import annotations


def _safe_num(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _format_money(v):
    if v is None:
        return "—"
    try:
        v = int(v)
    except (TypeError, ValueError):
        return "—"
    if v >= 100_000_000:
        return f"{v / 100_000_000:.2f}억"
    if v >= 10_000:
        return f"{v / 10_000:,.0f}만"
    return f"{v:,}원"


def _color_for(value, target: float, severity_pct: float = 20, lower_is_better: bool = False):
    """벤치 대비 색상 (배경, 보더, 글자, 라벨)."""
    if value is None:
        return ("#ecf0f1", "#95a5a6", "#7f8c8d", "—")
    diff = ((target - value) / target * 100) if not lower_is_better else ((value - target) / target * 100)
    if diff <= 0:
        return ("#eafaf1", "#27ae60", "#1e8449", "🟢")
    if diff < severity_pct:
        return ("#fef9e7", "#f39c12", "#9a7d0a", "🟡")
    return ("#fdedec", "#e74c3c", "#922b21", "🔴")


def _card(label: str, main: str, sub: str, bg: str, border: str, text: str, badge: str) -> str:
    return f"""<td style='background:{bg};border-left:4px solid {border};padding:12px;border-radius:6px;width:25%;vertical-align:top;'>
  <div style='font-size:11px;color:#666;letter-spacing:0.3px;'>{label}</div>
  <div style='font-size:18px;font-weight:bold;color:{text};margin:4px 0;'>{main} <span style='font-size:14px;'>{badge}</span></div>
  <div style='font-size:11px;color:#555;'>{sub}</div>
</td>"""


def build_kpi_cards_html(enriched: dict) -> str:
    """enriched ground truth → 4지표 KPI 카드 HTML 테이블."""
    inm = enriched.get("월별_재구매_매출", {}).get("통합", {}) or {}
    cur = inm.get("당월", {}) or {}
    mom = _safe_num(inm.get("MoM_변화_pct"))
    sales_val = _safe_num(cur.get("매출"))

    stages = enriched.get("단계별_전환율_현재", {}).get("통합") or []
    rate_1to2 = _safe_num(next((s.get("전환율") for s in stages if s.get("단계") == "1→2"), None))

    mn = enriched.get("M+N_리텐션_통합") or []
    m1 = _safe_num(mn[-1].get("M+1")) if mn else None

    interval = enriched.get("재구매_간격") or {}
    p50_raw = interval.get("P50") or interval.get("중앙값")
    # P50 — "15일" 같은 문자열이면 숫자만 추출
    p50_num = None
    if p50_raw:
        try:
            p50_num = float("".join(c for c in str(p50_raw) if c.isdigit() or c == "."))
        except ValueError:
            pass

    # 매출 카드 — MoM 기준 색
    if mom is None:
        sales_bg, sales_bd, sales_tx, sales_badge = "#ecf0f1", "#95a5a6", "#7f8c8d", "—"
    elif mom >= 0:
        sales_bg, sales_bd, sales_tx, sales_badge = "#eafaf1", "#27ae60", "#1e8449", "🟢"
    elif mom > -20:
        sales_bg, sales_bd, sales_tx, sales_badge = "#fef9e7", "#f39c12", "#9a7d0a", "🟡"
    else:
        sales_bg, sales_bd, sales_tx, sales_badge = "#fdedec", "#e74c3c", "#922b21", "🔴"

    sales_card = _card(
        "당월 매출",
        _format_money(sales_val),
        f"MoM {mom:+.1f}%" if mom is not None else "MoM —",
        sales_bg, sales_bd, sales_tx, sales_badge,
    )

    bg, bd, tx, badge = _color_for(rate_1to2, 30, severity_pct=15)
    conv_card = _card(
        "1→2 전환",
        f"{rate_1to2:.1f}%" if rate_1to2 is not None else "—",
        "목표 30%",
        bg, bd, tx, badge,
    )

    bg, bd, tx, badge = _color_for(m1, 20, severity_pct=15)
    m1_card = _card(
        "M+1 리텐션",
        f"{m1:.1f}%" if m1 is not None else "—",
        "벤치 20%",
        bg, bd, tx, badge,
    )

    # P50 — 14~16일이 정상 (lower_is_better)
    if p50_num is None:
        bg, bd, tx, badge = "#ecf0f1", "#95a5a6", "#7f8c8d", "—"
    elif p50_num <= 18:
        bg, bd, tx, badge = "#eafaf1", "#27ae60", "#1e8449", "🟢"
    elif p50_num <= 25:
        bg, bd, tx, badge = "#fef9e7", "#f39c12", "#9a7d0a", "🟡"
    else:
        bg, bd, tx, badge = "#fdedec", "#e74c3c", "#922b21", "🔴"
    p50_card = _card(
        "재구매 P50",
        str(p50_raw) if p50_raw else "—",
        "정상 14~16일",
        bg, bd, tx, badge,
    )

    return f"""<h2 style='color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:4px;font-size:15px;'>📌 KPI 한눈에</h2>
<table style='width:100%;border-collapse:separate;border-spacing:6px;margin:8px 0 16px 0;'>
  <tr>{sales_card}{conv_card}{m1_card}{p50_card}</tr>
</table>"""
