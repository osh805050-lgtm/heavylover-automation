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
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import email_sender
from meta_ads_client import (
    extract_action,
    extract_action_value,
    extract_cost_per_action,
    extract_purchase_roas,
    fetch_campaign_insights,
    last_n_days_kst,
)

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
    """캠페인 row → 지출/CPA/ROAS/CTR + 원시 지표"""
    spend = _to_float(row.get("spend"))
    impressions = _to_float(row.get("impressions"))
    clicks = _to_float(row.get("clicks"))
    ctr = _to_float(row.get("ctr"))  # Meta 반환 = %

    purchases = _first_non_none(extract_action, row, PURCHASE_ACTION_TYPES)
    purchase_value = _first_non_none(extract_action_value, row, PURCHASE_ACTION_TYPES)
    cpa_api = _first_non_none(extract_cost_per_action, row, PURCHASE_ACTION_TYPES)
    roas_api = extract_purchase_roas(row)

    # CPA 폴백: spend / purchases
    cpa = cpa_api
    if cpa is None and purchases and purchases > 0 and spend is not None:
        cpa = spend / purchases

    # ROAS 폴백: purchase_value / spend
    roas = roas_api
    if roas is None and purchase_value is not None and spend and spend > 0:
        roas = purchase_value / spend

    return {
        "campaign_id": row.get("campaign_id"),
        "campaign_name": row.get("campaign_name") or "(이름 없음)",
        "spend": spend,
        "impressions": impressions,
        "clicks": clicks,
        "ctr_pct": ctr,
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

    return f"<html><head>{css}</head><body>{head}{err_html}{totals_table}{highlight}{campaigns_table}</body></html>"


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
    print("Meta 광고 주간 리포트 생성 시작")

    cur_since, cur_until = last_n_days_kst(n=7, offset_days=0)
    prev_since, prev_until = last_n_days_kst(n=7, offset_days=7)
    print(f"current: {cur_since}~{cur_until}, previous: {prev_since}~{prev_until}")

    errors = []
    cur_raw = fetch_campaign_insights(cur_since, cur_until)
    prev_raw = fetch_campaign_insights(prev_since, prev_until)

    if not cur_raw["ok"]:
        errors.append(f"이번 주 API 실패: {cur_raw['error']}")
    if not prev_raw["ok"]:
        errors.append(f"이전 주 API 실패: {prev_raw['error']}")

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

    html = render_html((cur_since, cur_until), (prev_since, prev_until), comparison, totals, errors)
    text = render_text((cur_since, cur_until), (prev_since, prev_until), comparison, totals, errors)
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
