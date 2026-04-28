"""1년치 Meta 광고 종합 심층 리포트 — 4역할 + 계절성 + 퍼널 + 위너 패턴.

매주 일요일 09:00 또는 수동 실행.
- 1년치 daily.csv + daily_campaign.csv를 종합 분석
- 월별/요일별/시즌별 패턴 추출
- 퍼널 단계별 평균 drop-off (lib raw json 활용)
- ROAS 상위/하위 캠페인 + 생애주기 분석
- 4역할 페르소나 (claude-opus-4-7) 심층 인사이트
- 차트 6~8개 인라인 (트렌드/계절성/요일/퍼널/캠페인 분포 등)

원칙:
- daily.csv 데이터 < 60일이면 "데이터 누적 중 (N/60일)" 안내 + 가능한 분석만
- 모든 수치는 ground truth 기반, 추정 금지
"""
from __future__ import annotations

import csv
import io
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from anthropic import Anthropic
from dotenv import load_dotenv

import email_sender
import telegram_client
from meta_ads_funnel_analysis import overall_funnel, funnel_to_markdown, funnel_health_diagnosis

ROOT = Path(__file__).parent
ENV_PATH = ROOT / ".env"
DATA_DIR = ROOT / "data" / "meta_ads"
DAILY_CSV = DATA_DIR / "daily.csv"
DAILY_CAMP_CSV = DATA_DIR / "daily_campaign.csv"
RAW_DIR = DATA_DIR / "raw"

KST = timezone(timedelta(hours=9))
CLAUDE_MODEL = "claude-opus-4-7"
MAX_TOKENS = 4000

WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]


def _safe_float(v):
    if v in ("", None):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_csv_rows(path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def filter_account_rows(rows, days):
    rows = [r for r in rows if r.get("level") == "account"]
    today = datetime.now(KST).date()
    cutoff = (today - timedelta(days=days)).isoformat()
    return [r for r in rows if r.get("date", "") >= cutoff]


def aggregate_overall(rows):
    """전체 합계."""
    total_spend = sum((_safe_float(r.get("spend")) or 0) for r in rows)
    total_imp = sum((_safe_float(r.get("impressions")) or 0) for r in rows)
    total_clk = sum((_safe_float(r.get("clicks")) or 0) for r in rows)
    total_pur = sum((_safe_float(r.get("purchases")) or 0) for r in rows)
    total_pv = sum((_safe_float(r.get("purchase_value_krw")) or 0) for r in rows)
    return {
        "n_days": len(rows),
        "spend_total_krw": total_spend,
        "impressions_total": total_imp,
        "clicks_total": total_clk,
        "purchases_total": total_pur,
        "purchase_value_total_krw": total_pv,
        "ctr_avg_pct": (total_clk / total_imp * 100) if total_imp > 0 else None,
        "cpc_avg_krw": (total_spend / total_clk) if total_clk > 0 else None,
        "cpa_avg_krw": (total_spend / total_pur) if total_pur > 0 else None,
        "roas_avg": (total_pv / total_spend) if total_spend > 0 else None,
    }


def aggregate_by_month(rows):
    """월별 집계."""
    by_month = defaultdict(lambda: {
        "spend": 0, "impressions": 0, "clicks": 0,
        "purchases": 0, "purchase_value": 0, "n_days": 0,
    })
    for r in rows:
        d = r.get("date", "")
        if len(d) < 7:
            continue
        ym = d[:7]
        m = by_month[ym]
        m["spend"] += _safe_float(r.get("spend")) or 0
        m["impressions"] += _safe_float(r.get("impressions")) or 0
        m["clicks"] += _safe_float(r.get("clicks")) or 0
        m["purchases"] += _safe_float(r.get("purchases")) or 0
        m["purchase_value"] += _safe_float(r.get("purchase_value_krw")) or 0
        m["n_days"] += 1

    out = []
    for ym in sorted(by_month.keys()):
        m = by_month[ym]
        out.append({
            "month": ym,
            "n_days": m["n_days"],
            "spend": m["spend"],
            "impressions": m["impressions"],
            "clicks": m["clicks"],
            "purchases": m["purchases"],
            "purchase_value": m["purchase_value"],
            "ctr_pct": (m["clicks"] / m["impressions"] * 100) if m["impressions"] > 0 else None,
            "cpa": (m["spend"] / m["purchases"]) if m["purchases"] > 0 else None,
            "roas": (m["purchase_value"] / m["spend"]) if m["spend"] > 0 else None,
        })
    return out


def aggregate_by_weekday(rows):
    """요일별 평균 (월~일)."""
    by_dow = defaultdict(list)
    for r in rows:
        d = r.get("date", "")
        try:
            dt = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            continue
        dow = dt.weekday()  # 0=월
        by_dow[dow].append({
            "spend": _safe_float(r.get("spend")),
            "ctr_pct": _safe_float(r.get("ctr_pct")),
            "roas": _safe_float(r.get("roas")),
            "cpa_krw": _safe_float(r.get("cpa_krw")),
            "purchases": _safe_float(r.get("purchases")),
        })

    out = []
    for dow in range(7):
        rs = by_dow.get(dow, [])
        if not rs:
            continue
        def _avg(key):
            vals = [r[key] for r in rs if r[key] is not None]
            return statistics.mean(vals) if vals else None
        out.append({
            "weekday": WEEKDAY_KR[dow],
            "n_days": len(rs),
            "spend_avg": _avg("spend"),
            "ctr_pct_avg": _avg("ctr_pct"),
            "roas_avg": _avg("roas"),
            "cpa_avg": _avg("cpa_krw"),
            "purchases_avg": _avg("purchases"),
        })
    return out


def aggregate_campaigns(rows, days=365, top_n=10):
    """캠페인별 1년 누적 + 상위/하위."""
    by_camp = defaultdict(lambda: {
        "campaign_id": "", "campaign_name": "",
        "spend": 0, "impressions": 0, "clicks": 0,
        "purchases": 0, "purchase_value": 0,
        "first_date": None, "last_date": None, "n_days": 0,
    })
    today = datetime.now(KST).date()
    cutoff = (today - timedelta(days=days)).isoformat()

    for r in rows:
        if r.get("level") != "campaign":
            continue
        d = r.get("date", "")
        if d < cutoff:
            continue
        cid = r.get("campaign_id") or "unknown"
        c = by_camp[cid]
        c["campaign_id"] = cid
        if not c["campaign_name"]:
            c["campaign_name"] = r.get("campaign_name") or ""
        c["spend"] += _safe_float(r.get("spend")) or 0
        c["impressions"] += _safe_float(r.get("impressions")) or 0
        c["clicks"] += _safe_float(r.get("clicks")) or 0
        c["purchases"] += _safe_float(r.get("purchases")) or 0
        c["purchase_value"] += _safe_float(r.get("purchase_value_krw")) or 0
        c["n_days"] += 1
        if c["first_date"] is None or d < c["first_date"]:
            c["first_date"] = d
        if c["last_date"] is None or d > c["last_date"]:
            c["last_date"] = d

    out = []
    for c in by_camp.values():
        c["ctr_pct"] = (c["clicks"] / c["impressions"] * 100) if c["impressions"] > 0 else None
        c["cpa"] = (c["spend"] / c["purchases"]) if c["purchases"] > 0 else None
        c["roas"] = (c["purchase_value"] / c["spend"]) if c["spend"] > 0 else None
        # 생애주기 (일)
        if c["first_date"] and c["last_date"]:
            try:
                f_dt = datetime.strptime(c["first_date"], "%Y-%m-%d").date()
                l_dt = datetime.strptime(c["last_date"], "%Y-%m-%d").date()
                c["lifecycle_days"] = (l_dt - f_dt).days + 1
            except ValueError:
                c["lifecycle_days"] = None
        else:
            c["lifecycle_days"] = None
        out.append(c)

    # 노출 충분 (1000+) + ROAS 있는 것만 정렬
    eligible = [c for c in out if c["impressions"] >= 1000 and c["roas"] is not None]
    top = sorted(eligible, key=lambda c: c["roas"], reverse=True)[:top_n]
    bottom = sorted(eligible, key=lambda c: c["roas"])[:top_n]
    return {
        "all_campaigns": out,
        "n_total": len(out),
        "n_eligible": len(eligible),
        "top": top,
        "bottom": bottom,
    }


def load_funnel_aggregate(days=365):
    """raw json 디렉토리에서 마지막 N일치 퍼널 누적 합산."""
    if not RAW_DIR.exists():
        return None
    today = datetime.now(KST).date()
    cutoff = (today - timedelta(days=days)).isoformat()

    all_rows = []
    n_files = 0
    for p in sorted(RAW_DIR.glob("*.json")):
        date_part = p.stem
        if date_part < cutoff:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                all_rows.extend(data)
                n_files += 1
        except Exception:
            continue

    if not all_rows:
        return None
    funnel = overall_funnel(all_rows)
    funnel["n_days_aggregated"] = n_files
    return funnel


SYSTEM_PROMPT = """당신은 D2C 이커머스 Meta 광고 시니어 분석가다. HeavyLover(냉동 도시락 D2C, 20~30대 운동 직장인 남성 타겟) 1년치 누적 광고 성과를 종합 진단한다.

**한 응답 안에 4명이 순차로 발언**한다.

---

## 1. 분석가 (사실 정리)
- 1년 종합 핵심 지표 표 (총 지출, ROAS, CTR, CPA, 노출→구매 종합 전환율)
- 월별 추세 변곡점 (성장/정체/하락 구간)
- 퍼널 단계별 평균 drop-off 명시
- 요일별 패턴 (있으면)
- 추측 금지, 입력 JSON 숫자만

## 2. 전략가 (가설 + 시즌성)
- 월별 변동의 가능 원인 3개 (시즌·신제품·크리에이티브 교체·예산)
- 요일별 패턴이 의미하는 것 (B2C 휴일/주말 효과 등)
- 위너 캠페인의 공통 패턴 (타겟·제품·후킹)
- 패배 캠페인의 공통 패턴
- 신뢰도(높음/중간/낮음) 명시

## 3. 회의주의자 (반박)
- 1년 데이터의 시즌 한계 (겨울/여름 1번씩만 봄)
- 캠페인 비교 한계 (예산 분배·타겟 다른데 ROAS만 비교 가능한가)
- 퍼널 데이터 신뢰성 (CAPI 미설치 가능성, 픽셀 누락 등)
- 결론 단정 금지

## 4. 의사결정자 (1년 데이터 기반 액션 3~5개)
- 위너 패턴 응용한 신규 캠페인 1개
- 패배 패턴 즉시 정지 1~2개
- 시즌별 예산 가이드 (다음 분기)
- 퍼널 약점 단계 개선 액션
- 형식: "(액션) → (예상 효과·정량) → (검증 지표·기간)"

---

**규칙**:
1. 입력 JSON 숫자만 사용. 창작 금지.
2. 한국어 1500~2500자. 표·불릿 적극.
3. 헤비로버 컨텍스트: ROAS 베이스라인 3.5, Cafe24 100% Meta 의존, M+1 리텐션 14% 개선이 1순위 (재구매 자동화와 맞물림), 시리얼 신제품 2026-06 출시.
4. AI 화법 금지. 이모지 ✅⚠️🔴📊만 허용."""


USER_TEMPLATE = """1년치 Meta 광고 ground truth:

```json
{ctx_json}
```

위 4역할 형식대로 종합 심층 리포트 작성."""


def call_claude_4roles(ctx):
    load_dotenv(ENV_PATH, override=True)
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None, "ANTHROPIC_API_KEY 미설정"

    client = Anthropic(api_key=api_key)
    user = USER_TEMPLATE.format(
        ctx_json=json.dumps(ctx, ensure_ascii=False, indent=2, default=str)
    )
    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text.strip(), None
    except Exception as e:
        return None, f"Claude 호출 실패: {e}"


def _md_to_html(md):
    """간단 Markdown → HTML."""
    lines = md.splitlines()
    out = []
    in_list = False
    in_table = False
    for line in lines:
        s = line.rstrip()
        if s.startswith("## "):
            if in_list:
                out.append("</ul>"); in_list = False
            if in_table:
                out.append("</table>"); in_table = False
            out.append(f"<h2 style='color:#2c3e50;border-bottom:2px solid #667eea;padding-bottom:4px;margin-top:24px;'>{s[3:].strip()}</h2>")
        elif s.startswith("- "):
            if in_table:
                out.append("</table>"); in_table = False
            if not in_list:
                out.append("<ul>"); in_list = True
            out.append(f"<li>{s[2:].strip()}</li>")
        elif s.startswith("|") and s.endswith("|"):
            if in_list:
                out.append("</ul>"); in_list = False
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set("-:| ") for c in cells):
                continue
            tag = "th" if not in_table else "td"
            if not in_table:
                out.append("<table style='border-collapse:collapse;margin:8px 0;'>"); in_table = True
            cells_html = "".join(
                f"<{tag} style='border:1px solid #ddd;padding:6px 12px;'>{c}</{tag}>" for c in cells
            )
            out.append(f"<tr>{cells_html}</tr>")
        elif s == "---":
            if in_list:
                out.append("</ul>"); in_list = False
            if in_table:
                out.append("</table>"); in_table = False
            out.append("<hr style='border:none;border-top:1px solid #eee;margin:16px 0;'>")
        elif s == "":
            if in_list:
                out.append("</ul>"); in_list = False
            if in_table:
                out.append("</table>"); in_table = False
            out.append("<br>")
        else:
            out.append(f"<p style='margin:8px 0;'>{s}</p>")
    if in_list:
        out.append("</ul>")
    if in_table:
        out.append("</table>")
    return "\n".join(out)


def _render_charts_block(chart_cids):
    if not chart_cids:
        return ""
    rows = []
    for i in range(0, len(chart_cids), 2):
        chunk = chart_cids[i:i + 2]
        cells = "".join(
            f"<td style='padding:6px;width:50%;vertical-align:top;'>"
            f"<img src='cid:{cid}' style='width:100%;max-width:380px;height:auto;display:block;border-radius:4px;'>"
            f"</td>"
            for cid in chunk
        )
        if len(chunk) < 2:
            cells += "<td style='width:50%;'></td>"
        rows.append(f"<tr>{cells}</tr>")
    table = f"<table style='width:100%;border-collapse:collapse;margin:16px 0;'>{''.join(rows)}</table>"
    return f"<h2 style='color:#2c3e50;border-bottom:2px solid #667eea;padding-bottom:4px;'>📊 시각화 요약</h2>{table}"


def _kpi_card(label, value, sub, color):
    return (
        f"<td style='width:25%;padding:14px;background:{color};color:white;border-radius:6px;text-align:center;'>"
        f"<div style='font-size:11px;opacity:0.85;letter-spacing:0.5px;'>{label}</div>"
        f"<div style='font-size:22px;font-weight:700;margin-top:6px;'>{value}</div>"
        f"<div style='font-size:11px;opacity:0.85;margin-top:4px;'>{sub}</div>"
        f"</td>"
    )


def _verdict_color(actual, bench, higher_better):
    if actual is None or bench is None or bench == 0:
        return "#7f8c8d"
    ratio = actual / bench
    if higher_better:
        if ratio >= 1.5: return "#1abc9c"
        if ratio >= 1.0: return "#3498db"
        if ratio >= 0.7: return "#f39c12"
        return "#e74c3c"
    else:
        if ratio <= 0.7: return "#1abc9c"
        if ratio <= 1.0: return "#3498db"
        if ratio <= 1.5: return "#f39c12"
        return "#e74c3c"


def _build_yearly_kpi(ctx):
    o = ctx.get("overall", {})
    spend = o.get("spend_total_krw")
    pv = o.get("purchase_value_total_krw")
    pur = o.get("purchases_total")
    roas = o.get("roas_avg")
    cpa = o.get("cpa_avg_krw")

    spend_str = f"{int(spend/10000):,}만원" if spend and spend >= 10000 else (f"{int(spend):,}원" if spend else "—")
    pv_str = f"{int(pv/10000):,}만원" if pv and pv >= 10000 else (f"{int(pv):,}원" if pv else "—")
    pur_str = f"{int(pur):,}건" if pur else "—"
    roas_str = f"{roas:.2f}" if roas else "—"
    roas_color = _verdict_color(roas, 2.5, True)
    cpa_str = f"{int(cpa):,}원" if cpa else "—"
    cpa_color = _verdict_color(cpa, 30000, False)

    cards = [
        _kpi_card("총 지출", spend_str, "누적", "#34495e"),
        _kpi_card("총 매출", pv_str, "누적", "#2c3e50"),
        _kpi_card("ROAS", roas_str, f"벤치 2.5 · {pur_str}", roas_color),
        _kpi_card("CPA", cpa_str, "벤치 30,000원", cpa_color),
    ]
    return (
        "<table style='width:100%;border-collapse:separate;border-spacing:8px;margin:0 0 22px 0;'>"
        "<tr>" + "".join(cards) + "</tr></table>"
    )


def _build_funnel_alert(ctx):
    f = ctx.get("funnel", {})
    diag = f.get("diagnosis") or []
    drops = f.get("drop_offs") or []

    # 가장 큰 이탈 단계
    big_items = []
    valid = [d for d in drops if d.get("drop_off_pct") is not None and 0 <= d["drop_off_pct"] <= 100]
    if valid:
        biggest = max(valid, key=lambda d: d["drop_off_pct"])
        big_items.append(
            f"<li style='margin:6px 0;'>최대 이탈: <b>{biggest['from']} → {biggest['to']}</b> "
            f"<b style='color:#c0392b;'>{biggest['drop_off_pct']:.1f}%</b> 이탈 "
            f"({biggest['from_count']:,}→{biggest['to_count']:,})</li>"
        )

    danger = [d for d in diag if d.startswith("🔴") or "악화" in d or "이탈" in d]
    success = [d for d in diag if d.startswith("✅") or "우수" in d or "강함" in d]

    if not (big_items or danger or success):
        return ""

    out = []
    if danger or big_items:
        items = big_items + [f"<li style='margin:6px 0;'>{d}</li>" for d in danger]
        out.append(
            "<div style='background:#fdf2f2;border-left:4px solid #e74c3c;padding:14px 18px;border-radius:6px;margin:0 0 14px 0;'>"
            "<div style='font-weight:700;color:#c0392b;margin-bottom:8px;font-size:14px;'>🔴 약점 — 즉시 개선 필요</div>"
            f"<ul style='margin:0;padding-left:20px;color:#7d2828;'>{''.join(items)}</ul>"
            "</div>"
        )
    if success:
        items = [f"<li style='margin:6px 0;'>{d}</li>" for d in success]
        out.append(
            "<div style='background:#e8f8f5;border-left:4px solid #1abc9c;padding:14px 18px;border-radius:6px;margin:0 0 22px 0;'>"
            "<div style='font-weight:700;color:#0e6655;margin-bottom:8px;font-size:14px;'>✅ 강점 — 응용·확장 검토</div>"
            f"<ul style='margin:0;padding-left:20px;color:#0e6655;'>{''.join(items)}</ul>"
            "</div>"
        )
    return "".join(out)


def _wrap_html(body_html, ctx, chart_cids=None):
    period = ctx.get("period_label", "")
    n_days = ctx.get("n_days_data", "?")
    coverage = ctx.get("data_coverage_pct", "?")
    charts_html = _render_charts_block(chart_cids or [])
    kpi_html = _build_yearly_kpi(ctx)
    alerts_html = _build_funnel_alert(ctx)
    return f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'><title>HeavyLover Meta 광고 종합 심층</title></head>
<body style='font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif;max-width:800px;margin:0 auto;padding:20px;color:#333;line-height:1.6;background:#fafbfc;'>
<div style='background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;padding:20px 22px;border-radius:8px;margin-bottom:22px;box-shadow:0 2px 8px rgba(102,126,234,0.25);'>
  <h1 style='margin:0 0 6px 0;font-size:22px;'>📈 HeavyLover Meta 광고 종합 심층</h1>
  <div style='opacity:0.95;font-size:13px;'>{period} · {n_days}일 누적 (커버리지 {coverage}%) · 4역할 + 퍼널 + 계절성</div>
</div>
{kpi_html}
{alerts_html}
{charts_html}
<div style='background:white;padding:22px;border-radius:8px;border:1px solid #e1e4e8;'>
{body_html}
</div>
<hr style='margin-top:30px;border:none;border-top:1px solid #e1e4e8;'>
<div style='font-size:12px;color:#888;text-align:center;padding-top:8px;'>
  <p>자동 발송 · 매주 일요일 KST 09:00 · meta_ads_yearly_report.py</p>
</div>
</body></html>"""


def _fallback_summary(overall, monthly, funnel, error):
    lines = [
        "[Meta 광고 1년 종합 (fallback)]",
        f"⚠️ Claude 분석 실패: {error}",
        "",
        f"누적 일수: {overall['n_days']}일",
        f"총 지출: {int(overall['spend_total_krw']):,}원",
        f"총 구매: {int(overall['purchases_total'])}건",
        f"평균 ROAS: {overall['roas_avg']:.2f}" if overall['roas_avg'] else "평균 ROAS: N/A",
        f"평균 CPA: {int(overall['cpa_avg_krw']):,}원" if overall['cpa_avg_krw'] else "평균 CPA: N/A",
        f"평균 CTR: {overall['ctr_avg_pct']:.2f}%" if overall['ctr_avg_pct'] else "평균 CTR: N/A",
    ]
    if funnel:
        lines.append("")
        lines.append("[퍼널]")
        lines.append(funnel_to_markdown(funnel))
    return "\n".join(lines)


def build_report(days=365):
    today = datetime.now(KST).date()
    since = (today - timedelta(days=days)).isoformat()
    period_label = f"{since} ~ {(today - timedelta(days=1)).isoformat()}"

    # 1. 데이터 로드
    all_rows = load_csv_rows(DAILY_CSV)
    account_rows = filter_account_rows(all_rows, days)
    camp_rows = load_csv_rows(DAILY_CAMP_CSV)

    n_days = len(account_rows)
    if n_days < 7:
        return {
            "ok": False,
            "reason": f"데이터 누적 부족 ({n_days}/7일 최소). 백필 또는 일일 자동화로 누적 후 재실행.",
            "n_days": n_days,
        }

    # 2. 집계
    overall = aggregate_overall(account_rows)
    monthly = aggregate_by_month(account_rows)
    weekday = aggregate_by_weekday(account_rows)
    campaigns = aggregate_campaigns(camp_rows, days=days, top_n=10)

    # 3. 퍼널
    funnel = load_funnel_aggregate(days=days)
    funnel_diag = funnel_health_diagnosis(funnel) if funnel else []

    # 4. ctx 구성
    ctx = {
        "period_label": period_label,
        "n_days_data": n_days,
        "data_coverage_pct": round(n_days / days * 100, 1),
        "overall": overall,
        "monthly": monthly,
        "weekday": weekday,
        "campaigns_top_roas": [
            {k: v for k, v in c.items() if k != "campaign_id"}
            for c in campaigns["top"]
        ],
        "campaigns_bottom_roas": [
            {k: v for k, v in c.items() if k != "campaign_id"}
            for c in campaigns["bottom"]
        ],
        "n_campaigns_total": campaigns["n_total"],
        "n_campaigns_eligible": campaigns["n_eligible"],
        "funnel": {
            "stage_totals": funnel["stage_totals"] if funnel else None,
            "drop_offs": funnel["drop_offs"] if funnel else None,
            "n_days_aggregated": funnel.get("n_days_aggregated") if funnel else 0,
            "diagnosis": funnel_diag,
        },
    }

    # 5. Claude 호출
    analysis, err = call_claude_4roles(ctx)
    if not analysis:
        analysis = _fallback_summary(overall, monthly, funnel, err)
        is_fallback = True
    else:
        is_fallback = False

    # 6. 차트 생성
    try:
        from lib.charts_meta import generate_meta_yearly_charts
        charts = generate_meta_yearly_charts(monthly, weekday, campaigns, funnel)
    except Exception as e:
        print(f"차트 생성 실패: {e}")
        charts = {}

    return {
        "ok": True,
        "ctx": ctx,
        "analysis": analysis,
        "is_fallback": is_fallback,
        "charts": charts,
    }


def send_email_yearly(report):
    ctx = report["ctx"]
    analysis = report["analysis"]
    charts = report["charts"]
    period = ctx.get("period_label", "?")
    today_label = datetime.now(KST).strftime("%Y-%m-%d")

    body_html = _md_to_html(analysis)
    html = _wrap_html(body_html, ctx, chart_cids=list(charts.keys()))
    fallback_tag = " (fallback)" if report["is_fallback"] else ""
    subject = f"📈 HeavyLover Meta 광고 종합 심층{fallback_tag} — {today_label}"

    try:
        email_sender.send_email(
            subject=subject,
            text_body=analysis,
            html_body=html,
            inline_images=charts,
        )
        return True, None
    except Exception as e:
        return False, str(e)


def send_telegram_summary(report):
    ctx = report["ctx"]
    overall = ctx["overall"]
    n_days = ctx["n_days_data"]
    period = ctx.get("period_label", "")

    def _verdict(actual, bench, higher_better):
        if actual is None or bench is None or bench == 0:
            return "—"
        ratio = actual / bench
        if higher_better:
            if ratio >= 1.5: return "🟢"
            if ratio >= 1.0: return "🔵"
            if ratio >= 0.7: return "🟡"
            return "🔴"
        else:
            if ratio <= 0.7: return "🟢"
            if ratio <= 1.0: return "🔵"
            if ratio <= 1.5: return "🟡"
            return "🔴"

    lines = []
    lines.append(f"📈 [Meta광고 종합 리포트]")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append(f"기간: {period}")
    lines.append(f"누적: {n_days}일  (커버리지 {ctx['data_coverage_pct']}%)")
    lines.append("")

    # 핵심 성과
    lines.append("◆ 핵심 성과")
    lines.append(f"  총 지출   {int(overall['spend_total_krw']):,}원")
    if overall.get("purchase_value_total_krw"):
        lines.append(f"  총 매출   {int(overall['purchase_value_total_krw']):,}원")
    lines.append(f"  총 구매   {int(overall['purchases_total']):,}건")

    if overall.get("roas_avg") is not None:
        em = _verdict(overall['roas_avg'], 2.5, True)
        lines.append(f"  ROAS     {overall['roas_avg']:.2f}  {em}  (벤치 2.5)")
    lines.append("")

    # 효율
    lines.append("◆ 효율")
    if overall.get("ctr_avg_pct") is not None:
        em = _verdict(overall['ctr_avg_pct'], 1.2, True)
        lines.append(f"  CTR      {overall['ctr_avg_pct']:.2f}%  {em}  (벤치 1.2%)")
    if overall.get("cpc_avg_krw") is not None:
        em = _verdict(overall['cpc_avg_krw'], 700, False)
        lines.append(f"  CPC      {int(overall['cpc_avg_krw']):,}원  {em}  (벤치 700원)")
    if overall.get("cpa_avg_krw") is not None:
        em = _verdict(overall['cpa_avg_krw'], 30000, False)
        lines.append(f"  CPA      {int(overall['cpa_avg_krw']):,}원  {em}  (벤치 30,000원)")
    lines.append("")

    # 퍼널 진단
    funnel = ctx.get("funnel", {})
    diag = funnel.get("diagnosis") or []
    if diag:
        lines.append("◆ 퍼널 진단")
        for d in diag[:5]:
            lines.append(f"  {d}")
        lines.append("")

    # 위너 / 패배 캠페인 한 줄씩
    top = ctx.get("campaigns_top_roas") or []
    bot = ctx.get("campaigns_bottom_roas") or []
    if top or bot:
        lines.append("◆ 캠페인")
        if top:
            t = top[0]
            lines.append(f"  🟢 위너 ROAS {t['roas']:.2f} — {(t.get('campaign_name') or '?')[:30]}")
        if bot:
            b = bot[0]
            lines.append(f"  🔴 패배 ROAS {b['roas']:.2f} — {(b.get('campaign_name') or '?')[:30]}")
        lines.append("")

    lines.append("📧 이메일에 4역할 심층 분석 + 차트 4종 도착")

    return telegram_client.send_message("\n".join(lines), channel="ads")


def main():
    print("Meta 광고 1년 종합 리포트 생성 시작")
    report = build_report(days=365)

    if not report["ok"]:
        msg = f"📈 [Meta광고 종합] 생성 실패\n사유: {report['reason']}"
        print(msg)
        try:
            telegram_client.send_message(msg, channel="ads")
        except Exception:
            pass
        return 1

    ok_email, err_email = send_email_yearly(report)
    print(f"이메일: {'OK' if ok_email else 'FAIL: ' + str(err_email)}")

    ok_tel = send_telegram_summary(report)
    print(f"텔레그램: {ok_tel}")

    return 0 if ok_email else 2


if __name__ == "__main__":
    sys.exit(main())
