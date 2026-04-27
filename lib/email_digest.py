"""정부지원 레이더 주간 다이제스트 (Gmail HTML)

매주 월요일 08:00 KST 자동 발송. 지난 7일간 govt_radar 결과 누적 → 핵심 정리.

전제:
  - email_sender.py가 SMTP_USER/PASSWORD 등으로 발송 가능 상태
  - data/govt_radar/radar_YYYYMMDD.json 파일 누적

내용:
  1. 헤더: 기간 + 핵심 KPI
  2. 🚨 마감 임박 (D-7 이내) — 즉시 액션 필요
  3. ⭐ 이번주 신규 S/A 등급
  4. 📈 7일 추이 (수집량·적합 비율)
  5. 🔗 자세히 (GitHub 마크다운 + 캘린더)
"""

import json
import logging
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import email_sender

KST = timezone(timedelta(hours=9))
DATA_DIR = Path(__file__).parent.parent / "data" / "govt_radar"

log = logging.getLogger(__name__)


def _load_recent_results(days=7):
    """지난 N일 govt_radar 결과 JSON 로드 + 통합.

    Returns:
        list[dict]: 모든 공고 (중복 제거 — pblancId 기준)
    """
    today = datetime.now(KST).date()
    seen = {}
    daily_counts = {}

    for offset in range(days):
        d = today - timedelta(days=offset)
        f = DATA_DIR / f"radar_{d.strftime('%Y%m%d')}.json"
        if not f.exists():
            continue
        with open(f, "r", encoding="utf-8") as fp:
            items = json.load(fp)
        daily_counts[d.isoformat()] = {
            "total": len(items),
            "S": sum(1 for x in items if x.get("score", 0) >= 9),
            "A": sum(1 for x in items if 7 <= x.get("score", 0) < 9),
            "B": sum(1 for x in items if 5 <= x.get("score", 0) < 7),
        }
        for it in items:
            key = it.get("title", "") + "|" + (it.get("deadline") or "")
            if key not in seen or it.get("score", 0) > seen[key].get("score", 0):
                seen[key] = it

    return list(seen.values()), daily_counts


def _filter_actionable(items, today):
    """마감 D-7 이내 + 적합도 ≥ 5 (신청 가능)"""
    out = []
    for it in items:
        if it.get("score", 0) < 5:
            continue
        deadline = it.get("deadline")
        if not deadline:
            continue
        try:
            d = datetime.strptime(deadline, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        days_left = (d - today).days
        if 0 <= days_left <= 7:
            out.append(it)
    return sorted(out, key=lambda x: (x.get("deadline") or "9999"))


def _filter_high_grade(items):
    """S + A 등급"""
    return [it for it in items if it.get("score", 0) >= 7]


def _render_announcement_html(item, accent_color="#d32f2f"):
    """공고 한 건 HTML 카드"""
    title = escape(item.get("title", ""))
    score = item.get("score", 0)
    fit = item.get("fit_score", 0)
    region = item.get("region_score", 0)
    deadline_score = item.get("deadline_score", 0)
    region_label = escape(item.get("region_label", "?"))
    agency = escape(item.get("agency", "") or "")
    deadline = item.get("deadline") or ""
    days_left = item.get("deadline_days")
    body = escape((item.get("body_excerpt") or "")[:400])
    matched = ", ".join(escape(m) for m in item.get("matched", [])[:6])
    url = escape(item.get("url", ""))

    raw = item.get("raw", {}) or {}
    target = escape(str(raw.get("trgetNm") or raw.get("biz_enyy") or ""))
    realm = escape(str(raw.get("realm") or raw.get("supt_biz_clsfc") or ""))

    deadline_badge = ""
    if deadline and days_left is not None:
        if days_left <= 3:
            deadline_badge = f'<span style="background:#d32f2f;color:#fff;padding:2px 8px;border-radius:3px;font-size:11px;font-weight:600;">D-{days_left} 긴급</span>'
        elif days_left <= 7:
            deadline_badge = f'<span style="background:#f57c00;color:#fff;padding:2px 8px;border-radius:3px;font-size:11px;font-weight:600;">D-{days_left}</span>'

    score_html = f"""
        <span style="display:inline-block;background:{accent_color};color:#fff;font-weight:700;
                     padding:3px 10px;border-radius:12px;font-size:13px;margin-right:8px;">
            {score}/10
        </span>
    """

    return f"""
    <div style="border:1px solid #e0e0e0;border-radius:6px;padding:14px 16px;margin-bottom:12px;background:#fff;">
        <div style="margin-bottom:8px;">
            {score_html}
            {deadline_badge}
            <strong style="font-size:15px;color:#222;">{title}</strong>
        </div>
        <div style="color:#666;font-size:13px;margin-bottom:6px;">
            📊 적합 {fit} + 지역 {region} + 마감 {deadline_score} ({region_label})
            {f'  ·  📅 {deadline} (D{days_left})' if deadline else ''}
        </div>
        {f'<div style="color:#555;font-size:13px;margin-bottom:4px;">🏛 <strong>{agency}</strong></div>' if agency else ''}
        {f'<div style="color:#555;font-size:13px;margin-bottom:4px;">👥 {target}</div>' if target else ''}
        {f'<div style="color:#555;font-size:13px;margin-bottom:8px;">🏷 {realm}</div>' if realm else ''}
        {f'<div style="color:#444;font-size:13px;line-height:1.5;margin:8px 0;padding:10px;background:#fafafa;border-left:3px solid {accent_color};">{body}</div>' if body else ''}
        {f'<div style="color:#777;font-size:12px;margin-top:6px;">🔑 매칭: {matched}</div>' if matched else ''}
        {f'<div style="margin-top:10px;"><a href="{url}" style="color:#1a73e8;text-decoration:none;font-size:13px;">🔗 공고 원문 보기 →</a></div>' if url else ''}
    </div>
    """


def _render_trend_html(daily_counts):
    """7일 추이 표"""
    if not daily_counts:
        return ""
    rows = []
    for date in sorted(daily_counts.keys()):
        d = daily_counts[date]
        rows.append(f"""
            <tr>
                <td style="padding:6px 10px;border-bottom:1px solid #eee;">{date}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;">{d['total']}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;color:#d32f2f;font-weight:600;">{d['S']}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;color:#f57c00;font-weight:600;">{d['A']}</td>
                <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right;color:#388e3c;">{d['B']}</td>
            </tr>
        """)

    return f"""
    <table style="width:100%;border-collapse:collapse;font-size:13px;background:#fff;border:1px solid #e0e0e0;border-radius:6px;overflow:hidden;">
        <thead style="background:#f5f5f5;">
            <tr>
                <th style="padding:8px 10px;text-align:left;font-weight:600;">날짜</th>
                <th style="padding:8px 10px;text-align:right;font-weight:600;">전체</th>
                <th style="padding:8px 10px;text-align:right;font-weight:600;">S</th>
                <th style="padding:8px 10px;text-align:right;font-weight:600;">A</th>
                <th style="padding:8px 10px;text-align:right;font-weight:600;">B</th>
            </tr>
        </thead>
        <tbody>
            {"".join(rows)}
        </tbody>
    </table>
    """


def build_digest_html(items, daily_counts, today):
    """다이제스트 HTML 본문 구성"""
    actionable = _filter_actionable(items, today)
    high_grade = _filter_high_grade(items)

    # 통계
    total_collected = sum(d["total"] for d in daily_counts.values())
    s_count = sum(d["S"] for d in daily_counts.values())
    a_count = sum(d["A"] for d in daily_counts.values())

    # 시작/끝 일자
    if daily_counts:
        dates = sorted(daily_counts.keys())
        period = f"{dates[0]} ~ {dates[-1]}"
    else:
        period = today.isoformat()

    sections_html = []

    # 1. 마감 임박 (최우선)
    if actionable:
        cards = "\n".join(_render_announcement_html(it, "#d32f2f") for it in actionable)
        sections_html.append(f"""
        <h2 style="font-size:18px;color:#d32f2f;margin:24px 0 12px 0;">
            🚨 즉시 액션 — 마감 D-7 이내 ({len(actionable)}건)
        </h2>
        {cards}
        """)
    else:
        sections_html.append("""
        <div style="padding:14px;background:#e8f5e9;border-radius:6px;margin:24px 0 12px 0;color:#2e7d32;">
            ✅ 마감 D-7 이내 적합 공고 없음 — 여유 있는 한 주
        </div>
        """)

    # 2. 신규 S/A 등급
    if high_grade:
        # 마감 임박 제외 (이미 위에서 표시)
        actionable_keys = {(it.get("title"), it.get("deadline")) for it in actionable}
        new_high = [it for it in high_grade if (it.get("title"), it.get("deadline")) not in actionable_keys]

        if new_high:
            new_high_sorted = sorted(new_high, key=lambda x: -x.get("score", 0))[:15]
            cards = "\n".join(_render_announcement_html(it, "#f57c00") for it in new_high_sorted)
            sections_html.append(f"""
            <h2 style="font-size:18px;color:#f57c00;margin:32px 0 12px 0;">
                ⭐ 이번주 S·A 등급 ({len(new_high_sorted)}건 / 전체 {len(new_high)}건)
            </h2>
            {cards}
            """)

    # 3. 추이
    sections_html.append(f"""
    <h2 style="font-size:18px;color:#333;margin:32px 0 12px 0;">
        📈 지난 7일 추이
    </h2>
    {_render_trend_html(daily_counts)}
    """)

    # 4. 푸터
    sections_html.append(f"""
    <div style="margin-top:32px;padding:16px;background:#f5f5f5;border-radius:6px;color:#666;font-size:12px;line-height:1.6;">
        <p style="margin:0 0 6px 0;"><strong>📌 헤비로버 정부지원 레이더</strong></p>
        <p style="margin:0 0 6px 0;">매일 11:00 KST 텔레그램 알림 + 매주 월요일 다이제스트</p>
        <p style="margin:0 0 6px 0;">소스: 기업마당 API · K-Startup API · 네이버 메일 · 8개 포털</p>
        <p style="margin:0;">자동 생성 · 본사: 경기도 용인시 수지구</p>
    </div>
    """)

    body = "\n".join(sections_html)

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"></head>
    <body style="font-family:-apple-system,'맑은 고딕',sans-serif;background:#f9f9f9;margin:0;padding:20px;color:#333;">
        <div style="max-width:720px;margin:0 auto;background:#fff;border-radius:8px;padding:28px;box-shadow:0 1px 3px rgba(0,0,0,0.05);">
            <div style="border-bottom:2px solid #1a73e8;padding-bottom:16px;margin-bottom:8px;">
                <h1 style="font-size:22px;color:#1a73e8;margin:0 0 6px 0;">
                    🎯 정부지원 레이더 주간 다이제스트
                </h1>
                <p style="color:#666;margin:0;font-size:13px;">{period}</p>
            </div>

            <div style="display:flex;gap:12px;margin:20px 0;flex-wrap:wrap;">
                <div style="flex:1;min-width:120px;padding:12px;background:#e3f2fd;border-radius:6px;text-align:center;">
                    <div style="font-size:11px;color:#666;">7일 누적 수집</div>
                    <div style="font-size:24px;font-weight:700;color:#1565c0;">{total_collected:,}</div>
                </div>
                <div style="flex:1;min-width:120px;padding:12px;background:#ffebee;border-radius:6px;text-align:center;">
                    <div style="font-size:11px;color:#666;">S 등급 (긴급)</div>
                    <div style="font-size:24px;font-weight:700;color:#c62828;">{s_count}</div>
                </div>
                <div style="flex:1;min-width:120px;padding:12px;background:#fff3e0;border-radius:6px;text-align:center;">
                    <div style="font-size:11px;color:#666;">A 등급 (계획서)</div>
                    <div style="font-size:24px;font-weight:700;color:#ef6c00;">{a_count}</div>
                </div>
                <div style="flex:1;min-width:120px;padding:12px;background:#fce4ec;border-radius:6px;text-align:center;">
                    <div style="font-size:11px;color:#666;">즉시 액션</div>
                    <div style="font-size:24px;font-weight:700;color:#ad1457;">{len(actionable)}</div>
                </div>
            </div>

            {body}
        </div>
    </body>
    </html>
    """


def build_digest_text(items, daily_counts, today):
    """다이제스트 텍스트 (HTML 폴백)"""
    actionable = _filter_actionable(items, today)
    high_grade = _filter_high_grade(items)

    lines = []
    lines.append("=" * 60)
    lines.append("🎯 정부지원 레이더 주간 다이제스트")
    if daily_counts:
        dates = sorted(daily_counts.keys())
        lines.append(f"기간: {dates[0]} ~ {dates[-1]}")
    lines.append("=" * 60)
    lines.append("")

    if actionable:
        lines.append(f"🚨 즉시 액션 — 마감 D-7 이내 ({len(actionable)}건)")
        lines.append("-" * 60)
        for it in actionable:
            lines.append(f"\n[{it['score']}] {it['title']}")
            lines.append(f"  📅 마감 {it.get('deadline')} (D{it.get('deadline_days', '?')})")
            if it.get("agency"):
                lines.append(f"  🏛 {it['agency']}")
            if it.get("url"):
                lines.append(f"  🔗 {it['url']}")
        lines.append("")
    else:
        lines.append("✅ 마감 D-7 이내 적합 공고 없음")
        lines.append("")

    if high_grade:
        actionable_keys = {(it.get("title"), it.get("deadline")) for it in actionable}
        new_high = [it for it in high_grade if (it.get("title"), it.get("deadline")) not in actionable_keys]
        new_high_sorted = sorted(new_high, key=lambda x: -x.get("score", 0))[:15]
        if new_high_sorted:
            lines.append(f"⭐ 이번주 S·A 등급 ({len(new_high_sorted)}건)")
            lines.append("-" * 60)
            for it in new_high_sorted:
                lines.append(f"[{it['score']}] {it['title'][:70]}")
            lines.append("")

    return "\n".join(lines)


def send_weekly_digest(test_mode=False):
    """주간 다이제스트 발송 (메인 함수)

    Args:
        test_mode: True면 발송 없이 콘솔 출력만

    Returns:
        dict: {"ok": bool, "items": int, "actionable": int, "error"?: str}
    """
    today = datetime.now(KST).date()
    items, daily_counts = _load_recent_results(days=7)

    if not items:
        log.warning("지난 7일 결과 데이터 없음 — 다이제스트 스킵")
        return {"ok": False, "items": 0, "error": "no_data"}

    actionable = _filter_actionable(items, today)
    high_grade = _filter_high_grade(items)

    html = build_digest_html(items, daily_counts, today)
    text = build_digest_text(items, daily_counts, today)

    subject = (
        f"[정부지원 레이더] {today.strftime('%m/%d')} 주간 다이제스트 "
        f"— 즉시 액션 {len(actionable)}건, S·A {len(high_grade)}건"
    )

    if test_mode:
        print("=" * 70)
        print(f"제목: {subject}")
        print("=" * 70)
        print(text)
        print("=" * 70)
        print(f"(HTML {len(html)}자)")
        return {"ok": True, "items": len(items), "actionable": len(actionable), "test_mode": True}

    try:
        email_sender.send_email(subject=subject, text_body=text, html_body=html)
        log.info(f"다이제스트 발송 성공 (수신처: EMAIL_TO)")
        return {"ok": True, "items": len(items), "actionable": len(actionable)}
    except Exception as e:
        log.error(f"다이제스트 발송 실패: {e}")
        return {"ok": False, "items": len(items), "error": str(e)}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    test = "--test" in sys.argv or "--dry-run" in sys.argv
    result = send_weekly_digest(test_mode=test)
    print(json.dumps(result, ensure_ascii=False, indent=2))
