"""매일 09:10 이메일 심층 분석 — 4역할 페르소나 1회 호출.

분석가 → 전략가 → 회의주의자 → 의사결정자 가 순차로 발화하는
단일 Claude 호출. 비용 효율(API 1회) + 다관점 효과.

Anthropic 401 시 fallback: 원시 숫자 표 + 안내문.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from anthropic import Anthropic
from dotenv import load_dotenv

from sheets_sync import _open_sheet
from repurchase_report import build_ground_truth
from email_sender import send_email
from lib.historical_data import enrich
from lib import recommendation_log
from lib.charts import generate_daily_charts

KST = timezone(timedelta(hours=9))
ENV_PATH = Path(__file__).parent / ".env"


SYSTEM_PROMPT = """당신은 D2C 이커머스 운영 분석 시스템이다. HeavyLover(냉동 도시락 D2C, 20~30대 운동 직장인 남성 타겟) 재구매 KPI를 매일 진단한다.

**한 응답 안에 4명이 순차로 발언**한다. 각 페르소나는 분명히 분리된 섹션으로 작성하고, 다음 형식을 정확히 따른다:

---

## 1. 분석가 (사실 정리)
- 어제·당월 핵심 숫자 3~5개를 표 형식으로 (지표 / 값 / WoW / MoM / 이상치 여부)
- 이상치 플래그(±2σ) 명시
- 추측·해석 금지. 오직 입력 JSON에 있는 숫자만.

## 2. 전략가 (가설 제시)
- 위 변화의 가능한 원인 3개를 가설로 제시
- 각 가설에 신뢰도(높음/중간/낮음) 표시
- 외부 요인(시즌·광고·신제품) 가능성 포함
- 단정 금지, "가설" 명시

## 3. 회의주의자 (반박)
- 전략가 가설 각각에 대해 데이터 한계·반례 지적
- "이 데이터로 그 결론이 가능한가?" 검증
- 빠진 데이터·교란 변수 명시
- 가설이 약하면 솔직히 "단정 불가" 선언

## 4. 의사결정자 (액션 권고)
- 회의주의자 반박 반영해 **검증 가능한** 액션 1개만
- 형식: "(액션) → (예상 효과) → (검증 지표·기간)"
- 예: "M+1 코호트에 7일차 SMS 발송 → M+1 리텐션 14% → 18% 향상 → 4주 후 4월 코호트 M+1 재측정"
- 모호한 권고("개선하자") 금지

---

**규칙**:
1. 입력 JSON에 있는 숫자만 사용. 창작 금지.
2. 한국어. 800~1500자 이내. 표·불릿 적극 활용.
3. 이모지 최소 (✅⚠️🔴📊만 허용)
4. AI 화법 금지 ("~로 보입니다", "알아보겠습니다")"""

USER_PROMPT_TEMPLATE = """오늘의 ground truth + 7일 누적 비교 + 이상치 플래그:

```json
{gt_json}
```

{recommendation_block}

위 4역할 형식대로 일일 심층 리포트 작성."""


def call_claude(enriched_gt: dict, rec_block: str = "") -> str | None:
    load_dotenv(ENV_PATH, override=True)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    client = Anthropic(api_key=api_key)
    gt_json = json.dumps(enriched_gt, ensure_ascii=False, indent=2, default=str)
    user = USER_PROMPT_TEMPLATE.format(gt_json=gt_json, recommendation_block=rec_block)

    try:
        resp = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=2500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"Claude API 오류: {e}")
        return None


def _md_to_html(md: str) -> str:
    """간단 Markdown → HTML 변환 (헤더·불릿·표만)."""
    lines = md.splitlines()
    out = []
    in_list = False
    in_table = False
    for line in lines:
        s = line.rstrip()
        if s.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            if in_table:
                out.append("</table>")
                in_table = False
            out.append(f"<h2 style='color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:4px;'>{s[3:].strip()}</h2>")
        elif s.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{s[2:].strip()}</li>")
        elif s.startswith("|") and s.endswith("|"):
            if in_list:
                out.append("</ul>")
                in_list = False
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set("-:| ") for c in cells):
                continue  # separator row
            tag = "th" if not in_table else "td"
            if not in_table:
                out.append("<table style='border-collapse:collapse;margin:8px 0;'>")
                in_table = True
            cells_html = "".join(
                f"<{tag} style='border:1px solid #ddd;padding:6px 12px;'>{c}</{tag}>" for c in cells
            )
            out.append(f"<tr>{cells_html}</tr>")
        elif s == "---":
            if in_list:
                out.append("</ul>")
                in_list = False
            if in_table:
                out.append("</table>")
                in_table = False
            out.append("<hr style='border:none;border-top:1px solid #eee;margin:16px 0;'>")
        elif s == "":
            if in_list:
                out.append("</ul>")
                in_list = False
            if in_table:
                out.append("</table>")
                in_table = False
            out.append("<br>")
        else:
            out.append(f"<p style='margin:8px 0;'>{s}</p>")
    if in_list:
        out.append("</ul>")
    if in_table:
        out.append("</table>")
    return "\n".join(out)


def _render_charts_block(chart_cids: list[str]) -> str:
    """차트 cid 리스트를 받아 모바일/데스크톱 양쪽 호환 그리드 HTML 반환."""
    if not chart_cids:
        return ""
    cells = "".join(
        f"<td style='padding:6px;width:50%;vertical-align:top;'>"
        f"<img src='cid:{cid}' style='width:100%;max-width:380px;height:auto;display:block;border-radius:4px;'>"
        f"</td>"
        for cid in chart_cids
    )
    rows = []
    cells_per_row = 2
    chunks = [chart_cids[i:i + cells_per_row] for i in range(0, len(chart_cids), cells_per_row)]
    for chunk in chunks:
        row_cells = "".join(
            f"<td style='padding:6px;width:50%;vertical-align:top;'>"
            f"<img src='cid:{cid}' style='width:100%;max-width:380px;height:auto;display:block;border-radius:4px;'>"
            f"</td>"
            for cid in chunk
        )
        if len(chunk) < cells_per_row:
            row_cells += "<td style='width:50%;'></td>" * (cells_per_row - len(chunk))
        rows.append(f"<tr>{row_cells}</tr>")
    table = f"<table style='width:100%;border-collapse:collapse;margin:16px 0;'>{''.join(rows)}</table>"
    return f"<h2 style='color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:4px;'>📈 시각화 요약</h2>{table}"


def _wrap_html(body_html: str, gt: dict, chart_cids: list[str] | None = None) -> str:
    today = datetime.now(KST).strftime("%Y-%m-%d (%a)")
    charts_html = _render_charts_block(chart_cids or [])
    return f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'><title>HeavyLover 재구매 일일 리포트</title></head>
<body style='font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif;max-width:760px;margin:0 auto;padding:20px;color:#333;line-height:1.55;'>
<div style='background:#f8f9fa;padding:16px;border-radius:6px;margin-bottom:20px;'>
  <h1 style='margin:0 0 6px 0;color:#1a73e8;'>📊 HeavyLover 재구매 일일 심층</h1>
  <div style='color:#666;'>{today} · 4역할 페르소나 분석</div>
</div>
{charts_html}
{body_html}
<hr style='margin-top:30px;'>
<div style='font-size:12px;color:#888;'>
  <p>자동 발송 · 시트: <a href='https://docs.google.com/spreadsheets/d/1DEEz2iSa_REKUsYetyZMSqZsVm6_LFbOAasrzXjYU5s'>재구매 분석시트</a></p>
  <p>리포트 위치: Vultr /root/heavylover-repurchase/ · 매일 09:10 자동</p>
</div>
</body></html>"""


def fallback_email_body(enriched_gt: dict, error_msg: str) -> tuple[str, str]:
    """Claude 401 등 실패 시 원시 숫자 표만 보내는 fallback."""
    inm = enriched_gt.get("월별_재구매_매출", {}).get("통합", {}) or {}
    cur = inm.get("당월", {}) or {}
    prev = inm.get("전월", {}) or {}
    stages = enriched_gt.get("단계별_전환율_현재", {}).get("통합") or []
    s_1to2 = next((s for s in stages if s.get("단계") == "1→2"), {})
    s_2to3 = next((s for s in stages if s.get("단계") == "2→3"), {})

    mn = enriched_gt.get("M+N_리텐션_통합") or []
    m1_recent = mn[-1].get("M+1") if mn else "—"

    flags = enriched_gt.get("이상치_플래그") or []

    text = f"""HeavyLover 재구매 일일 리포트 (fallback 모드)

⚠️ Claude 분석 실패 — 원시 숫자만 전달
{error_msg}

[당월 vs 전월]
- 당월 재구매 매출: {cur.get('매출')}
- 전월 재구매 매출: {prev.get('매출')}
- MoM: {inm.get('MoM_변화_pct')}%

[단계별 전환]
- 1→2: {s_1to2.get('전환율')}% ({s_1to2.get('해석', '')})
- 2→3: {s_2to3.get('전환율')}%

[코호트 잔존]
- 최신 M+1: {m1_recent}%

[이상치 플래그]
{json.dumps(flags, ensure_ascii=False, indent=2) if flags else "없음"}

Anthropic 결제 활성 후 자동으로 4역할 분석 재개됩니다.
"""
    html = _wrap_html(_md_to_html(text), enriched_gt)
    return text, html


def main() -> int:
    today = datetime.now(KST).strftime("%Y-%m-%d")
    try:
        ss = _open_sheet()
        gt = build_ground_truth(ss)
        enriched = enrich(gt)
        rec_block = recommendation_log.format_for_prompt(days=7)

        analysis = call_claude(enriched, rec_block=rec_block)

        try:
            charts = generate_daily_charts(gt, enriched)
        except Exception as e:
            print(f"차트 생성 실패: {e}")
            charts = {}

        if analysis:
            html = _wrap_html(_md_to_html(analysis), enriched, chart_cids=list(charts.keys()))
            send_email(
                subject=f"📊 HeavyLover 재구매 일일 — {today}",
                text_body=analysis,
                html_body=html,
                inline_images=charts,
            )
            # 의사결정자 액션을 추출해 recommendations.jsonl에 저장
            # (간단 휴리스틱: "## 4. 의사결정자" 섹션 텍스트)
            action = ""
            if "의사결정자" in analysis:
                parts = analysis.split("의사결정자")
                if len(parts) >= 2:
                    section = parts[1].split("##")[0].strip()
                    action = section[:300]
            if action:
                recommendation_log.append(today, "daily", action)
            print(f"일일 이메일 발송 완료 ({today})")
            return 0
        else:
            text, html = fallback_email_body(enriched, "Anthropic API 401 또는 호출 실패")
            # fallback도 차트는 포함 (분석 텍스트 없어도 시각화는 가치)
            html_with_charts = _wrap_html(_md_to_html(text), enriched, chart_cids=list(charts.keys()))
            send_email(
                subject=f"⚠️ HeavyLover 재구매 일일 (fallback) — {today}",
                text_body=text,
                html_body=html_with_charts,
                inline_images=charts,
            )
            print(f"일일 이메일 fallback 발송 ({today})")
            return 0
    except Exception as e:
        err = f"일일 이메일 치명적 오류: {e}"
        print(err)
        try:
            send_email(
                subject=f"🚨 HeavyLover 일일 리포트 오류 — {today}",
                text_body=err,
            )
        except Exception:
            pass
        return 2


if __name__ == "__main__":
    sys.exit(main())
