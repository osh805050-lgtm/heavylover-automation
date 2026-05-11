"""
⚠️ 2026-05-12 비활성: System User Token(무기한) 사용 중. 정책 변경으로 만료 토큰 복귀 시만 재활성.

Meta User Access Token 자동 연장 (60일 만료 회피)

매주 월요일 자동 호출 (.github/workflows/meta-ads-weekly.yml에 통합) — 현재 workflow에서 제거됨.

원리:
- Graph API `oauth/access_token?grant_type=fb_exchange_token` 호출
- 만료 전이라면 새 60일짜리 long-lived 토큰 발급 (같은 토큰 재발급)
- 결과를 .env(로컬) + GitHub Secrets(원격)에 자동 갱신

환경변수:
    META_ACCESS_TOKEN   현재 토큰 (만료 전이어야 함)
    META_APP_ID         Meta 앱 ID — 광고 자동화 앱
    META_APP_SECRET     Meta 앱 시크릿
    GH_REPO_FOR_SECRETS (선택) gh CLI로 secret 갱신할 저장소 (예: osh805050-lgtm/heavylover-automation)

미설정 시: skip + 텔레그램 경고. 워크플로우 실패 안 시킴.

원칙 (CLAUDE.md §0):
- 토큰 갱신 실패해도 다른 자동화는 계속 돌도록 (silent fallback)
- 갱신 결과는 텔레그램에 보고
"""

import io
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

# Windows cp949 콘솔 대비
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
ENV_PATH = ROOT / ".env"
KST = timezone(timedelta(hours=9))

GRAPH_BASE = "https://graph.facebook.com/v21.0"


def _notify_telegram(msg):
    try:
        import telegram_client
        telegram_client.send_message(msg, channel="ops")
    except Exception:
        print(f"[telegram skip] {msg}")


def _update_env_token(new_token):
    """로컬 .env의 META_ACCESS_TOKEN 갱신"""
    if not ENV_PATH.exists():
        return False
    txt = ENV_PATH.read_text(encoding="utf-8")
    lines = txt.splitlines()
    new_lines = []
    found = False
    for line in lines:
        if line.startswith("META_ACCESS_TOKEN="):
            new_lines.append(f"META_ACCESS_TOKEN={new_token}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"META_ACCESS_TOKEN={new_token}")
    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return True


def _update_github_secret(new_token):
    """GitHub Actions Secret 갱신 (gh CLI)"""
    try:
        r = subprocess.run(
            ["gh", "secret", "set", "META_ACCESS_TOKEN", "--body", new_token],
            capture_output=True, text=True, cwd=str(ROOT), encoding="utf-8",
        )
        if r.returncode == 0:
            return True, ""
        return False, r.stderr.strip()
    except FileNotFoundError:
        return False, "gh CLI 없음"
    except Exception as e:
        return False, str(e)


def refresh():
    load_dotenv(ENV_PATH, override=True)

    current_token = os.getenv("META_ACCESS_TOKEN", "").strip()
    app_id = os.getenv("META_APP_ID", "").strip()
    app_secret = os.getenv("META_APP_SECRET", "").strip()

    if not current_token:
        msg = "[Meta 토큰 갱신 skip] META_ACCESS_TOKEN 없음"
        print(msg)
        _notify_telegram(msg)
        return 1

    if not app_id or not app_secret:
        msg = ("[Meta 토큰 갱신 skip] META_APP_ID 또는 META_APP_SECRET 미설정.\n"
               "광고 자동화 앱 → 기본 설정에서 발급 후 .env + GitHub Secrets 등록 필요.")
        print(msg)
        _notify_telegram(msg)
        return 1

    print(f"Meta 토큰 갱신 시도 (앱 {app_id})")
    try:
        r = requests.get(
            f"{GRAPH_BASE}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": app_id,
                "client_secret": app_secret,
                "fb_exchange_token": current_token,
            },
            timeout=30,
        )
    except requests.RequestException as e:
        msg = f"[Meta 토큰 갱신 실패] 네트워크 오류: {e}"
        print(msg)
        _notify_telegram(msg)
        return 2

    if r.status_code != 200:
        msg = f"[Meta 토큰 갱신 실패] HTTP {r.status_code}: {r.text[:300]}"
        print(msg)
        _notify_telegram(msg)
        return 2

    body = r.json()
    new_token = body.get("access_token")
    expires_in = body.get("expires_in")  # 초

    if not new_token:
        msg = f"[Meta 토큰 갱신 실패] 응답에 access_token 없음: {body}"
        print(msg)
        _notify_telegram(msg)
        return 2

    # 같은 토큰 재발급될 수 있음 (Meta가 결정)
    if new_token == current_token:
        msg = "[Meta 토큰 갱신] 같은 토큰 재발급 (만료 시점 갱신됨, 정상)"
    else:
        msg = "[Meta 토큰 갱신] 새 토큰 발급"

    if expires_in:
        expire_dt = datetime.now(KST) + timedelta(seconds=expires_in)
        msg += f" — 만료: {expire_dt.strftime('%Y-%m-%d')} ({expires_in//86400}일 후)"

    # 로컬 .env 갱신
    env_ok = _update_env_token(new_token)
    msg += f"\n  .env 갱신: {'OK' if env_ok else 'FAIL'}"

    # GitHub Secrets 갱신
    gh_ok, gh_err = _update_github_secret(new_token)
    if gh_ok:
        msg += "\n  GitHub Secrets 갱신: OK"
    else:
        msg += f"\n  GitHub Secrets 갱신: SKIP ({gh_err})"

    print(msg)
    _notify_telegram(msg)
    return 0


if __name__ == "__main__":
    sys.exit(refresh())
