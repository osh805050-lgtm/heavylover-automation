"""Google Calendar 자동등록 (Layer 3 확장)

적합도 ≥ 7 공고에 대해 D-7, D-3, 마감 당일 3개 이벤트를 자동 생성.
멱등성: 같은 공고(pblancId/pbancSn)에 대해 deterministic event_id 사용 → 중복 등록 방지.

전제:
  - GOOGLE_SA_KEY_JSON (서비스 계정 JSON) 또는 GOOGLE_SA_KEY_PATH (파일 경로)
  - GOOGLE_CALENDAR_ID (공유된 캘린더 ID)
  - 본사 캘린더에 서비스 계정 이메일을 "변경 권한"으로 공유

미설정 시: RuntimeError 발생, 호출 측에서 try/except로 스킵 가능.

사용:
    from lib import calendar_client
    result = calendar_client.sync_announcements(scored_items)
"""

import base64
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent.parent / ".env"
KST = timezone(timedelta(hours=9))
SCOPES = ["https://www.googleapis.com/auth/calendar"]
CALENDAR_THRESHOLD = 7.0  # 적합도 ≥ 7만 등록

log = logging.getLogger(__name__)


def _load_sa_info():
    """서비스 계정 키 JSON dict 로드 (스코프 무관 — 재사용 가능).

    우선순위:
      1) GOOGLE_SA_KEY_JSON 환경변수에 JSON 원본 또는 Base64
      2) GOOGLE_SA_KEY_PATH 환경변수에 파일 경로
      3) 프로젝트 루트의 gcp-key.json
    """
    load_dotenv(ENV_PATH, override=True)

    raw_json = os.getenv("GOOGLE_SA_KEY_JSON")
    if raw_json:
        # Base64 디코딩 시도 (GitHub Secrets에서 줄바꿈 회피용)
        if not raw_json.lstrip().startswith("{"):
            try:
                raw_json = base64.b64decode(raw_json).decode("utf-8")
            except Exception:
                pass
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"GOOGLE_SA_KEY_JSON 파싱 실패: {e}")

    key_path = os.getenv("GOOGLE_SA_KEY_PATH")
    if not key_path:
        default = Path(__file__).parent.parent / "gcp-key.json"
        if default.exists():
            key_path = str(default)
    if not key_path or not Path(key_path).exists():
        raise RuntimeError(
            "Google Service Account 키 미설정. "
            "GOOGLE_SA_KEY_JSON 또는 GOOGLE_SA_KEY_PATH 또는 ./gcp-key.json 필요."
        )
    with open(key_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_credentials(scopes=None):
    """서비스 계정 자격증명 로드 (기본은 Calendar 스코프, scopes 파라미터로 다른 API용 발급 가능)."""
    info = _load_sa_info()
    use_scopes = scopes or SCOPES
    from google.oauth2 import service_account
    return service_account.Credentials.from_service_account_info(info, scopes=use_scopes)


def _get_calendar_service():
    """Calendar API 서비스 객체 반환"""
    credentials = _load_credentials()
    from googleapiclient.discovery import build
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _get_calendar_id():
    load_dotenv(ENV_PATH, override=True)
    cal_id = os.getenv("GOOGLE_CALENDAR_ID")
    if not cal_id:
        raise RuntimeError("GOOGLE_CALENDAR_ID가 .env에 없습니다.")
    return cal_id


def _make_event_id(announcement_id, kind):
    """deterministic event_id — 같은 공고+kind 재실행 시 중복 방지.

    Google Calendar event_id 규칙: base32hex 알파벳 (0-9, a-v)만 허용, 5~1024자.
    md5 → base32hex lowercase 변환 (26자).
    """
    base = f"hlradar-{announcement_id}-{kind}"
    digest = hashlib.md5(base.encode("utf-8")).digest()
    encoded = base64.b32hexencode(digest).decode("ascii").rstrip("=").lower()
    return f"hlr{encoded}"


def _get_announcement_id(item):
    """공고 고유 ID 추출 (소스 무관)"""
    raw = item.get("raw", {}) or {}
    pid = raw.get("pblancId") or raw.get("pbanc_sn") or raw.get("pbancSn")
    if pid:
        return str(pid)
    # URL에서 pblancId 파라미터 추출 (raw가 비어있어도 URL에 포함된 경우)
    url = item.get("url", "") or ""
    if "pblancId=" in url:
        import urllib.parse as _up
        qs = _up.urlparse(url).query
        params = _up.parse_qs(qs)
        pid = (params.get("pblancId") or [""])[0]
        if pid:
            return pid
    # fallback: title + deadline 해시 (제목이 바뀌면 중복 위험 있음)
    base = f"{item.get('title','')}-{item.get('deadline','')}-{item.get('agency','')}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()[:16]


def _build_description(item):
    """캘린더 이벤트 본문 — 점수 분해 + 본문 + 매칭 + URL"""
    lines = []
    lines.append(f"📊 적합도 {item['score']}/10 (적합 {item.get('fit_score','?')} + 지역 {item.get('region_score','?')} + 마감 {item.get('deadline_score','?')})")
    lines.append(f"📍 지역: {item.get('region_label','?')}")
    if item.get("agency"):
        lines.append(f"🏛 발주: {item['agency']}")
    lines.append("")

    raw = item.get("raw", {}) or {}
    target = raw.get("trgetNm") or raw.get("biz_enyy")
    if target:
        lines.append(f"👥 대상: {target}")
    realm = raw.get("realm") or raw.get("supt_biz_clsfc")
    if realm:
        lines.append(f"🏷 분야: {realm}")
    lines.append("")

    body = item.get("body_excerpt", "")
    if body:
        lines.append("📝 사업 개요:")
        lines.append(body[:1500])
        lines.append("")

    matched = item.get("matched", [])
    if matched:
        lines.append(f"🔑 매칭 키워드: {', '.join(matched[:8])}")

    if item.get("url"):
        lines.append("")
        lines.append(f"🔗 공고 원문: {item['url']}")

    return "\n".join(lines)


def _create_or_update_event(service, calendar_id, event_id, summary, date_iso, description):
    """이벤트 생성 또는 업데이트 (멱등). Rate limit 시 자동 재시도.

    date_iso: "YYYY-MM-DD" (종일 이벤트)
    """
    import time as _time
    body = {
        "id": event_id,
        "summary": summary,
        "description": description,
        "start": {"date": date_iso, "timeZone": "Asia/Seoul"},
        "end": {"date": date_iso, "timeZone": "Asia/Seoul"},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 60 * 9},  # 09:00 알람 (자정 기준 9시간 후)
            ],
        },
    }

    def _insert():
        return service.events().insert(calendarId=calendar_id, body=body).execute()

    def _update():
        return service.events().update(
            calendarId=calendar_id, eventId=event_id, body=body
        ).execute()

    # 1차: insert (rate limit 시 최대 3회 재시도, 지수 백오프)
    for attempt in range(3):
        try:
            _insert()
            _time.sleep(0.15)  # 다음 호출까지 150ms 갭 — 초당 6~7건 이하
            return "created"
        except Exception as e:
            err = str(e)
            err_lower = err.lower()
            # 이미 존재 → update로 분기
            if "already exists" in err_lower or "duplicate" in err_lower or "409" in err_lower:
                break
            # rate limit → 재시도
            if "ratelimitexceeded" in err_lower or "rate limit" in err_lower:
                _time.sleep(2 ** attempt)  # 1, 2, 4초
                continue
            log.warning(f"이벤트 생성 실패 ({event_id}): {err[:120]}")
            return "error"

    # 2차: update (rate limit 시 최대 3회 재시도)
    for attempt in range(3):
        try:
            _update()
            _time.sleep(0.15)
            return "updated"
        except Exception as e:
            err_lower = str(e).lower()
            if "ratelimitexceeded" in err_lower or "rate limit" in err_lower:
                _time.sleep(2 ** attempt)
                continue
            log.warning(f"이벤트 업데이트 실패: {str(e)[:120]}")
            return "skipped"

    return "error"


def sync_announcements(scored_items, log=None):
    """적합도 ≥ 7 + 마감일 있는 공고를 캘린더에 등록.

    한 공고당 최대 3개 이벤트:
      - D-7: "[D-7] {제목}" — 마감 7일 전
      - D-3: "[D-3 긴급] {제목}" — 마감 3일 전
      - 마감일 당일: "[마감] {제목}"

    Returns:
        dict: {"eligible": int, "created": int, "updated": int, "skipped": int, "errors": int}
    """
    log = log or logging.getLogger(__name__)
    stats = {"eligible": 0, "created": 0, "updated": 0, "skipped": 0, "errors": 0, "deleted": 0}

    # 강등된 공고(자격미달·검증불가) → 기존 등록 이벤트 자동 삭제
    # 점수 ≥7 + 마감일 있던 공고만 (등록됐을 가능성 있는 것). Rate limit 회피.
    # 타지역/제외/비공고/메뉴는 처음부터 점수 0이라 등록 안 됐으므로 delete 시도 불필요.
    LLM_DEMOTED_TIER_PREFIX = ("자격미달", "검증불가")
    demoted = [
        s for s in scored_items
        if (s.get("tier") or "").startswith(LLM_DEMOTED_TIER_PREFIX)
        and s.get("deadline")
        and (s.get("score") or 0) >= CALENDAR_THRESHOLD  # 등록 가능성 있던 것만
    ]

    # 등록 대상: 점수 ≥7 + 마감일 + 자격미달·검증불가·타지역 등 강등 안 된 것
    EXCLUDE_FROM_CALENDAR = (
        "타지역", "제외", "비공고", "메뉴", "자격미달", "검증불가",
    )
    eligible = [
        s for s in scored_items
        if s.get("score", 0) >= CALENDAR_THRESHOLD and s.get("deadline")
        and not (s.get("tier") or "").startswith(EXCLUDE_FROM_CALENDAR)
    ]
    stats["eligible"] = len(eligible)

    if not eligible and not demoted:
        log.info("캘린더 등록 대상 없음 (적합도 ≥ 7 + 마감일 있는 공고)")
        return stats

    try:
        service = _get_calendar_service()
        calendar_id = _get_calendar_id()
    except RuntimeError as e:
        # 키/캘린더 미설정 — 스킵 (호출 측에서 처리)
        raise
    except ImportError:
        raise RuntimeError(
            "google-api-python-client 미설치. "
            "pip install google-api-python-client google-auth"
        )

    today = datetime.now(KST).date()

    # 강등 공고 자동 삭제 (이전 등록 이벤트 정리) — rate limit 보호용 sleep 포함
    import time as _time
    for item in demoted:
        announcement_id = _get_announcement_id(item)
        for kind in ["d7", "d3", "deadline"]:
            event_id = _make_event_id(announcement_id, kind)
            try:
                service.events().delete(
                    calendarId=calendar_id, eventId=event_id
                ).execute()
                stats["deleted"] += 1
                _time.sleep(0.1)  # 100ms — 초당 10 요청 이하로 제한
            except Exception as e:
                err = str(e)
                if "404" not in err and "Not Found" not in err and "deleted" not in err:
                    if "rateLimitExceeded" in err:
                        _time.sleep(2)  # rate limit 시 2초 대기 (한 번만)

    if stats["deleted"]:
        log.info(f"강등 공고 자동 삭제: {stats['deleted']}건")

    for item in eligible:
        try:
            deadline_str = item["deadline"]  # YYYY-MM-DD
            deadline_dt = datetime.strptime(deadline_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue

        announcement_id = _get_announcement_id(item)
        title_short = item["title"][:60]
        description = _build_description(item)

        # D-7
        d7 = deadline_dt - timedelta(days=7)
        if d7 >= today:
            event_id = _make_event_id(announcement_id, "d7")
            r = _create_or_update_event(
                service, calendar_id, event_id,
                f"[D-7] {title_short}",
                d7.isoformat(), description,
            )
            stats[r] = stats.get(r, 0) + 1

        # D-3
        d3 = deadline_dt - timedelta(days=3)
        if d3 >= today:
            event_id = _make_event_id(announcement_id, "d3")
            r = _create_or_update_event(
                service, calendar_id, event_id,
                f"[D-3 긴급] {title_short}",
                d3.isoformat(), description,
            )
            stats[r] = stats.get(r, 0) + 1

        # 마감 당일
        if deadline_dt >= today:
            event_id = _make_event_id(announcement_id, "deadline")
            r = _create_or_update_event(
                service, calendar_id, event_id,
                f"[마감] {title_short}",
                deadline_dt.isoformat(), description,
            )
            stats[r] = stats.get(r, 0) + 1

    return stats


def test_connection():
    """연결 테스트 — 인증 + 캘린더 접근 권한 확인"""
    try:
        service = _get_calendar_service()
        calendar_id = _get_calendar_id()
        # 캘린더 메타데이터 조회
        cal = service.calendars().get(calendarId=calendar_id).execute()
        return {
            "ok": True,
            "calendar_id": calendar_id,
            "summary": cal.get("summary"),
            "time_zone": cal.get("timeZone"),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        result = test_connection()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # 최근 결과 JSON 로드 + 캘린더 등록
        from datetime import datetime as _dt
        today = _dt.now(KST).strftime("%Y%m%d")
        result_file = Path(__file__).parent.parent / "data" / "govt_radar" / f"radar_{today}.json"
        if not result_file.exists():
            print(f"결과 파일 없음: {result_file}")
            sys.exit(1)
        with open(result_file, "r", encoding="utf-8") as f:
            scored = json.load(f)
        print(f"로드: {len(scored)}건")
        stats = sync_announcements(scored)
        print(f"결과: {stats}")
