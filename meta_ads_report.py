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
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from meta_ads_client import (
    extract_action,
    extract_action_value,
    extract_cost_per_action,
    extract_purchase_roas,
    fetch_account_insights,
    validate_insights,
)
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


def _fmt_num(v, decimals=0, suffix=""):
    if v is None:
        return "데이터 없음"
    try:
        if decimals == 0:
            return f"{int(round(v)):,}{suffix}"
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
    """CLAUDE.md §8 자동 플래그 조건"""
    flags = []
    if m["frequency"] is not None and m["frequency"] > 5:
        flags.append(f"⚠️ Frequency {m['frequency']:.2f} > 5 → 크리에이티브 피로")
    if m["cpa_krw"] is not None and m["cpa_krw"] > BENCHMARK["cpa_krw"] * 1.5:
        flags.append(
            f"⚠️ CPA {int(m['cpa_krw']):,}원 > 벤치×1.5 ({int(BENCHMARK['cpa_krw']*1.5):,}원) "
            "→ 오디언스/크리에이티브 재검토"
        )
    if m["roas"] is not None and m["roas"] < 2.0:
        flags.append(f"⚠️ ROAS {m['roas']:.2f} < 2.0 → 캠페인 일시 정지 검토")
    if (
        m["impressions"] is not None and m["impressions"] < 1000
        and m["spend"] is not None and m["spend"] > 0
    ):
        flags.append("⚠️ 노출 1,000 미만 + 지출 발생 → Learning Limited 의심")
    return flags


def format_markdown_report(target_date, metrics, flags, validation, raw_data):
    """발행용 마크다운 리포트"""
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

    lines.append("## 핵심 지표")
    lines.append("")
    lines.append("| 지표 | 실측 | 업계 평균 | 대비 |")
    lines.append("|---|---|---|---|")
    lines.append(
        f"| 지출 | {_fmt_num(metrics['spend'], 0, '원')} | - | - |"
    )
    lines.append(
        f"| 노출 | {_fmt_num(metrics['impressions'], 0)} | - | - |"
    )
    lines.append(
        f"| 클릭 | {_fmt_num(metrics['clicks'], 0)} | - | - |"
    )
    lines.append(
        f"| CTR | {_fmt_num(metrics['ctr_pct'], 2, '%')} | "
        f"{BENCHMARK['ctr_pct']}% | "
        f"{_compare(metrics['ctr_pct'], BENCHMARK['ctr_pct'], higher_better=True)} |"
    )
    lines.append(
        f"| CPC | {_fmt_num(metrics['cpc_krw'], 0, '원')} | "
        f"{BENCHMARK['cpc_krw']:,}원 | "
        f"{_compare(metrics['cpc_krw'], BENCHMARK['cpc_krw'], higher_better=False)} |"
    )
    lines.append(
        f"| Frequency | {_fmt_num(metrics['frequency'], 2)} | "
        f"{BENCHMARK['frequency_low']}~{BENCHMARK['frequency_high']} | - |"
    )
    lines.append(
        f"| 구매 수 | {_fmt_num(metrics['purchases'], 0)} | - | - |"
    )
    lines.append(
        f"| 구매 매출 | {_fmt_num(metrics['purchase_value_krw'], 0, '원')} | - | - |"
    )
    lines.append(
        f"| 전환율 | {_fmt_num(metrics['conv_rate_pct'], 2, '%')} | - | - |"
    )
    lines.append(
        f"| CPA | {_fmt_num(metrics['cpa_krw'], 0, '원')} | "
        f"{BENCHMARK['cpa_krw']:,}원 | "
        f"{_compare(metrics['cpa_krw'], BENCHMARK['cpa_krw'], higher_better=False)} |"
    )
    roas_cell = _fmt_num(metrics['roas'], 2)
    if metrics.get("roas_computed"):
        roas_cell += " (계산치)"
    lines.append(
        f"| ROAS | {roas_cell} | {BENCHMARK['roas']} | "
        f"{_compare(metrics['roas'], BENCHMARK['roas'], higher_better=True)} |"
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


def format_telegram_summary(target_date, metrics, flags, ok):
    """텔레그램 간결 요약 (이모지 정책 준수: 최소)"""
    if not ok:
        return f"[Meta 광고 {target_date}]\n데이터 없음 (API 실패 또는 노출 없음)"

    def _line(label, actual_str, bench_str=None, cmp_str=None):
        parts = [f"{label}: {actual_str}"]
        if bench_str:
            parts.append(f"(벤치 {bench_str})")
        if cmp_str:
            parts.append(f"→ {cmp_str}")
        return " ".join(parts)

    lines = [f"[Meta 광고 {target_date}]"]
    lines.append(_line("지출", _fmt_num(metrics['spend'], 0, '원')))
    lines.append(
        _line("CTR", _fmt_num(metrics['ctr_pct'], 2, '%'),
              f"{BENCHMARK['ctr_pct']}%",
              _compare(metrics['ctr_pct'], BENCHMARK['ctr_pct'], True))
    )
    lines.append(
        _line("CPC", _fmt_num(metrics['cpc_krw'], 0, '원'),
              f"{BENCHMARK['cpc_krw']:,}원",
              _compare(metrics['cpc_krw'], BENCHMARK['cpc_krw'], False))
    )
    lines.append(
        _line("ROAS", _fmt_num(metrics['roas'], 2),
              str(BENCHMARK['roas']),
              _compare(metrics['roas'], BENCHMARK['roas'], True))
    )
    lines.append(
        _line("CPA", _fmt_num(metrics['cpa_krw'], 0, '원'),
              f"{BENCHMARK['cpa_krw']:,}원",
              _compare(metrics['cpa_krw'], BENCHMARK['cpa_krw'], False))
    )
    lines.append(
        f"전환: {_fmt_num(metrics['purchases'], 0)}건 / "
        f"전환율 {_fmt_num(metrics['conv_rate_pct'], 2, '%')}"
    )
    lines.append(
        f"Frequency: {_fmt_num(metrics['frequency'], 2)}"
    )

    if flags:
        lines.append("")
        lines.append("플래그:")
        for f in flags:
            lines.append(f"  {f}")

    return "\n".join(lines)


def save_report(target_date, content):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{target_date}.md"
    path.write_text(content, encoding="utf-8")
    return path


def run():
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
        telegram_client.send_message(
            f"[Meta 광고 {target_date}] 데이터 없음\n사유: {err_msg}"
        )
        return 1

    row = raw["data"][0]
    metrics = compute_metrics(row)
    flags = build_flags(metrics)

    content = format_markdown_report(target_date, metrics, flags, validation, raw["data"])
    path = save_report(target_date, content)
    print(f"리포트 저장: {path}")

    summary = format_telegram_summary(target_date, metrics, flags, ok=True)
    sent = telegram_client.send_message(summary)
    print(f"텔레그램 전송: {sent}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
