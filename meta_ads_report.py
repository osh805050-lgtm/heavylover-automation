"""
Meta 광고 일일 리포트 생성 + 텔레그램 전송

CLAUDE.md §8 기준:
- 필수 지표: CPC, CTR, 전환율, ROAS, CPA (+ Frequency, Spend)
- 각 지표에 업계 평균 대비 비교 컬럼
- 자동 플래그: Frequency>5, CPA>벤치×1.5, ROAS<2.0, Learning 유사 상태

원칙 (CLAUDE.md §0):
- 추정과 확정 데이터 분리. 데이터 없으면 "데이터 없음" 명시, 절대 채우지 않음.
- 팩트 기반. 창작·추론 금지.

출력:
- docs/meta-ads/reports/{YYYY-MM-DD}.md  (원본 JSON + 요약 리포트)
- 텔레그램에 요약 메시지 전송
"""

import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from meta_ads_client import (
    extract_action,
    extract_action_value,
    extract_cost_per_action,
    extract_purchase_roas,
    fetch_account_insights,
    fetch_campaign_insights,
    validate_insights,
)
import meta_ads_history
import meta_ads_self_benchmark
import meta_ads_claude_comment
import email_sender
from meta_ads_weekly_report import summarize_row as summarize_campaign_row, _to_float
import telegram_client

# Windows cp949 콘솔 대비
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
REPORTS_DIR = ROOT / "docs" / "meta-ads" / "reports"
KST = timezone(timedelta(hours=9))

# CLAUDE.md §8 벤치마크 (2026년, 한국 D2C 식품)
BENCHMARK = {
    "ctr_pct": 1.2,          # %
    "cpc_krw": 700,          # 원
    "roas": 2.5,
    "cpa_krw": 30_000,       # 원
    "frequency_low": 2.0,
    "frequency_high": 4.0,
}

# Kill Criteria (CLAUDE.md §14, docs/strategy/outputs/ 확정)
KILL_CRITERIA = {
    "K1_roas_min": 2.8,      # ROAS < 2.8 → 광고비 -30% (발동 시 승현님 수동 집행 필요)
    "K6_aov_min": 58_000,    # AOV < 58,000원 2개월 연속 → 타겟 리셋
}

# 광고 계정 통화: USD. 자사 KRW 벤치마크와 비교 위해 환산.
# 환율 고정 1,450원/USD (2026-04-28 승인). 변동 환율 미사용 — 추세 일관성 우선.
CURRENCY_KRW_PER_USD = 1450
CURRENCY_FIELDS_USD = {"spend", "cpc_krw", "cpm_krw", "cpa_krw", "purchase_value_krw"}

# Codex review 2026-05-10: failures.md ⑯(통화 단위 가정) 재현 차단.
# 광고 계정 통화가 USD 아니면 1450 곱셈으로 모든 금액이 ×1450배 부풀려짐.
# H-5 fix: 모듈 import 시점에 raise하면 bootstrap_meta_yearly, meta_ads_adset_backfill 등
# 다른 스크립트의 import도 함께 crash → guard를 _check_account_currency()로 분리해
# run() 진입 시점에만 호출한다.
_ACCOUNT_CURRENCY = os.getenv("META_AD_ACCOUNT_CURRENCY", "USD").upper()


def _check_account_currency():
    """통화 guard — run() 진입 시점에만 호출. import 시 raise 금지."""
    account_currency = os.getenv("META_AD_ACCOUNT_CURRENCY", "USD").upper()
    if account_currency != "USD" and os.getenv("META_ALLOW_NON_USD") != "1":
        raise RuntimeError(
            f"⚠️ Meta 광고 계정 통화가 {account_currency} (USD 아님). "
            f"이 상태로 _to_krw 호출하면 모든 금액 ×{CURRENCY_KRW_PER_USD} 사고 발생. "
            "META_ALLOW_NON_USD=1 환경변수 설정 시만 진행 (단, _to_krw 로직 검토 필수)."
        )


def _to_krw(value, currency_unit="USD"):
    """USD → KRW 환산. None은 None. 이미 KRW면 그대로."""
    if value is None:
        return None
    if currency_unit == "KRW":
        return value
    try:
        return float(value) * CURRENCY_KRW_PER_USD
    except (TypeError, ValueError):
        return None


def convert_metrics_to_krw(m):
    """compute_metrics 결과 dict를 KRW 단위로 환산. 비율 지표(CTR·ROAS·Frequency)는 그대로."""
    _check_account_currency()  # guard: import 경로로 직접 호출해도 non-USD 차단
    out = dict(m)
    for k in ("spend", "cpc_krw", "cpm_krw", "cpa_krw", "purchase_value_krw"):
        if out.get(k) is not None:
            out[k] = _to_krw(out[k])
    return out

# 구매 액션 타입 후보 (Meta는 픽셀/오프사이트/온사이트 여러 형태로 반환)
PURCHASE_ACTION_TYPES = [
    "omni_purchase",
    "purchase",
    "offsite_conversion.fb_pixel_purchase",
]


def _first_non_none(fn, row, keys):
    for k in keys:
        v = fn(row, k)
        if v is not None:
            return v, k
    return None, None


from lib.format_utils import fmt_money, fmt_ratio, fmt_pct, fmt_count


def _fmt_num(v, decimals=0, suffix=""):
    if v is None:
        return "데이터 없음"
    try:
        if suffix == "원":
            return fmt_money(v)
        if suffix == "%":
            return fmt_pct(v, decimals=decimals)
        if decimals == 0:
            return fmt_count(v, suffix=suffix) if suffix else f"{int(round(v)):,}"
        return f"{v:,.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return "데이터 없음"


def _compare(actual, benchmark, higher_better=True):
    """벤치마크 대비 비율 문자열 (우수/평균/미달)"""
    if actual is None or benchmark is None or benchmark == 0:
        return "비교 불가"
    ratio = actual / benchmark
    if higher_better:
        if ratio >= 1.5:
            verdict = "우수"
        elif ratio >= 1.0:
            verdict = "평균 이상"
        elif ratio >= 0.7:
            verdict = "평균 미달"
        else:
            verdict = "크게 미달"
    else:
        if ratio <= 0.7:
            verdict = "우수"
        elif ratio <= 1.0:
            verdict = "평균 이내"
        elif ratio <= 1.5:
            verdict = "평균 초과"
        else:
            verdict = "크게 초과"
    return f"{ratio*100:.0f}% ({verdict})"


def compute_metrics(row):
    """API row 한 줄에서 지표 계산. 누락 필드는 None 유지."""
    def _f(key):
        v = row.get(key)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    spend = _f("spend")
    impressions = _f("impressions")
    clicks = _f("clicks")
    ctr = _f("ctr")                    # Meta 반환값 = % (예: 1.23)
    cpc = _f("cpc")                    # 원 (KRW 계정일 때)
    cpm = _f("cpm")
    frequency = _f("frequency")
    reach = _f("reach")

    # 구매 관련 (여러 action_type 중 먼저 발견되는 것 사용)
    purchases, purch_key = _first_non_none(extract_action, row, PURCHASE_ACTION_TYPES)
    purchase_value, _ = _first_non_none(extract_action_value, row, PURCHASE_ACTION_TYPES)
    cpa, _ = _first_non_none(extract_cost_per_action, row, PURCHASE_ACTION_TYPES)
    roas = extract_purchase_roas(row)

    # 전환율 = purchases / clicks * 100
    conv_rate = None
    if purchases is not None and clicks and clicks > 0:
        conv_rate = purchases / clicks * 100

    # ROAS가 응답에 없으면 계산으로 보완 (purchase_value / spend)
    roas_computed_flag = False
    if roas is None and purchase_value is not None and spend and spend > 0:
        roas = purchase_value / spend
        roas_computed_flag = True

    return {
        "spend": spend,
        "impressions": impressions,
        "clicks": clicks,
        "ctr_pct": ctr,
        "cpc_krw": cpc,
        "cpm_krw": cpm,
        "frequency": frequency,
        "reach": reach,
        "purchases": purchases,
        "purchase_value_krw": purchase_value,
        "cpa_krw": cpa,
        "roas": roas,
        "conv_rate_pct": conv_rate,
        "purchase_action_used": purch_key,
        "roas_computed": roas_computed_flag,
    }


def build_flags(m):
    """CLAUDE.md §8 자동 플래그 조건 + Kill Criteria K1~K3"""
    flags = []
    if m["frequency"] is not None and m["frequency"] > 5:
        flags.append(f"⚠️ 같은 광고 반복 노출 {m['frequency']:.2f}회 > 5회 → 소재 교체 필요 (광고 피로)")
    if m["cpa_krw"] is not None and m["cpa_krw"] > BENCHMARK["cpa_krw"] * 1.5:
        flags.append(
            f"⚠️ 고객 1명 구매 비용 {int(m['cpa_krw']):,}원 — 기준({int(BENCHMARK['cpa_krw']*1.5):,}원) 초과 "
            "→ 타겟·소재 재검토"
        )
    # Kill Criteria K1: ROAS < 2.8 → 광고비 -30% (2.0 미만은 즉시 중단)
    k1_threshold = KILL_CRITERIA["K1_roas_min"]
    if m["roas"] is not None and m["roas"] < k1_threshold:
        if m["roas"] < 2.0:
            flags.append(
                f"🔴 [K1 발동] ROAS {m['roas']:.2f} < 2.0 → 광고비 즉시 -30% 집행 필요 "
                "(Kill Criteria K1 초과 — 승현님 수동 조치 필요)"
            )
        else:
            flags.append(
                f"🟡 [K1 경보] ROAS {m['roas']:.2f} — Kill Criteria 기준({k1_threshold}) 미달 "
                "→ 광고비 -30% 준비. 3일 연속 시 즉시 집행"
            )
    if (
        m["impressions"] is not None and m["impressions"] < 1000
        and m["spend"] is not None and m["spend"] > 0
    ):
        flags.append("⚠️ 광고 노출 1,000회 미만 + 광고비 지출 → 광고 학습 부족 (예산·기간 부족 가능성)")
    return flags


def format_markdown_report(target_date, metrics, flags, validation, raw_data, self_bench=None):
    """발행용 마크다운 리포트 (정적 벤치 + 자사 P50 듀얼)"""
    lines = []
    lines.append(f"# Meta 광고 일일 리포트 — {target_date}")
    lines.append("")
    lines.append(f"생성: {datetime.now(KST).isoformat(timespec='seconds')} KST")
    lines.append("")

    if not validation["valid"]:
        lines.append("## ⚠️ 데이터 유효성 경고")
        for i in validation["issues"]:
            lines.append(f"- {i}")
        lines.append("")

    sb = self_bench or {}

    def _self_cell(metric, actual, higher_better=True):
        b = sb.get(metric)
        if not b:
            return "-"
        return meta_ads_self_benchmark.format_self_bench_cell(
            metric, actual, b, higher_better=higher_better
        )

    lines.append("## 핵심 지표")
    lines.append("")
    lines.append("| 지표 | 오늘 | 업계 기준값 | 업계 대비 | 우리 중간값(P50) |")
    lines.append("|---|---|---|---|---|")
    lines.append(
        f"| 지출 | {_fmt_num(metrics['spend'], 0, '원')} | - | - | - |"
    )
    lines.append(
        f"| 노출 | {_fmt_num(metrics['impressions'], 0)} | - | - | - |"
    )
    lines.append(
        f"| 클릭 | {_fmt_num(metrics['clicks'], 0)} | - | - | - |"
    )
    lines.append(
        f"| CTR | {_fmt_num(metrics['ctr_pct'], 2, '%')} | "
        f"{BENCHMARK['ctr_pct']}% | "
        f"{_compare(metrics['ctr_pct'], BENCHMARK['ctr_pct'], higher_better=True)} | "
        f"{_self_cell('ctr_pct', metrics['ctr_pct'], True)} |"
    )
    lines.append(
        f"| CPC | {_fmt_num(metrics['cpc_krw'], 0, '원')} | "
        f"{BENCHMARK['cpc_krw']:,}원 | "
        f"{_compare(metrics['cpc_krw'], BENCHMARK['cpc_krw'], higher_better=False)} | "
        f"{_self_cell('cpc_krw', metrics['cpc_krw'], False)} |"
    )
    lines.append(
        f"| Frequency | {_fmt_num(metrics['frequency'], 2)} | "
        f"{BENCHMARK['frequency_low']}~{BENCHMARK['frequency_high']} | - | "
        f"{_self_cell('frequency', metrics['frequency'], False)} |"
    )
    lines.append(
        f"| 구매 수 | {_fmt_num(metrics['purchases'], 0)} | - | - | - |"
    )
    lines.append(
        f"| 구매 매출 | {_fmt_num(metrics['purchase_value_krw'], 0, '원')} | - | - | - |"
    )
    lines.append(
        f"| 전환율 | {_fmt_num(metrics['conv_rate_pct'], 2, '%')} | - | - | - |"
    )
    lines.append(
        f"| CPA | {_fmt_num(metrics['cpa_krw'], 0, '원')} | "
        f"{BENCHMARK['cpa_krw']:,}원 | "
        f"{_compare(metrics['cpa_krw'], BENCHMARK['cpa_krw'], higher_better=False)} | "
        f"{_self_cell('cpa_krw', metrics['cpa_krw'], False)} |"
    )
    roas_cell = _fmt_num(metrics['roas'], 2)
    if metrics.get("roas_computed"):
        roas_cell += " (계산치)"
    lines.append(
        f"| ROAS | {roas_cell} | {BENCHMARK['roas']} | "
        f"{_compare(metrics['roas'], BENCHMARK['roas'], higher_better=True)} | "
        f"{_self_cell('roas', metrics['roas'], True)} |"
    )
    lines.append("")

    if metrics.get("purchase_action_used"):
        lines.append(
            f"_구매 기준 action_type: `{metrics['purchase_action_used']}`_"
        )
        lines.append("")

    lines.append("## 자동 플래그")
    lines.append("")
    if flags:
        for f in flags:
            lines.append(f"- {f}")
    else:
        lines.append("- 특이사항 없음")
    lines.append("")

    lines.append("## 원본 응답 (ground truth)")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(raw_data, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _flag_reason_action(flag_str: str) -> tuple[str, str]:
    """플래그 문자열에서 (이유, 액션) 쌍을 규칙 기반으로 반환."""
    f = flag_str.lower()
    if "k1" in f or "roas" in f:
        return (
            "광고비 대비 매출이 기준(2.8) 아래로 떨어짐",
            "광고비 -30% 준비. 3일 연속이면 즉시 집행",
        )
    if "frequency" in f or "반복 노출" in f or "소재 교체" in f:
        return (
            "같은 사람에게 광고가 너무 많이 보여 피로도 높아짐",
            "새 소재로 교체하거나 타겟 범위를 넓히기",
        )
    if "cpa" in f or "구매 비용" in f or "고객 1명" in f:
        return (
            "고객 1명 구매하는 데 드는 광고비가 기준 초과",
            "타겟·소재 점검 — 클릭은 많은데 구매 안 되는 경우 결제 퍼널 확인",
        )
    if "학습" in f or "노출 1,000" in f:
        return (
            "광고 학습에 필요한 데이터가 부족한 상태",
            "예산을 약간 늘리거나 기간을 더 두기 (최소 7일 유지)",
        )
    # 기타 플래그는 원문 그대로
    return ("광고 지표에 주의 신호가 감지됨", "메일에서 상세 내용 확인")


def format_telegram_summary(target_date, metrics, flags, ok, action_text=None,
                             partial_data=False, partial_reasons=None):
    """텔레그램 간결 요약 — 핵심 한 줄 + 주의사항·이유·액션만.

    partial_data=True면 헤더에 [PARTIAL] prefix + 누락 데이터 라인 추가.
    """
    if not ok:
        return (
            f"📈 [Meta광고]  {target_date}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ 데이터 없음 (API 실패 또는 노출 없음)"
        )

    partial_prefix = "[PARTIAL] " if partial_data else ""
    partial_note = ""
    if partial_data:
        reasons_text = ", ".join(partial_reasons) if partial_reasons else "일부 fetch 실패"
        partial_note = (
            f"⚠️ 부분 데이터 (누락: {reasons_text})\n"
            f"   history 시계열 append 건너뜀\n"
        )

    def _roas_emoji(roas):
        if roas is None:
            return "—"
        if roas >= BENCHMARK['roas'] * 1.5:
            return "🟢"
        if roas >= BENCHMARK['roas']:
            return "🔵"
        if roas >= KILL_CRITERIA['K1_roas_min']:
            return "🟡"
        return "🔴"

    spend = metrics.get("spend")
    roas = metrics.get("roas")
    purchases = metrics.get("purchases")
    purchase_value = metrics.get("purchase_value_krw")
    funnel_line = metrics.get("_funnel_summary")

    lines = []

    # ═══ 헤더 + 핵심 한 줄
    lines.append(f"📈 {partial_prefix}[Meta광고]  {target_date}")
    lines.append("━━━━━━━━━━━━━━━━━━")
    if partial_note:
        lines.append(partial_note.rstrip())
        lines.append("")
    roas_em = _roas_emoji(roas)
    lines.append(
        f"ROAS {_fmt_num(roas, 2)} {roas_em}  "
        f"지출 {_fmt_num(spend, 0, '원')}  "
        f"구매 {_fmt_num(purchases, 0)}건"
    )
    lines.append("")

    # ═══ 오늘 신경 쓸 것 (플래그 + 퍼널)
    lines.append("━━━ 오늘 신경 쓸 것 ━━━")

    alert_items = []
    for f in flags:
        reason, action = _flag_reason_action(f)
        alert_items.append((f, reason, action))

    if funnel_line:
        alert_items.append((
            f"퍼널 이탈: {funnel_line}",
            "결제 단계에서 고객 절반 이상이 이탈하고 있음",
            "배송비 사전 표시 확인 or 결제 버튼 위치 점검",
        ))

    if not alert_items:
        lines.append("🟢 이상 없음")
    else:
        for i, (flag_text, reason, action) in enumerate(alert_items):
            if i > 0:
                lines.append("─────────────────")
            lines.append(f"⚠️ {reason}")
            lines.append(f"→ {action}")

    lines.append("")
    lines.append("📧 상세 분석 → 메일 확인")

    return "\n".join(lines)


def build_email_html(target_date, metrics, flags, validation, self_bench,
                     deep_analysis_md, recent_trend, campaign_summaries):
    """이메일 심층 리포트 — HTML"""
    bench_table_md = format_markdown_report(
        target_date, metrics, flags, validation, [], self_bench=self_bench
    )
    # 마크다운 표를 그대로 HTML <pre>로 넣지 않고, 간단히 파싱하는 대신
    # 핵심 표만 별도로 HTML로 작성 + Claude 분석은 마크다운→HTML 간이 변환

    css = """
    <style>
      body{font-family:-apple-system,Segoe UI,sans-serif;color:#222;max-width:780px;margin:0 auto;padding:20px}
      h1{font-size:20px;border-bottom:2px solid #333;padding-bottom:6px}
      h2{font-size:16px;color:#333;margin-top:24px;border-left:3px solid #555;padding-left:8px}
      table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px}
      th,td{border:1px solid #ddd;padding:6px 8px;text-align:right}
      th{background:#f3f3f3;text-align:center}
      td.name{text-align:left}
      .flag{background:#fff4d6;padding:8px;border-radius:4px;margin:6px 0}
      .meta{color:#666;font-size:12px}
      .claude{background:#f7f9ff;border-left:3px solid #4a6cf7;padding:12px;margin:12px 0;white-space:pre-wrap;font-family:inherit;font-size:14px;line-height:1.6}
      pre.trend{background:#f7f7f7;padding:10px;border-radius:4px;font-size:12px;overflow-x:auto}
    </style>
    """

    def cell(actual, bench_static, static_cmp, self_cell):
        return f"<td>{actual}</td><td>{bench_static}</td><td>{static_cmp}</td><td>{self_cell}</td>"

    def _self_cell(metric, actual, higher_better):
        b = (self_bench or {}).get(metric)
        if not b:
            return "-"
        return meta_ads_self_benchmark.format_self_bench_cell(metric, actual, b, higher_better=higher_better)

    bench_ctr_static = f"{BENCHMARK['ctr_pct']}%"
    bench_cpc_static = f"{BENCHMARK['cpc_krw']:,}원"
    bench_freq_static = f"{BENCHMARK['frequency_low']}~{BENCHMARK['frequency_high']}"
    bench_cpa_static = f"{BENCHMARK['cpa_krw']:,}원"
    bench_roas_static = str(BENCHMARK['roas'])

    rows_html = ""
    rows_html += f"<tr><td class='name'>지출</td><td>{_fmt_num(metrics['spend'], 0, '원')}</td><td>-</td><td>-</td><td>-</td></tr>"
    rows_html += f"<tr><td class='name'>노출</td><td>{_fmt_num(metrics['impressions'], 0)}</td><td>-</td><td>-</td><td>-</td></tr>"
    rows_html += f"<tr><td class='name'>클릭</td><td>{_fmt_num(metrics['clicks'], 0)}</td><td>-</td><td>-</td><td>-</td></tr>"
    rows_html += (
        "<tr><td class='name'>CTR</td>"
        + cell(_fmt_num(metrics['ctr_pct'],2,'%'), bench_ctr_static,
               _compare(metrics['ctr_pct'], BENCHMARK['ctr_pct'], True),
               _self_cell('ctr_pct', metrics['ctr_pct'], True))
        + "</tr>"
    )
    rows_html += (
        "<tr><td class='name'>CPC</td>"
        + cell(_fmt_num(metrics['cpc_krw'],0,'원'), bench_cpc_static,
               _compare(metrics['cpc_krw'], BENCHMARK['cpc_krw'], False),
               _self_cell('cpc_krw', metrics['cpc_krw'], False))
        + "</tr>"
    )
    rows_html += (
        "<tr><td class='name'>Frequency</td>"
        + cell(_fmt_num(metrics['frequency'],2), bench_freq_static, '-',
               _self_cell('frequency', metrics['frequency'], False))
        + "</tr>"
    )
    rows_html += f"<tr><td class='name'>구매 수</td><td>{_fmt_num(metrics['purchases'],0)}</td><td>-</td><td>-</td><td>-</td></tr>"
    rows_html += f"<tr><td class='name'>구매 매출</td><td>{_fmt_num(metrics['purchase_value_krw'],0,'원')}</td><td>-</td><td>-</td><td>-</td></tr>"
    rows_html += f"<tr><td class='name'>전환율</td><td>{_fmt_num(metrics['conv_rate_pct'],2,'%')}</td><td>-</td><td>-</td><td>-</td></tr>"
    rows_html += (
        "<tr><td class='name'>CPA</td>"
        + cell(_fmt_num(metrics['cpa_krw'],0,'원'), bench_cpa_static,
               _compare(metrics['cpa_krw'], BENCHMARK['cpa_krw'], False),
               _self_cell('cpa_krw', metrics['cpa_krw'], False))
        + "</tr>"
    )
    rows_html += (
        "<tr><td class='name'>ROAS</td>"
        + cell(_fmt_num(metrics['roas'],2), bench_roas_static,
               _compare(metrics['roas'], BENCHMARK['roas'], True),
               _self_cell('roas', metrics['roas'], True))
        + "</tr>"
    )

    flags_html = ""
    if flags:
        flags_html = "<h2>자동 플래그</h2>" + "".join(f"<div class='flag'>{f}</div>" for f in flags)
    else:
        flags_html = "<h2>자동 플래그</h2><p>특이사항 없음</p>"

    claude_html = ""
    if deep_analysis_md:
        claude_html = f"<h2>Claude 심층 분석</h2><div class='claude'>{deep_analysis_md}</div>"

    trend_html = ""
    if recent_trend:
        trend_rows = "".join(
            f"<tr><td class='name'>{t.get('date','')}</td>"
            f"<td>{t.get('spend','') or '-'}</td>"
            f"<td>{t.get('ctr_pct','') or '-'}</td>"
            f"<td>{t.get('cpc_krw','') or '-'}</td>"
            f"<td>{t.get('roas','') or '-'}</td>"
            f"<td>{t.get('cpa_krw','') or '-'}</td></tr>"
            for t in recent_trend
        )
        trend_html = f"""
        <h2>직전 7일 추세</h2>
        <table>
          <tr><th>날짜</th><th>지출</th><th>CTR%</th><th>CPC</th><th>ROAS</th><th>CPA</th></tr>
          {trend_rows}
        </table>
        """

    camp_html = ""
    if campaign_summaries:
        camp_rows_html = ""
        for c in sorted(campaign_summaries, key=lambda x: (x.get("spend") or 0), reverse=True):
            camp_rows_html += (
                f"<tr><td class='name'>{c.get('campaign_name','-')}</td>"
                f"<td>{_fmt_num(c.get('spend'),0,'원')}</td>"
                f"<td>{_fmt_num(c.get('ctr_pct'),2,'%')}</td>"
                f"<td>{_fmt_num(c.get('cpa_krw'),0,'원')}</td>"
                f"<td>{_fmt_num(c.get('roas'),2)}</td>"
                f"<td>{_fmt_num(c.get('purchases'),0)}</td></tr>"
            )
        camp_html = f"""
        <h2>캠페인별 ({target_date})</h2>
        <table>
          <tr><th>캠페인</th><th>지출</th><th>CTR</th><th>CPA</th><th>ROAS</th><th>구매</th></tr>
          {camp_rows_html}
        </table>
        """

    return f"""<!doctype html><html><head>{css}</head><body>
    <h1>Meta 광고 일일 심층 리포트 — {target_date}</h1>
    <div class='meta'>생성: {datetime.now(KST).isoformat(timespec='seconds')} KST</div>
    <h2>핵심 지표 (정적 벤치 + 자사 P50 듀얼)</h2>
    <table>
      <tr><th>지표</th><th>실측</th><th>업계 평균</th><th>정적 대비</th><th>자사 P50</th></tr>
      {rows_html}
    </table>
    {flags_html}
    {trend_html}
    {camp_html}
    {claude_html}
    </body></html>"""


def save_report(target_date, content):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{target_date}.md"
    path.write_text(content, encoding="utf-8")
    return path


def run():
    _check_account_currency()  # H-5: import 시점이 아닌 run() 진입 시 통화 guard

    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--model", default=None, help="Claude 모델 오버라이드 (품질 비교 테스트용)")
    args, _ = parser.parse_known_args()
    if args.model:
        import meta_ads_email_daily as _med
        _med.CLAUDE_MODEL = args.model
        print(f"[테스트] Claude 모델 오버라이드: {args.model}")

    print("Meta 광고 리포트 생성 시작")
    raw = fetch_account_insights()
    target_date = raw["target_date"]

    validation = validate_insights(raw)
    print(f"date={target_date} ok={raw['ok']} valid={validation['valid']}")
    if validation["issues"]:
        for i in validation["issues"]:
            print(f"  - {i}")

    if not raw["ok"] or not raw["data"]:
        # Fallback: 데이터 없음을 명시적으로 리포트
        empty_metrics = {
            "spend": None, "impressions": None, "clicks": None,
            "ctr_pct": None, "cpc_krw": None, "cpm_krw": None,
            "frequency": None, "reach": None, "purchases": None,
            "purchase_value_krw": None, "cpa_krw": None, "roas": None,
            "conv_rate_pct": None, "purchase_action_used": None,
            "roas_computed": False,
        }
        content = format_markdown_report(
            target_date, empty_metrics, [], validation, raw.get("data") or []
        )
        path = save_report(target_date, content)
        print(f"fallback 리포트 저장: {path}")

        err_msg = raw.get("error") or "응답 데이터 비어있음"

        # 토큰 만료 자동 감지 — 명확한 안내 메시지
        token_expired = any(
            keyword in err_msg
            for keyword in ["Session has expired", "expired", "OAuthException", "code\":190", "code\":463"]
        )
        if token_expired:
            tg_msg = (
                f"🚨 [Meta광고 토큰 만료] {target_date}\n"
                "─────────────\n"
                "Meta API 토큰이 만료됐습니다.\n\n"
                "[해결]\n"
                "1. https://developers.facebook.com/tools/explorer/\n"
                "2. 앱 '광고 자동화' 선택 → User Token 발급\n"
                "3. 권한: ads_read 체크\n"
                "4. 토큰 복사 후 Claude에게 붙여넣기\n\n"
                "(앱 시크릿 발급 후 자동 갱신 cron 활성화 시 이 알림 사라짐)"
            )
        else:
            tg_msg = f"📈 [Meta광고] {target_date}\n─────────────\n데이터 없음 (API 실패)\n사유: {err_msg}"

        telegram_client.send_message(tg_msg, channel="ads")
        return 1

    row = raw["data"][0]
    metrics_usd = compute_metrics(row)
    metrics = convert_metrics_to_krw(metrics_usd)
    print(f"통화 환산: USD spend={metrics_usd.get('spend')} → KRW spend={metrics.get('spend')}")
    flags = build_flags(metrics)

    # Codex review 2026-05-10: 캠페인·adset fetch 실패 추적용 partial_data 플래그.
    # True면 history append 차단 + 텔레그램·이메일에 [PARTIAL] 표시.
    partial_data = False
    partial_reasons = []

    # 캠페인별 fetch (해당 일자만, 시계열 누적용) — KRW 환산 포함
    campaign_summaries = []
    try:
        camp_raw = fetch_campaign_insights(target_date, target_date)
        if camp_raw["ok"]:
            for r in camp_raw.get("data", []):
                c = summarize_campaign_row(r)
                # USD → KRW (단가성 필드만)
                for k in ("spend", "purchase_value", "cpa_krw"):
                    if c.get(k) is not None:
                        c[k] = float(c[k]) * CURRENCY_KRW_PER_USD
                campaign_summaries.append(c)
            print(f"캠페인별 데이터 수집: {len(campaign_summaries)}건 (KRW 환산)")
        else:
            err = camp_raw.get('error')
            print(f"⚠️ 캠페인별 fetch 실패: {err}")
            partial_data = True
            partial_reasons.append("campaign")
    except Exception as e:
        print(f"⚠️ 캠페인별 fetch 예외 (계속 진행): {e}")
        partial_data = True
        partial_reasons.append("campaign")

    # 시계열 누적 (CSV + Google Sheets) — 자사 벤치 계산 전에 먼저 누적
    # partial_data=True면 시계열 오염 방지 위해 skip.
    if partial_data:
        print("⚠️ history append 건너뜀 (partial_data: 캠페인 fetch 실패)")
    else:
        try:
            hist = meta_ads_history.append_daily(
                target_date, raw, metrics, campaign_summaries
            )
            print(f"history append: daily={hist['daily_rows']}, campaign={hist['campaign_rows']}")
            print(f"  sheet daily: {hist['sheet'].get('daily', '')}")
            if hist['sheet'].get('campaign'):
                print(f"  sheet campaign: {hist['sheet']['campaign']}")
        except Exception as e:
            print(f"history 누적 실패 (리포트는 계속): {e}")

    # 광고세트(adset) 단위 시계열 누적 — 트랙 A
    # CAC 낮지만 재구매 안 좋은 vs CAC 높지만 재구매 좋은 광고세트 식별용 데이터 축적
    try:
        from meta_ads_client import fetch_adset_daily_range
        adset_raw = fetch_adset_daily_range(target_date, target_date)
        if adset_raw["ok"]:
            adset_summaries = []
            for r in adset_raw.get("data", []):
                m = summarize_campaign_row(r)  # 동일 액션 추출 로직 재사용
                # USD → KRW 환산 (단가성 필드만)
                for k in ("spend", "purchase_value", "cpa_krw"):
                    if m.get(k) is not None:
                        m[k] = float(m[k]) * CURRENCY_KRW_PER_USD
                adset_summaries.append({
                    "date": target_date,
                    "adset_id": r.get("adset_id"),
                    "adset_name": r.get("adset_name") or "(이름 없음)",
                    "campaign_id": r.get("campaign_id"),
                    "campaign_name": r.get("campaign_name") or "(이름 없음)",
                    "spend": m.get("spend"),
                    "impressions": m.get("impressions"),
                    "clicks": m.get("clicks"),
                    "ctr_pct": m.get("ctr_pct"),
                    "cpc_krw": (m["spend"] / m["clicks"]) if m.get("spend") and m.get("clicks") else None,
                    "frequency": _to_float(r.get("frequency")) if r.get("frequency") else None,
                    "purchases": m.get("purchases"),
                    "purchase_value_krw": m.get("purchase_value"),
                    "cpa_krw": m.get("cpa_krw"),
                    "roas": m.get("roas"),
                })
            # partial_data 시 adset history도 차단 (시계열 오염 방지)
            if partial_data:
                print(f"⚠️ adset history append 건너뜀 (partial_data 이전 단계 실패)")
            else:
                adset_hist = meta_ads_history.append_adset_range(adset_summaries)
                print(f"adset 시계열: {len(adset_summaries)}건 수집 → CSV {adset_hist['adset_rows']}행, {adset_hist['sheet']}")
        else:
            print(f"⚠️ adset fetch 실패 (계속 진행): {adset_raw.get('error', '')[:200]}")
            partial_data = True
            if "adset" not in partial_reasons:
                partial_reasons.append("adset")
    except Exception as e:
        # 401/토큰 만료 감지 시 텔레그램 ops 채널 알림 (§외부API다루기 규칙 7)
        err_str = str(e)
        if any(k in err_str for k in ["OAuthException", "Session has expired", "401", "code:190", "code:463"]):
            try:
                from telegram_client import send_message
                send_message(
                    f"⚠️ Meta adset 수집 실패 — 토큰 만료 의심\n"
                    f"오류: {err_str[:200]}\n"
                    f"확인: refresh_meta_token.py 또는 Graph API Explorer 재발급",
                    channel="ops",
                )
            except Exception:
                pass
        print(f"⚠️ adset 누적 예외 (리포트 계속): {e}")
        partial_data = True
        if "adset" not in partial_reasons:
            partial_reasons.append("adset")

    # 자사 동적 벤치 (14일 미만이면 ok=False, 정적 벤치만 사용)
    try:
        self_bench = meta_ads_self_benchmark.compute_all(window=30)
        n_ok = sum(1 for b in self_bench.values() if b.get("ok"))
        print(f"자사 벤치: {n_ok}/{len(self_bench)} 지표 활성화")
    except Exception as e:
        self_bench = {}
        print(f"자사 벤치 계산 실패: {e}")

    # 마크다운 리포트 (자사 벤치 듀얼 포함)
    content = format_markdown_report(
        target_date, metrics, flags, validation, raw["data"], self_bench=self_bench
    )
    path = save_report(target_date, content)
    print(f"리포트 저장: {path}")

    # Claude 액션 코멘트 (텔레그램용 짧은 + 이메일용 심층)
    metrics_with_date = dict(metrics)
    metrics_with_date["_target_date"] = target_date
    recent_trend = []
    try:
        recent_trend = meta_ads_claude_comment.load_recent_trend(target_date, days=7)
    except Exception as e:
        print(f"recent_trend 로드 실패: {e}")

    winner_patterns = []
    try:
        winner_patterns = meta_ads_claude_comment.load_winner_patterns()
    except Exception as e:
        print(f"winner_patterns 로드 실패: {e}")

    short_text, short_err = meta_ads_claude_comment.generate_short(
        metrics_with_date, self_bench, flags, recent_trend, winner_patterns
    )
    if short_err:
        print(f"Claude 짧은 코멘트 skip: {short_err}")
    deep_text, deep_err = meta_ads_claude_comment.generate_deep(
        metrics_with_date, self_bench, flags, recent_trend, winner_patterns
    )
    if deep_err:
        print(f"Claude 심층 분석 skip: {deep_err}")

    # 퍼널 한 줄 — 가장 큰 drop-off 텔레그램에 노출
    try:
        from meta_ads_funnel_analysis import overall_funnel
        f = overall_funnel(raw.get("data") or [])
        drops = f.get("drop_offs") or []
        valid = [d for d in drops if d.get("drop_off_pct") is not None]
        if valid:
            biggest = max(valid, key=lambda d: d["drop_off_pct"])
            metrics["_funnel_summary"] = (
                f"퍼널 최대 이탈: {biggest['from']}→{biggest['to']} "
                f"{biggest['drop_off_pct']:.1f}% 이탈 "
                f"({biggest['from_count']:,}→{biggest['to_count']:,})"
            )
    except Exception as e:
        print(f"퍼널 요약 생성 실패: {e}")

    # 텔레그램 (요약 + 짧은 코멘트)
    summary = format_telegram_summary(
        target_date, metrics, flags, ok=True, action_text=short_text,
        partial_data=partial_data, partial_reasons=partial_reasons,
    )
    sent = telegram_client.send_message(summary, channel="ads")
    print(f"텔레그램 전송: {sent}{' [PARTIAL]' if partial_data else ''}")

    # 이메일 — 4역할 페르소나 심층 + 차트 인라인 (재구매 일일 리포트와 동일 수준)
    try:
        import meta_ads_email_daily
        sheet_id = os.getenv("GOOGLE_SHEETS_ID", "").strip()
        sheet_url = (
            f"https://docs.google.com/spreadsheets/d/{sheet_id}" if sheet_id else ""
        )
        ok, err = meta_ads_email_daily.send_daily_email(
            target_date=target_date,
            metrics=metrics,
            self_bench=self_bench,
            flags=flags,
            recent_trend=recent_trend,
            campaigns=campaign_summaries,
            winner_patterns=winner_patterns,
            sheet_url=sheet_url,
            raw_account_rows=raw.get("data") or [],
            partial_data=partial_data,
            partial_reasons=partial_reasons,
        )
        if ok:
            print("이메일 4역할 심층 발송 완료")
        else:
            print(f"이메일 발송 실패 (텔레그램은 발송됨): {err}")
    except Exception as e:
        print(f"이메일 모듈 호출 실패: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(run())
