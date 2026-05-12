"""
Meta 광고 주간 리포트 (캠페인별, 직전 주 대비 비교)

- 지난 7일 (D-7 ~ D-1) vs 이전 7일 (D-14 ~ D-8)
- 캠페인별: 지출, CPA, ROAS, CTR
- |변동률| >= 20% 항목 별도 표시
- 이메일 전송 (제목: "[주별 메타 광고 성과 리포트] YYYY-MM-DD ~ YYYY-MM-DD")

원칙 (CLAUDE.md §0):
- 데이터 없으면 "데이터 없음" 명시
- 이전 기간에 없던 캠페인 = "신규", 이번에 0인 캠페인 = "종료"
- 숫자 창작 금지. 모든 값은 API 응답에서 파생
"""

import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import email_sender
from dotenv import load_dotenv
from meta_ads_client import (
    extract_action,
    extract_action_value,
    extract_cost_per_action,
    extract_purchase_roas,
    fetch_campaign_insights,
    last_n_days_kst,
)
from lib.glossary import glossary_details_html
from lib.meta_currency import _to_krw, _check_account_currency, CURRENCY_KRW_PER_USD, _compare

# Windows cp949 콘솔 대비
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
REPORTS_DIR = ROOT / "docs" / "meta-ads" / "weekly"
KST = timezone(timedelta(hours=9))

CHANGE_THRESHOLD_PCT = 20.0  # 변동 플래그 기준
PURCHASE_ACTION_TYPES = [
    "omni_purchase",
    "purchase",
    "offsite_conversion.fb_pixel_purchase",
]


def _first_non_none(fn, row, keys):
    for k in keys:
        v = fn(row, k)
        if v is not None:
            return v
    return None


def _to_float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def summarize_row(row):
    """캠페인 row → 지출/CPA/ROAS/CTR + 원시 지표 (USD → KRW 환산 적용)"""
    spend = _to_krw(_to_float(row.get("spend")))  # USD → KRW
    impressions = _to_float(row.get("impressions"))
    clicks = _to_float(row.get("clicks"))
    ctr = _to_float(row.get("ctr"))  # Meta 반환 = %

    purchases = _first_non_none(extract_action, row, PURCHASE_ACTION_TYPES)
    purchase_value = _to_krw(_to_float(_first_non_none(extract_action_value, row, PURCHASE_ACTION_TYPES)))  # USD → KRW
    cpa_api = _to_krw(_to_float(_first_non_none(extract_cost_per_action, row, PURCHASE_ACTION_TYPES)))  # USD → KRW
    roas_api, _ = extract_purchase_roas(row)  # 비율 지표 — 환산 불필요

    # CPA 폴백: spend(KRW) / purchases
    cpa = cpa_api
    if cpa is None and purchases and purchases > 0 and spend is not None:
        cpa = spend / purchases

    # ROAS 폴백: purchase_value(KRW) / spend(KRW) — 비율이므로 환산 불필요
    roas = roas_api
    if roas is None and purchase_value is not None and spend and spend > 0:
        roas = purchase_value / spend

    cpc_krw = (spend / clicks) if (spend is not None and clicks and clicks > 0) else None

    return {
        "campaign_id": row.get("campaign_id"),
        "campaign_name": row.get("campaign_name") or "(이름 없음)",
        "spend": spend,
        "impressions": impressions,
        "clicks": clicks,
        "ctr_pct": ctr,
        "cpc_krw": cpc_krw,
        "purchases": purchases,
        "purchase_value": purchase_value,
        "cpa_krw": cpa,
        "roas": roas,
    }


def pct_change(current, previous):
    """변동률(%). 이전값 None/0 처리.

    Returns:
        (change_pct, label)
        - change_pct: float 또는 None
        - label: "신규" / "종료" / f"{change_pct:+.1f}%" / "비교 불가"
    """
    if previous is None and current is None:
        return None, "비교 불가"
    if previous in (None, 0):
        if current and current > 0:
            return None, "신규"
        return None, "비교 불가"
    if current is None or current == 0:
        return -100.0, "종료"
    change = (current - previous) / previous * 100
    return change, f"{change:+.1f}%"


def build_comparison(current_rows, previous_rows):
    """캠페인 ID로 조인하여 비교 테이블 구성"""
    cur = {r["campaign_id"]: r for r in current_rows if r.get("campaign_id")}
    prev = {r["campaign_id"]: r for r in previous_rows if r.get("campaign_id")}
    all_ids = set(cur.keys()) | set(prev.keys())

    rows = []
    for cid in all_ids:
        c = cur.get(cid) or {}
        p = prev.get(cid) or {}

        name = c.get("campaign_name") or p.get("campaign_name") or "(이름 없음)"

        changes = {}
        flagged = False
        for metric in ("spend", "cpa_krw", "roas", "ctr_pct"):
            cv = c.get(metric)
            pv = p.get(metric)
            ch, label = pct_change(cv, pv)
            changes[metric] = {"current": cv, "previous": pv, "change_pct": ch, "label": label}
            if ch is not None and abs(ch) >= CHANGE_THRESHOLD_PCT:
                flagged = True
            if label in ("신규", "종료"):
                flagged = True

        rows.append({
            "campaign_id": cid,
            "campaign_name": name,
            "current": c,
            "previous": p,
            "changes": changes,
            "flagged": flagged,
        })

    # 지출 내림차순
    rows.sort(key=lambda r: (r["current"].get("spend") or 0), reverse=True)
    return rows


def _fmt(v, decimals=0, suffix=""):
    if v is None:
        return "데이터 없음"
    try:
        if decimals == 0:
            return f"{int(round(v)):,}{suffix}"
        return f"{v:,.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return "데이터 없음"


def _cell_change(cell):
    label = cell["label"]
    if label == "비교 불가":
        return label
    return label


# 주간 플래그 임계값 (CLAUDE.md §14 Kill Criteria + 내부 벤치마크)
_WEEKLY_BENCHMARKS = {
    "roas_kill": 2.8,    # K1 경보 기준
    "cpa_warn": 30_000,  # CPA 경고 기준 (원)
    "roas_good": 4.0,    # 우수 기준
    "cpa_good": 20_000,  # 우수 기준 (원)
}


def _build_weekly_flags(totals):
    """7일 집계 기준 자동 플래그. 빈 리스트 반환 시 이상 없음."""
    flags = []
    cur = totals.get("current") or {}
    roas = cur.get("roas")
    cpa = cur.get("cpa_krw")
    if roas is not None and roas < _WEEKLY_BENCHMARKS["roas_kill"]:
        flags.append(
            f"🚨 K1 경보: ROAS {roas:.2f} < 기준 {_WEEKLY_BENCHMARKS['roas_kill']} "
            "— 광고비 -30% 검토 필요"
        )
    if cpa is not None and cpa > _WEEKLY_BENCHMARKS["cpa_warn"]:
        flags.append(
            f"⚠️ CPA {cpa:,.0f}원 > 기준 {_WEEKLY_BENCHMARKS['cpa_warn']:,}원"
        )
    return flags


def render_html(cur_range, prev_range, rows, totals, errors):
    cur_s, cur_u = cur_range
    prv_s, prv_u = prev_range

    css = """
    <style>
      body { font-family: -apple-system, Segoe UI, sans-serif; color: #222; }
      h1 { font-size: 18px; margin-bottom: 4px; }
      .meta { color: #666; font-size: 12px; margin-bottom: 16px; }
      table { border-collapse: collapse; width: 100%; margin-bottom: 16px; font-size: 13px; }
      th, td { border: 1px solid #ddd; padding: 6px 8px; text-align: right; }
      th { background: #f3f3f3; text-align: center; }
      td.name { text-align: left; }
      tr.flagged { background: #fff4d6; }
      .chg-up { color: #b5360c; font-weight: 600; }
      .chg-down { color: #0a6b3b; font-weight: 600; }
      .chg-neu { color: #666; }
      .note { font-size: 12px; color: #444; }
      .err { color: #a00; font-size: 12px; }
    </style>
    """

    def chg_span(cell):
        ch = cell["change_pct"]
        label = cell["label"]
        if label in ("신규", "종료"):
            return f'<span class="chg-up">{label}</span>'
        if ch is None:
            return f'<span class="chg-neu">{label}</span>'
        cls = "chg-up" if abs(ch) >= CHANGE_THRESHOLD_PCT else "chg-neu"
        return f'<span class="{cls}">{label}</span>'

    head = f"""
    <h1>주별 메타 광고 성과 리포트</h1>
    <div class="meta">
      비교 기간: <b>{cur_s} ~ {cur_u}</b> vs {prv_s} ~ {prv_u}<br>
      생성: {datetime.now(KST).isoformat(timespec='seconds')} KST<br>
      하이라이트 기준: |변동률| ≥ {CHANGE_THRESHOLD_PCT:.0f}% 또는 신규/종료
    </div>
    """

    # 집계
    tot_cur = totals["current"]
    tot_prev = totals["previous"]
    tot_chg = totals["changes"]

    totals_table = f"""
    <h3>전체 합계</h3>
    <table>
      <tr>
        <th></th><th>이번 주</th><th>이전 주</th><th>변동</th>
      </tr>
      <tr>
        <td class="name">지출</td>
        <td>{_fmt(tot_cur.get('spend'), 0, '원')}</td>
        <td>{_fmt(tot_prev.get('spend'), 0, '원')}</td>
        <td>{chg_span(tot_chg['spend'])}</td>
      </tr>
      <tr>
        <td class="name">구매 수</td>
        <td>{_fmt(tot_cur.get('purchases'), 0)}</td>
        <td>{_fmt(tot_prev.get('purchases'), 0)}</td>
        <td>{chg_span(tot_chg['purchases'])}</td>
      </tr>
      <tr>
        <td class="name">구매 매출</td>
        <td>{_fmt(tot_cur.get('purchase_value'), 0, '원')}</td>
        <td>{_fmt(tot_prev.get('purchase_value'), 0, '원')}</td>
        <td>{chg_span(tot_chg['purchase_value'])}</td>
      </tr>
      <tr>
        <td class="name">CTR</td>
        <td>{_fmt(tot_cur.get('ctr_pct'), 2, '%')}</td>
        <td>{_fmt(tot_prev.get('ctr_pct'), 2, '%')}</td>
        <td>{chg_span(tot_chg['ctr_pct'])}</td>
      </tr>
      <tr>
        <td class="name">CPA</td>
        <td>{_fmt(tot_cur.get('cpa_krw'), 0, '원')}</td>
        <td>{_fmt(tot_prev.get('cpa_krw'), 0, '원')}</td>
        <td>{chg_span(tot_chg['cpa_krw'])}</td>
      </tr>
      <tr>
        <td class="name">ROAS</td>
        <td>{_fmt(tot_cur.get('roas'), 2)}</td>
        <td>{_fmt(tot_prev.get('roas'), 2)}</td>
        <td>{chg_span(tot_chg['roas'])}</td>
      </tr>
    </table>
    """

    # 캠페인별 테이블
    def campaign_row_html(r):
        c = r["current"]
        ch = r["changes"]
        cls = ' class="flagged"' if r["flagged"] else ""
        return f"""
        <tr{cls}>
          <td class="name">{r['campaign_name']}</td>
          <td>{_fmt(c.get('spend'), 0, '원')}</td>
          <td>{chg_span(ch['spend'])}</td>
          <td>{_fmt(c.get('cpa_krw'), 0, '원')}</td>
          <td>{chg_span(ch['cpa_krw'])}</td>
          <td>{_fmt(c.get('roas'), 2)}</td>
          <td>{chg_span(ch['roas'])}</td>
          <td>{_fmt(c.get('ctr_pct'), 2, '%')}</td>
          <td>{chg_span(ch['ctr_pct'])}</td>
        </tr>
        """

    campaign_rows_html = "\n".join(campaign_row_html(r) for r in rows) or \
        '<tr><td colspan="9">데이터 없음</td></tr>'

    campaigns_table = f"""
    <h3>캠페인별 요약 (지출 내림차순)</h3>
    <table>
      <tr>
        <th rowspan="2">캠페인</th>
        <th colspan="2">지출</th>
        <th colspan="2">CPA</th>
        <th colspan="2">ROAS</th>
        <th colspan="2">CTR</th>
      </tr>
      <tr>
        <th>이번 주</th><th>변동</th>
        <th>이번 주</th><th>변동</th>
        <th>이번 주</th><th>변동</th>
        <th>이번 주</th><th>변동</th>
      </tr>
      {campaign_rows_html}
    </table>
    """

    # 변동 하이라이트 섹션
    flagged = [r for r in rows if r["flagged"]]
    if flagged:
        hl_rows = []
        for r in flagged:
            bits = []
            for metric, kor in [("spend", "지출"), ("cpa_krw", "CPA"), ("roas", "ROAS"), ("ctr_pct", "CTR")]:
                cell = r["changes"][metric]
                if cell["label"] in ("신규", "종료"):
                    bits.append(f"{kor}: {cell['label']}")
                elif cell["change_pct"] is not None and abs(cell["change_pct"]) >= CHANGE_THRESHOLD_PCT:
                    bits.append(f"{kor} {cell['label']}")
            hl_rows.append(f"<li><b>{r['campaign_name']}</b> — {', '.join(bits)}</li>")
        highlight = f"""
        <h3>변동 ≥ {CHANGE_THRESHOLD_PCT:.0f}% 또는 신규/종료 ({len(flagged)}건)</h3>
        <ul>{''.join(hl_rows)}</ul>
        """
    else:
        highlight = f"<h3>변동 ≥ {CHANGE_THRESHOLD_PCT:.0f}% 또는 신규/종료</h3><p>해당 없음</p>"

    err_html = ""
    if errors:
        err_items = "".join(f"<li>{e}</li>" for e in errors)
        err_html = f'<div class="err"><b>경고</b><ul>{err_items}</ul></div>'

    weekly_flags = _build_weekly_flags(totals)
    flags_html = ""
    if weekly_flags:
        flag_items = "".join(f"<li>{f}</li>" for f in weekly_flags)
        flags_html = (
            "<div style='background:#fff3cd;border:1px solid #ffc107;padding:12px;"
            "margin-bottom:16px;border-radius:4px;'>"
            f"<b>자동 플래그</b><ul style='margin:4px 0;'>{flag_items}</ul></div>"
        )

    return f"<html><head>{css}</head><body>{head}{err_html}{flags_html}{totals_table}{highlight}{campaigns_table}{{claude_section}}{{glossary_section}}</body></html>"


def render_text(cur_range, prev_range, rows, totals, errors):
    cur_s, cur_u = cur_range
    prv_s, prv_u = prev_range
    lines = []
    lines.append("주별 메타 광고 성과 리포트")
    lines.append(f"비교 기간: {cur_s} ~ {cur_u} vs {prv_s} ~ {prv_u}")
    lines.append(f"생성: {datetime.now(KST).isoformat(timespec='seconds')} KST")
    lines.append(f"하이라이트 기준: |변동률| >= {CHANGE_THRESHOLD_PCT:.0f}% 또는 신규/종료")
    lines.append("")

    if errors:
        lines.append("[경고]")
        for e in errors:
            lines.append(f" - {e}")
        lines.append("")

    tc, tp, tch = totals["current"], totals["previous"], totals["changes"]
    lines.append("[전체 합계]")
    lines.append(f" 지출: {_fmt(tc.get('spend'),0,'원')} (이전 {_fmt(tp.get('spend'),0,'원')}, {tch['spend']['label']})")
    lines.append(f" 구매: {_fmt(tc.get('purchases'),0)}건 (이전 {_fmt(tp.get('purchases'),0)}, {tch['purchases']['label']})")
    lines.append(f" 매출: {_fmt(tc.get('purchase_value'),0,'원')} (이전 {_fmt(tp.get('purchase_value'),0,'원')}, {tch['purchase_value']['label']})")
    lines.append(f" CTR: {_fmt(tc.get('ctr_pct'),2,'%')} (이전 {_fmt(tp.get('ctr_pct'),2,'%')}, {tch['ctr_pct']['label']})")
    lines.append(f" CPA: {_fmt(tc.get('cpa_krw'),0,'원')} (이전 {_fmt(tp.get('cpa_krw'),0,'원')}, {tch['cpa_krw']['label']})")
    lines.append(f" ROAS: {_fmt(tc.get('roas'),2)} (이전 {_fmt(tp.get('roas'),2)}, {tch['roas']['label']})")
    lines.append("")

    flagged = [r for r in rows if r["flagged"]]
    lines.append(f"[변동 >= {CHANGE_THRESHOLD_PCT:.0f}% 또는 신규/종료] {len(flagged)}건")
    for r in flagged:
        bits = []
        for metric, kor in [("spend","지출"),("cpa_krw","CPA"),("roas","ROAS"),("ctr_pct","CTR")]:
            cell = r["changes"][metric]
            if cell["label"] in ("신규","종료"):
                bits.append(f"{kor}={cell['label']}")
            elif cell["change_pct"] is not None and abs(cell["change_pct"]) >= CHANGE_THRESHOLD_PCT:
                bits.append(f"{kor} {cell['label']}")
        lines.append(f" - {r['campaign_name']}: {', '.join(bits)}")
    lines.append("")

    lines.append("[캠페인별 (지출순)]")
    for r in rows:
        c = r["current"]
        lines.append(
            f" - {r['campaign_name']}: "
            f"지출 {_fmt(c.get('spend'),0,'원')} ({r['changes']['spend']['label']}), "
            f"CPA {_fmt(c.get('cpa_krw'),0,'원')} ({r['changes']['cpa_krw']['label']}), "
            f"ROAS {_fmt(c.get('roas'),2)} ({r['changes']['roas']['label']}), "
            f"CTR {_fmt(c.get('ctr_pct'),2,'%')} ({r['changes']['ctr_pct']['label']})"
        )
    return "\n".join(lines)


def aggregate_totals(rows_summary):
    """캠페인 summary 리스트에서 전체 합계 계산 (비율 지표는 재계산)"""
    spend = sum((r.get("spend") or 0) for r in rows_summary)
    impressions = sum((r.get("impressions") or 0) for r in rows_summary)
    clicks = sum((r.get("clicks") or 0) for r in rows_summary)
    purchases = sum((r.get("purchases") or 0) for r in rows_summary)
    purchase_value = sum((r.get("purchase_value") or 0) for r in rows_summary)

    ctr_pct = (clicks / impressions * 100) if impressions > 0 else None
    cpa_krw = (spend / purchases) if purchases > 0 else None
    roas = (purchase_value / spend) if spend > 0 else None

    return {
        "spend": spend if spend > 0 else None,
        "impressions": impressions if impressions > 0 else None,
        "clicks": clicks if clicks > 0 else None,
        "purchases": purchases if purchases > 0 else None,
        "purchase_value": purchase_value if purchase_value > 0 else None,
        "ctr_pct": ctr_pct,
        "cpa_krw": cpa_krw,
        "roas": roas,
    }


def totals_changes(cur, prev):
    changes = {}
    for k in ("spend", "purchases", "purchase_value", "ctr_pct", "cpa_krw", "roas"):
        ch, label = pct_change(cur.get(k), prev.get(k))
        changes[k] = {"current": cur.get(k), "previous": prev.get(k), "change_pct": ch, "label": label}
    return changes


_WEEKLY_SYSTEM_PROMPT = """당신은 D2C 이커머스 Meta 광고 주간 성과 분석 시스템이다. HeavyLover(냉동 도시락 D2C, 20~30대 운동 직장인 남성 타겟) 광고 주간 성과를 진단한다.

독자 수준: 마케팅·통계 용어 모름. 숫자는 알지만 전문 해석은 낯섦.
목표: 5분 안에 읽고 이번 주 광고가 어땠는지, 다음 주에 뭘 해야 할지 바로 알 수 있게.

전문 용어는 반드시 첫 등장 시 괄호 안에 한국어로 풀어써야 한다:
- ROAS → "ROAS(광고 1원당 돌아오는 매출)"
- CPA → "CPA(고객 1명 구매하는 데 드는 광고비)"
- CTR → "CTR(광고 본 사람 중 클릭한 비율)"

**응답은 반드시 아래 3개 블록 순서대로. 블록 사이 빈 줄 1개.**

---

## 📌 이번 주 핵심 1줄
지난주 대비 가장 중요한 변화를 평어체 1문장으로. 숫자 포함. 전문 용어 없이.
예시: "이번 주는 광고비가 5% 늘었는데 구매는 12% 줄어 고객 1명 사는 비용이 지난주보다 18% 높아졌습니다."

---

## 🤔 왜 이런 변화가 생겼을까?
이유 2~3가지를 쉬운 말로. 형식:
- **이유 1** (확실성: 높음/중간/낮음): 쉬운 설명 1~2문장. 근거 숫자 1개만.
- **이유 2** ...
마지막에 "아직 데이터가 없어서 확인 못 한 것: ..." 한 줄 추가.

---

## ✅ 다음 주 할 일 1가지
구체적으로 딱 1가지. 형식:
**할 일**: (무엇을) (왜) (언제까지)
**기대 효과**: 잘 되면 어떤 숫자가 얼마나 바뀌는지
**확인 방법**: X일 후 어떤 수치를 보면 됨
**안 되면**: 다음 대안

---

**절대 규칙**:
1. 입력 JSON 숫자만 사용. 창작·추측 금지.
2. 한국어. 전문용어는 반드시 첫 등장 시 괄호로 풀이.
3. AI 화법 금지 ("~로 보입니다", "~일 수 있습니다"). 직접 말하기.
4. 3개 블록 전부 완성. 도중에 끊기지 말 것.
5. "개선하자", "검토하자" 같은 모호한 표현 금지 — 구체적 행동만.
6. 헤비로버 상황: ROAS 3.5가 기준선. 결제 단계 이탈이 가장 큰 문제."""

ENV_PATH = Path(__file__).parent / ".env"
WEEKLY_CLAUDE_MODEL = "claude-sonnet-4-6"


def _call_claude_weekly(totals, comparison, cur_range, prev_range):
    """주간 데이터를 Claude에게 넘겨 3블록 분석 반환. 실패 시 None."""
    load_dotenv(ENV_PATH, override=True)
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None

    ctx = {
        "current_range": f"{cur_range[0]} ~ {cur_range[1]}",
        "previous_range": f"{prev_range[0]} ~ {prev_range[1]}",
        "totals_current": totals["current"],
        "totals_previous": totals["previous"],
        "totals_changes": {k: v["label"] for k, v in totals["changes"].items()},
        "campaigns": [
            {
                "name": r["campaign_name"],
                "current": r["current"],
                "changes": {k: v["label"] for k, v in r["changes"].items()},
                "flagged": r["flagged"],
            }
            for r in comparison
        ][:15],
        "static_benchmark": {"roas": 2.5, "cpa_krw": 30000, "ctr_pct": 1.2},
    }

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=WEEKLY_CLAUDE_MODEL,
            max_tokens=2000,
            system=_WEEKLY_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": (
                    f"이번 주({ctx['current_range']}) Meta 광고 주간 성과 데이터:\n\n"
                    f"```json\n{json.dumps(ctx, ensure_ascii=False, indent=2, default=str)}\n```\n\n"
                    "위 3블록 형식대로 주간 심층 분석 작성."
                ),
            }],
        )
        if not resp.content:
            return None
        text = resp.content[0].text.strip()
        if resp.stop_reason == "max_tokens":
            print("⚠️ weekly Claude 응답 truncated (stop_reason=max_tokens)")
            text += "\n\n⚠️ [응답 잘림 — max_tokens 초과]"
        return text
    except Exception as e:
        print(f"주간 Claude 호출 실패: {e}")
        return None


def _weekly_md_to_html(md):
    """주간 Claude 분석 마크다운 → HTML. 재구매 이메일과 동일 배경색 카드."""
    import re
    BLOCK_COLORS = {
        "📌": ("#fff3cd", "#856404", "#ffc107"),
        "🤔": ("#f0f0f0", "#333333", "#6c757d"),
        "✅": ("#d4edda", "#155724", "#28a745"),
    }

    def _bold(s):
        s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
        return s

    lines = md.splitlines()
    out = []
    in_list = False
    in_block = False

    def _close():
        nonlocal in_list, in_block
        if in_list:
            out.append("</ul>"); in_list = False
        if in_block:
            out.append("</div>"); in_block = False

    for line in lines:
        s = line.rstrip()
        if s.startswith("## "):
            _close()
            title = s[3:].strip()
            key = next((e for e in ("📌", "🤔", "✅") if e in title), "")
            bg, fg, border = BLOCK_COLORS.get(key, ("#f8f9fa", "#2c3e50", "#6c757d"))
            out.append(
                f"<div style='background:{bg};border-left:5px solid {border};"
                f"border-radius:0 8px 8px 0;padding:16px 18px;margin:20px 0 8px 0;'>"
                f"<div style='font-size:15px;font-weight:800;color:{fg};margin-bottom:10px;'>{title}</div>"
            )
            in_block = True
        elif s.startswith("- "):
            if not in_list:
                out.append("<ul style='margin:6px 0;padding-left:18px;'>"); in_list = True
            out.append(f"<li style='margin:5px 0;line-height:1.6;'>{_bold(s[2:].strip())}</li>")
        elif s == "---":
            _close()
        elif s == "":
            if in_list:
                out.append("</ul>"); in_list = False
        else:
            out.append(f"<p style='margin:6px 0;line-height:1.7;'>{_bold(s)}</p>")

    _close()
    return "\n".join(out)


def save_artifact(cur_range, html, text, meta):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{cur_range[0]}_to_{cur_range[1]}"
    (REPORTS_DIR / f"{stem}.html").write_text(html, encoding="utf-8")
    (REPORTS_DIR / f"{stem}.txt").write_text(text, encoding="utf-8")
    (REPORTS_DIR / f"{stem}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return REPORTS_DIR / f"{stem}.html"


def run():
    DRY_RUN = os.getenv("META_WEEKLY_DRY_RUN") == "1"
    if DRY_RUN:
        print("[DRY RUN] META_WEEKLY_DRY_RUN=1 — 이메일 발송 없이 HTML만 저장합니다.")
    _check_account_currency()
    print("Meta 광고 주간 리포트 생성 시작")

    cur_since, cur_until = last_n_days_kst(n=7, offset_days=0)
    prev_since, prev_until = last_n_days_kst(n=7, offset_days=7)
    print(f"current: {cur_since}~{cur_until}, previous: {prev_since}~{prev_until}")

    errors = []
    cur_raw = fetch_campaign_insights(cur_since, cur_until)
    prev_raw = fetch_campaign_insights(prev_since, prev_until)

    _TOKEN_EXPIRY = ["OAuthException", "Session has expired", "401", "code:190", "code:463"]
    if not cur_raw["ok"]:
        errors.append(f"이번 주 API 실패: {cur_raw['error']}")
        if any(k in (cur_raw.get("error") or "") for k in _TOKEN_EXPIRY):
            try:
                from telegram_client import send_message
                send_message(
                    f"⚠️ Meta 주간 리포트 — 토큰 만료 의심\n오류: {(cur_raw.get('error') or '')[:200]}",
                    channel="ops",
                )
            except Exception:
                pass
    if not prev_raw["ok"]:
        errors.append(f"이전 주 API 실패: {prev_raw['error']}")
        if any(k in (prev_raw.get("error") or "") for k in _TOKEN_EXPIRY):
            try:
                from telegram_client import send_message
                send_message(
                    f"⚠️ Meta 주간 리포트(이전 주) — 토큰 만료 의심\n오류: {(prev_raw.get('error') or '')[:200]}",
                    channel="ops",
                )
            except Exception:
                pass

    cur_rows = [summarize_row(r) for r in cur_raw.get("data", [])]
    prev_rows = [summarize_row(r) for r in prev_raw.get("data", [])]

    comparison = build_comparison(cur_rows, prev_rows)

    cur_total = aggregate_totals(cur_rows)
    prev_total = aggregate_totals(prev_rows)
    totals = {
        "current": cur_total,
        "previous": prev_total,
        "changes": totals_changes(cur_total, prev_total),
    }

    html_raw = render_html((cur_since, cur_until), (prev_since, prev_until), comparison, totals, errors)
    text = render_text((cur_since, cur_until), (prev_since, prev_until), comparison, totals, errors)

    # DRY RUN 조기 종료 — Claude API 호출 및 이메일 발송 전에 차단
    if DRY_RUN:
        dry_html = html_raw.replace("{claude_section}", "").replace("{glossary_section}", "")
        dry_path = ROOT / "dry_run_weekly.html"
        dry_path.write_text(dry_html, encoding="utf-8")
        print(f"[DRY RUN] HTML 저장: {dry_path}")
        return 0

    # Claude 주간 분석 (3블록) + 용어 풀이
    print("Claude 주간 분석 호출 중...")
    claude_md = _call_claude_weekly(totals, comparison, (cur_since, cur_until), (prev_since, prev_until))
    if claude_md:
        claude_html = (
            "<hr style='margin:32px 0;border:none;border-top:2px solid #dee2e6;'>"
            "<h2 style='color:#2c3e50;font-size:17px;margin-bottom:4px;'>📊 이번 주 인사이트 (Claude 분석)</h2>"
            + _weekly_md_to_html(claude_md)
        )
        print("Claude 주간 분석 완료")
    else:
        claude_html = "<p style='color:#888;font-size:13px;'>Claude 분석 생략 (API 미응답)</p>"
        print("Claude 분석 스킵")

    html = html_raw.replace("{claude_section}", claude_html).replace("{glossary_section}", glossary_details_html())

    meta = {
        "current_range": [cur_since, cur_until],
        "previous_range": [prev_since, prev_until],
        "errors": errors,
        "totals": totals,
        "campaigns": comparison,
        "raw_current": cur_raw.get("data", []),
        "raw_previous": prev_raw.get("data", []),
    }
    path = save_artifact((cur_since, cur_until), html, text, meta)
    print(f"리포트 저장: {path}")

    subject = f"[주별 메타 광고 성과 리포트] {cur_since} ~ {cur_until}"
    try:
        email_sender.send_email(subject, text, html)
        print("이메일 전송 완료")
    except Exception as e:
        print(f"이메일 전송 실패: {e}")
        return 2

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(run())
