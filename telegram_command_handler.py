"""정부지원 레이더 텔레그램 명령 처리기

GitHub Actions 5분 cron에서 실행. 텔레그램에서 받은 명령을 처리해 응답.

지원 명령:
  /details S1   — 공고 풀 본문·자격·신청방법
  /why S1       — 점수 분해·매칭 키워드·LLM 판정 사유
  /save A2      — 관심 공고 JSON 박제 (다이제스트 합류)
  /draft S1     — 사업계획서 5섹션 자동 생성 (GitHub + Google Docs)
  /help, /start — 도움말

멱등성:
  data/govt_radar/last_processed_update_id.txt에 마지막 처리 update_id 박제.
  cron 재실행 시 offset+1로 신규만 처리.
"""

import io
import json
import logging
import os
import re
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

import telegram_client

# Windows 콘솔 UTF-8
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).parent
ENV_PATH = ROOT / ".env"
RADAR_DIR = ROOT / "data" / "govt_radar"
SAVED_PATH = RADAR_DIR / "saved_announcements.json"
LAST_ID_PATH = RADAR_DIR / "last_processed_update_id.txt"
DRAFT_DIR = ROOT / "docs" / "govt-proposals" / "drafts"
KST = timezone(timedelta(hours=9))
API_BASE = "https://api.telegram.org"

log = logging.getLogger(__name__)


# ============================================================
# 공통 헬퍼
# ============================================================
def _load_latest_radar():
    """최신 radar_YYYYMMDD.json 로드. 반환: (items, filename)"""
    files = sorted(RADAR_DIR.glob("radar_2*.json"))
    if not files:
        return [], ""
    latest = files[-1]
    items = json.loads(latest.read_text(encoding="utf-8"))
    return items, latest.name


def _find_by_notify_id(items, notify_id):
    if not notify_id:
        return None
    nid = notify_id.upper().lstrip("#")
    return next((i for i in items if (i.get("notify_id") or "").upper() == nid), None)


def _split_message(text, limit=3500):
    """텔레그램 4096자 제한 회피. 줄 단위 분할."""
    if len(text) <= limit:
        return [text]
    chunks = []
    current = []
    cur_len = 0
    for line in text.split("\n"):
        if cur_len + len(line) + 1 > limit and current:
            chunks.append("\n".join(current))
            current = [line]
            cur_len = len(line) + 1
        else:
            current.append(line)
            cur_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def _stable_key(item):
    """공고 중복 방지 키 (pblancId/pbancSn + 제목)"""
    raw = item.get("raw") or {}
    pid = raw.get("pblancId") or raw.get("pbancSn") or ""
    return f"{pid}|{(item.get('title') or '').strip()[:80]}"


def _read_last_update_id():
    if not LAST_ID_PATH.exists():
        return 0
    try:
        return int(LAST_ID_PATH.read_text(encoding="utf-8").strip() or "0")
    except (ValueError, OSError):
        return 0


def _save_last_update_id(update_id):
    LAST_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_ID_PATH.write_text(str(update_id), encoding="utf-8")


def _fetch_new_updates(limit=20):
    """getUpdates에서 신규 메시지만 받아옴 (offset 기반)."""
    load_dotenv(ENV_PATH, override=True)
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 미설정")

    last_id = _read_last_update_id()
    params = {"limit": limit, "timeout": 0}
    if last_id:
        params["offset"] = last_id + 1

    r = requests.get(f"{API_BASE}/bot{token}/getUpdates", params=params, timeout=30)
    if not r.ok:
        log.warning(f"getUpdates 실패: {r.status_code}")
        return []
    updates = r.json().get("result", [])
    return updates


# ============================================================
# 명령 핸들러
# ============================================================
def _handle_help():
    msg = [
        "🤖 정부지원 레이더 명령 가이드",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        "/details S1  — 공고 풀 본문·자격·신청방법",
        "/why S1      — 점수 분해·LLM 판정 사유",
        "/save A2     — 관심 공고 박제 (다이제스트 합류)",
        "/draft S1    — 사업계획서 초안 생성 (1~2분)",
        "",
        "공고 번호는 매일 11시 알림에 표시된 #S1·#A1·#B1 형태.",
        "오늘 알림 안에서만 유효합니다.",
    ]
    telegram_client.send_message("\n".join(msg))


def _handle_details(notify_id):
    items, _ = _load_latest_radar()
    item = _find_by_notify_id(items, notify_id)
    if not item:
        telegram_client.send_message(
            f"⚠️ {notify_id} 공고를 찾을 수 없습니다.\n오늘 알림에 있는 번호인지 확인해주세요."
        )
        return

    raw = item.get("raw") or {}
    msg = []
    msg.append(f"📋 #{notify_id} 상세")
    msg.append("━━━━━━━━━━━━━━━━━━━━")
    msg.append(f"제목: {item.get('title', '?')}")
    msg.append(f"발주: {item.get('agency', '?')}")
    deadline = item.get("deadline") or "?"
    d_days = item.get("deadline_days")
    msg.append(f"마감: {deadline}" + (f" (D{d_days})" if d_days is not None else ""))
    msg.append(f"점수: {item.get('score', '?')} ({item.get('region_label', '?')})")
    msg.append("")
    if raw.get("trgetNm"):
        msg.append(f"👥 대상: {raw['trgetNm']}")
    if raw.get("realm"):
        msg.append(f"🏷 분야: {raw['realm']}")
    if raw.get("biz_enyy"):
        msg.append(f"📅 업력: {raw['biz_enyy']}")
    if raw.get("hashtags"):
        msg.append(f"#️⃣ 태그: {raw['hashtags']}")
    msg.append("")
    msg.append("📝 본문")
    body = (item.get("body_excerpt") or "").strip()
    msg.append(body if body else "(본문 없음 — URL 클릭)")
    msg.append("")
    if raw.get("reqstMthPapersCn"):
        msg.append(f"✍️ 신청방법: {raw['reqstMthPapersCn'][:300]}")
    if raw.get("refrncNm"):
        msg.append(f"📞 문의: {raw['refrncNm']}")
    if raw.get("flpthNm"):
        msg.append(f"📎 첨부: {raw['flpthNm']}")
    msg.append("")
    if item.get("url"):
        msg.append(f"🔗 {item['url']}")

    full = "\n".join(msg)
    for chunk in _split_message(full, 3500):
        telegram_client.send_message(chunk)


def _handle_why(notify_id):
    items, _ = _load_latest_radar()
    item = _find_by_notify_id(items, notify_id)
    if not item:
        telegram_client.send_message(f"⚠️ {notify_id} 없음 — 오늘 알림 번호 확인")
        return

    msg = []
    msg.append(f"🔍 #{notify_id} 적합도 분석")
    msg.append("━━━━━━━━━━━━━━━━━━━━")
    title = (item.get("title") or "?")[:65]
    msg.append(f"제목: {title}")
    msg.append(f"총점: {item.get('score', '?')} ({item.get('tier', '?')})")
    msg.append("")
    msg.append("📊 점수 분해")
    msg.append(f"  • 사업적합도: {item.get('fit_score', 0)} / 8")
    msg.append(
        f"  • 지역: {item.get('region_score', 0)} / 2 ({item.get('region_label', '?')})"
    )
    msg.append(f"  • 마감임박: {item.get('deadline_score', 0)}")
    msg.append("")
    matched = item.get("matched") or []
    if matched:
        msg.append(f"🔑 매칭 키워드 ({len(matched)}개)")
        msg.append(f"  {', '.join(matched[:10])}")
        msg.append("")
    elig = item.get("eligibility") or {}
    if elig:
        emoji = {"yes": "✅", "no": "❌", "unsure": "❓"}.get(elig.get("eligible"), "")
        msg.append(f"🤖 LLM 자격 판정 {emoji}")
        msg.append(f"  결과: {elig.get('eligible', '?')}")
        msg.append(f"  사유: {elig.get('reason', '-')}")
    else:
        msg.append("🤖 LLM 자격 판정: 미실행 (적합도 5점 미만)")
    msg.append("")
    tags = item.get("tags") or []
    if tags:
        msg.append(f"🏷 태그: {', '.join(tags)}")

    telegram_client.send_message("\n".join(msg))


def _handle_save(notify_id):
    items, src_file = _load_latest_radar()
    item = _find_by_notify_id(items, notify_id)
    if not item:
        telegram_client.send_message(f"⚠️ {notify_id} 없음")
        return

    saved = []
    if SAVED_PATH.exists():
        try:
            saved = json.loads(SAVED_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            saved = []

    key = _stable_key(item)
    if any(_stable_key(s) == key for s in saved):
        telegram_client.send_message(
            f"ℹ️ #{notify_id} 이미 저장됨 (현재 관심 공고 {len(saved)}건)"
        )
        return

    item_to_save = dict(item)
    item_to_save["saved_at"] = datetime.now(KST).isoformat()
    item_to_save["saved_from"] = src_file
    saved.append(item_to_save)

    SAVED_PATH.parent.mkdir(parents=True, exist_ok=True)
    SAVED_PATH.write_text(
        json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    deadline = item.get("deadline") or "?"
    title = (item.get("title") or "?")[:50]
    msg = [
        f"⭐ #{notify_id} 저장 완료",
        f"  제목: {title}",
        f"  마감: {deadline}",
        f"  현재 관심 공고: {len(saved)}건",
        "",
        "매주 월요일 다이제스트 상단에 자동 포함됩니다.",
    ]
    telegram_client.send_message("\n".join(msg))


def _handle_draft(notify_id):
    items, _ = _load_latest_radar()
    item = _find_by_notify_id(items, notify_id)
    if not item:
        telegram_client.send_message(f"⚠️ {notify_id} 없음")
        return

    title = (item.get("title") or "?")[:60]
    telegram_client.send_message(
        f"⏳ #{notify_id} 사업계획서 초안 생성 중...\n"
        f"  제목: {title}\n"
        f"  소요: 1~2분"
    )

    try:
        from lib import proposal_generator
    except ImportError as e:
        telegram_client.send_message(f"⚠️ proposal_generator 로드 실패: {e}")
        return

    try:
        draft_md = proposal_generator.generate_draft(item)
    except Exception as e:
        log.error(f"draft 생성 실패: {e}\n{traceback.format_exc()}")
        telegram_client.send_message(
            f"⚠️ 초안 생성 실패: {type(e).__name__}: {str(e)[:120]}"
        )
        return

    # 1. GitHub 저장
    today = datetime.now(KST).strftime("%Y-%m-%d")
    safe_title = re.sub(r"[^\w가-힣]+", "_", item.get("title", "untitled"))[:40]
    md_path = DRAFT_DIR / f"{today}-{notify_id}-{safe_title}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(draft_md, encoding="utf-8")

    # 2. Google Docs 업로드 (best-effort)
    docs_url = ""
    try:
        docs_url = proposal_generator.upload_to_google_docs(item, draft_md)
    except Exception as e:
        log.warning(f"Docs 업로드 실패 (스킵): {e}")

    # 3. 응답
    msg = [
        f"📄 #{notify_id} 사업계획서 초안 완료",
        "━━━━━━━━━━━━━━━━━━━━",
        f"제목: {title}",
        f"분량: {len(draft_md)}자",
        "",
        f"📁 GitHub: {md_path.relative_to(ROOT).as_posix()}",
    ]
    if docs_url:
        msg.append(f"📝 Google Docs: {docs_url}")
    else:
        msg.append("📝 Google Docs: 업로드 실패 (Drive API 활성화 필요)")
    msg.append("")
    msg.append("⚠️ 후수정 필요: 본문 [데이터 없음] 표시 항목 반드시 채우기")
    telegram_client.send_message("\n".join(msg))


# ============================================================
# 메인
# ============================================================
KNOWN_COMMANDS = {"/details", "/why", "/save", "/draft", "/help", "/start"}


def _process_update(update):
    """단일 update 처리. 알려진 명령만 응답."""
    msg = update.get("message") or update.get("edited_message") or {}
    text = (msg.get("text") or "").strip()
    if not text or not text.startswith("/"):
        return

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().split("@")[0]  # /details@bot_name 형태 대응
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd not in KNOWN_COMMANDS:
        return  # /done, /cancel 등 다른 봇 명령 무시

    log.info(f"명령 수신: {cmd} {arg}")

    try:
        if cmd in ("/help", "/start"):
            _handle_help()
        elif cmd == "/details":
            _handle_details(arg)
        elif cmd == "/why":
            _handle_why(arg)
        elif cmd == "/save":
            _handle_save(arg)
        elif cmd == "/draft":
            _handle_draft(arg)
    except Exception as e:
        log.error(f"명령 처리 실패 {cmd} {arg}: {e}\n{traceback.format_exc()}")
        try:
            telegram_client.send_message(
                f"⚠️ {cmd} 처리 실패: {type(e).__name__}: {str(e)[:120]}"
            )
        except Exception:
            pass


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    log.info("=" * 60)
    log.info(f"명령 처리기 시작 - {datetime.now(KST).isoformat()}")

    try:
        updates = _fetch_new_updates()
    except Exception as e:
        log.error(f"getUpdates 실패: {e}")
        return

    if not updates:
        log.info("신규 메시지 0건")
        return

    log.info(f"신규 메시지 {len(updates)}건 처리")
    for u in updates:
        _process_update(u)

    last_id = updates[-1]["update_id"]
    _save_last_update_id(last_id)
    log.info(f"last_update_id={last_id} 저장")
    log.info("명령 처리기 종료")


if __name__ == "__main__":
    main()
