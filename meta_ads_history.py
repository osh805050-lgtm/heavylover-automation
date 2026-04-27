"""
Meta 광고 시계열 누적 저장소 (CSV + Google Sheets 동시).

원칙 (CLAUDE.md §0):
- 같은 (date, campaign_id) 키 재실행 시 덮어쓰기 (중복 누적 방지)
- 누락 필드는 빈 문자열. 숫자 창작 금지.
- 시트 환경변수 미설정 시 silent skip — 워크플로우 실패 안 시킴
"""

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data" / "meta_ads"
RAW_DIR = DATA_DIR / "raw"
DAILY_CSV = DATA_DIR / "daily.csv"
DAILY_CAMPAIGN_CSV = DATA_DIR / "daily_campaign.csv"
KST = timezone(timedelta(hours=9))

COLUMNS = [
    "date", "level", "campaign_id", "campaign_name",
    "spend", "impressions", "clicks",
    "ctr_pct", "cpc_krw", "frequency",
    "purchases", "purchase_value_krw", "cpa_krw", "roas",
    "raw_json_path", "appended_at",
]


def _ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)


def _save_raw(target_date, raw_data):
    _ensure_dirs()
    path = RAW_DIR / f"{target_date}.json"
    path.write_text(json.dumps(raw_data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _load_csv(path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path, rows):
    _ensure_dirs()
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})


def _row_from_metrics(target_date, level, campaign_id, campaign_name, m, raw_path):
    def _v(x):
        return "" if x is None else x
    return {
        "date": target_date,
        "level": level,
        "campaign_id": campaign_id or "account",
        "campaign_name": campaign_name or "",
        "spend": _v(m.get("spend")),
        "impressions": _v(m.get("impressions")),
        "clicks": _v(m.get("clicks")),
        "ctr_pct": _v(m.get("ctr_pct")),
        "cpc_krw": _v(m.get("cpc_krw")),
        "frequency": _v(m.get("frequency")),
        "purchases": _v(m.get("purchases")),
        "purchase_value_krw": _v(m.get("purchase_value_krw") or m.get("purchase_value")),
        "cpa_krw": _v(m.get("cpa_krw")),
        "roas": _v(m.get("roas")),
        "raw_json_path": raw_path,
        "appended_at": datetime.now(KST).isoformat(timespec="seconds"),
    }


def _upsert(path, new_rows, key_fn):
    existing = _load_csv(path)
    new_keys = {key_fn(r) for r in new_rows}
    kept = [r for r in existing if key_fn(r) not in new_keys]
    merged = kept + new_rows
    merged.sort(key=lambda r: (r.get("date", ""), r.get("campaign_id", "")), reverse=True)
    _write_csv(path, merged)
    return len(merged)


def append_daily(target_date, raw, account_metrics, campaign_summaries=None):
    raw_path = _save_raw(target_date, raw.get("data") if isinstance(raw, dict) else raw)
    account_row = _row_from_metrics(target_date, "account", "account", "", account_metrics, raw_path)
    daily_n = _upsert(DAILY_CSV, [account_row], key_fn=lambda r: (r["date"], r["campaign_id"]))

    camp_rows = []
    camp_n = 0
    if campaign_summaries:
        for c in campaign_summaries:
            camp_rows.append(_row_from_metrics(
                target_date, "campaign",
                c.get("campaign_id"), c.get("campaign_name"),
                {
                    "spend": c.get("spend"), "impressions": c.get("impressions"),
                    "clicks": c.get("clicks"), "ctr_pct": c.get("ctr_pct"),
                    "purchases": c.get("purchases"), "purchase_value": c.get("purchase_value"),
                    "cpa_krw": c.get("cpa_krw"), "roas": c.get("roas"),
                },
                raw_path,
            ))
        camp_n = _upsert(DAILY_CAMPAIGN_CSV, camp_rows, key_fn=lambda r: (r["date"], r["campaign_id"]))

    sheet_msgs = _push_to_sheets(account_row, camp_rows)
    return {
        "daily_rows": daily_n,
        "campaign_rows": camp_n,
        "raw_path": raw_path,
        "sheet": sheet_msgs,
    }


def _push_to_sheets(account_row, campaign_rows):
    msgs = {"daily": "", "campaign": ""}
    try:
        import meta_ads_sheets_client as sheets
    except ImportError as e:
        msgs["daily"] = f"sheets 모듈 import 실패: {e}"
        return msgs

    daily_res = sheets.push_daily_rows([account_row], level="account")
    if daily_res["ok"]:
        msgs["daily"] = f"daily 시트 +{daily_res['appended']} (replaced {daily_res['replaced']})"
    else:
        msgs["daily"] = f"daily 시트 skip — {daily_res['error']}"

    if campaign_rows:
        camp_res = sheets.push_daily_rows(campaign_rows, level="campaign")
        if camp_res["ok"]:
            msgs["campaign"] = f"campaign 시트 +{camp_res['appended']} (replaced {camp_res['replaced']})"
        else:
            msgs["campaign"] = f"campaign 시트 skip — {camp_res['error']}"
    return msgs


def load_recent_account(days=30):
    rows = _load_csv(DAILY_CSV)
    rows = [r for r in rows if r.get("level") == "account"]
    rows.sort(key=lambda r: r.get("date", ""))
    if not rows:
        return []
    today = datetime.now(KST).date()
    cutoff = (today - timedelta(days=days)).isoformat()
    return [r for r in rows if r.get("date", "") >= cutoff]


if __name__ == "__main__":
    rows = load_recent_account(30)
    print(f"daily.csv 최근 30일 행 수: {len(rows)}")
