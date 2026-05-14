"""pipeline_meta 탭 기반 신선도 체크 + row 기록.

3-state:
  fresh   = writer=gas 최신 row, run_id 오늘 날짜 시작, status=success
  stale   = gas row 없음 / run_id 어제 이전 / status≠success
  unknown = 탭 없음 / API 오류 / 파싱 에러 → fail-closed (stale과 동일 처리)

pipeline_meta 탭 헤더:
  run_id | writer | status | started_at | finished_at | extra

writer 종류:
  sheets_sync — 1단계 raw 동기화
  gas         — 2단계 GAS 분석 (GAS 코드에서 직접 기록)
  reporter    — 3단계 repurchase_report.py
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
PIPELINE_META_TAB = "pipeline_meta"
PIPELINE_META_HEADER = ["run_id", "writer", "status", "started_at", "finished_at", "extra"]
ALERT_STATE_PATH = Path(__file__).parent.parent / "data" / "alert_state.json"


def _now_kst() -> datetime:
    return datetime.now(KST)


def _today_iso() -> str:
    return _now_kst().strftime("%Y-%m-%d")


def _load_alert_state() -> dict:
    try:
        if ALERT_STATE_PATH.exists():
            return json.loads(ALERT_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_alert_state(state: dict) -> None:
    try:
        ALERT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        ALERT_STATE_PATH.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def _get_or_create_meta_tab(spreadsheet):
    try:
        return spreadsheet.worksheet(PIPELINE_META_TAB)
    except Exception:
        ws = spreadsheet.add_worksheet(title=PIPELINE_META_TAB, rows=500, cols=10)
        ws.update(values=[PIPELINE_META_HEADER], range_name="A1")
        return ws


def write_pipeline_meta_row(
    spreadsheet,
    writer: str,
    run_id: str,
    started_at: str,
    finished_at: str,
    status: str,
    **kwargs,
) -> None:
    """pipeline_meta 탭에 row 1개 append. 실패해도 조용히 넘어감."""
    try:
        ws = _get_or_create_meta_tab(spreadsheet)
        extra = json.dumps(kwargs, ensure_ascii=False) if kwargs else ""
        ws.append_row(
            [run_id, writer, status, started_at, finished_at, extra],
            value_input_option="RAW",
        )
    except Exception as e:
        print(f"[sheet_staleness] pipeline_meta 기록 실패 (무시): {e}", flush=True)


def check_pipeline_freshness(spreadsheet) -> str:
    """writer=gas row 기준으로 2단계 신선도 반환.

    staleness check는 오직 GAS row만 본다.
    reporter(3단계)가 오늘 row를 써도 gas row 없으면 stale.
    """
    today = _today_iso()
    try:
        ws = spreadsheet.worksheet(PIPELINE_META_TAB)
        rows = ws.get_all_values()
        if len(rows) < 2:
            return "stale"

        header = rows[0]
        try:
            idx_run_id = header.index("run_id")
            idx_writer = header.index("writer")
            idx_status = header.index("status")
        except ValueError:
            return "unknown"

        gas_rows = [
            r for r in rows[1:]
            if len(r) > idx_writer and r[idx_writer] == "gas"
        ]
        if not gas_rows:
            return "stale"

        latest = gas_rows[-1]
        run_id = latest[idx_run_id] if len(latest) > idx_run_id else ""
        status = latest[idx_status] if len(latest) > idx_status else ""

        if run_id.startswith(today) and status == "success":
            return "fresh"
        return "stale"

    except Exception:
        return "unknown"


def alert_if_not_fresh(state: str) -> None:
    """stale/unknown 시 ops 채널 알림 (당일 dedup). fresh 시 회복 알림."""
    if state == "fresh":
        alert_state = _load_alert_state()
        if alert_state.get("staleness_sent"):
            try:
                from telegram_client import send_message
                send_message(
                    "✅ 재구매 분석 시트 정상화 됐습니다 (GAS 오늘 실행 확인)",
                    channel="ops",
                )
            except Exception:
                pass
            alert_state.pop("staleness_sent", None)
            _save_alert_state(alert_state)
        return

    today = _today_iso()
    incident_key = f"staleness:{today}"
    alert_state = _load_alert_state()

    if alert_state.get(incident_key):
        return  # 오늘 이미 발송

    # [2026-05-15] 비전공자 친화 메시지
    if state == "stale":
        msg = (
            f"⚠️ 오늘 분석 자동 실행 안 됨\n"
            f"\n"
            f"대시보드가 어제 수치로 보일 수 있어요.\n"
            f"오늘 아침 구글 시트 안에서 자동으로 돌아야 할 분석 (Apps Script)이 멈췄거나 안 돌았어요.\n"
            f"\n"
            f"대응:\n"
            f"• 구글 시트 → 확장 프로그램 → Apps Script → ⏱시계 아이콘 → 트리거 페이지 확인\n"
            f"• 트리거 없으면 setupDailyTrigger 함수 1회 실행\n"
            f"• 또는 Claude한테 점검 요청\n"
            f"\n"
            f"(오늘 날짜: {today})"
        )
    else:  # unknown
        msg = (
            f"⚠️ 시트 접속 안 됨\n"
            f"\n"
            f"오늘 아침 구글 시트 자체에 접근이 안 됐어요.\n"
            f"네트워크 문제 또는 시트 권한 문제 의심.\n"
            f"\n"
            f"대응:\n"
            f"• 잠시 후 자동 재시도\n"
            f"• 30분 후에도 같은 메시지 오면 Claude한테 점검 요청\n"
            f"\n"
            f"(오늘 날짜: {today})"
        )
    try:
        from telegram_client import send_message
        send_message(msg, channel="ops")
        alert_state[incident_key] = _now_kst().isoformat()
        alert_state["staleness_sent"] = True
        _save_alert_state(alert_state)
    except Exception as e:
        print(f"[sheet_staleness] ops 알림 실패: {e}", flush=True)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env", override=True)
    from sheets_sync import _open_sheet
    ss = _open_sheet()
    state = check_pipeline_freshness(ss)
    print(f"pipeline freshness: {state}")
    alert_if_not_fresh(state)
