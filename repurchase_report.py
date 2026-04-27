"""매일 09:00 재구매 분석 리포트.

1. 시트 분석 탭에서 raw 숫자 추출 (ground_truth JSON)
2. 파이썬이 모든 수치 계산 (MoM %, 추세 등)
3. Claude API는 "해석"만 담당 (숫자는 JSON에 있는 것만 사용)
4. 검증 훅 통과할 때까지 최대 3회 재분석
5. 실패 시 raw 숫자만 텔레그램 발송

.env 필요 값:
- GOOGLE_SA_KEY_PATH, REPURCHASE_SHEET_ID, ANTHROPIC_API_KEY
- TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (기존)
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

from sheets_sync import _open_sheet
from telegram_client import send_message

KST = timezone(timedelta(hours=9))
ENV_PATH = Path(__file__).parent / ".env"

ANALYSIS_LOG_DIR = Path(__file__).parent / "logs"
ANALYSIS_LOG_DIR.mkdir(exist_ok=True)


def _log(msg: str):
    print(f"[{datetime.now(KST).strftime('%H:%M:%S')}] {msg}", flush=True)


# ============================================================
# 시트 분류 (탭 이름 + 헤더로 식별)
# ============================================================

def _classify_tabs(spreadsheet) -> dict:
    """모든 탭을 순회하며 용도별로 분류."""
    classified: dict = {
        "cafe24_monthly": None,       # 카페24 월별 재구매
        "ss_monthly": None,           # 스마트스토어 월별 재구매
        "integrated_monthly": None,   # 통합 월별 재구매
        "cafe24_stage": None,         # 카페24 단계별 전환율 (1→2, 2→3, 3→4)
        "ss_stage": None,
        "integrated_stage": None,
        "cafe24_cohort_stage": None,  # 카페24 코호트별 1→2, 2→3
        "ss_cohort_stage": None,
        "integrated_cohort_stage": None,
        "mn_retention": None,         # M+N 리텐션
        "ltv": None,                  # 코호트 매출 + LTV
        "interval_stats": None,       # 재구매 간격 P50/P90
        "interval_dist": None,        # 재구매 간격 분포
        "visit_count_cafe24": None,   # 구매횟수 분포
        "visit_count_ss": None,
        "visit_count_integrated": None,
    }

    for ws in spreadsheet.worksheets():
        title = ws.title
        try:
            header = ws.row_values(1)
        except Exception:
            continue
        if not header:
            continue
        hdr_str = "|".join(header)
        title_lower = title.replace(" ", "").replace("_", "")

        # 헤더 패턴 매칭
        is_monthly_like = hdr_str.startswith("기간|재구매자수|재구매건수")
        is_stage_flat = "단계별 전환율" in hdr_str and "해석" in hdr_str
        is_cohort_stage = hdr_str.startswith("코호트월|첫구매자수|1→2 전환수")
        is_mn = "M+1" in hdr_str and "M+12" in hdr_str
        is_ltv = "1인당LTV" in hdr_str or "첫구매AOV" in hdr_str
        is_interval_stat = header[:3] == ["지표", "값", "의미"]
        is_interval_dist = header[:3] == ["구간", "건수", "비율"]
        is_visit_count = header[:3] == ["구분", "고객수", "비율"]

        # 플랫폼 판별 (title에서)
        is_cafe24 = "카페24" in title or "cafe24" in title_lower.lower()
        is_ss = "스마트스토어" in title or "smartstore" in title_lower.lower()
        is_integrated = "통합" in title or "integrated" in title_lower.lower()

        # 월별 (기간이 YYYY-MM 형식) vs 일/주별 — 첫 데이터 행 확인
        if is_monthly_like:
            # 첫 데이터 행의 기간 값 확인
            try:
                first_data = ws.get("A2")
                first_val = first_data[0][0] if first_data and first_data[0] else ""
            except Exception:
                first_val = ""
            # "2024-11" (월) vs "2024-11-04" (일) vs "2024-11-04(주)" (주)
            is_month = bool(re.match(r"^\d{4}-\d{2}$", first_val.strip()))
            if is_month:
                if is_cafe24:
                    classified["cafe24_monthly"] = ws
                elif is_ss:
                    classified["ss_monthly"] = ws
                elif is_integrated:
                    classified["integrated_monthly"] = ws
            continue

        if is_stage_flat:
            if is_cafe24:
                classified["cafe24_stage"] = ws
            elif is_ss:
                classified["ss_stage"] = ws
            elif is_integrated:
                classified["integrated_stage"] = ws
            continue

        if is_cohort_stage:
            if is_cafe24:
                classified["cafe24_cohort_stage"] = ws
            elif is_ss:
                classified["ss_cohort_stage"] = ws
            elif is_integrated:
                classified["integrated_cohort_stage"] = ws
            continue

        if is_mn:
            classified["mn_retention"] = ws
            continue

        if is_ltv:
            classified["ltv"] = ws
            continue

        if is_interval_stat:
            classified["interval_stats"] = ws
            continue

        if is_interval_dist:
            classified["interval_dist"] = ws
            continue

        if is_visit_count:
            if is_cafe24:
                classified["visit_count_cafe24"] = ws
            elif is_ss:
                classified["visit_count_ss"] = ws
            elif is_integrated:
                classified["visit_count_integrated"] = ws
            continue

    return classified


# ============================================================
# 숫자 파싱 헬퍼
# ============================================================

def _to_int(v) -> int | None:
    if v is None or v == "":
        return None
    s = str(v).replace(",", "").replace("₩", "").replace(" ", "").strip()
    if not s or s in ("-", "─"):
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _to_pct(v) -> float | None:
    """'16.7%' → 16.7 (float)."""
    if v is None or v == "":
        return None
    s = str(v).replace("%", "").replace(",", "").strip()
    if not s or s in ("-", "─"):
        return None
    try:
        return round(float(s), 2)
    except ValueError:
        return None


# ============================================================
# Ground truth 추출
# ============================================================

def _extract_monthly(ws) -> list[dict]:
    """월별 재구매 탭 → 최근 13개월."""
    if not ws:
        return []
    rows = ws.get_all_values()
    out = []
    for r in rows[1:]:
        if not r or not r[0] or not re.match(r"^\d{4}-\d{2}$", r[0].strip()):
            continue
        out.append({
            "월": r[0].strip(),
            "재구매자수": _to_int(r[1]) if len(r) > 1 else 0,
            "재구매건수": _to_int(r[2]) if len(r) > 2 else 0,
            "재구매매출": _to_int(r[3]) if len(r) > 3 else 0,
            "AOV": _to_int(r[4]) if len(r) > 4 else 0,
            "재구매율": _to_pct(r[6]) if len(r) > 6 else 0,
            "신규구매자수": _to_int(r[7]) if len(r) > 7 else 0,
            "신규매출": _to_int(r[8]) if len(r) > 8 else 0,
        })
    return out[-13:]  # 최근 13개월


def _extract_stage_flat(ws) -> list[dict]:
    """단계별 전환율 (1→2, 2→3, 3→4)."""
    if not ws:
        return []
    rows = ws.get_all_values()
    out = []
    for r in rows[1:]:
        if not r or not r[0] or "→" not in r[0]:
            continue
        out.append({
            "단계": r[0].strip(),
            "기준고객수": _to_int(r[1]) if len(r) > 1 else 0,
            "전환고객수": _to_int(r[2]) if len(r) > 2 else 0,
            "전환율": _to_pct(r[3]) if len(r) > 3 else 0,
            "평균소요일": _to_int(r[4]) if len(r) > 4 else 0,
            "중앙값소요일": _to_int(r[5]) if len(r) > 5 else 0,
            "해석": r[6].strip() if len(r) > 6 else "",
        })
    return out


def _extract_cohort_stage(ws) -> list[dict]:
    """코호트별 1→2, 2→3 전환율 (월별 추세)."""
    if not ws:
        return []
    rows = ws.get_all_values()
    out = []
    for r in rows[1:]:
        if not r or not r[0] or not re.match(r"^\d{4}-\d{2}$", r[0].strip()):
            continue
        out.append({
            "코호트월": r[0].strip(),
            "첫구매자수": _to_int(r[1]) if len(r) > 1 else 0,
            "1→2_전환수": _to_int(r[2]) if len(r) > 2 else 0,
            "1→2_전환율": _to_pct(r[3]) if len(r) > 3 else 0,
            "1→2_평균소요일": _to_int(r[4]) if len(r) > 4 else 0,
            "2→3_전환수": _to_int(r[5]) if len(r) > 5 else 0,
            "2→3_전환율": _to_pct(r[6]) if len(r) > 6 else 0,
        })
    return out


def _extract_mn(ws) -> list[dict]:
    if not ws:
        return []
    rows = ws.get_all_values()
    out = []
    for r in rows[1:]:
        if not r or not r[0] or not re.match(r"^\d{4}-\d{2}$", r[0].strip()):
            continue
        out.append({
            "코호트월": r[0].strip(),
            "첫구매자수": _to_int(r[1]) if len(r) > 1 else 0,
            "M+1": _to_pct(r[2]) if len(r) > 2 else None,
            "M+2": _to_pct(r[3]) if len(r) > 3 else None,
            "M+3": _to_pct(r[4]) if len(r) > 4 else None,
            "M+6": _to_pct(r[7]) if len(r) > 7 else None,
        })
    return out


def _extract_interval_stats(ws) -> dict:
    if not ws:
        return {}
    rows = ws.get_all_values()
    out = {}
    for r in rows[1:]:
        if len(r) < 2 or not r[0]:
            continue
        out[r[0].strip()] = r[1].strip()
    return out


def build_ground_truth(spreadsheet) -> dict:
    _log("시트 탭 분류 중...")
    tabs = _classify_tabs(spreadsheet)
    missing = [k for k, v in tabs.items() if v is None]
    _log(f"  분류 결과: {len(tabs)-len(missing)}/{len(tabs)}개 식별, 누락: {missing}")

    now = datetime.now(KST)
    current_month = now.strftime("%Y-%m")
    # 직전 월
    prev_month_dt = (now.replace(day=1) - timedelta(days=1))
    prev_month = prev_month_dt.strftime("%Y-%m")

    # 월별 매출 (통합 + 플랫폼별)
    integrated_monthly = _extract_monthly(tabs.get("integrated_monthly"))
    cafe24_monthly = _extract_monthly(tabs.get("cafe24_monthly"))
    ss_monthly = _extract_monthly(tabs.get("ss_monthly"))

    def _find_month(rows, ym):
        for r in rows:
            if r["월"] == ym:
                return r
        return None

    integrated_cur = _find_month(integrated_monthly, current_month) or {}
    integrated_prev = _find_month(integrated_monthly, prev_month) or {}
    cafe24_cur = _find_month(cafe24_monthly, current_month) or {}
    cafe24_prev = _find_month(cafe24_monthly, prev_month) or {}
    ss_cur = _find_month(ss_monthly, current_month) or {}
    ss_prev = _find_month(ss_monthly, prev_month) or {}

    def _pct_change(cur, prev):
        if not prev or prev == 0:
            return None
        return round((cur - prev) / prev * 100, 1)

    # 단계별 전환율 (통합 기준)
    integrated_stage = _extract_stage_flat(tabs.get("integrated_stage"))
    cafe24_stage = _extract_stage_flat(tabs.get("cafe24_stage"))
    ss_stage = _extract_stage_flat(tabs.get("ss_stage"))

    # 코호트 추세 (통합): 최근 6개월 1→2, 2→3 전환율
    integrated_cohort = _extract_cohort_stage(tabs.get("integrated_cohort_stage"))
    # 최근 6개월 중 완결 코호트만 (최근 1~2개월은 아직 집계 중일 수 있음)
    cohort_recent = integrated_cohort[-8:]

    # 최근 3개월 vs 그 이전 3개월 평균
    def _avg_or_none(values):
        clean = [v for v in values if v is not None]
        return round(sum(clean) / len(clean), 2) if clean else None

    if len(integrated_cohort) >= 6:
        # 최근 1~2개월은 제외 (진행 중), 완결 코호트 중 최신 3개월 vs 그 이전 3개월
        completed = [c for c in integrated_cohort if c["1→2_전환율"] is not None and c["첫구매자수"] >= 5]
        last3 = completed[-3:] if len(completed) >= 3 else completed
        prev3 = completed[-6:-3] if len(completed) >= 6 else []
        cohort_trend_1to2 = {
            "최근3개월_평균": _avg_or_none([c["1→2_전환율"] for c in last3]),
            "이전3개월_평균": _avg_or_none([c["1→2_전환율"] for c in prev3]),
            "최근3개월_코호트": [c["코호트월"] for c in last3],
            "이전3개월_코호트": [c["코호트월"] for c in prev3],
        }
        cohort_trend_2to3 = {
            "최근3개월_평균": _avg_or_none([c["2→3_전환율"] for c in last3]),
            "이전3개월_평균": _avg_or_none([c["2→3_전환율"] for c in prev3]),
        }
    else:
        cohort_trend_1to2 = {"최근3개월_평균": None, "이전3개월_평균": None}
        cohort_trend_2to3 = {"최근3개월_평균": None, "이전3개월_평균": None}

    # 추세 변화 (%p)
    def _delta(t):
        a = t.get("최근3개월_평균")
        b = t.get("이전3개월_평균")
        if a is None or b is None:
            return None
        return round(a - b, 2)

    cohort_trend_1to2["변화_pp"] = _delta(cohort_trend_1to2)
    cohort_trend_2to3["변화_pp"] = _delta(cohort_trend_2to3)

    # M+N 리텐션 — 완결된 최신 코호트 (M+1 기준 6개월 이상 지난 것)
    mn = _extract_mn(tabs.get("mn_retention"))
    mn_completed = [m for m in mn if m.get("M+1") is not None]

    gt = {
        "리포트_날짜": now.strftime("%Y-%m-%d"),
        "당월": current_month,
        "전월": prev_month,
        "월별_재구매_매출": {
            "통합": {
                "당월": {
                    "매출": integrated_cur.get("재구매매출"),
                    "재구매자수": integrated_cur.get("재구매자수"),
                    "재구매건수": integrated_cur.get("재구매건수"),
                    "AOV": integrated_cur.get("AOV"),
                },
                "전월": {
                    "매출": integrated_prev.get("재구매매출"),
                    "재구매자수": integrated_prev.get("재구매자수"),
                    "재구매건수": integrated_prev.get("재구매건수"),
                    "AOV": integrated_prev.get("AOV"),
                },
                "MoM_변화_금액": (
                    (integrated_cur.get("재구매매출") or 0) - (integrated_prev.get("재구매매출") or 0)
                ),
                "MoM_변화_pct": _pct_change(
                    integrated_cur.get("재구매매출") or 0,
                    integrated_prev.get("재구매매출") or 0,
                ),
            },
            "카페24": {
                "당월_매출": cafe24_cur.get("재구매매출"),
                "전월_매출": cafe24_prev.get("재구매매출"),
                "MoM_pct": _pct_change(
                    cafe24_cur.get("재구매매출") or 0,
                    cafe24_prev.get("재구매매출") or 0,
                ),
            },
            "스마트스토어": {
                "당월_매출": ss_cur.get("재구매매출"),
                "전월_매출": ss_prev.get("재구매매출"),
                "MoM_pct": _pct_change(
                    ss_cur.get("재구매매출") or 0,
                    ss_prev.get("재구매매출") or 0,
                ),
            },
        },
        "단계별_전환율_현재": {
            "통합": integrated_stage,
            "카페24": cafe24_stage,
            "스마트스토어": ss_stage,
        },
        "코호트_추세_통합": {
            "최근_6개월": cohort_recent,
            "1→2_추세": cohort_trend_1to2,
            "2→3_추세": cohort_trend_2to3,
        },
        "M+N_리텐션_통합": mn_completed[-6:] if mn_completed else [],
        "재구매_간격": _extract_interval_stats(tabs.get("interval_stats")),
        "업계_벤치마크": {
            "M+1_리텐션_평균": "20~30%",
            "D2C_식품_재구매율": "30~35%",
        },
    }
    return gt


# ============================================================
# 마트 탭 작성 (Looker Studio 데이터 소스)
# ============================================================

MART_MONTHLY_HEADER = [
    "연월", "채널", "신규구매자", "재구매자", "재구매율", "재구매AOV", "재구매매출", "갱신시각",
]
MART_COHORT_HEADER = [
    "코호트월", "채널", "첫구매자수", "M+1", "M+2", "M+3", "M+6", "갱신시각",
]
MART_STAGE_HEADER = [
    "채널", "단계", "기준고객수", "전환고객수", "전환율", "갱신시각",
]
MART_SUMMARY_HEADER = [
    "지표", "값", "벤치마크", "상태", "갱신시각",
]


def _ensure_mart_tab(spreadsheet, name: str, header: list[str]):
    """탭이 없으면 만들고 헤더를 보장. 있으면 그대로 반환."""
    try:
        ws = spreadsheet.worksheet(name)
    except Exception:
        ws = spreadsheet.add_worksheet(title=name, rows=200, cols=max(10, len(header)))
        ws.update("A1", [header])
        return ws

    cur = ws.row_values(1)
    if cur != header:
        ws.update("A1", [header])
    return ws


def _summary_status(value, good: float, warn: float, higher_is_better: bool = True) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    if higher_is_better:
        if v >= good:
            return "✅"
        if v >= warn:
            return "⚠️"
        return "🔴"
    else:
        if v <= good:
            return "✅"
        if v <= warn:
            return "⚠️"
        return "🔴"


def write_marts(spreadsheet, gt: dict, tabs: dict):
    """마트 4종(월별/코호트/단계/요약)을 long-format으로 덮어쓴다.

    - 시트=raw 저장소, Looker Studio=시각화 원칙
    - 기존 19개 분석 탭은 건드리지 않음 (롤백·검증용 보존)
    """
    now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

    # ---------- mart_monthly ----------
    monthly_rows: list[list] = []
    for ch_key, ch_label in [
        ("integrated_monthly", "통합"),
        ("cafe24_monthly", "카페24"),
        ("ss_monthly", "스마트스토어"),
    ]:
        for r in _extract_monthly(tabs.get(ch_key)):
            monthly_rows.append([
                r["월"], ch_label,
                r.get("신규구매자수") or 0,
                r.get("재구매자수") or 0,
                r.get("재구매율") or 0,
                r.get("AOV") or 0,
                r.get("재구매매출") or 0,
                now_str,
            ])

    ws = _ensure_mart_tab(spreadsheet, "mart_monthly", MART_MONTHLY_HEADER)
    ws.clear()
    ws.update("A1", [MART_MONTHLY_HEADER] + monthly_rows)
    _log(f"  mart_monthly: {len(monthly_rows)}행")

    # ---------- mart_cohort ----------
    cohort_rows: list[list] = []
    # mn_retention 탭은 통합 1개만 존재 (코드 구조상)
    for r in _extract_mn(tabs.get("mn_retention")):
        cohort_rows.append([
            r["코호트월"], "통합",
            r.get("첫구매자수") or 0,
            r.get("M+1"), r.get("M+2"), r.get("M+3"), r.get("M+6"),
            now_str,
        ])

    ws = _ensure_mart_tab(spreadsheet, "mart_cohort", MART_COHORT_HEADER)
    ws.clear()
    ws.update("A1", [MART_COHORT_HEADER] + cohort_rows)
    _log(f"  mart_cohort: {len(cohort_rows)}행")

    # ---------- mart_stage ----------
    stage_rows: list[list] = []
    for ch_key, ch_label in [
        ("integrated_stage", "통합"),
        ("cafe24_stage", "카페24"),
        ("ss_stage", "스마트스토어"),
    ]:
        for r in _extract_stage_flat(tabs.get(ch_key)):
            stage_rows.append([
                ch_label, r.get("단계", ""),
                r.get("기준고객수") or 0,
                r.get("전환고객수") or 0,
                r.get("전환율") or 0,
                now_str,
            ])

    ws = _ensure_mart_tab(spreadsheet, "mart_stage", MART_STAGE_HEADER)
    ws.clear()
    ws.update("A1", [MART_STAGE_HEADER] + stage_rows)
    _log(f"  mart_stage: {len(stage_rows)}행")

    # ---------- mart_summary ----------
    inm = gt.get("월별_재구매_매출", {}).get("통합", {})
    stage = gt.get("단계별_전환율_현재", {}).get("통합", [])
    s1_2 = next((s for s in stage if s.get("단계") == "1→2"), {})
    s2_3 = next((s for s in stage if s.get("단계") == "2→3"), {})
    mn_recent = (gt.get("M+N_리텐션_통합") or [])
    m1_recent = mn_recent[-1].get("M+1") if mn_recent else None
    interval = gt.get("재구매_간격", {}) or {}

    summary_rows = [
        ["당월 재구매 매출", inm.get("당월", {}).get("매출"), "—", "—", now_str],
        ["전월 재구매 매출", inm.get("전월", {}).get("매출"), "—", "—", now_str],
        ["MoM 변화율(%)", inm.get("MoM_변화_pct"), "0% 이상", _summary_status(inm.get("MoM_변화_pct"), 0, -10, True), now_str],
        ["1→2 전환율(%)", s1_2.get("전환율"), "30%+ ✅ / 23~30% ⚠️", _summary_status(s1_2.get("전환율"), 30, 23, True), now_str],
        ["2→3 전환율(%)", s2_3.get("전환율"), "40%+ ✅", _summary_status(s2_3.get("전환율"), 40, 30, True), now_str],
        ["M+1 리텐션 최신 코호트(%)", m1_recent, "20~30% ✅", _summary_status(m1_recent, 20, 14, True), now_str],
        ["재구매 간격 P50(일)", interval.get("P50") or interval.get("중앙값") or interval.get("50%"), "15일 부근", "—", now_str],
        ["재구매 간격 P90(일)", interval.get("P90") or interval.get("90%"), "31~62일", "—", now_str],
    ]

    ws = _ensure_mart_tab(spreadsheet, "mart_summary", MART_SUMMARY_HEADER)
    ws.clear()
    ws.update("A1", [MART_SUMMARY_HEADER] + summary_rows)
    _log(f"  mart_summary: {len(summary_rows)}행")


# ============================================================
# Claude 분석
# ============================================================

SYSTEM_PROMPT = """당신은 10년차 D2C 이커머스 경영 전문가다. HeavyLover(냉동 도시락 D2C, 20~30대 운동 직장인 남성 타겟) 재구매 KPI를 매일 진단한다.

**핵심 원칙 (절대 위반 금지):**

1. **숫자는 입력 JSON에 있는 것만 사용한다.** 새로운 숫자를 창작하거나 추정하지 않는다. JSON에 없는 값을 인용해야 할 경우 "데이터 없음"이라고 명시한다.

2. **추측·가설 금지.** 원인을 단정하지 않는다. "~때문으로 보입니다", "~일 수 있습니다", "아마도", "추정하건대", "~로 보입니다" 같은 표현 사용 금지. 관찰된 사실과 그 의미만 서술한다.

3. **향상/악화 판정은 최근 3개월 추세선 vs 그 이전 3개월 기준으로만 내린다.** 단일 월 비교는 노이즈 가능성을 언급한다.

4. **경영 관점.** 재구매 1%p 변화가 CAC 회수 속도와 LTV에 미치는 영향을 염두에 두되, 구체적 금액 계산은 JSON에 없으면 하지 않는다.

5. **포맷.** 불릿/헤더 남발 금지. 문장 중심. 전체 길이 800자 이내. 이모지는 ⚠️ ✅ 📊만 최소한으로.

**리포트 필수 섹션:**

1. **매출 요약**: 당월 재구매 매출 vs 전월 (금액 + % 변화). 통합 기준, 카페24/SS 분해.
2. **1→2 전환 진단**: 현재 전환율 + 최근 3개월 추세 (향상/악화/정체 중 하나). JSON의 "변화_pp" 값 사용.
3. **2→3 전환 진단**: 동일 방식.
4. **핵심 시사점**: 오늘 승현 대표가 알아야 할 한 줄. 조치가 필요한 지점이 있다면 구체 지표로 지정.
5. **추가 확인 권고 (선택)**: 더 볼 지표가 있다면 언급.

입력 JSON의 키 구조:
- 월별_재구매_매출.통합.{당월, 전월, MoM_변화_금액, MoM_변화_pct}
- 단계별_전환율_현재.통합: [{단계, 기준고객수, 전환고객수, 전환율, 해석}]
- 코호트_추세_통합.{1→2_추세.최근3개월_평균, 이전3개월_평균, 변화_pp / 2→3_추세.*}
- M+N_리텐션_통합: 최근 6개 코호트
"""

USER_PROMPT_TEMPLATE = """다음은 오늘의 ground truth JSON이다. 이 JSON에 있는 숫자만 사용해 리포트를 작성하라.

```json
{gt_json}
```

{feedback_block}

위 원칙에 따라 리포트를 작성하라."""


def call_claude(gt: dict, feedback: str = "") -> str:
    load_dotenv(ENV_PATH, override=True)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 미설정")

    client = Anthropic(api_key=api_key)
    feedback_block = f"\n**이전 시도 피드백 (반드시 수정할 것):**\n{feedback}\n" if feedback else ""

    gt_json = json.dumps(gt, ensure_ascii=False, indent=2, default=str)
    user = USER_PROMPT_TEMPLATE.format(gt_json=gt_json, feedback_block=feedback_block)

    resp = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text.strip()


# ============================================================
# 검증 훅
# ============================================================

BANNED_PHRASES = [
    "로 보입니다", "일 수 있습니다", "로 보여집니다", "것으로 보이",
    "아마도", "추정하건대", "추측", "짐작",
    "것으로 보여", "로 사료됩니다", "가능성이 높", "가능성이 있",
    "일 것으로", "일 것 같", "라고 판단됩니다", "듯 합니다",
]


def _collect_numbers_from_gt(gt: dict) -> set[str]:
    """GT JSON에 포함된 모든 숫자를 문자열 집합으로 수집 (검증용)."""
    nums: set[str] = set()

    def _walk(x):
        if isinstance(x, dict):
            for v in x.values():
                _walk(v)
        elif isinstance(x, list):
            for v in x:
                _walk(v)
        elif isinstance(x, (int, float)):
            if x == 0:
                nums.add("0")
                return
            # 여러 포맷 허용
            nums.add(str(x))
            nums.add(str(int(x)) if x == int(x) else str(x))
            # 콤마 포맷
            try:
                nums.add(f"{int(x):,}")
            except (ValueError, OverflowError):
                pass
            # float → round 1 / round 2
            if isinstance(x, float):
                nums.add(f"{x:.1f}")
                nums.add(f"{x:.2f}")
        elif isinstance(x, str):
            # 숫자 포함 문자열도 체크 (예: "1,247건" → "1247")
            for m in re.findall(r"\d[\d,\.]*", x):
                clean = m.replace(",", "")
                nums.add(clean)
                nums.add(m)

    _walk(gt)
    return nums


def validate(text: str, gt: dict) -> list[str]:
    issues: list[str] = []

    # 1. 금지 표현
    for phrase in BANNED_PHRASES:
        if phrase in text:
            issues.append(f"금지 표현 감지: '{phrase}'")

    # 2. 필수 섹션 키워드
    required_keywords = ["당월", "전월", "1→2", "2→3"]
    for kw in required_keywords:
        if kw not in text:
            issues.append(f"필수 섹션 누락: '{kw}' 언급 없음")

    # 3. 숫자 검증 (원/건 단위 수치만 체크, 퍼센트 포함)
    gt_nums = _collect_numbers_from_gt(gt)

    # 리포트에서 숫자 후보 추출: 3자리 이상 또는 소수점 포함 또는 %
    candidates = re.findall(r"\d{1,3}(?:,\d{3})+|\d+\.\d+%?|\d+%", text)
    unknowns = []
    for c in candidates:
        c_clean = c.replace(",", "").replace("%", "")
        if c in gt_nums or c_clean in gt_nums:
            continue
        # 0/1/2 같은 작은 숫자는 skip
        try:
            if float(c_clean) < 10:
                continue
        except ValueError:
            continue
        unknowns.append(c)

    if unknowns:
        # 상위 3개만 보고 (너무 많으면 프롬프트 폭증)
        issues.append(f"JSON에 없는 숫자 감지: {unknowns[:5]}. 입력 JSON에 있는 숫자만 사용할 것.")

    return issues


def generate_report_with_retry(gt: dict, max_retries: int = 3) -> tuple[str | None, list[str]]:
    feedback = ""
    last_issues: list[str] = []
    for attempt in range(1, max_retries + 1):
        _log(f"Claude 분석 시도 #{attempt}")
        try:
            report = call_claude(gt, feedback)
        except Exception as e:
            _log(f"  Claude API 오류: {e}")
            last_issues = [f"Claude API 오류: {e}"]
            continue

        issues = validate(report, gt)
        if not issues:
            _log(f"  ✅ 시도 #{attempt} 통과")
            return report, []

        _log(f"  ❌ 시도 #{attempt} 검증 실패 ({len(issues)}건):")
        for i in issues:
            _log(f"     - {i}")
        last_issues = issues
        feedback = "\n".join(f"- {i}" for i in issues)

    return None, last_issues


# ============================================================
# 메인
# ============================================================

def _format_fallback(gt: dict, issues: list[str]) -> str:
    inm = gt.get("월별_재구매_매출", {}).get("통합", {})
    stage = gt.get("단계별_전환율_현재", {}).get("통합", [])
    s1_2 = next((s for s in stage if s.get("단계") == "1→2"), {})
    s2_3 = next((s for s in stage if s.get("단계") == "2→3"), {})

    lines = [
        "⚠️ 재구매 리포트 자동 분석 실패 — 원시 숫자만 전달",
        "",
        f"당월({gt.get('당월')}) 재구매 매출: {inm.get('당월', {}).get('매출')}원",
        f"전월({gt.get('전월')}) 재구매 매출: {inm.get('전월', {}).get('매출')}원",
        f"MoM 변화: {inm.get('MoM_변화_pct')}%",
        "",
        f"1→2 전환율: {s1_2.get('전환율')}% ({s1_2.get('해석')})",
        f"2→3 전환율: {s2_3.get('전환율')}% ({s2_3.get('해석')})",
        "",
        f"검증 실패 사유:",
    ]
    for i in issues[:5]:
        lines.append(f"- {i}")
    return "\n".join(lines)


def run() -> dict:
    _log("=== 재구매 리포트 시작 ===")
    ss = _open_sheet()
    gt = build_ground_truth(ss)

    # 마트 4종 갱신 (Looker Studio 데이터 소스). 실패해도 리포트는 계속 진행.
    try:
        _log("마트 탭 갱신 중...")
        write_marts(ss, gt, _classify_tabs(ss))
        _log("✅ 마트 탭 갱신 완료")
    except Exception as e:
        _log(f"⚠️ 마트 탭 갱신 실패 (리포트는 계속): {e}")

    # GT를 로그 저장 (감사 목적)
    date_str = datetime.now(KST).strftime("%Y-%m-%d")
    gt_log = ANALYSIS_LOG_DIR / f"gt_{date_str}.json"
    gt_log.write_text(json.dumps(gt, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _log(f"ground_truth 저장: {gt_log}")

    report, issues = generate_report_with_retry(gt)

    if report:
        header = f"📊 재구매 리포트 {date_str}\n\n"
        send_message(header + report)
        _log("✅ 리포트 텔레그램 발송 완료")
        # 성공 로그
        (ANALYSIS_LOG_DIR / f"report_{date_str}.md").write_text(
            header + report, encoding="utf-8"
        )
        return {"status": "success", "issues": []}

    fallback = _format_fallback(gt, issues)
    send_message(fallback)
    _log("⚠️ 분석 실패, fallback 발송")
    return {"status": "failed", "issues": issues}


if __name__ == "__main__":
    try:
        r = run()
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        sys.exit(0 if r["status"] == "success" else 1)
    except Exception as e:
        _log(f"치명적 오류: {e}")
        try:
            send_message(f"🚨 재구매 리포트 치명적 오류: {e}")
        except Exception:
            pass
        sys.exit(2)
