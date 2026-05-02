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
from lib.kpi_cards import build_kpi_cards_html
from lib.glossary import glossary_details_html

KST = timezone(timedelta(hours=9))
ENV_PATH = Path(__file__).parent / ".env"


SYSTEM_PROMPT = """당신은 HeavyLover(냉동 도시락 D2C) 재구매 지표를 분석하는 전문가다. 독자는 비전공자 창업자 1명이다.

독자 수준: 마케팅·통계 용어 모름. 숫자는 알지만 전문 해석은 낯섦.
목표: 5분 안에 읽고 오늘 뭘 해야 할지 바로 알 수 있게.

**응답은 반드시 아래 4개 블록 순서대로. 블록 사이 빈 줄 1개.**

---

## 📌 오늘의 핵심 1줄
가장 중요한 변화를 평어체 1문장으로. 숫자 포함. 전문 용어 없이.
예시: "이번 달 재구매 고객이 지난달보다 32% 줄었습니다 — 원인 확인이 필요합니다."

---

## 📊 숫자 현황
아래 4가지만, 표 없이 불릿으로 간결하게:
- 이번 달 재구매 매출: XXX만원 (지난달보다 +X% / -X%)
- 첫 구매 후 2번째 구매한 비율: X% (목표 30%)
- 첫 구매 후 한 달 안에 돌아온 고객 비율: X% (목표 20%)
- 평균 재구매 간격: X일

이상한 수치 있으면 ⚠️ 표시 후 한 줄 설명. 없으면 생략.

---

## 🤔 왜 이런 수치가 나왔을까?
이유 2~3가지를 쉬운 말로. 형식:
- **이유 1** (확실성: 높음/중간/낮음): 쉬운 설명 1~2문장. 근거 숫자 1개만.
- **이유 2** ...
마지막에 "아직 데이터가 없어서 확인 못 한 것: ..." 한 줄 추가.

---

## ✅ 오늘 할 일 1가지
구체적으로 딱 1가지. 형식:
**할 일**: (누가) (무엇을) (언제까지)
**기대 효과**: 잘 되면 어떤 숫자가 얼마나 바뀌는지
**확인 방법**: X주 후에 어떤 수치를 보면 됨
**안 되면**: 다음 대안

---

**절대 규칙**:
- 입력 JSON 숫자만 사용. 만들어내기 금지.
- 전문 용어 쓰면 즉시 괄호로 풀이. 예: 코호트(같은 달에 처음 산 고객 묶음)
- "~로 보입니다", "~일 수 있습니다", "살펴보겠습니다" 금지. 직접 말하기.
- 가설이면 "아직 확인 안 됨" 명시.
- 전체 800~1200자. 짧고 명확하게."""

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
            model="claude-sonnet-4-6",
            max_tokens=3500,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        print(f"Claude API 오류: {e}")
        return None


def _md_to_html(md: str) -> str:
    """Markdown → HTML. 블록 헤더(## 📌/📊/🤔/✅)는 배경색 카드로 렌더링."""
    # 헤더별 색상
    BLOCK_COLORS = {
        "📌": ("#fff3cd", "#856404"),   # 노랑 — 핵심 1줄
        "📊": ("#e8f4f8", "#0c5460"),   # 파랑 — 숫자 현황
        "🤔": ("#f0f0f0", "#333"),       # 회색 — 이유
        "✅": ("#d4edda", "#155724"),   # 초록 — 할 일
    }
    lines = md.splitlines()
    out = []
    in_list = False
    in_table = False
    in_block = False

    def _close_block():
        nonlocal in_block
        if in_block:
            out.append("</div>")
            in_block = False

    def _bold(s):
        import re
        return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)

    for line in lines:
        s = line.rstrip()
        if s.startswith("## "):
            if in_list:
                out.append("</ul>")
                in_list = False
            if in_table:
                out.append("</table>")
                in_table = False
            _close_block()
            title = s[3:].strip()
            bg, fg = "#f8f9fa", "#2c3e50"
            for emoji, (b, f) in BLOCK_COLORS.items():
                if emoji in title:
                    bg, fg = b, f
                    break
            out.append(
                f"<div style='background:{bg};border-left:4px solid {fg};padding:14px 16px;"
                f"margin:16px 0 8px 0;border-radius:0 6px 6px 0;'>"
                f"<div style='font-size:15px;font-weight:bold;color:{fg};margin-bottom:8px;'>{title}</div>"
            )
            in_block = True
        elif s.startswith("- "):
            if not in_list:
                out.append("<ul style='margin:4px 0 4px 16px;padding:0;'>")
                in_list = True
            out.append(f"<li style='margin:4px 0;'>{_bold(s[2:].strip())}</li>")
        elif s.startswith("|") and s.endswith("|"):
            if in_list:
                out.append("</ul>")
                in_list = False
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(set(c) <= set("-:| ") for c in cells):
                continue
            tag = "th" if not in_table else "td"
            if not in_table:
                out.append("<table style='border-collapse:collapse;margin:8px 0;width:100%;'>")
                in_table = True
            style = "border:1px solid #ddd;padding:7px 12px;background:#fff;" if tag == "td" \
                else "border:1px solid #ccc;padding:7px 12px;background:#f0f0f0;font-weight:bold;"
            cells_html = "".join(f"<{tag} style='{style}'>{c}</{tag}>" for c in cells)
            out.append(f"<tr>{cells_html}</tr>")
        elif s == "---":
            if in_list:
                out.append("</ul>")
                in_list = False
            if in_table:
                out.append("</table>")
                in_table = False
            _close_block()
        elif s == "":
            if in_list:
                out.append("</ul>")
                in_list = False
            if in_table:
                out.append("</table>")
                in_table = False
        else:
            out.append(f"<p style='margin:5px 0;'>{_bold(s)}</p>")

    if in_list:
        out.append("</ul>")
    if in_table:
        out.append("</table>")
    _close_block()
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
    try:
        kpi_html = build_kpi_cards_html(gt)
    except Exception as e:
        print(f"KPI 카드 생성 실패: {e}")
        kpi_html = ""
    return f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'><title>HeavyLover 재구매 일일 리포트</title></head>
<body style='font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",sans-serif;max-width:760px;margin:0 auto;padding:20px;color:#333;line-height:1.55;'>
<div style='background:#f8f9fa;padding:16px;border-radius:6px;margin-bottom:16px;'>
  <h1 style='margin:0 0 6px 0;color:#1a73e8;font-size:20px;'>📊 HeavyLover 재구매 일일 심층</h1>
  <div style='color:#666;font-size:13px;'>{today} · 6섹션 페르소나 분석</div>
</div>
{kpi_html}
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
            html = _wrap_html(
                glossary_details_html() + _md_to_html(analysis),
                enriched,
                chart_cids=list(charts.keys()),
            )
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
            # 크레딧 부족이면 ops 채널 즉시 알림
            try:
                from telegram_client import send_message as _tg
                _tg(
                    f"🚨 Anthropic 크레딧 부족 — 재구매 분석 실패\n"
                    f"console.anthropic.com → Plans & Billing → Add credits",
                    channel="ops",
                )
            except Exception:
                pass
            text, html = fallback_email_body(enriched, "Anthropic API 크레딧 부족 또는 호출 실패")
            html_with_charts = _wrap_html(
                glossary_details_html() + _md_to_html(text),
                enriched,
                chart_cids=list(charts.keys()),
            )
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
