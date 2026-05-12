"""Meta 광고 차트 — 일일 심층 메일 인라인 첨부용 PNG 생성.

원칙 (lib/charts.py와 동일):
- matplotlib Agg, 한글 폰트 자동 탐색
- PNG bytes 반환
- 데이터 부족 시 None
"""
from __future__ import annotations

import io
import platform
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

_FONT_INITIALIZED = False

BENCHMARK_ROAS = 2.5       # 업계 평균 기준선
HEAVYLOVER_BASELINE = 3.5  # 헤비로버 내부 목표선


def _init_font() -> None:
    global _FONT_INITIALIZED
    if _FONT_INITIALIZED:
        return
    if platform.system() == "Windows":
        candidates = ["Malgun Gothic", "맑은 고딕", "DejaVu Sans"]
    else:
        candidates = ["NanumGothic", "Nanum Gothic", "DejaVu Sans"]
    available = {f.name for f in font_manager.fontManager.ttflist}
    chosen = next((c for c in candidates if c in available), None)
    if chosen:
        plt.rcParams["font.family"] = chosen
    plt.rcParams["axes.unicode_minus"] = False
    _FONT_INITIALIZED = True


def _fig_to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def _safe_num(v) -> Optional[float]:
    if v in ("", None):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def chart_7d_trend(recent_trend: list[dict]) -> Optional[bytes]:
    """7일 추세 — 지출(bar) + ROAS(line) 듀얼 축."""
    _init_font()
    if not recent_trend or len(recent_trend) < 2:
        return None

    dates = [r.get("date", "?")[-5:] for r in recent_trend]  # MM-DD
    spend = [_safe_num(r.get("spend")) or 0 for r in recent_trend]
    roas = [_safe_num(r.get("roas")) for r in recent_trend]

    fig, ax1 = plt.subplots(figsize=(8, 4.2))
    bars = ax1.bar(dates, spend, color="#3498db", alpha=0.7, label="지출(원)")
    ax1.set_ylabel("지출 (원)", color="#2c3e50")
    ax1.tick_params(axis="x", rotation=30)
    for bar, s in zip(bars, spend):
        if s > 0:
            ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                     f"{int(s):,}", ha="center", va="bottom", fontsize=8, color="#2c3e50")

    ax2 = ax1.twinx()
    valid_x = [d for d, r in zip(dates, roas) if r is not None]
    valid_y = [r for r in roas if r is not None]
    if valid_y:
        ax2.plot(valid_x, valid_y, color="#e67e22", marker="o", linewidth=2.2, label="ROAS")
        ax2.axhline(y=BENCHMARK_ROAS, color="#e74c3c", linestyle="--", linewidth=1, alpha=0.6, label=f"벤치 {BENCHMARK_ROAS}")
        ax2.set_ylabel("ROAS", color="#e67e22")
        for x, y in zip(valid_x, valid_y):
            ax2.text(x, y + 0.05, f"{y:.2f}", ha="center", fontsize=8, color="#e67e22", fontweight="bold")

    ax1.set_title("7일 광고 추세 — 지출 + ROAS", fontsize=12, fontweight="bold")
    ax1.grid(True, alpha=0.2, axis="y")
    fig.tight_layout()
    return _fig_to_png(fig)


def chart_metric_vs_benchmark(metrics: dict, bench: dict) -> Optional[bytes]:
    """오늘 핵심 지표 vs 정적 벤치 — 가로 막대 (정규화 비율)."""
    _init_font()
    items = [
        ("CTR%", _safe_num(metrics.get("ctr_pct")), bench.get("ctr_pct"), True),
        ("CPC", _safe_num(metrics.get("cpc_krw")), bench.get("cpc_krw"), False),
        ("ROAS", _safe_num(metrics.get("roas")), bench.get("roas"), True),
        ("CPA", _safe_num(metrics.get("cpa_krw")), bench.get("cpa_krw"), False),
        ("Frequency", _safe_num(metrics.get("frequency")),
         (bench.get("frequency_low", 2) + bench.get("frequency_high", 4)) / 2, False),
    ]

    valid = [(label, val, b, hb) for label, val, b, hb in items if val is not None and b]
    if not valid:
        return None

    labels = [v[0] for v in valid]
    ratios = []
    colors = []
    for label, val, b, higher_better in valid:
        ratio = val / b if b else 1.0
        if higher_better:
            ratios.append(ratio)
            colors.append("#27ae60" if ratio >= 1 else "#e74c3c")
        else:
            ratios.append(2 - ratio)  # CPC·CPA는 낮을수록 좋으니 뒤집어서 표시
            colors.append("#27ae60" if ratio <= 1 else "#e74c3c")

    fig, ax = plt.subplots(figsize=(8, 3.8))
    bars = ax.barh(labels, ratios, color=colors, alpha=0.85)
    ax.axvline(x=1.0, color="#7f8c8d", linestyle="--", linewidth=1.2, label="벤치 = 1.0")
    for bar, ratio, (label, val, b, higher_better) in zip(bars, ratios, valid):
        actual_ratio = val / b if b else 0
        ax.text(bar.get_width() + 0.02, bar.get_y() + bar.get_height() / 2,
                f"{actual_ratio:.0%}", va="center", fontsize=9, fontweight="bold")
    ax.set_xlim(0, max(BENCHMARK_ROAS, max(ratios) + 0.3))
    ax.set_xlabel("벤치 대비 (높을수록 좋음, 1.0 = 동일)")
    ax.set_title("오늘 핵심 지표 vs 업계 벤치", fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.2, axis="x")
    ax.legend(loc="lower right")
    fig.tight_layout()
    return _fig_to_png(fig)


def chart_campaign_roas(campaigns: list[dict], top_n: int = 8) -> Optional[bytes]:
    """캠페인별 ROAS — 상위 N개 막대."""
    _init_font()
    if not campaigns:
        return None

    sorted_c = sorted(
        [c for c in campaigns if _safe_num(c.get("roas")) is not None],
        key=lambda c: _safe_num(c.get("roas")) or 0,
        reverse=True,
    )[:top_n]

    if not sorted_c:
        return None

    names = [(c.get("campaign_name") or "?")[:25] for c in sorted_c]
    roas_vals = [_safe_num(c.get("roas")) or 0 for c in sorted_c]
    spend_vals = [_safe_num(c.get("spend")) or 0 for c in sorted_c]

    colors = ["#27ae60" if r >= BENCHMARK_ROAS else "#e67e22" if r >= 1.5 else "#e74c3c" for r in roas_vals]

    fig, ax = plt.subplots(figsize=(8, max(3, len(sorted_c) * 0.45)))
    bars = ax.barh(names[::-1], roas_vals[::-1], color=colors[::-1], alpha=0.85)
    ax.axvline(x=BENCHMARK_ROAS, color="#7f8c8d", linestyle="--", linewidth=1.2, label=f"벤치 {BENCHMARK_ROAS}")

    for bar, r, s in zip(bars, roas_vals[::-1], spend_vals[::-1]):
        ax.text(bar.get_width() + 0.05, bar.get_y() + bar.get_height() / 2,
                f"{r:.2f}  ({int(s):,}원)", va="center", fontsize=8)

    ax.set_xlabel("ROAS")
    ax.set_title(f"캠페인별 ROAS (상위 {len(sorted_c)})", fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.2, axis="x")
    ax.legend(loc="lower right")
    fig.tight_layout()
    return _fig_to_png(fig)


def generate_meta_daily_charts(metrics: dict, bench_static: dict,
                                recent_trend: list[dict],
                                campaigns: list[dict]) -> dict[str, bytes]:
    """일일 메일에 첨부할 차트 dict."""
    out = {}
    c = chart_7d_trend(recent_trend)
    if c:
        out["meta_trend_7d"] = c
    c = chart_metric_vs_benchmark(metrics, bench_static)
    if c:
        out["meta_bench_compare"] = c
    c = chart_campaign_roas(campaigns)
    if c:
        out["meta_campaign_roas"] = c
    return out


# ============================================================
# 연간 종합 리포트용 차트
# ============================================================

def chart_monthly_trend(monthly: list[dict]) -> Optional[bytes]:
    """월별 지출 + ROAS 듀얼 축."""
    _init_font()
    if not monthly or len(monthly) < 2:
        return None

    months = [m["month"][-5:] for m in monthly]  # MM 또는 YY-MM
    spend = [_safe_num(m.get("spend")) or 0 for m in monthly]
    roas = [_safe_num(m.get("roas")) for m in monthly]

    fig, ax1 = plt.subplots(figsize=(9, 4.5))
    ax1.bar(months, spend, color="#3498db", alpha=0.7, label="월 지출(원)")
    ax1.set_ylabel("월 지출 (원)", color="#2c3e50")
    ax1.tick_params(axis="x", rotation=30)

    ax2 = ax1.twinx()
    valid_x = [m for m, r in zip(months, roas) if r is not None]
    valid_y = [r for r in roas if r is not None]
    if valid_y:
        ax2.plot(valid_x, valid_y, color="#e67e22", marker="o", linewidth=2.2, label="ROAS")
        ax2.axhline(y=BENCHMARK_ROAS, color="#e74c3c", linestyle="--", linewidth=1, alpha=0.6)
        ax2.set_ylabel("ROAS", color="#e67e22")

    ax1.set_title("월별 지출 + ROAS 추세", fontsize=12, fontweight="bold")
    ax1.grid(True, alpha=0.2, axis="y")
    fig.tight_layout()
    return _fig_to_png(fig)


def chart_weekday_pattern(weekday: list[dict]) -> Optional[bytes]:
    """요일별 평균 ROAS + CPA."""
    _init_font()
    if not weekday or len(weekday) < 4:
        return None

    days = [w["weekday"] for w in weekday]
    roas = [_safe_num(w.get("roas_avg")) or 0 for w in weekday]
    cpa = [_safe_num(w.get("cpa_avg")) or 0 for w in weekday]

    fig, ax1 = plt.subplots(figsize=(8, 4))
    bars = ax1.bar(days, roas, color="#16a085", alpha=0.8, label="ROAS")
    ax1.axhline(y=BENCHMARK_ROAS, color="#e74c3c", linestyle="--", linewidth=1, alpha=0.6, label=f"벤치 {BENCHMARK_ROAS}")
    ax1.set_ylabel("ROAS", color="#16a085")
    for bar, r in zip(bars, roas):
        if r > 0:
            ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                     f"{r:.2f}", ha="center", fontsize=9, fontweight="bold")

    ax2 = ax1.twinx()
    ax2.plot(days, cpa, color="#c0392b", marker="o", linewidth=2, label="CPA(원)")
    ax2.set_ylabel("CPA (원)", color="#c0392b")

    ax1.set_title("요일별 평균 ROAS + CPA", fontsize=12, fontweight="bold")
    ax1.grid(True, alpha=0.2, axis="y")
    fig.tight_layout()
    return _fig_to_png(fig)


def chart_funnel(funnel: dict) -> Optional[bytes]:
    """퍼널 단계별 카운트 + 단계 통과율."""
    _init_font()
    if not funnel:
        return None

    stages = funnel.get("stage_totals") or {}
    if not stages:
        return None

    labels_kr = {
        "impression": "노출",
        "link_click": "클릭",
        "view_content": "콘텐츠 조회",
        "add_to_cart": "장바구니",
        "initiate_checkout": "결제 시작",
        "purchase": "구매",
    }
    keys = ["impression", "link_click", "view_content", "add_to_cart", "initiate_checkout", "purchase"]
    counts = [stages.get(k) or 0 for k in keys]
    labels = [labels_kr[k] for k in keys]

    if max(counts) == 0:
        return None

    fig, ax = plt.subplots(figsize=(9, 4.5))
    bars = ax.barh(labels[::-1], counts[::-1], color=plt.cm.viridis([i / len(keys) for i in range(len(keys))][::-1]))

    # 단계 통과율 텍스트
    drops = funnel.get("drop_offs") or []
    drop_map = {d["to"]: d["conversion_rate_pct"] for d in drops if d.get("conversion_rate_pct") is not None}
    for bar, label, count in zip(bars, labels[::-1], counts[::-1]):
        rate = drop_map.get(label)
        rate_s = f" ({rate:.1f}% 통과)" if rate is not None else ""
        ax.text(bar.get_width() * 1.01, bar.get_y() + bar.get_height() / 2,
                f"{int(count):,}{rate_s}", va="center", fontsize=9)

    ax.set_xscale("log")
    ax.set_xlabel("카운트 (log scale)")
    ax.set_title(f"퍼널 단계별 누적 ({funnel.get('n_days_aggregated', '?')}일)",
                 fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.2, axis="x")
    fig.tight_layout()
    return _fig_to_png(fig)


def chart_top_bottom_campaigns(campaigns_data: dict) -> Optional[bytes]:
    """ROAS 상위/하위 캠페인 비교 (이중 패널)."""
    _init_font()
    top = campaigns_data.get("top") or []
    bottom = campaigns_data.get("bottom") or []
    if not top and not bottom:
        return None

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))

    if top:
        names_t = [(c.get("campaign_name") or "?")[:22] for c in top[:6]]
        roas_t = [_safe_num(c.get("roas")) or 0 for c in top[:6]]
        ax1.barh(names_t[::-1], roas_t[::-1], color="#27ae60", alpha=0.85)
        ax1.set_title(f"위너 ROAS 상위 {len(top[:6])}", fontsize=11, fontweight="bold")
        ax1.set_xlabel("ROAS")
        ax1.axvline(x=BENCHMARK_ROAS, color="#7f8c8d", linestyle="--", linewidth=1)
        ax1.grid(True, alpha=0.2, axis="x")
        for i, r in enumerate(roas_t[::-1]):
            ax1.text(r + 0.05, i, f"{r:.2f}", va="center", fontsize=8)

    if bottom:
        names_b = [(c.get("campaign_name") or "?")[:22] for c in bottom[:6]]
        roas_b = [_safe_num(c.get("roas")) or 0 for c in bottom[:6]]
        ax2.barh(names_b[::-1], roas_b[::-1], color="#e74c3c", alpha=0.85)
        ax2.set_title(f"패배 ROAS 하위 {len(bottom[:6])}", fontsize=11, fontweight="bold")
        ax2.set_xlabel("ROAS")
        ax2.axvline(x=BENCHMARK_ROAS, color="#7f8c8d", linestyle="--", linewidth=1)
        ax2.grid(True, alpha=0.2, axis="x")
        for i, r in enumerate(roas_b[::-1]):
            ax2.text(r + 0.05, i, f"{r:.2f}", va="center", fontsize=8)

    fig.suptitle("위너 vs 패배 캠페인", fontsize=13, fontweight="bold")
    fig.tight_layout()
    return _fig_to_png(fig)


def generate_meta_yearly_charts(monthly: list[dict], weekday: list[dict],
                                 campaigns: dict, funnel: Optional[dict]) -> dict[str, bytes]:
    """연간 종합 메일에 첨부할 차트 dict."""
    out = {}
    c = chart_monthly_trend(monthly)
    if c:
        out["meta_yearly_monthly"] = c
    c = chart_weekday_pattern(weekday)
    if c:
        out["meta_yearly_weekday"] = c
    c = chart_funnel(funnel)
    if c:
        out["meta_yearly_funnel"] = c
    c = chart_top_bottom_campaigns(campaigns)
    if c:
        out["meta_yearly_campaigns"] = c
    return out
