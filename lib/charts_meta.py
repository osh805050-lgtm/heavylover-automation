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
        ax2.axhline(y=2.5, color="#e74c3c", linestyle="--", linewidth=1, alpha=0.6, label="벤치 2.5")
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
    ax.set_xlim(0, max(2.5, max(ratios) + 0.3))
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

    colors = ["#27ae60" if r >= 2.5 else "#e67e22" if r >= 1.5 else "#e74c3c" for r in roas_vals]

    fig, ax = plt.subplots(figsize=(8, max(3, len(sorted_c) * 0.45)))
    bars = ax.barh(names[::-1], roas_vals[::-1], color=colors[::-1], alpha=0.85)
    ax.axvline(x=2.5, color="#7f8c8d", linestyle="--", linewidth=1.2, label="벤치 2.5")

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
