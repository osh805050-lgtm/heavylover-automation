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


def fetch_account_daily_range(since, until, max_retries=3):
    """계정 합계 일별 시계열 (date_start별 1행씩).

    Args:
        since: "YYYY-MM-DD"
        until: "YYYY-MM-DD" (inclusive)

    Returns:
        dict: {"ok": bool, "data": list[dict], "since": str, "until": str, "error": str|None}
              data 각 행에 date_start, date_stop이 같은 일자로 들어옴
    """
    env = _get_env()
    if not env["token"] or not env["account_id"]:
        return {"ok": False, "data": [], "since": since, "until": until,
                "error": "META_ACCESS_TOKEN 또는 META_AD_ACCOUNT_ID 환경변수 없음"}

    account_id = env["account_id"].replace("act_", "")
    url = f"{GRAPH_BASE}/{env['api_version']}/act_{account_id}/insights"

    params = {
        "access_token": env["token"],
        "fields": ",".join(INSIGHT_FIELDS),
        "time_range": f'{{"since":"{since}","until":"{until}"}}',
        "level": "account",
        "time_increment": 1,  # 일별 분할
        "action_attribution_windows": '["7d_click","1d_view"]',
        "limit": 500,
    }

    all_rows = []
    next_url = url
    next_params = params
    last_err = None

    for _ in range(50):
        got = False
        for attempt in range(max_retries):
            try:
                r = requests.get(next_url, params=next_params, timeout=120)
                if r.status_code == 200:
                    body = r.json()
                    all_rows.extend(body.get("data", []))
                    next_cursor = (body.get("paging") or {}).get("next")
                    if next_cursor:
                        next_url = next_cursor
                        next_params = None
                    else:
                        next_url = None
                    got = True
                    break
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    return {"ok": False, "data": all_rows, "since": since, "until": until,
                            "error": f"HTTP {r.status_code}: {r.text[:500]}"}
                last_err = f"HTTP {r.status_code}: {r.text[:300]}"
            except requests.RequestException as e:
                last_err = f"네트워크 오류: {e}"
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
        if not got:
            return {"ok": False, "data": all_rows, "since": since, "until": until,
                    "error": f"재시도 실패: {last_err}"}
        if not next_url:
            break

    return {"ok": True, "data": all_rows, "since": since, "until": until, "error": None}


def fetch_campaign_daily_range(since, until, max_retries=3):
    """캠페인별 일별 시계열 (campaign_id × date_start)."""
    env = _get_env()
    if not env["token"] or not env["account_id"]:
        return {"ok": False, "data": [], "since": since, "until": until,
                "error": "META_ACCESS_TOKEN 또는 META_AD_ACCOUNT_ID 환경변수 없음"}

    account_id = env["account_id"].replace("act_", "")
    url = f"{GRAPH_BASE}/{env['api_version']}/act_{account_id}/insights"

    fields = INSIGHT_FIELDS + ["campaign_id", "campaign_name"]
    params = {
        "access_token": env["token"],
        "fields": ",".join(fields),
        "time_range": f'{{"since":"{since}","until":"{until}"}}',
        "level": "campaign",
        "time_increment": 1,
        "action_attribution_windows": '["7d_click","1d_view"]',
        "limit": 500,
    }

    all_rows = []
    next_url = url
    next_params = params
    last_err = None

    MAX_PAGES_CAMPAIGN = 400
    for page_n, _ in enumerate(range(MAX_PAGES_CAMPAIGN)):  # 1년치 캠페인×일별이라 페이지 많을 수 있음
        got = False
        for attempt in range(max_retries):
            try:
                r = requests.get(next_url, params=next_params, timeout=180)
                if r.status_code == 200:
                    body = r.json()
                    all_rows.extend(body.get("data", []))
                    next_cursor = (body.get("paging") or {}).get("next")
                    if next_cursor:
                        next_url = next_cursor
                        next_params = None
                    else:
                        next_url = None
                    got = True
                    break
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    return {"ok": False, "data": all_rows, "since": since, "until": until,
                            "error": f"HTTP {r.status_code}: {r.text[:500]}"}
                last_err = f"HTTP {r.status_code}: {r.text[:300]}"
            except requests.RequestException as e:
                last_err = f"네트워크 오류: {e}"
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
        if not got:
            return {"ok": False, "data": all_rows, "since": since, "until": until,
                    "error": f"재시도 실패: {last_err}"}
        if not next_url:
            break
    else:
        print(f"⚠️ campaign 페이지 한도({MAX_PAGES_CAMPAIGN}) 도달 — 데이터 truncation 가능")
        try:
            from telegram_client import send_message
            send_message(f"⚠️ Meta campaign fetch 페이지 한도 {MAX_PAGES_CAMPAIGN} 도달 — truncation 가능", channel="ops")
        except Exception:
            pass

    return {"ok": True, "data": all_rows, "since": since, "until": until, "error": None}


def fetch_adset_daily_range(since, until, max_retries=3):
    """광고세트별 일별 시계열 (adset_id × date_start).

    fetch_campaign_daily_range() 패턴을 그대로 따르되 level=adset.
    응답에 adset_id, adset_name, campaign_id, campaign_name 모두 포함.
    실측 검증 완료 (2026-05-03): /act_445075134545178/insights?level=adset
    """
    env = _get_env()
    if not env["token"] or not env["account_id"]:
        return {"ok": False, "data": [], "since": since, "until": until,
                "error": "META_ACCESS_TOKEN 또는 META_AD_ACCOUNT_ID 환경변수 없음"}

    account_id = env["account_id"].replace("act_", "")
    url = f"{GRAPH_BASE}/{env['api_version']}/act_{account_id}/insights"

    fields = INSIGHT_FIELDS + ["adset_id", "adset_name", "campaign_id", "campaign_name"]
    params = {
        "access_token": env["token"],
        "fields": ",".join(fields),
        "time_range": f'{{"since":"{since}","until":"{until}"}}',
        "level": "adset",
        "time_increment": 1,
        "action_attribution_windows": '["7d_click","1d_view"]',
        "limit": 500,
    }

    all_rows = []
    next_url = url
    next_params = params
    last_err = None

    MAX_PAGES_ADSET = 800
    for _ in range(MAX_PAGES_ADSET):  # adset×일별은 캠페인보다 페이지 더 많음
        got = False
        for attempt in range(max_retries):
            try:
                r = requests.get(next_url, params=next_params, timeout=180)
                if r.status_code == 200:
                    body = r.json()
                    all_rows.extend(body.get("data", []))
                    next_cursor = (body.get("paging") or {}).get("next")
                    if next_cursor:
                        next_url = next_cursor
                        next_params = None
                    else:
                        next_url = None
                    got = True
                    break
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    return {"ok": False, "data": all_rows, "since": since, "until": until,
                            "error": f"HTTP {r.status_code}: {r.text[:500]}"}
                last_err = f"HTTP {r.status_code}: {r.text[:300]}"
            except requests.RequestException as e:
                last_err = f"네트워크 오류: {e}"
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
        if not got:
            return {"ok": False, "data": all_rows, "since": since, "until": until,
                    "error": f"재시도 실패: {last_err}"}
        if not next_url:
            break
    else:
        print(f"⚠️ adset 페이지 한도({MAX_PAGES_ADSET}) 도달 — 데이터 truncation 가능")
        try:
            from telegram_client import send_message
            send_message(f"⚠️ Meta adset fetch 페이지 한도 {MAX_PAGES_ADSET} 도달 — truncation 가능", channel="ops")
        except Exception:
            pass

    return {"ok": True, "data": all_rows, "since": since, "until": until, "error": None}


def fetch_ad_daily_range(since, until, max_retries=3):
    """광고(ad) 단위 일별 시계열 (ad_id × date_start).

    fetch_adset_daily_range() 패턴을 그대로 따르되 level=ad.
    응답에 ad_id, ad_name, adset_id, adset_name, campaign_id, campaign_name 포함.
    """
    env = _get_env()
    if not env["token"] or not env["account_id"]:
        return {"ok": False, "data": [], "since": since, "until": until,
                "error": "META_ACCESS_TOKEN 또는 META_AD_ACCOUNT_ID 환경변수 없음"}

    account_id = env["account_id"].replace("act_", "")
    url = f"{GRAPH_BASE}/{env['api_version']}/act_{account_id}/insights"

    fields = INSIGHT_FIELDS + ["ad_id", "ad_name", "adset_id", "adset_name", "campaign_id", "campaign_name"]
    params = {
        "access_token": env["token"],
        "fields": ",".join(fields),
        "time_range": f'{{"since":"{since}","until":"{until}"}}',
        "level": "ad",
        "time_increment": 1,
        "action_attribution_windows": '["7d_click","1d_view"]',
        "limit": 500,
    }

    all_rows = []
    next_url = url
    next_params = params
    last_err = None

    MAX_PAGES_AD = 1600  # adset(800) × 광고 2~3개/adset 예상 마진
    for _ in range(MAX_PAGES_AD):
        got = False
        for attempt in range(max_retries):
            try:
                r = requests.get(next_url, params=next_params, timeout=180)
                if r.status_code == 200:
                    body = r.json()
                    all_rows.extend(body.get("data", []))
                    next_cursor = (body.get("paging") or {}).get("next")
                    if next_cursor:
                        next_url = next_cursor
                        next_params = None
                    else:
                        next_url = None
                    got = True
                    break
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    return {"ok": False, "data": all_rows, "since": since, "until": until,
                            "error": f"HTTP {r.status_code}: {r.text[:500]}"}
                last_err = f"HTTP {r.status_code}: {r.text[:300]}"
            except requests.RequestException as e:
                last_err = f"네트워크 오류: {e}"
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
        if not got:
            return {"ok": False, "data": all_rows, "since": since, "until": until,
                    "error": f"재시도 실패: {last_err}"}
        if not next_url:
            break
    else:
        print(f"⚠️ ad 페이지 한도({MAX_PAGES_AD}) 도달 — 데이터 truncation 가능")
        try:
            from telegram_client import send_message
            send_message(f"⚠️ Meta ad fetch 페이지 한도 {MAX_PAGES_AD} 도달 — truncation 가능", channel="ops")
        except Exception:
            pass

    return {"ok": True, "data": all_rows, "since": since, "until": until, "error": None}


def fetch_ad_creatives(ad_ids, max_retries=3):
    """광고별 creative thumbnail_url 조회 (캐시 우선, 7일 TTL).

    캐시 키: "{ad_id}:{creative_id}" — creative 교체 시 자동 무효화.
    캐시 파일: data/meta_ads/creatives_cache.json
    """
    import json as _json

    env = _get_env()
    if not env["token"]:
        return {}

    cache_path = Path(__file__).parent / "data" / "meta_ads" / "creatives_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        cache = _json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    except Exception:
        cache = {}

    now = datetime.now(timezone.utc).isoformat()
    updated = False
    result = {}

    for ad_id in ad_ids:
        # 캐시 확인 (7일 TTL)
        cached = cache.get(ad_id)
        if cached:
            try:
                fetched_at = datetime.fromisoformat(cached.get("fetched_at", "2000-01-01T00:00:00+00:00"))
                age_days = (datetime.now(timezone.utc) - fetched_at).days
                if age_days < 7:
                    result[ad_id] = cached
                    continue
            except Exception:
                pass

        # 캐시 미스 or 만료 → API 호출
        url = f"{GRAPH_BASE}/{env['api_version']}/{ad_id}"
        params = {
            "access_token": env["token"],
            "fields": "creative{thumbnail_url,id,name}",
        }
        for attempt in range(max_retries):
            try:
                r = requests.get(url, params=params, timeout=30)
                if r.status_code == 200:
                    body = r.json()
                    creative = body.get("creative") or {}
                    entry = {
                        "ad_id": ad_id,
                        "creative_id": creative.get("id", ""),
                        "creative_name": creative.get("name", ""),
                        "thumbnail_url": creative.get("thumbnail_url", ""),
                        "fetched_at": now,
                    }
                    # 캐시 키에 creative_id 포함 — 동일 ad_id에 creative 교체 시 감지
                    cache_key = f"{ad_id}:{entry['creative_id']}"
                    cache[cache_key] = entry
                    cache[ad_id] = entry  # ad_id 단순 키도 유지 (빠른 조회용)
                    result[ad_id] = entry
                    updated = True
                    break
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    break
                last_err = f"HTTP {r.status_code}"
            except requests.RequestException:
                pass
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

    if updated:
        try:
            cache_path.write_text(_json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"⚠️ creatives_cache.json 저장 실패: {e}")

    return result


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
    """purchase_roas 배열에서 대표 ROAS를 (value, source_type) 튜플로 반환.

    우선순위: offsite_conversion.fb_pixel_purchase > purchase > omni_purchase
    source_type은 실제 action_type 문자열 그대로 저장 (단축 표기 금지).
    없으면 (None, "").
    """
    for preferred in [
        "offsite_conversion.fb_pixel_purchase",
        "purchase",
        "omni_purchase",
    ]:
        for a in row.get("purchase_roas", []) or []:
            if a.get("action_type") == preferred:
                try:
                    return float(a.get("value", 0)), preferred
                except (TypeError, ValueError):
                    continue
    # fallback: 첫 번째 항목 (source 불명)
    arr = row.get("purchase_roas", []) or []
    if arr:
        try:
            return float(arr[0].get("value", 0)), ""
        except (TypeError, ValueError):
            return None, ""
    return None, ""


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
