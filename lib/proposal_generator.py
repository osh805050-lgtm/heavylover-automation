"""사업계획서 5섹션 초안 자동 생성 (Stage D)

공고 한 건을 받아서 헤비로버 ground truth(data/heavylover_profile.json)를
주입한 상태로 Claude Sonnet에 프로필 캐싱으로 호출 → 마크다운 5섹션 반환.

비용:
  - Sonnet 4.6, 입력 캐싱 적용
  - 1회 ~$0.5 (입력 ~3K 토큰 + 출력 ~3K 토큰)

규칙:
  - 모든 수치는 ground truth에서만. 없으면 "[데이터 없음 — 승현님 확인 필요]"
  - AI 화법·과장 금지 (CLAUDE.md §0)
  - 1500~2500자, 마크다운 헤더(#·##) 사용
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent.parent / ".env"
PROFILE_PATH = Path(__file__).parent.parent / "data" / "heavylover_profile.json"
KST = timezone(timedelta(hours=9))
MODEL = "claude-sonnet-4-6"

log = logging.getLogger(__name__)

_profile_cache = None
_client_cache = None


def _load_profile():
    global _profile_cache
    if _profile_cache is None:
        _profile_cache = json.dumps(
            json.loads(PROFILE_PATH.read_text(encoding="utf-8")),
            ensure_ascii=False,
            indent=2,
        )
    return _profile_cache


def _get_client():
    global _client_cache
    if _client_cache is None:
        load_dotenv(ENV_PATH, override=True)
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY 미설정")
        _client_cache = Anthropic(api_key=key)
    return _client_cache


SYSTEM_PROMPT = """너는 한국 정부 사업계획서 평가위원이자 작성 코치다.
헤비로버(D2C 식품, 경기 용인 수지) 프로필을 기반으로 정부 지원사업 공고에
신청하는 사업계획서 5섹션 초안을 작성한다.

규칙:
- 모든 수치(매출·연차·재구매·ROAS 등)는 ground truth에서만 인용.
  없으면 반드시 "[데이터 없음 — 승현님 확인 필요]" 명시. 추정·창작 금지.
- AI 화법(~할 수 있습니다·중요한 것은·~로 보입니다) 금지. 단정형으로.
- 과장(놀라운/혁신적인/최고의/유일한/엄청난) 금지.
- 시장 규모는 출처 명시(통계청·KOTRA·산업협회 등). 출처 모르면 "[출처 확인 필요]".
- 공고 평가 관점: 자격·실적·차별점·실행계획·예산이 명확히 드러나도록.
- 마크다운 헤더(#, ##) 사용. 본문 1,500~2,500자.

섹션 구조 (반드시 이 순서·헤더):
# {공고명} 사업계획서 초안

## 1. 사업개요
- 한 줄 요약 + 문제 + 헤비로버 해결책

## 2. 시장 환경
- 타겟 시장 규모·트렌드 (출처 필수)

## 3. 헤비로버 차별점
- CRM·인프라·실적 (ground truth 우선)
- M+1 리텐션 14% 약점은 솔직히 명시 + 개선 계획으로 전환

## 4. 실행 계획
- 3개월·6개월·12개월 마일스톤

## 5. 예산·기대효과
- 지원금 사용처 + 매출 목표

## 후수정 체크리스트
- [ ] [데이터 없음] 표시 항목 채우기
- [ ] 외부 출처 검증
- [ ] 팀원 이력 첨부
"""


def generate_draft(item: dict) -> str:
    """공고 한 건 → 사업계획서 마크다운 초안 반환.

    Args:
        item: govt_radar 공통 스키마

    Returns:
        str: 마크다운 본문 (1500~2500자)
    """
    title = (item.get("title") or "").strip()
    agency = (item.get("agency") or "").strip()
    deadline = item.get("deadline") or "?"
    body = (item.get("body_excerpt") or "")[:1500].strip()
    raw = item.get("raw") or {}

    profile = _load_profile()
    user_msg = (
        f"# 헤비로버 ground truth\n```json\n{profile}\n```\n\n"
        f"# 공고 정보\n"
        f"제목: {title}\n"
        f"발주: {agency}\n"
        f"마감: {deadline}\n"
        f"대상: {raw.get('trgetNm', '?')}\n"
        f"분야: {raw.get('realm', '?')}\n"
        f"본문:\n{body}\n\n"
        f"위 공고에 헤비로버가 신청하는 사업계획서 초안을 5섹션 마크다운으로 작성하라."
    )

    client = _get_client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_msg}],
    )
    return resp.content[0].text.strip()


def upload_to_google_docs(item: dict, markdown_text: str) -> str:
    """Google Drive에 사업계획서 마크다운을 Google Docs로 업로드.

    Returns:
        str: Docs URL. 실패 시 빈 문자열.
    """
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaInMemoryUpload
        from lib.calendar_client import _load_credentials
    except ImportError as e:
        log.warning(f"Google API 라이브러리 미설치: {e}")
        return ""

    try:
        creds = _load_credentials(
            scopes=[
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/documents",
            ]
        )
        drive = build("drive", "v3", credentials=creds, cache_discovery=False)

        notify_id = item.get("notify_id", "?")
        title = (item.get("title") or "?")[:50]
        file_meta = {
            "name": f"[{notify_id}] {title}",
            "mimeType": "application/vnd.google-apps.document",
        }
        media = MediaInMemoryUpload(
            markdown_text.encode("utf-8"), mimetype="text/plain"
        )
        f = (
            drive.files()
            .create(body=file_meta, media_body=media, fields="id,webViewLink")
            .execute()
        )

        # 사용자 Gmail에 writer 권한 공유
        user_email = os.getenv("GOOGLE_DOCS_SHARE_EMAIL", "osh805050@gmail.com")
        try:
            drive.permissions().create(
                fileId=f["id"],
                body={"type": "user", "role": "writer", "emailAddress": user_email},
                sendNotificationEmail=False,
            ).execute()
        except Exception as e:
            log.warning(f"Docs 공유 실패 (스킵): {e}")

        return f.get("webViewLink", "")
    except Exception as e:
        log.warning(f"Google Docs 업로드 실패: {type(e).__name__}: {e}")
        return ""


if __name__ == "__main__":
    import sys
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    sample = {
        "title": "2026년도 초기창업패키지 통합공고",
        "agency": "창업진흥원",
        "deadline": "2026-05-31",
        "body_excerpt": "전국 창업 3년 이내 기업 대상. 사업화 자금 최대 1억원 지원.",
        "raw": {"trgetNm": "창업기업", "realm": "창업"},
        "notify_id": "TEST",
    }
    print(f"=== 샘플 사업계획서 초안 생성 (모델: {MODEL}) ===\n")
    draft = generate_draft(sample)
    print(draft)
