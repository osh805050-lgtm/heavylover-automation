"""Meta 광고 퍼널 이탈 분석.

Meta Pixel 이벤트 기반 단계별 drop-off:
  노출(impressions) → 클릭(link_click) → 콘텐츠 조회(view_content)
  → 장바구니(add_to_cart) → 결제 시작(initiate_checkout) → 구매(purchase)

용도:
- 일일 리포트의 보조 분석 — "어디서 가장 많이 떨어지는지"
- 1년치 종합 리포트의 핵심 인사이트 (단계별 평균 drop-off)

원칙:
- 각 단계 액션이 없으면 None (창작 금지)
- 직전 단계 0건이면 비율 계산 안 함 ("계산 불가")
"""
from __future__ import annotations

import statistics
from typing import Optional

from meta_ads_client import extract_action

# 단계 정의 — Meta Pixel 표준 이벤트 + Meta 노출/클릭
FUNNEL_STAGES = [
    ("impression", "노출", None),  # row.impressions에서 직접
    ("link_click", "클릭", "link_click"),
    ("view_content", "콘텐츠 조회", "view_content"),
    ("add_to_cart", "장바구니", "add_to_cart"),
    ("initiate_checkout", "결제 시작", "initiate_checkout"),
    ("purchase", "구매", "purchase"),
]


def _safe_num(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def extract_funnel(row: dict) -> dict:
    """단일 row(account 또는 campaign)에서 퍼널 단계별 카운트 추출."""
    counts = {}
    counts["impression"] = _safe_num(row.get("impressions"))
    for key, label, action_type in FUNNEL_STAGES:
        if action_type is None:
            continue
        v = extract_action(row, action_type)
        counts[key] = v
    return counts


def compute_drop_offs(counts: dict) -> list[dict]:
    """단계 → 단계 drop-off 비율 계산.

    Returns:
        list[{"from": str, "to": str, "from_count": int|None, "to_count": int|None,
              "conversion_rate_pct": float|None, "drop_off_pct": float|None,
              "conversion_label": str}]
    """
    out = []
    keys = [s[0] for s in FUNNEL_STAGES]
    labels = {s[0]: s[1] for s in FUNNEL_STAGES}

    for i in range(len(keys) - 1):
        f_key = keys[i]
        t_key = keys[i + 1]
        f_cnt = counts.get(f_key)
        t_cnt = counts.get(t_key)
        rate = None
        drop = None
        cmt = ""
        if f_cnt is None or t_cnt is None:
            cmt = "데이터 없음"
        elif f_cnt == 0:
            cmt = "직전 단계 0 — 계산 불가"
        else:
            rate = (t_cnt / f_cnt) * 100
            drop = 100 - rate
            cmt = f"{rate:.2f}% 통과 / {drop:.2f}% 이탈"
        out.append({
            "from": labels[f_key],
            "to": labels[t_key],
            "from_count": int(f_cnt) if f_cnt is not None else None,
            "to_count": int(t_cnt) if t_cnt is not None else None,
            "conversion_rate_pct": rate,
            "drop_off_pct": drop,
            "conversion_label": cmt,
        })
    return out


def overall_funnel(rows: list[dict]) -> dict:
    """여러 row 합산 → 전체 퍼널.

    Args:
        rows: API 원본 row 리스트 (account-level 또는 campaign-level 모두 가능)
    """
    totals = {key: 0 for key, *_ in FUNNEL_STAGES}
    nulls = {key: 0 for key, *_ in FUNNEL_STAGES}
    for r in rows:
        c = extract_funnel(r)
        for k in totals:
            v = c.get(k)
            if v is None:
                nulls[k] += 1
            else:
                totals[k] += v

    drop_offs = compute_drop_offs(totals)

    return {
        "stage_totals": totals,
        "stage_nulls": nulls,  # 데이터 누락 row 카운트
        "drop_offs": drop_offs,
        "n_rows": len(rows),
    }


def funnel_health_diagnosis(funnel: dict) -> list[str]:
    """퍼널 결과를 보고 자동 진단 문장 생성."""
    msgs = []
    drops = funnel["drop_offs"]
    totals = funnel["stage_totals"]

    # 노출 → 클릭 (CTR)
    imp_to_click = next((d for d in drops if d["from"] == "노출"), None)
    if imp_to_click and imp_to_click["conversion_rate_pct"] is not None:
        ctr = imp_to_click["conversion_rate_pct"]
        if ctr < 0.8:
            msgs.append(f"🔴 노출→클릭 CTR {ctr:.2f}% (벤치 1.2% 대비 -33%+) — 크리에이티브·후킹 약함")
        elif ctr > 2.0:
            msgs.append(f"✅ 노출→클릭 CTR {ctr:.2f}% (벤치 우수) — 크리에이티브 강함, 예산 확장 검토")

    # 클릭 → 콘텐츠 조회 (랜딩 도달)
    click_to_view = next((d for d in drops if d["from"] == "클릭"), None)
    if click_to_view and click_to_view["conversion_rate_pct"] is not None:
        r = click_to_view["conversion_rate_pct"]
        if r < 60:
            msgs.append(f"⚠️ 클릭→콘텐츠 조회 {r:.1f}% — 랜딩 페이지 로딩·이탈 검토 (40%+가 이탈)")

    # 콘텐츠 조회 → 장바구니
    view_to_cart = next((d for d in drops if d["from"] == "콘텐츠 조회"), None)
    if view_to_cart and view_to_cart["conversion_rate_pct"] is not None:
        r = view_to_cart["conversion_rate_pct"]
        if r < 3:
            msgs.append(f"🔴 콘텐츠→장바구니 {r:.2f}% — 상세페이지 설득력·가격 저항 큼")
        elif r > 8:
            msgs.append(f"✅ 콘텐츠→장바구니 {r:.2f}% — 상세페이지 설득력 강함")

    # 장바구니 → 결제 시작
    cart_to_checkout = next((d for d in drops if d["from"] == "장바구니"), None)
    if cart_to_checkout and cart_to_checkout["conversion_rate_pct"] is not None:
        r = cart_to_checkout["conversion_rate_pct"]
        if r < 50:
            msgs.append(f"🔴 장바구니→결제 시작 {r:.1f}% (50% 미만) — 카트 페이지 UX·할인쿠폰 트리거 검토")

    # 결제 시작 → 구매
    checkout_to_purchase = next((d for d in drops if d["from"] == "결제 시작"), None)
    if checkout_to_purchase and checkout_to_purchase["conversion_rate_pct"] is not None:
        r = checkout_to_purchase["conversion_rate_pct"]
        if r < 50:
            msgs.append(f"🔴 결제→구매 {r:.1f}% (50% 미만) — 비회원 구매 가능 여부·간편결제(카카오페이·토스페이·네이버페이)·냉동 배송일 표시 확인 (배송비·소셜로그인은 완료)")
        elif r > 75:
            msgs.append(f"✅ 결제→구매 {r:.1f}% — 결제 페이지 마찰 적음")

    # 전체 노출→구매 종합
    imp = totals.get("impression") or 0
    pur = totals.get("purchase") or 0
    if imp > 0 and pur > 0:
        overall = (pur / imp) * 100
        msgs.append(f"📊 노출→구매 종합 전환율 {overall:.4f}% (1만 노출당 {overall*100:.1f}건)")

    return msgs


def funnel_to_markdown(funnel: dict) -> str:
    """퍼널 결과를 마크다운 표로 렌더."""
    lines = []
    lines.append("| 단계 | 카운트 | 직전 대비 통과율 | 이탈률 |")
    lines.append("|---|---|---|---|")

    totals = funnel["stage_totals"]
    drops = funnel["drop_offs"]

    # 첫 단계
    first_key, first_label, _ = FUNNEL_STAGES[0]
    cnt = totals.get(first_key)
    cnt_s = f"{int(cnt):,}" if cnt is not None else "—"
    lines.append(f"| {first_label} | {cnt_s} | — | — |")

    for d in drops:
        cnt_s = f"{d['to_count']:,}" if d['to_count'] is not None else "—"
        rate_s = f"{d['conversion_rate_pct']:.2f}%" if d['conversion_rate_pct'] is not None else "—"
        drop_s = f"{d['drop_off_pct']:.2f}%" if d['drop_off_pct'] is not None else "—"
        lines.append(f"| {d['to']} | {cnt_s} | {rate_s} | {drop_s} |")

    return "\n".join(lines)


if __name__ == "__main__":
    # 테스트 — 어제 1일치
    from meta_ads_client import fetch_account_insights
    raw = fetch_account_insights()
    if raw["ok"] and raw["data"]:
        f = overall_funnel(raw["data"])
        print(funnel_to_markdown(f))
        print()
        for m in funnel_health_diagnosis(f):
            print(m)
    else:
        print(f"FAIL: {raw.get('error')}")
