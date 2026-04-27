"""
Meta (Facebook) Marketing API 클라이언트

- 광고 계정(act_...) 전체의 전일 Insights를 조회
- 재시도(exponential backoff) + 응답 검증 + ground truth 원본 보관
- 필드가 누락되면 "데이터 없음"으로 명시 (추측 금지)

환경변수:
    META_ACCESS_TOKEN     시스템 유저 토큰 또는 장기 사용자 토큰
    META_AD_ACCOUNT_ID    광고 계정 ID (예: 123456789, act_ 접두어 없이)
    META_API_VERSION      (선택) 기본 v21.0
"""

import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent / ".env"
GRAPH_BASE = "https://graph.facebook.com"

# 요청할 필드 (account-level insights)
INSIGHT_FIELDS = [
    "spend",
    "impressions",
    "clicks",
    "ctr",
    "cpc",
    "cpm",
    "frequency",
    "reach",
    "actions",
    "action_values",
    "cost_per_action_type",
    "purchase_roas",
    "date_start",
    "date_stop",
]

# 필수 필드 (누락 시 검증 실패로 처리)
REQUIRED_NUMERIC_FIELDS = ["spend", "impressions", "clicks"]

KST = timezone(timedelta(hours=9))


def _get_env():
    load_dotenv(ENV_PATH, override=True)
    return {
        "token": os.getenv("META_ACCESS_TOKEN"),
        "account_id": os.getenv("META_AD_ACCOUNT_ID"),
        "api_version": os.getenv("META_API_VERSION", "v21.0"),
    }


def _yesterday_kst():
    """전일 KST 날짜 문자열 (YYYY-MM-DD)"""
    now_kst = datetime.now(KST)
    y = now_kst.date() - timedelta(days=1)
    return y.isoformat()


def last_n_days_kst(n=7, offset_days=0):
    """KST 기준 지난 n일 범위 (since, until) 반환.

    Args:
        n: 일수 (기본 7)
        offset_days: 0=최신 N일 (D-(n) ~ D-1),
                     n=그 이전 N일 (D-(2n) ~ D-(n+1)) — 주 비교용

    Returns:
        (since_str, until_str): "YYYY-MM-DD" 튜플
    """
    today = datetime.now(KST).date()
    until = today - timedelta(days=1 + offset_days)
    since = until - timedelta(days=n - 1)
    return since.isoformat(), until.isoformat()


def fetch_account_insights(target_date=None, max_retries=3):
    """광고 계정 전체 일간 Insights 조회

    Args:
        target_date: YYYY-MM-DD 문자열. None이면 전일(KST).
        max_retries: 최대 재시도 횟수 (exponential backoff)

    Returns:
        dict: {
            "ok": bool,
            "data": list[dict],       # API 원본 응답 (ground truth)
            "target_date": str,
            "error": str | None,
        }
    """
    env = _get_env()
    if not env["token"] or not env["account_id"]:
        return {
            "ok": False,
            "data": [],
            "target_date": target_date or _yesterday_kst(),
            "error": "META_ACCESS_TOKEN 또는 META_AD_ACCOUNT_ID 환경변수 없음",
        }

    target = target_date or _yesterday_kst()
    account_id = env["account_id"].replace("act_", "")
    url = f"{GRAPH_BASE}/{env['api_version']}/act_{account_id}/insights"

    params = {
        "access_token": env["token"],
        "fields": ",".join(INSIGHT_FIELDS),
        "time_range": f'{{"since":"{target}","until":"{target}"}}',
        "level": "account",
        "action_attribution_windows": '["7d_click","1d_view"]',
    }

    last_err = None
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=60)
            if r.status_code == 200:
                body = r.json()
                return {
                    "ok": True,
                    "data": body.get("data", []),
                    "target_date": target,
                    "error": None,
                }
            # 4xx는 일반적으로 재시도 의미 없음 (토큰/권한 문제)
            if 400 <= r.status_code < 500 and r.status_code != 429:
                return {
                    "ok": False,
                    "data": [],
                    "target_date": target,
                    "error": f"HTTP {r.status_code}: {r.text[:500]}",
                }
            last_err = f"HTTP {r.status_code}: {r.text[:300]}"
        except requests.RequestException as e:
            last_err = f"네트워크 오류: {e}"

        # exponential backoff
        if attempt < max_retries - 1:
            time.sleep(2 ** attempt)

    return {
        "ok": False,
        "data": [],
        "target_date": target,
        "error": f"재시도 {max_retries}회 모두 실패. 마지막 오류: {last_err}",
    }


def fetch_campaign_insights(since, until, max_retries=3):
    """캠페인별 Insights 조회 (날짜 범위 합산)

    Args:
        since: "YYYY-MM-DD"
        until: "YYYY-MM-DD" (inclusive)
        max_retries: 재시도 횟수

    Returns:
        dict: {
            "ok": bool,
            "data": list[dict],         # 캠페인별 row (campaign_id, campaign_name 포함)
            "since": str, "until": str,
            "error": str | None,
        }
    """
    env = _get_env()
    if not env["token"] or not env["account_id"]:
        return {
            "ok": False, "data": [],
            "since": since, "until": until,
            "error": "META_ACCESS_TOKEN 또는 META_AD_ACCOUNT_ID 환경변수 없음",
        }

    account_id = env["account_id"].replace("act_", "")
    url = f"{GRAPH_BASE}/{env['api_version']}/act_{account_id}/insights"

    fields = INSIGHT_FIELDS + ["campaign_id", "campaign_name"]
    params = {
        "access_token": env["token"],
        "fields": ",".join(fields),
        "time_range": f'{{"since":"{since}","until":"{until}"}}',
        "level": "campaign",
        "action_attribution_windows": '["7d_click","1d_view"]',
        "limit": 200,
    }

    all_rows = []
    last_err = None
    next_url = url
    next_params = params

    # 페이지네이션 + 재시도
    for _ in range(50):  # 최대 50 페이지 (안전장치)
        got = False
        for attempt in range(max_retries):
            try:
                r = requests.get(next_url, params=next_params, timeout=60)
                if r.status_code == 200:
                    body = r.json()
                    all_rows.extend(body.get("data", []))
                    paging = body.get("paging", {}) or {}
                    next_cursor = paging.get("next")
                    if next_cursor:
                        next_url = next_cursor
                        next_params = None  # next URL에 이미 쿼리 포함
                    else:
                        next_url = None
                    got = True
                    break
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    return {
                        "ok": False, "data": all_rows,
                        "since": since, "until": until,
                        "error": f"HTTP {r.status_code}: {r.text[:500]}",
                    }
                last_err = f"HTTP {r.status_code}: {r.text[:300]}"
            except requests.RequestException as e:
                last_err = f"네트워크 오류: {e}"
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

        if not got:
            return {
                "ok": False, "data": all_rows,
                "since": since, "until": until,
                "error": f"재시도 실패. 마지막 오류: {last_err}",
            }
        if not next_url:
            break

    return {
        "ok": True, "data": all_rows,
        "since": since, "until": until,
        "error": None,
    }


def validate_insights(raw):
    """API 응답 유효성 검증 (ground truth 훼손 없이)

    Args:
        raw: fetch_account_insights() 반환값

    Returns:
        dict: {
            "valid": bool,
            "issues": list[str],  # 사람이 읽을 수 있는 문제 목록
        }
    """
    issues = []

    if not raw.get("ok"):
        issues.append(f"API 호출 실패: {raw.get('error')}")
        return {"valid": False, "issues": issues}

    data = raw.get("data", [])
    if not data:
        issues.append("응답에 data 배열이 비어있음 (해당 일자에 노출 없음 가능)")
        return {"valid": False, "issues": issues}

    row = data[0]

    # 필수 숫자 필드 존재 + 음수 아님
    for f in REQUIRED_NUMERIC_FIELDS:
        if f not in row:
            issues.append(f"필수 필드 누락: {f}")
            continue
        try:
            v = float(row[f])
            if v < 0:
                issues.append(f"{f} 값이 음수: {v}")
        except (TypeError, ValueError):
            issues.append(f"{f} 값이 숫자가 아님: {row[f]!r}")

    # 수식 일관성 (CTR ≈ clicks/impressions * 100)
    try:
        imp = float(row.get("impressions", 0))
        clk = float(row.get("clicks", 0))
        ctr_reported = float(row.get("ctr", 0))
        if imp > 0:
            ctr_expected = clk / imp * 100
            if ctr_expected > 0 and abs(ctr_reported - ctr_expected) / ctr_expected > 0.05:
                issues.append(
                    f"CTR 일관성 편차 >5%: reported={ctr_reported:.3f}, "
                    f"computed={ctr_expected:.3f}"
                )
    except (TypeError, ValueError):
        pass  # 수식 검증은 best-effort

    return {"valid": len(issues) == 0, "issues": issues}


def extract_action(row, action_type):
    """actions 배열에서 특정 action_type의 value를 반환. 없으면 None."""
    for a in row.get("actions", []) or []:
        if a.get("action_type") == action_type:
            try:
                return float(a.get("value", 0))
            except (TypeError, ValueError):
                return None
    return None


def extract_action_value(row, action_type):
    """action_values 배열에서 특정 action_type의 value를 반환. 없으면 None."""
    for a in row.get("action_values", []) or []:
        if a.get("action_type") == action_type:
            try:
                return float(a.get("value", 0))
            except (TypeError, ValueError):
                return None
    return None


def extract_cost_per_action(row, action_type):
    """cost_per_action_type 배열에서 특정 action의 CPA를 반환. 없으면 None."""
    for a in row.get("cost_per_action_type", []) or []:
        if a.get("action_type") == action_type:
            try:
                return float(a.get("value", 0))
            except (TypeError, ValueError):
                return None
    return None


def extract_purchase_roas(row):
    """purchase_roas 배열에서 대표 ROAS를 반환. 없으면 None."""
    for a in row.get("purchase_roas", []) or []:
        if a.get("action_type") in ("omni_purchase", "purchase", "offsite_conversion.fb_pixel_purchase"):
            try:
                return float(a.get("value", 0))
            except (TypeError, ValueError):
                continue
    # fallback: 첫 번째
    arr = row.get("purchase_roas", []) or []
    if arr:
        try:
            return float(arr[0].get("value", 0))
        except (TypeError, ValueError):
            return None
    return None


if __name__ == "__main__":
    # 간단 테스트
    print("Meta Ads API 연결 테스트...")
    result = fetch_account_insights()
    print(f"ok={result['ok']}, date={result['target_date']}")
    if result["ok"]:
        v = validate_insights(result)
        print(f"valid={v['valid']}, issues={v['issues']}")
        if result["data"]:
            print("원본 응답(첫 행):")
            print(result["data"][0])
    else:
        print(f"error: {result['error']}")
