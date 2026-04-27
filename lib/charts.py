"""차트 생성 — 일일/주간 메일 본문에 인라인 첨부할 PNG를 생성한다.

원칙:
- matplotlib Agg 백엔드 (서버 헤드리스)
- 한글 폰트 자동 탐색 (Windows: Malgun Gothic, Linux: NanumGothic)
- PNG bytes 반환 → email_sender.send_email(inline_images={...})
- 데이터 부족 시 None 반환 (호출부가 분기)
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

    candidates = []
    if platform.system() == "Windows":
        candidates = ["Malgun Gothic", "맑은 고딕", "NanumGothic", "Apple SD Gothic Neo"]
    elif platform.system() == "Darwin":
        candidates = ["Apple SD Gothic Neo", "AppleGothic", "NanumGothic"]
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
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def chart_monthly_sales(gt: dict) -> Optional[bytes]:
    """월별 코호트 매출 추세 — gt['코호트_추세_통합']['최근_6개월']의 첫구매자수+전환율."""
    _init_font()
    cohorts = gt.get("코호트_추세_통합", {}).get("최근_6개월") or []
    if not cohorts:
        return None

    months = [c.get("코호트월", "?") for c in cohorts]
    first_buyers = [_safe_num(c.get("첫구매자수")) or 0 for c in cohorts]
    conv_rates = [_safe_num(c.get("1→2_전환율")) for c in cohorts]

    fig, ax1 = plt.subplots(figsize=(8, 4.2))
    ax1.bar(months, first_buyers, color="#3498db", alpha=0.75, label="첫구매자수")
    ax1.set_ylabel("첫구매자수 (명)", color="#2c3e50")
    ax1.tick_params(axis="x", rotation=30)

    ax2 = ax1.twinx()
    valid_x = [m for m, r in zip(months, conv_rates) if r is not None]
    valid_y = [r for r in conv_rates if r is not None]
    if valid_y:
        ax2.plot(valid_x, valid_y, color="#e67e22", marker="o", linewidth=2, label="1→2 전환율(%)")
        ax2.set_ylabel("1→2 전환율 (%)", color="#e67e22")

    ax1.set_title("월별 코호트 — 첫구매자수 + 1→2 전환율", fontsize=12, fontweight="bold")
    ax1.grid(True, alpha=0.25, axis="y")
    fig.tight_layout()
    return _fig_to_png(fig)


def chart_stage_funnel(gt: dict) -> Optional[bytes]:
    """단계별 전환율 — 통합/카페24/스마트스토어 1→2 전환율 막대."""
    _init_font()
    sources = ["통합", "카페24", "스마트스토어"]
    rates = []
    for s in sources:
        stages = gt.get("단계별_전환율_현재", {}).get(s) or []
        rate = next((st.get("전환율") for st in stages if st.get("단계") == "1→2"), None)
        rates.append(_safe_num(rate))

    if not any(r for r in rates if r is not None):
        return None

    fig, ax = plt.subplots(figsize=(7, 4))
    colors = ["#34495e", "#3498db", "#16a085"]
    plot_rates = [r if r is not None else 0 for r in rates]
    bars = ax.bar(sources, plot_rates, color=colors, alpha=0.85)
    ax.axhline(y=30, color="#e74c3c", linestyle="--", linewidth=1.2, label="목표 30%")
    ax.axhline(y=20, color="#f39c12", linestyle="--", linewidth=1, label="벤치 20%")

    for bar, r in zip(bars, rates):
        if r is None:
            continue
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                f"{r:.1f}%", ha="center", fontsize=10, fontweight="bold")

    ax.set_ylabel("전환율 (%)")
    ax.set_title("채널별 1→2 재구매 전환율 (60일 누적)", fontsize=12, fontweight="bold")
    ax.set_ylim(0, max(40, max(plot_rates) + 8))
    ax.legend(loc="upper right")
    ax.grid(True, alpha=0.25, axis="y")
    fig.tight_layout()
    return _fig_to_png(fig)


def chart_cohort_retention(gt: dict) -> Optional[bytes]:
    """코호트 잔존율 — M+1~M+6 라인 차트."""
    _init_font()
    cohorts = gt.get("M+N_리텐션_통합") or []
    if not cohorts:
        return None

    fig, ax = plt.subplots(figsize=(8, 4.2))
    x_labels = ["M+1", "M+2", "M+3", "M+6"]
    cmap = plt.get_cmap("viridis")

    plotted = 0
    for i, c in enumerate(cohorts[-6:]):
        ys = [_safe_num(c.get(k)) for k in x_labels]
        valid_x = [x for x, y in zip(x_labels, ys) if y is not None]
        valid_y = [y for y in ys if y is not None]
        if len(valid_y) >= 2:
            color = cmap(i / max(len(cohorts) - 1, 1))
            ax.plot(valid_x, valid_y, marker="o", linewidth=2, label=c.get("코호트월", "?"), color=color)
            plotted += 1

    if plotted == 0:
        plt.close(fig)
        return None

    ax.axhline(y=20, color="#e74c3c", linestyle="--", linewidth=1, alpha=0.6, label="벤치 20%")
    ax.set_ylabel("잔존율 (%)")
    ax.set_xlabel("개월 경과")
    ax.set_title("코호트별 M+N 리텐션 곡선", fontsize=12, fontweight="bold")
    ax.legend(loc="upper right", fontsize=8, ncol=2)
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    return _fig_to_png(fig)


def chart_wow_gauge(enriched: dict) -> Optional[bytes]:
    """WoW 변화 게이지 — 매출/재구매자/1→2/2→3 4지표 한 화면."""
    _init_font()
    wow = enriched.get("WoW_비교") or {}
    if not wow or wow.get("error"):
        return None

    items = [
        ("매출 WoW (%)", _safe_num(wow.get("당월_매출_WoW_pct"))),
        ("재구매자수 WoW (%)", _safe_num(wow.get("재구매자수_WoW_pct"))),
        ("1→2 전환 WoW (pp)", _safe_num(wow.get("1→2전환율_WoW_pp"))),
        ("2→3 전환 WoW (pp)", _safe_num(wow.get("2→3전환율_WoW_pp"))),
    ]
    items = [(k, v) for k, v in items if v is not None]
    if not items:
        return None

    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    labels = [k for k, _ in items]
    values = [v for _, v in items]
    colors = ["#27ae60" if v >= 0 else "#c0392b" for v in values]
    bars = ax.barh(labels, values, color=colors, alpha=0.85)
    ax.axvline(x=0, color="#2c3e50", linewidth=0.8)
    for bar, v in zip(bars, values):
        offset = 0.3 if v >= 0 else -0.3
        ax.text(v + offset, bar.get_y() + bar.get_height() / 2,
                f"{v:+.1f}", va="center",
                ha="left" if v >= 0 else "right", fontweight="bold")
    ax.set_title(f"WoW 변화 (기준일: {wow.get('기준일', '?')})", fontsize=12, fontweight="bold")
    ax.grid(True, alpha=0.25, axis="x")
    fig.tight_layout()
    return _fig_to_png(fig)


def chart_weekly_sales(history: list[dict], today_gt: dict) -> Optional[bytes]:
    """주간 메일 전용 — 7일 일별 당월 매출 추세 + 7일 평균선."""
    _init_font()
    all_gt = list(history) + [today_gt]
    if len(all_gt) < 2:
        return None

    dates = []
    sales = []
    for g in all_gt:
        d = g.get("리포트_날짜", "?")
        cur = g.get("월별_재구매_매출", {}).get("통합", {}).get("당월", {})
        v = _safe_num(cur.get("매출"))
        if v is not None:
            dates.append(d[5:] if len(d) >= 10 else d)  # MM-DD
            sales.append(v / 10000)  # 만원 단위

    if len(sales) < 2:
        return None

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(dates, sales, marker="o", color="#2980b9", linewidth=2, label="당월 누적 매출")
    avg = sum(sales) / len(sales)
    ax.axhline(y=avg, color="#e67e22", linestyle="--", linewidth=1.2, label=f"평균 {avg:,.0f}만원")
    ax.fill_between(dates, sales, alpha=0.18, color="#3498db")
    ax.set_ylabel("매출 (만원)")
    ax.set_title("일별 당월 누적 재구매 매출 (7일)", fontsize=12, fontweight="bold")
    ax.tick_params(axis="x", rotation=30)
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.25)
    fig.tight_layout()
    return _fig_to_png(fig)


def generate_daily_charts(gt: dict, enriched: dict) -> dict[str, bytes]:
    """일일 메일용 차트 4종. 생성 실패한 항목은 dict에서 제외."""
    out = {}
    for cid, fn in [
        ("chart_monthly", lambda: chart_monthly_sales(gt)),
        ("chart_stage", lambda: chart_stage_funnel(gt)),
        ("chart_cohort", lambda: chart_cohort_retention(gt)),
        ("chart_wow", lambda: chart_wow_gauge(enriched)),
    ]:
        try:
            png = fn()
            if png:
                out[cid] = png
        except Exception as e:
            print(f"차트 생성 실패 {cid}: {e}")
    return out


def generate_weekly_charts(gt: dict, enriched: dict, history: list[dict]) -> dict[str, bytes]:
    """주간 메일용 차트 5종 (일일 4종 + 주간 매출 시계열)."""
    out = generate_daily_charts(gt, enriched)
    try:
        weekly = chart_weekly_sales(history, gt)
        if weekly:
            out["chart_weekly_sales"] = weekly
    except Exception as e:
        print(f"주간 매출 차트 실패: {e}")
    return out
