"""Meta 광고 일일 심층 이메일 — 4역할 페르소나 + 차트 인라인.

기존 report_email_daily.py(재구매 일일)와 동일 수준:
- 4역할 (분석가/전략가/회의주의자/의사결정자) 1회 호출
- 차트 PNG 인라인 첨부 (lib/charts_meta.py)
- 마크다운→HTML 간이 변환
- Anthropic 401 시 fallback (원시 숫자 표)

호출: meta_ads_report.py에서 Claude 짧은 코멘트 + 이메일 심층 두 종 중
이메일 단계를 본 모듈로 격상.
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from anthropic import Anthropic
from dotenv import load_dotenv

import email_sender
from lib.charts_meta import generate_meta_daily_charts
from lib.glossary import glossary_details_html
from meta_ads_funnel_analysis import overall_funnel, funnel_to_markdown, funnel_health_diagnosis

KST = timezone(timedelta(hours=9))
ENV_PATH = Path(__file__).parent / ".env"

CLAUDE_MODEL = "claude-sonnet-4-6"  # 일일 리포트 — 비용 효율 우선 (월간만 opus)
MAX_TOKENS = 4000


SYSTEM_PROMPT = """당신은 D2C 이커머스 Meta 광고 운영 분석 시스템이다. HeavyLover(냉동 도시락 D2C, 20~30대 운동 직장인 남성 타겟) 광고 성과를 매일 진단한다.

독자는 마케팅 비전공자 창업자다. 전문 용어를 쓸 때는 반드시 괄호 안에 한국어로 풀어써야 한다.
용어 풀이 필수 예시:
- ROAS → "ROAS(광고 1원당 돌아오는 매출)"
- CPA → "CPA(고객 1명 사는 데 드는 광고비)"
- CTR → "CTR(광고 본 사람 중 클릭한 비율)"
- Frequency → "Frequency(같은 사람에게 광고 노출된 평균 횟수)"
- Kill Criteria / K1 → "광고 중단 기준(ROAS가 2.8 아래로 3일 연속이면 광고비 -30%)"
- P50 → "P50(우리 광고 성과 중간값)"
- P75 → "P75(우리 광고 성과 상위 25% 기준값)"
- CBO → "CBO(캠페인 예산 자동 배분 방식)"
- ABO → "ABO(광고 세트별 예산 직접 지정 방식)"
- drop-off → "이탈(그 단계에서 포기한 사람 비율)"

**한 응답 안에 4명이 순차로 발언**한다. 각 섹션은 반드시 모두 작성해야 하며 중간에 끊기면 안 된다.

---

## 1. 분석가 (숫자 정리)
- 어제 핵심 지표 5~7개를 표로 (지표 / 실측 / 업계 기준 / 우리 평균 / 판정)
- 7일 추세에서 눈에 띄는 변화 명시
- 캠페인 단위 변동 ≥20%면 별도 표기
- 퍼널에서 가장 많이 이탈하는 단계 1~2개 명시 (예: "상품페이지→장바구니 91% 이탈")
- 추측 금지. 숫자만.

## 2. 전략가 (원인 추정)
- 위 변화의 가능한 원인 3개, 각각 확신도(높음/중간/낮음) 표시
- 잘 됐던 광고 패턴(있으면)과 연결해 설명
- 추정이면 "추정" 명시

## 3. 회의주의자 (반박)
- 전략가 원인 각각에 "데이터가 부족해서 단정 못 하는 이유" 지적
- 하루치 데이터로 결론 내리기 어려운 부분 명시
- 숫자 간 모순 지적

## 4. 오늘 할 일 (결론)
- 반박을 반영해 지금 당장 할 수 있는 구체적 액션 1~3개
- 형식: "(무엇을) → (왜) → (며칠 후 어떤 숫자로 확인)"
- 퍼널에서 가장 많이 이탈하는 단계 개선 액션 1개 필수
- 광고비 50% 이상 조정 권고는 신중히 (이유 명시)
- "개선하자", "검토하자" 같은 모호한 표현 금지 — 구체적 행동만

---

**규칙**:
1. 입력 JSON 숫자만 사용. 창작 금지.
2. 한국어. 전문용어는 반드시 괄호로 풀이.
3. 이모지 최소 (✅⚠️🔴📊만 허용)
4. AI 화법 금지 ("~로 보입니다", "알아보겠습니다")
5. 4개 섹션 전부 완성할 것. 도중에 끊기지 말 것.
6. 헤비로버 상황: 광고비 대비 매출이 3.5배가 기준선, 결제 단계에서 절반이 이탈하는 것이 가장 큰 문제, 광고는 Meta 단독 의존"""


USER_TEMPLATE = """오늘({target_date}) Meta 광고 ground truth + 7일 추세 + 자사 벤치 + 위너 패턴:

```json
{ctx_json}
```

위 4역할 형식대로 일일 심층 리포트 작성."""


def _build_context(target_date, metrics, self_bench, flags, recent_trend,
                   campaigns, winner_patterns, raw_account_rows=None):
    ctx = {
        "target_date": target_date,
        "metrics": {k: v for k, v in metrics.items() if not k.startswith("_")},
        "static_benchmark_2026_kr_food": {
            "ctr_pct": 1.2, "cpc_krw": 700, "roas": 2.5,
            "cpa_krw": 30000, "frequency_low": 2.0, "frequency_high": 4.0,
        },
        "self_benchmark_30d": {
            m: {"p25": b.get("p25"), "p50": b.get("p50"), "p75": b.get("p75"),
                "n": b.get("n"), "ok": b.get("ok"), "reason": b.get("reason")}
            for m, b in (self_bench or {}).items()
        },
        "auto_flags": flags or [],
        "recent_7d_trend": recent_trend or [],
        "campaigns_today": [
            {k: v for k, v in c.items() if k != "raw_json_path"}
            for c in (campaigns or [])
        ][:20],
        "winner_patterns_recent": (winner_patterns or [])[:5],
    }

    # 퍼널 — raw account row가 있으면 단계별 drop-off 분석 포함
    if raw_account_rows:
        try:
            funnel = overall_funnel(raw_account_rows)
            ctx["funnel_today"] = {
                "stage_totals": funnel["stage_totals"],
                "drop_offs": funnel["drop_offs"],
                "diagnosis": funnel_health_diagnosis(funnel),
            }
        except Exception as e:
            ctx["funnel_today"] = {"error": str(e)}

    return ctx


def call_claude_4roles(ctx):
    load_dotenv(ENV_PATH, override=True)
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None, "ANTHROPIC_API_KEY 미설정"

    client = Anthropic(api_key=api_key)
    user = USER_TEMPLATE.format(
        target_date=ctx["target_date"],
        ctx_json=json.dumps(ctx, ensure_ascii=False, indent=2, default=str),
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
    """Markdown → HTML. ## 섹션마다 배경색 카드로 분리해 가독성 확보."""
    import re

    # 섹션별 색상 (헤더 텍스트에 숫자 기준)
    SECTION_COLORS = {
        "1": ("#e8f4f8", "#0c5460", "#17a2b8"),   # 파랑 — 숫자 정리
        "2": ("#fff8e1", "#856404", "#ffc107"),   # 노랑 — 원인 추정
        "3": ("#fdf2f8", "#6c1f57", "#e83e8c"),   # 분홍 — 반박
        "4": ("#d4edda", "#155724", "#28a745"),   # 초록 — 오늘 할 일
    }

    def _bold(s):
        s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
        s = re.sub(r'\*(.+?)\*', r'<em>\1</em>', s)
        return s

    lines = md.splitlines()
    out = []
    in_list = False
    in_table = False
    in_section = False

    def _close_all():
        nonlocal in_list, in_table, in_section
        if in_list:
            out.append("</ul>"); in_list = False
        if in_table:
            out.append("</table>"); in_table = False
        if in_section:
            out.append("</div>"); in_section = False

    for line in lines:
        s = line.rstrip()

        if s.startswith("## "):
            _close_all()
            title = s[3:].strip()
            # 섹션 번호 추출 (예: "1. 분석가" → "1")
            num_match = re.match(r'^(\d+)', title)
            num = num_match.group(1) if num_match else ""
            bg, fg, border = SECTION_COLORS.get(num, ("#f8f9fa", "#2c3e50", "#6c757d"))
            out.append(
                f"<div style='background:{bg};border-left:5px solid {border};"
                f"border-radius:0 8px 8px 0;padding:16px 18px;margin:20px 0 8px 0;'>"
                f"<div style='font-size:16px;font-weight:800;color:{fg};margin-bottom:10px;"
                f"letter-spacing:-0.3px;'>{title}</div>"
            )
            in_section = True

        elif s.startswith("- "):
            if in_table:
                out.append("</table>"); in_table = False
            if not in_list:
                out.append("<ul style='margin:6px 0 6px 0;padding-left:18px;'>"); in_list = True
            out.append(f"<li style='margin:5px 0;line-height:1.6;'>{_bold(s[2:].strip())}</li>")

        elif s.startswith("|") and s.endswith("|"):
            if in_list:
                out.append("</ul>"); in_list = False
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set("-:| ") for c in cells):
                continue
            is_header = not in_table
            if not in_table:
                out.append(
                    "<div style='overflow-x:auto;margin:10px 0;'>"
                    "<table style='border-collapse:collapse;width:100%;font-size:13px;'>"
                )
                in_table = True
            if is_header:
                cells_html = "".join(
                    f"<th style='border:1px solid #dee2e6;padding:8px 12px;"
                    f"background:#343a40;color:white;text-align:left;white-space:nowrap;'>{c}</th>"
                    for c in cells
                )
            else:
                cells_html = "".join(
                    f"<td style='border:1px solid #dee2e6;padding:7px 12px;"
                    f"background:white;vertical-align:top;'>{_bold(c)}</td>"
                    for c in cells
                )
            out.append(f"<tr>{cells_html}</tr>")

        elif s == "---":
            _close_all()

        elif s == "":
            if in_list:
                out.append("</ul>"); in_list = False
            if in_table:
                out.append("</table></div>"); in_table = False

        else:
            if in_table:
                out.append("</table></div>"); in_table = False
            out.append(f"<p style='margin:6px 0;line-height:1.7;'>{_bold(s)}</p>")

    _close_all()
    if in_table:
        out.append("</table></div>")
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
    return f"<h2 style='color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:4px;'>📊 시각화 요약</h2>{table}"


def _kpi_card(label, value, sub, color):
    """KPI 카드 1개 — 모바일에서 한눈에."""
    return (
        f"<td style='width:25%;padding:12px;background:{color};color:white;border-radius:6px;text-align:center;'>"
        f"<div style='font-size:11px;opacity:0.85;letter-spacing:0.5px;'>{label}</div>"
        f"<div style='font-size:20px;font-weight:700;margin-top:4px;'>{value}</div>"
        f"<div style='font-size:11px;opacity:0.85;margin-top:4px;'>{sub}</div>"
        f"</td>"
    )


def _verdict_color(actual, bench, higher_better, palette=None):
    """벤치 대비 색상 — 카드 배경에 사용."""
    palette = palette or {
        "good": "#1abc9c", "ok": "#3498db", "warn": "#f39c12", "bad": "#e74c3c", "neutral": "#7f8c8d"
    }
    if actual is None or bench is None or bench == 0:
        return palette["neutral"]
    ratio = actual / bench
    if higher_better:
        if ratio >= 1.5: return palette["good"]
        if ratio >= 1.0: return palette["ok"]
        if ratio >= 0.7: return palette["warn"]
        return palette["bad"]
    else:
        if ratio <= 0.7: return palette["good"]
        if ratio <= 1.0: return palette["ok"]
        if ratio <= 1.5: return palette["warn"]
        return palette["bad"]


def _build_kpi_cards(ctx):
    """일일 핵심 지표 4개 카드 (지출/구매/ROAS/CPA)."""
    m = ctx.get("metrics", {})
    bench = ctx.get("static_benchmark_2026_kr_food", {})

    spend = m.get("spend")
    purchases = m.get("purchases")
    roas = m.get("roas")
    cpa = m.get("cpa_krw")

    spend_str = f"{int(spend):,}원" if spend else "—"
    pur_str = f"{int(purchases):,}건" if purchases else "—"
    pur_value = m.get("purchase_value_krw")
    pur_value_str = f"매출 {int(pur_value):,}원" if pur_value else ""

    roas_str = f"{roas:.2f}" if roas else "—"
    roas_color = _verdict_color(roas, bench.get("roas", 2.5), True)
    roas_sub = f"벤치 {bench.get('roas', 2.5)}"

    cpa_str = f"{int(cpa):,}원" if cpa else "—"
    cpa_color = _verdict_color(cpa, bench.get("cpa_krw", 30000), False)
    cpa_sub = f"벤치 {bench.get('cpa_krw', 30000):,}원"

    cards = [
        _kpi_card("지출", spend_str, "오늘", "#34495e"),
        _kpi_card("구매", pur_str, pur_value_str or "오늘", "#2c3e50"),
        _kpi_card("ROAS", roas_str, roas_sub, roas_color),
        _kpi_card("CPA", cpa_str, cpa_sub, cpa_color),
    ]
    return (
        "<table style='width:100%;border-collapse:separate;border-spacing:8px;margin:0 0 20px 0;'>"
        "<tr>" + "".join(cards) + "</tr></table>"
    )


def _build_alerts_box(ctx):
    """플래그·퍼널 약점을 경고 박스로."""
    flags = ctx.get("auto_flags") or []
    funnel = ctx.get("funnel_today") or {}
    drops = funnel.get("drop_offs") or []
    big_drop = None
    if drops:
        valid = [d for d in drops if d.get("drop_off_pct") is not None]
        if valid:
            big_drop = max(valid, key=lambda d: d["drop_off_pct"])

    items = []
    for f in flags:
        items.append(f"<li style='margin:4px 0;'>{f}</li>")
    if big_drop:
        items.append(
            f"<li style='margin:4px 0;'>퍼널 최대 이탈: "
            f"<b>{big_drop['from']} → {big_drop['to']}</b> "
            f"<b>{big_drop['drop_off_pct']:.1f}%</b> 이탈 "
            f"({big_drop['from_count']:,}→{big_drop['to_count']:,})</li>"
        )

    if not items:
        return ""

    return (
        "<div style='background:#fff8e1;border-left:4px solid #f39c12;padding:14px 18px;border-radius:6px;margin:0 0 20px 0;'>"
        "<div style='font-weight:700;color:#b8770e;margin-bottom:8px;font-size:14px;'>⚠️ 즉시 확인 필요</div>"
        f"<ul style='margin:0;padding-left:20px;color:#5d4204;'>{''.join(items)}</ul>"
        "</div>"
    )


def _wrap_html(body_html, target_date, chart_cids=None, sheet_url="", ctx=None):
    from datetime import datetime, timezone, timedelta
    KST = timezone(timedelta(hours=9))
    generated_at = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    charts_html = _render_charts_block(chart_cids or [])
    sheet_link_html = (
        f"<a href='{sheet_url}' style='color:#667eea;'>📊 Google Sheets 열기</a>" if sheet_url else ""
    )
    kpi_html = _build_kpi_cards(ctx) if ctx else ""
    alerts_html = _build_alerts_box(ctx) if ctx else ""
    model_label = CLAUDE_MODEL.replace("claude-", "").replace("-", " ").upper()

    return f"""<!DOCTYPE html>
<html><head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>HeavyLover Meta 광고 일일</title>
</head>
<body style='font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",Malgun Gothic,sans-serif;max-width:720px;margin:0 auto;padding:16px;color:#222;line-height:1.65;background:#f0f2f5;'>

<!-- 헤더 -->
<div style='background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;padding:22px 24px;border-radius:12px;margin-bottom:16px;box-shadow:0 4px 12px rgba(102,126,234,0.3);'>
  <div style='font-size:11px;opacity:0.8;letter-spacing:1px;margin-bottom:6px;'>HEAVYLOVER · META 광고 일일 리포트</div>
  <h1 style='margin:0 0 6px 0;font-size:24px;font-weight:800;letter-spacing:-0.5px;'>📈 {target_date} 광고 성과</h1>
  <div style='opacity:0.9;font-size:13px;'>분석 모델: {model_label} &nbsp;|&nbsp; 생성: {generated_at}</div>
</div>

<!-- KPI 카드 -->
{kpi_html}

<!-- 경고 박스 -->
{alerts_html}

<!-- 차트 -->
{charts_html}

<!-- 본문 -->
<div style='background:white;border-radius:12px;border:1px solid #e1e4e8;padding:24px;margin-top:4px;box-shadow:0 1px 4px rgba(0,0,0,0.06);'>
{body_html}
</div>

<!-- 푸터 -->
<div style='margin-top:20px;padding:12px 0;border-top:1px solid #dee2e6;font-size:11px;color:#aaa;text-align:center;'>
  매일 09:00 KST 자동 발송 &nbsp;|&nbsp; {sheet_link_html}
</div>

</body></html>"""


def _fallback_text(target_date, metrics, flags, error_msg):
    return f"""HeavyLover Meta 광고 일일 (fallback) — {target_date}

⚠️ Claude 4역할 분석 실패 — 원시 숫자만 전달
사유: {error_msg}

[핵심 지표]
- 지출: {metrics.get('spend')}원
- 노출: {metrics.get('impressions')}
- 클릭: {metrics.get('clicks')}
- CTR: {metrics.get('ctr_pct')}%
- CPC: {metrics.get('cpc_krw')}원
- ROAS: {metrics.get('roas')}
- CPA: {metrics.get('cpa_krw')}원
- Frequency: {metrics.get('frequency')}
- 구매: {metrics.get('purchases')}건

[자동 플래그]
{chr(10).join(f'- {f}' for f in flags) if flags else '특이사항 없음'}
"""


def send_daily_email(target_date, metrics, self_bench, flags,
                    recent_trend, campaigns, winner_patterns,
                    sheet_url="", raw_account_rows=None):
    """일일 심층 메일 발송. 성공 True / 실패 False."""
    ctx = _build_context(target_date, metrics, self_bench, flags,
                         recent_trend, campaigns, winner_patterns,
                         raw_account_rows=raw_account_rows)

    # 차트 생성 (실패해도 메일은 발송)
    bench_static = ctx["static_benchmark_2026_kr_food"]
    try:
        charts = generate_meta_daily_charts(metrics, bench_static, recent_trend, campaigns)
    except Exception as e:
        print(f"차트 생성 실패: {e}")
        charts = {}

    # Claude 4역할 호출
    analysis, err = call_claude_4roles(ctx)

    if analysis:
        body_html = glossary_details_html() + _md_to_html(analysis)
        html = _wrap_html(body_html, target_date, chart_cids=list(charts.keys()),
                          sheet_url=sheet_url, ctx=ctx)
        text_body = analysis
        model_short = "Opus" if "opus" in CLAUDE_MODEL else "Sonnet"
        subject = f"📈 HeavyLover Meta 광고 일일 [{model_short}] — {target_date}"
    else:
        # 크레딧 부족 여부를 ops 채널에 별도 알림
        if err and "credit balance is too low" in str(err).lower():
            try:
                from telegram_client import send_message
                send_message(
                    f"🚨 Anthropic 크레딧 부족 — Meta 광고 분석 실패\n"
                    f"console.anthropic.com → Plans & Billing → Add credits\n"
                    f"에러: {str(err)[:200]}",
                    channel="ops",
                )
            except Exception:
                pass
        text_body = _fallback_text(target_date, metrics, flags, err or "분석 실패")
        body_html = glossary_details_html() + _md_to_html(text_body)
        html = _wrap_html(body_html, target_date, chart_cids=list(charts.keys()),
                          sheet_url=sheet_url, ctx=ctx)
        subject = f"⚠️ HeavyLover Meta 광고 일일 (fallback) — {target_date}"

    try:
        email_sender.send_email(
            subject=subject,
            text_body=text_body,
            html_body=html,
            inline_images=charts,
        )
        return True, None
    except Exception as e:
        return False, f"이메일 발송 실패: {e}"


if __name__ == "__main__":
    # 단독 테스트 — 더미 데이터
    target = datetime.now(KST).date().isoformat()
    metrics = {"spend": 121901, "impressions": 20323, "clicks": 301,
               "ctr_pct": 1.48, "cpc_krw": 405, "frequency": 1.25,
               "purchases": 6, "purchase_value_krw": 411191,
               "cpa_krw": 20317, "roas": 3.37, "conv_rate_pct": 1.99}
    ok, err = send_daily_email(target, metrics, {}, [], [], [], [])
    print(f"send_daily_email: ok={ok} err={err}")
