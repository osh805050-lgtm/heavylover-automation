"""위너 광고 기획 패턴 누적 (주 1회)."""

import csv
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data" / "meta_ads"
DAILY_CAMPAIGN_CSV = DATA_DIR / "daily_campaign.csv"
WINNERS_JSONL = DATA_DIR / "winner_patterns.jsonl"
KST = timezone(timedelta(hours=9))

MIN_IMPRESSIONS = 1000
MIN_CAMPAIGNS_FOR_RANKING = 5
TOP_RATIO = 0.25

TARGET_KEYWORDS = {
    "20대": "20s_male", "30대": "30s_male", "40대": "40s_male",
    "남": "male", "여": "female",
    "헬스": "fitness_active", "벌크업": "bulk", "다이어트": "diet",
    "직장인": "office_worker", "운동": "active",
}
HOOK_KEYWORDS = {
    "단백질": "protein", "kcal": "calorie", "고단백": "high_protein",
    "저당": "low_sugar", "수비드": "sous_vide", "냉동": "frozen",
    "훈제": "smoked", "닭다리": "chicken_thigh", "닭가슴": "chicken_breast",
    "도시락": "lunchbox", "시리얼": "cereal",
}


def _parse_float(v):
    if v in ("", None):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _load_campaign_rows(days=30):
    if not DAILY_CAMPAIGN_CSV.exists():
        return []
    today = datetime.now(KST).date()
    cutoff = (today - timedelta(days=days)).isoformat()
    rows = []
    with DAILY_CAMPAIGN_CSV.open("r", encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r.get("level") != "campaign":
                continue
            if r.get("date", "") < cutoff:
                continue
            rows.append(r)
    return rows


def _aggregate_by_campaign(rows):
    agg = {}
    for r in rows:
        cid = r.get("campaign_id") or "unknown"
        a = agg.setdefault(cid, {
            "campaign_id": cid,
            "campaign_name": r.get("campaign_name") or "",
            "spend": 0.0, "impressions": 0.0, "clicks": 0.0,
            "purchases": 0.0, "purchase_value": 0.0, "days": 0,
        })
        for k in ("spend", "impressions", "clicks", "purchases", "purchase_value_krw"):
            v = _parse_float(r.get(k))
            if v is not None:
                target = "purchase_value" if k == "purchase_value_krw" else k
                a[target] += v
        a["days"] += 1
        if not a["campaign_name"] and r.get("campaign_name"):
            a["campaign_name"] = r["campaign_name"]

    out = []
    for a in agg.values():
        spend = a["spend"]; imp = a["impressions"]; clk = a["clicks"]
        pur = a["purchases"]; pv = a["purchase_value"]
        a["ctr_pct"] = (clk / imp * 100) if imp > 0 else None
        a["cpa_krw"] = (spend / pur) if pur > 0 else None
        a["roas"] = (pv / spend) if spend > 0 else None
        out.append(a)
    return out


def _extract_keywords(name):
    if not name:
        return {"target": "", "hooks": []}
    targets = [v for k, v in TARGET_KEYWORDS.items() if k in name]
    hooks = [v for k, v in HOOK_KEYWORDS.items() if k in name]
    num_hooks = re.findall(r"\d+\s*(?:kcal|g|원)", name)
    hooks.extend(num_hooks)
    return {
        "target": "+".join(sorted(set(targets))) if targets else "",
        "hooks": sorted(set(hooks)),
    }


def _hypothesize_with_claude(winner):
    try:
        from meta_ads_claude_comment import _get_client
    except ImportError:
        return ""
    client, err = _get_client()
    if err:
        return ""
    try:
        prompt = f"""아래 헤비로버 Meta 광고 캠페인이 ROAS 상위 25%에 든 이유를 한 줄로 가설을 세워라.
40자 이내, 마크다운 없이, 명사구 위주.

캠페인명: {winner['campaign_name']}
타겟 추출: {winner['target_inferred']}
후킹 추출: {', '.join(winner['hooks_inferred']) if winner['hooks_inferred'] else '(없음)'}
ROAS: {winner['roas_30d']:.2f}
CTR: {winner['ctr_pct_30d']:.2f}%
CPA: {int(winner['cpa_krw_30d']):,}원
노출: {int(winner['impressions_30d']):,}
"""
        resp = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=120,
            messages=[{"role": "user", "content": prompt}],
        )
        return (resp.content[0].text if resp.content else "").strip()
    except Exception:
        return ""


def identify_winners(window_days=30):
    week_start = datetime.now(KST).date().isoformat()
    rows = _load_campaign_rows(days=window_days)
    if not rows:
        return {"ok": False, "winners": [], "week_start": week_start,
                "n_total": 0, "reason": "캠페인 데이터 없음"}

    aggregated = _aggregate_by_campaign(rows)
    eligible = [a for a in aggregated
                if a.get("impressions", 0) >= MIN_IMPRESSIONS
                and a.get("roas") is not None]

    if len(eligible) < MIN_CAMPAIGNS_FOR_RANKING:
        return {"ok": False, "winners": [], "week_start": week_start,
                "n_total": len(eligible),
                "reason": f"비교 가능한 캠페인 부족 ({len(eligible)}/{MIN_CAMPAIGNS_FOR_RANKING})"}

    eligible.sort(key=lambda a: a["roas"], reverse=True)
    top_n = max(1, int(len(eligible) * TOP_RATIO))
    top = eligible[:top_n]

    winners = []
    for a in top:
        kw = _extract_keywords(a["campaign_name"])
        winner = {
            "week_start": week_start,
            "campaign_id": a["campaign_id"],
            "campaign_name": a["campaign_name"],
            "roas_30d": a["roas"],
            "ctr_pct_30d": a["ctr_pct"] or 0,
            "cpa_krw_30d": a["cpa_krw"] or 0,
            "impressions_30d": a["impressions"],
            "spend_30d": a["spend"],
            "target_inferred": kw["target"],
            "hooks_inferred": kw["hooks"],
        }
        winner["claude_hypothesis"] = _hypothesize_with_claude(winner)
        winner["appended_at"] = datetime.now(KST).isoformat(timespec="seconds")
        winners.append(winner)

    return {"ok": True, "winners": winners, "week_start": week_start,
            "n_total": len(eligible), "reason": None}


def persist_winners(winners):
    if not winners:
        return {"appended": 0}
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    existing = []
    if WINNERS_JSONL.exists():
        for line in WINNERS_JSONL.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                existing.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    new_keys = {(w["week_start"], w["campaign_id"]) for w in winners}
    kept = [e for e in existing if (e.get("week_start"), e.get("campaign_id")) not in new_keys]
    merged = kept + winners

    with WINNERS_JSONL.open("w", encoding="utf-8") as f:
        for w in merged:
            f.write(json.dumps(w, ensure_ascii=False) + "\n")

    return {"appended": len(winners), "total": len(merged)}


def push_winners_to_sheet(winners):
    if not winners:
        return {"ok": True, "appended": 0, "error": None}
    try:
        import meta_ads_sheets_client as sheets
    except ImportError as e:
        return {"ok": False, "appended": 0, "error": f"sheets import 실패: {e}"}

    rows = []
    for w in winners:
        rows.append({
            "week_start": w["week_start"],
            "campaign_id": w["campaign_id"],
            "campaign_name": w["campaign_name"],
            "roas_30d": round(w["roas_30d"], 3),
            "ctr_pct_30d": round(w["ctr_pct_30d"], 3),
            "cpa_krw_30d": int(w["cpa_krw_30d"]) if w["cpa_krw_30d"] else "",
            "impressions_30d": int(w["impressions_30d"]),
            "spend_30d": int(w["spend_30d"]),
            "target_inferred": w["target_inferred"],
            "hook_inferred": ", ".join(w["hooks_inferred"]),
            "claude_hypothesis": w["claude_hypothesis"],
            "appended_at": w["appended_at"],
        })
    return sheets.push_winners(rows)


def run():
    print("위너 광고 패턴 식별 시작")
    result = identify_winners(window_days=30)

    if not result["ok"]:
        print(f"위너 식별 skip: {result['reason']}")
        return 0

    winners = result["winners"]
    print(f"위너 {len(winners)}개 식별 (전체 {result['n_total']}개 중)")

    persist = persist_winners(winners)
    print(f"jsonl 누적: +{persist['appended']} (총 {persist.get('total','?')})")

    sheet_res = push_winners_to_sheet(winners)
    if sheet_res["ok"]:
        print(f"시트 push: +{sheet_res['appended']}")
    else:
        print(f"시트 push skip: {sheet_res['error']}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run())
