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
from meta_ads_funnel_analysis import overall_funnel, funnel_to_markdown, funnel_health_diagnosis

KST = timezone(timedelta(hours=9))
ENV_PATH = Path(__file__).parent / ".env"

CLAUDE_MODEL = "claude-opus-4-7"  # 재구매 일일과 동일
MAX_TOKENS = 2500


SYSTEM_PROMPT = """당신은 D2C 이커머스 Meta 광고 운영 분석 시스템이다. HeavyLover(냉동 도시락 D2C, 20~30대 운동 직장인 남성 타겟) 광고 성과를 매일 진단한다.

**한 응답 안에 4명이 순차로 발언**한다. 각 페르소나는 분명히 분리된 섹션으로 작성하고, 다음 형식을 정확히 따른다:

---

## 1. 분석가 (사실 정리)
- 어제 핵심 지표 5~7개를 표로 (지표 / 실측 / 업계 벤치 / 자사 P50 / 판정)
- 7일 추세에서 변곡점·이상치(±2σ) 명시
- 캠페인 단위 변동 ≥20%면 별도 표기
- **퍼널 단계별 drop-off**: funnel_today.drop_offs에서 가장 큰 이탈 단계 1~2개 명시 (예: "콘텐츠→장바구니 91% 이탈")
- 추측·해석 금지. 오직 입력 JSON에 있는 숫자만.

## 2. 전략가 (가설 제시)
- 위 변화의 가능한 원인 3개를 가설로 제시 (오디언스 피로 / 크리에이티브 노화 / 외부 시즌성 등)
- 각 가설에 신뢰도(높음/중간/낮음) 표시
- 위너 광고 패턴(있으면)과 연결해 "왜 잘됐나/잘 안됐나" 가설
- 단정 금지, "가설" 명시

## 3. 회의주의자 (반박)
- 전략가 가설 각각에 대해 데이터 한계·반례 지적
- "1일치로 트렌드 단정 가능한가?" 검증
- Frequency·CTR·CPA·ROAS 간 모순 지적
- 가설이 약하면 솔직히 "단정 불가" 선언

## 4. 의사결정자 (액션 권고)
- 회의주의자 반박 반영해 **검증 가능한** 액션 1~3개
- 형식: "(액션) → (예상 효과) → (검증 지표·기간)"
- 예시:
  - "캠페인 X 일시정지 → CPA 45,200원이 벤치×1.5 초과 + 7일 연속 악화 → 3일 후 잔존 캠페인 CPA 모니터"
  - "위너 광고 'XX_30대남_단백질40g' 예산 +20% → 자사 P75 상회 14일 연속 → 7일 후 ROAS 재측정"
- **퍼널 약점 단계 액션 1개 필수** (가장 큰 drop-off 단계 개선): 예 "콘텐츠→장바구니 92% 이탈 → 상세페이지 첫 스크롤 후킹 강화 → 7일 후 add_to_cart 비율 +2%p 목표"
- 광고비 ±50% 이상 조정 권고는 신중히 (이유 명시)
- 모호한 권고("최적화하자") 금지

---

**규칙**:
1. 입력 JSON에 있는 숫자만 사용. 창작 금지.
2. 한국어. 1000~1800자 이내. 표·불릿 적극 활용.
3. 이모지 최소 (✅⚠️🔴📊만 허용)
4. AI 화법 금지 ("~로 보입니다", "알아보겠습니다")
5. 헤비로버 컨텍스트: ROAS 베이스라인 3.5, Cafe24 100% Meta 의존, M+1 리텐션 14% 개선이 1순위, CBO Broad 메인 + ABO 테스트, Broad > Lookalike, ASC는 주 50전환+ 시 활성"""


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
    """간단 Markdown → HTML 변환 (헤더·불릿·표만). report_email_daily와 동일 패턴."""
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
            out.append(f"<h2 style='color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:4px;margin-top:24px;'>{s[3:].strip()}</h2>")
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
    return f"<h2 style='color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:4px;'>📊 시각화 요약</h2>{table}"


def _wrap_html(body_html, target_date, chart_cids=None, sheet_url=""):
    today_label = target_date
    charts_html = _render_charts_block(chart_cids or [])
    sheet_link_html = (
        f"<p>시트: <a href='{sheet_url}'>HeavyLover Meta Ads</a></p>" if sheet_url else ""
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'><title>HeavyLover Meta 광고 일일 심층</title></head>
<body style='font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif;max-width:760px;margin:0 auto;padding:20px;color:#333;line-height:1.55;'>
<div style='background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white;padding:18px 20px;border-radius:6px;margin-bottom:20px;'>
  <h1 style='margin:0 0 6px 0;font-size:22px;'>📈 HeavyLover Meta 광고 일일 심층</h1>
  <div style='opacity:0.95;font-size:13px;'>{today_label} · 4역할 페르소나 분석 + 시각화</div>
</div>
{charts_html}
{body_html}
<hr style='margin-top:30px;'>
<div style='font-size:12px;color:#888;'>
  <p>자동 발송 · GitHub Actions cron (KST 09:00) · 매일 자동</p>
  {sheet_link_html}
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
        body_html = _md_to_html(analysis)
        html = _wrap_html(body_html, target_date, chart_cids=list(charts.keys()),
                          sheet_url=sheet_url)
        text_body = analysis
        subject = f"📈 HeavyLover Meta 광고 일일 심층 — {target_date}"
    else:
        text_body = _fallback_text(target_date, metrics, flags, err or "분석 실패")
        body_html = _md_to_html(text_body)
        html = _wrap_html(body_html, target_date, chart_cids=list(charts.keys()),
                          sheet_url=sheet_url)
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
