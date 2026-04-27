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


def _load_credentials():
    """서비스 계정 자격증명 로드.

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
            info = json.loads(raw_json)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"GOOGLE_SA_KEY_JSON 파싱 실패: {e}")
    else:
        # 파일 경로 시도
        key_path = os.getenv("GOOGLE_SA_KEY_PATH")
        if not key_path:
            # 프로젝트 루트 폴백
            default = Path(__file__).parent.parent / "gcp-key.json"
            if default.exists():
                key_path = str(default)
        if not key_path or not Path(key_path).exists():
            raise RuntimeError(
                "Google Service Account 키 미설정. "
                "GOOGLE_SA_KEY_JSON 또는 GOOGLE_SA_KEY_PATH 또는 ./gcp-key.json 필요. "
                "docs/govt-radar/06-google-calendar-setup.md 참고."
            )
        with open(key_path, "r", encoding="utf-8") as f:
            info = json.load(f)

    # google-auth lazy import (의존성 미설치 시 ImportError 방지)
    from google.oauth2 import service_account
    return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)


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
    pid = raw.get("pblancId") or raw.get("pbanc_sn")
    if pid:
        return str(pid)
    # fallback: title + deadline 해시
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
    """이벤트 생성 또는 업데이트 (멱등).

    date_iso: "YYYY-MM-DD" (종일 이벤트)
    """
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
    try:
        service.events().insert(calendarId=calendar_id, body=body).execute()
        return "created"
    except Exception as e:
        # 이미 존재하면 업데이트 시도
        msg = str(e).lower()
        if "already exists" in msg or "duplicate" in msg or "409" in msg:
            try:
                service.events().update(
                    calendarId=calendar_id, eventId=event_id, body=body
                ).execute()
                return "updated"
            except Exception as e2:
                log.warning(f"이벤트 업데이트 실패: {e2}")
                return "skipped"
        log.warning(f"이벤트 생성 실패 ({event_id}): {e}")
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
    stats = {"eligible": 0, "created": 0, "updated": 0, "skipped": 0, "errors": 0}

    eligible = [
        s for s in scored_items
        if s.get("score", 0) >= CALENDAR_THRESHOLD and s.get("deadline")
    ]
    stats["eligible"] = len(eligible)

    if not eligible:
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
