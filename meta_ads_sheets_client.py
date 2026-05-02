"""Google Sheets 푸시 클라이언트 (Meta 광고 전용)

환경변수:
    GOOGLE_SHEETS_ID                대상 스프레드시트 ID
    GOOGLE_SERVICE_ACCOUNT_JSON     서비스 계정 키 (파일경로 / JSON / Base64)
    GOOGLE_SA_KEY_PATH              위 미설정 시 fallback (재구매용 키 자동 재사용)
"""

import base64
import json
import os
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent / ".env"

DAILY_WS = "Meta_Ads_Daily"
DAILY_CAMPAIGN_WS = "Meta_Ads_Daily_Campaign"
DAILY_ADSET_WS = "Meta_Ads_Daily_AdSet"
WINNERS_WS = "Meta_Ads_Winners"

HISTORY_HEADERS = [
    "date", "level", "campaign_id", "campaign_name",
    "spend", "impressions", "clicks",
    "ctr_pct", "cpc_krw", "frequency",
    "purchases", "purchase_value_krw", "cpa_krw", "roas",
    "raw_json_path", "appended_at",
]

ADSET_HEADERS = [
    "date", "adset_id", "adset_name", "campaign_id", "campaign_name",
    "spend", "impressions", "clicks",
    "ctr_pct", "cpc_krw", "frequency",
    "purchases", "purchase_value_krw", "cpa_krw", "roas",
    "raw_json_path", "appended_at",
]

WINNER_HEADERS = [
    "week_start", "campaign_id", "campaign_name",
    "roas_30d", "ctr_pct_30d", "cpa_krw_30d",
    "impressions_30d", "spend_30d",
    "target_inferred", "hook_inferred", "claude_hypothesis",
    "appended_at",
]


def _load_credentials():
    load_dotenv(ENV_PATH, override=True)
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

    if not raw:
        sa_path = os.getenv("GOOGLE_SA_KEY_PATH", "").strip()
        if sa_path:
            p = Path(sa_path)
            if not p.is_absolute():
                p = ENV_PATH.parent / sa_path
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
        return None

    if raw.endswith(".json") and Path(raw).exists():
        with open(raw, "r", encoding="utf-8") as f:
            return json.load(f)

    if raw.startswith("{"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

    try:
        decoded = base64.b64decode(raw).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return None


def _get_client():
    load_dotenv(ENV_PATH, override=True)
    sheets_id = os.getenv("GOOGLE_SHEETS_ID", "").strip()
    if not sheets_id:
        return None, None, "GOOGLE_SHEETS_ID 미설정"

    creds_dict = _load_credentials()
    if not creds_dict:
        return None, None, "GOOGLE_SERVICE_ACCOUNT_JSON 로드 실패"

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as e:
        return None, None, f"gspread/google-auth 미설치: {e}"

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    try:
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(sheets_id)
        return gc, sh, None
    except Exception as e:
        return None, None, f"시트 연결 실패: {e}"


def _ensure_worksheet(sh, title, headers):
    try:
        ws = sh.worksheet(title)
        first_row = ws.row_values(1)
        if first_row != headers:
            ws.update("A1", [headers])
        return ws
    except Exception:
        ws = sh.add_worksheet(title=title, rows=2000, cols=max(20, len(headers)))
        ws.update("A1", [headers])
        return ws


def _row_to_list(row, headers):
    return [row.get(h, "") for h in headers]


def _delete_rows_by_keys(ws, headers, key_indices, keys_to_remove):
    if not keys_to_remove:
        return 0
    all_values = ws.get_all_values()
    if len(all_values) <= 1:
        return 0
    rows_to_delete = []
    for i, row in enumerate(all_values[1:], start=2):
        if len(row) < max(key_indices) + 1:
            continue
        key = tuple(row[idx] for idx in key_indices)
        if key in keys_to_remove:
            rows_to_delete.append(i)
    for r in sorted(rows_to_delete, reverse=True):
        ws.delete_rows(r)
    return len(rows_to_delete)


def push_daily_rows(rows, level):
    if not rows:
        return {"ok": True, "appended": 0, "replaced": 0, "error": None}

    gc, sh, err = _get_client()
    if err:
        return {"ok": False, "appended": 0, "replaced": 0, "error": err}

    title = DAILY_WS if level == "account" else DAILY_CAMPAIGN_WS
    ws = _ensure_worksheet(sh, title, HISTORY_HEADERS)

    key_indices = [HISTORY_HEADERS.index("date"), HISTORY_HEADERS.index("campaign_id")]
    keys = {(r["date"], r["campaign_id"]) for r in rows}
    replaced = _delete_rows_by_keys(ws, HISTORY_HEADERS, key_indices, keys)

    payload = [_row_to_list(r, HISTORY_HEADERS) for r in rows]
    ws.append_rows(payload, value_input_option="USER_ENTERED")

    return {"ok": True, "appended": len(payload), "replaced": replaced, "error": None}


def push_adset_rows(rows):
    """Meta_Ads_Daily_AdSet 시트에 광고세트 단위 행 upsert.

    중복 제거 키: (date, adset_id). 같은 날짜+광고세트면 기존 행 삭제 후 신규 추가.
    """
    if not rows:
        return {"ok": True, "appended": 0, "replaced": 0, "error": None}

    gc, sh, err = _get_client()
    if err:
        return {"ok": False, "appended": 0, "replaced": 0, "error": err}

    ws = _ensure_worksheet(sh, DAILY_ADSET_WS, ADSET_HEADERS)
    key_indices = [ADSET_HEADERS.index("date"), ADSET_HEADERS.index("adset_id")]
    keys = {(r["date"], r["adset_id"]) for r in rows}
    replaced = _delete_rows_by_keys(ws, ADSET_HEADERS, key_indices, keys)

    payload = [_row_to_list(r, ADSET_HEADERS) for r in rows]
    ws.append_rows(payload, value_input_option="USER_ENTERED")

    return {"ok": True, "appended": len(payload), "replaced": replaced, "error": None}


def push_winners(rows):
    if not rows:
        return {"ok": True, "appended": 0, "replaced": 0, "error": None}

    gc, sh, err = _get_client()
    if err:
        return {"ok": False, "appended": 0, "replaced": 0, "error": err}

    ws = _ensure_worksheet(sh, WINNERS_WS, WINNER_HEADERS)
    key_indices = [WINNER_HEADERS.index("week_start"), WINNER_HEADERS.index("campaign_id")]
    keys = {(r["week_start"], r["campaign_id"]) for r in rows}
    replaced = _delete_rows_by_keys(ws, WINNER_HEADERS, key_indices, keys)

    payload = [_row_to_list(r, WINNER_HEADERS) for r in rows]
    ws.append_rows(payload, value_input_option="USER_ENTERED")

    return {"ok": True, "appended": len(payload), "replaced": replaced, "error": None}


def healthcheck():
    gc, sh, err = _get_client()
    if err:
        return f"시트 연결 실패: {err}"
    try:
        title = sh.title
        sheets = [w.title for w in sh.worksheets()]
        return f"OK '{title}' / 워크시트: {sheets}"
    except Exception as e:
        return f"시트 메타데이터 조회 실패: {e}"


if __name__ == "__main__":
    print(healthcheck())
