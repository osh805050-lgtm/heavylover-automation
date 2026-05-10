"""송장 자동 등록 모듈

텔레그램 /tracking 명령 → 바탕화면 더다 엑셀 자동 감지 → 카페24/SS 송장 등록

실행 주기: Vultr cron 5분마다 /tracking 명령 폴링
"""

import csv
import glob
import io
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd
import requests
from dotenv import load_dotenv

# Windows cp949 콘솔 대응
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
import cafe24_client
import coupang_client
import naver_client
import telegram_client

# 더다 송장 엑셀 OneDrive 경로 (rclone remote 기준) — 바탕화면
ONEDRIVE_TRACKING_DIR = os.getenv(
    "ONEDRIVE_TRACKING_DIR",
    "heavylover_onedrive:바탕 화면/",
)
# 서버 로컬 다운로드 위치
LOCAL_TRACKING_DIR = Path(os.getenv("LOCAL_TRACKING_DIR", "/tmp/tracking_excel"))

ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(ENV_PATH, override=True)

# PlusCL API 설정
PLUSCL_BASE = "https://service.pluscl.com"

# 택배사 코드 매핑 - 헤비로버는 로젠택배 전용
# 이 몰(musclecipe001)에서 로젠택배의 카페24 코드는 0004 (테스트 확인됨)
# PlusCL 택배사 코드는 실제 응답에서 확인 필요 (예상: D005)

# 카페24 shipping_company_code (이 몰 기준)
CAFE24_LOGEN = "0004"

# 네이버 deliveryCompanyCode
NAVER_LOGEN = "KGB"  # 로젠택배 (네이버 시스템에선 KGB 코드)

# 결과 CSV 저장 디렉터리 (run 단위 영속 로그)
TRACKING_RESULTS_DIR = Path(__file__).parent / "data" / "tracking"


@dataclass
class TrackingResult:
    """송장 등록 1건 결과 (CSV 영속화용)"""
    channel: str            # cafe24 | naver | coupang
    order_id: str
    item_code: str          # cafe24=order_item_code, naver=productOrderId, coupang=vendorItemId
    tracking_no: str
    status: str             # sent | failed | skipped | conflict_existing
    api_response_code: str  # HTTP code 또는 카테고리 (예: "exception", "rate_limit")
    api_response_body: str  # 응답 본문 truncate (200자)


class TrackingParseError(ValueError):
    """엑셀 파싱 단계에서 명확히 reject해야 할 입력 — 운영자 액션 필요"""
    pass


# 송장번호: 보통 10~16자리 숫자. 한국 택배 표준 (안전하게 6~20자리 허용)
_VALID_TRACKING_RE = re.compile(r"^\d{6,20}$")
# SS productOrderId: 16자리 숫자, "20"으로 시작 (연도 prefix)
_VALID_SS_ORDER_RE = re.compile(r"^20\d{14}$")
# 카페24 주문번호: YYYYMMDD-NNNNNNN 또는 비슷한 하이픈 포함 형식
_VALID_CAFE24_ORDER_RE = re.compile(r"^\d{6,10}-\d{4,10}$")
# 쿠팡 orderId: 13자리 정도 숫자 (안전하게 8~15자리 허용)
_VALID_COUPANG_ORDER_RE = re.compile(r"^\d{8,15}$")

def find_today_excel():
    """OneDrive 바탕화면에서 오늘 날짜 송장 엑셀만 다운로드 후 경로 반환.

    오늘 날짜 파일이 없으면 None 반환 (이전 날짜 fallback 없음 — 잘못된 송장번호 등록 차단).
    """
    import subprocess
    LOCAL_TRACKING_DIR.mkdir(parents=True, exist_ok=True)

    # rclone으로 최신 파일 동기화
    r = subprocess.run(
        ["rclone", "copy", ONEDRIVE_TRACKING_DIR, str(LOCAL_TRACKING_DIR),
         "--include", "일반_*.xls*", "--max-depth", "1", "--transfers=4"],
        capture_output=True, text=True, timeout=120,
    )
    if r.returncode != 0:
        print(f"rclone 오류: {r.stderr[:200]}")

    # 오늘 날짜 파일만 찾음 — 없으면 None (이전 날짜 fallback 제거)
    today = datetime.now().strftime("%Y%m%d")
    today_files = sorted(LOCAL_TRACKING_DIR.glob(f"일반_*{today}*.xls*"))
    return today_files[-1] if today_files else None


def read_tracking_excel(path: Path):
    """더다 송장 엑셀 읽기. 카페24/SS/쿠팡 분류 + 전화번호 기준 구매자 수 반환.

    분류 기준:
      - 카페24: 주문번호에 하이픈 포함 (YYYYMMDD-NNNNNNN)
      - 스마트스토어: 16자리 숫자, "20"으로 시작
      - 쿠팡: 그 외 (13자리 숫자 등)

    Returns:
        dict: {
            "cafe24": [(order_id, item_code, tracking_no)],
            "naver": [(product_order_id, tracking_no)],
            "coupang": [(order_id, tracking_no)],
            "cafe24_buyers": int,
            "naver_buyers": int,
            "coupang_buyers": int,
            "filename": str,
        }
    """
    # 핵심: 송장번호·주문번호는 반드시 string dtype으로 읽어야 함
    # int(float(s)) 변환 시 16자리 SS productOrderId가 부동소수점 오차로 마지막 자리 손실
    # → 엉뚱한 주문에 송장 등록되는 high-severity 결함
    suffix = path.suffix.lower()
    if suffix == ".xls":
        import xlrd
        wb = xlrd.open_workbook(str(path), encoding_override="cp949")
        ws = wb.sheet_by_index(0)
        headers = ws.row_values(0)
        rows = []
        for i in range(1, ws.nrows):
            row_vals = []
            for col_idx, val in enumerate(ws.row_values(i)):
                ctype = ws.cell_type(i, col_idx)
                # xlrd cell types: 0=empty, 1=text, 2=number, 3=date, 4=bool, 5=error
                # H-2 fix: 숫자형 셀(ctype=2)을 string으로 변환할 때 16자리 ID 정밀도 손실 방지.
                # float >= 1e15 이면 이미 float53 정밀도 손실 가능 → repr로 보존해
                # 이후 _normalize_id 에서 TrackingParseError로 reject하게 한다.
                # (str(int(1.2345678901234e+15)) 는 마지막 자리가 틀린 값을 무음으로 통과시킴)
                if ctype == 2 and isinstance(val, float):
                    if val.is_integer() and abs(val) < 1e15:
                        row_vals.append(str(int(val)))
                    else:
                        # float >= 1e15 또는 비정수 → repr 보존, _normalize_id에서 reject
                        row_vals.append(repr(val))
                else:
                    row_vals.append(val)
            rows.append(row_vals)
        df = pd.DataFrame(rows, columns=headers)
    else:
        # openpyxl 엔진은 dtype=str로 읽어야 16자리 정수가 1.234E+15로 손실되지 않음
        df = pd.read_excel(path, dtype=str)

    def _normalize_id(val, *, field_name: str, row_idx: int) -> str:
        """주문번호/송장번호 셀을 string으로 안전 변환.

        - 부동소수점·과학적 표기는 reject (이미 정밀도 손실됐을 가능성)
        - 공백/None/'nan'은 빈 문자열 반환 (호출 측에서 skip)
        - 숫자만 남기되 자릿수 검증은 호출 측에서 채널별로 수행
        """
        if val is None:
            return ""
        if isinstance(val, float):
            if pd.isna(val):
                return ""
            # float 자체로 들어온 시점 = 이미 dtype=str 분기 실패한 상황
            # 정수 float은 자릿수 16 미만이면 복원 가능, 그 이상은 reject
            if val.is_integer() and abs(val) < 1e15:
                return str(int(val))
            raise TrackingParseError(
                f"행 {row_idx+2} '{field_name}' 컬럼이 부동소수점({val!r})으로 읽혔습니다. "
                f"엑셀 셀 서식을 '텍스트'로 변경 후 다시 업로드해주세요."
            )
        s = str(val).strip()
        if not s or s.lower() == "nan":
            return ""
        # 과학적 표기 (1.234E+15) — 정밀도 손실 의심, reject
        if re.search(r"[eE][+\-]?\d", s):
            raise TrackingParseError(
                f"행 {row_idx+2} '{field_name}' 컬럼에 과학적 표기('{s}') 값이 있습니다. "
                f"엑셀 셀 서식을 '텍스트'로 변경 후 다시 업로드해주세요."
            )
        # 끝의 .0 제거 (정수형 float이 string으로 들어온 경우)
        if re.fullmatch(r"\d+\.0+", s):
            s = s.split(".")[0]
        # 잔여 소수점 — 송장/주문번호는 정수이어야 함
        if "." in s:
            raise TrackingParseError(
                f"행 {row_idx+2} '{field_name}' 컬럼에 소수점 포함 값('{s}')이 있습니다. "
                f"엑셀 셀 서식을 '텍스트'로 변경 후 다시 업로드해주세요."
            )
        return s

    cafe24_rows = []
    naver_rows = []
    coupang_rows = []
    cafe24_phones = set()
    naver_phones = set()
    coupang_phones = set()

    for idx, row in df.iterrows():
        order_no = _normalize_id(row.get("주문번호", ""), field_name="주문번호", row_idx=idx)
        tracking = _normalize_id(row.get("송장번호", ""), field_name="송장번호", row_idx=idx)
        phone_raw = row.get("수취인 휴대전화") or row.get("수취인 전화") or ""
        phone = str(phone_raw).strip() if phone_raw is not None else ""

        if not order_no or not tracking:
            continue

        # 송장번호 형식 검증 (모든 채널 공통)
        if not _VALID_TRACKING_RE.match(tracking):
            raise TrackingParseError(
                f"행 {idx+2} 송장번호('{tracking}')가 숫자 6~20자리 형식을 벗어납니다."
            )

        # 카페24: YYYYMMDD-NNNNNNN 형식 (하이픈 포함)
        if "-" in order_no:
            if not _VALID_CAFE24_ORDER_RE.match(order_no):
                raise TrackingParseError(
                    f"행 {idx+2} 카페24 주문번호('{order_no}') 형식 이상."
                )
            item_code = ""
            raw_item = row.get("주문 상품코드", "")
            if raw_item is not None and not (isinstance(raw_item, float) and pd.isna(raw_item)):
                item_code = str(raw_item).strip()
            cafe24_rows.append((order_no, item_code, tracking))
            if phone:
                cafe24_phones.add(phone)
        elif _VALID_SS_ORDER_RE.match(order_no):
            # 스마트스토어: 16자리, "20"으로 시작
            naver_rows.append((order_no, tracking))
            if phone:
                naver_phones.add(phone)
        elif _VALID_COUPANG_ORDER_RE.match(order_no):
            # 쿠팡: 8~15자리 숫자
            coupang_rows.append((order_no, tracking))
            if phone:
                coupang_phones.add(phone)
        else:
            raise TrackingParseError(
                f"행 {idx+2} 주문번호('{order_no}')가 어느 채널 형식에도 맞지 않습니다."
            )

    return {
        "cafe24": cafe24_rows,
        "naver": naver_rows,
        "coupang": coupang_rows,
        "cafe24_buyers": len(cafe24_phones),
        "naver_buyers": len(naver_phones),
        "coupang_buyers": len(coupang_phones),
        "filename": path.name,
    }


def _dedup_by_order(
    items: List[tuple],
    *,
    channel: str,
    order_idx: int = 0,
    item_idx: Optional[int] = None,
    tracking_idx: int = -1,
) -> Tuple[dict, List[TrackingResult]]:
    """주문 단위 dedup. 같은 주문에 다른 송장번호가 있으면 reject.

    Returns:
        kept: dict[(channel, order_id, item_code)] = (order_id, item_code, tracking_no)
              item_code는 입력에 없거나 빈 경우 "" — 단일 패키지로 간주.
        conflicts: 같은 주문/아이템에 다른 송장번호가 있어 reject된 항목 (TrackingResult, status="skipped")
    """
    kept: dict = {}
    conflicts: List[TrackingResult] = []
    # 주문 단위 트래킹 번호 추적 (같은 주문 다중 행에 다른 송장이면 충돌)
    order_trackings: dict = {}

    for row in items:
        order_id = row[order_idx]
        tracking = row[tracking_idx]
        item_code = row[item_idx].strip() if item_idx is not None and row[item_idx] else ""

        # 같은 주문에 다른 송장번호가 들어오면 충돌 — 자동 등록 차단
        prev_trackings = order_trackings.setdefault(order_id, set())
        prev_trackings.add(tracking)
        if len(prev_trackings) > 1:
            conflicts.append(TrackingResult(
                channel=channel,
                order_id=order_id,
                item_code=item_code,
                tracking_no=tracking,
                status="skipped",
                api_response_code="conflict_multi_tracking",
                api_response_body=f"order has multiple trackings: {sorted(prev_trackings)}",
            ))
            continue

        # item-level 키: (channel, order_id, item_code)
        # item_code 비어있는 경우 order 단위 단일 패키지 — order_id만으로 키 구성.
        # H-1 fix: item_code 있을 때는 각 item마다 별도 키 → multi-item(2박스) 주문의
        # 모든 아이템이 kept에 남아 cafe24_orders_to_register 그룹핑에서 item_codes set에 모두 add됨.
        key = (channel, order_id, item_code)
        if key not in kept:
            kept[key] = (order_id, item_code, tracking)
        # 같은 (order, item) 중복 라인은 동일 송장이면 무시 (조용히)
    return kept, conflicts


def _write_run_csv(results: List[TrackingResult]) -> Optional[Path]:
    """run 단위 결과 CSV 영속화.

    경로: data/tracking/run_YYYYMMDD_HHMMSS.csv
    """
    if not results:
        return None
    TRACKING_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = TRACKING_RESULTS_DIR / f"run_{ts}.csv"
    fieldnames = [
        "channel", "order_id", "item_code", "tracking_no",
        "status", "api_response_code", "api_response_body",
    ]
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in results:
            w.writerow(asdict(r))
    return out_path


def _truncate_body(text, limit: int = 200) -> str:
    if text is None:
        return ""
    s = str(text).replace("\n", " ").replace("\r", " ")
    return s[:limit]


def run_from_excel():
    """엑셀 기반 송장 등록 — 발주 자동화(/tracking)에서 호출됨"""
    now = datetime.now()
    print(f"=== 엑셀 송장 등록 시작 ({now:%Y-%m-%d %H:%M:%S}) ===\n")

    # 1) 엑셀 파일 찾기 (오늘 날짜만 — 이전 날짜 fallback 없음)
    excel_path = find_today_excel()
    if not excel_path:
        today = datetime.now().strftime("%Y%m%d")
        telegram_client.send_message(
            f"⚠️ 오늘({today}) 송장 엑셀을 찾을 수 없습니다.\n"
            f"OneDrive 바탕화면에 '일반_{today}.xls' 파일을 올린 후\n"
            f"다음 11시 자동화에서 다시 시도해주세요.",
            channel="ops",
        )
        return

    print(f"  파일: {excel_path.name}")

    # 2) 엑셀 파싱 (string-dtype 강제, scientific notation reject)
    try:
        data = read_tracking_excel(excel_path)
    except TrackingParseError as e:
        # 운영자가 액션 가능한 명확한 메시지
        telegram_client.send_message(
            f"⚠️ 엑셀 파싱 실패 — 자동 등록 중단\n{e}",
            channel="ops",
        )
        return
    except Exception as e:
        telegram_client.send_message(f"⚠️ 엑셀 읽기 실패: {e}", channel="ops")
        return

    cafe24_items = data["cafe24"]
    naver_items = data["naver"]
    coupang_items = data["coupang"]
    total_buyers = data["cafe24_buyers"] + data["naver_buyers"] + data["coupang_buyers"]

    if not cafe24_items and not naver_items and not coupang_items:
        telegram_client.send_message("⚠️ 등록할 송장이 없습니다.", channel="ops")
        return

    # 3) 즉시 등록 시작 (재확인 단계 없음 — 이미 /tracking 받은 상태)
    telegram_client.send_message(
        f"📦 송장 등록 시작\n"
        f"파일: {data['filename']}\n"
        f"카페24 {data['cafe24_buyers']}명 + SS {data['naver_buyers']}명 + 쿠팡 {data['coupang_buyers']}명 = 총 {total_buyers}명",
        channel="ops",
    )

    # 4) 송장 등록
    print("[등록] 카페24 + 스마트스토어 송장 등록 중...")
    results: List[TrackingResult] = []
    cafe24_success, cafe24_fail = 0, []
    naver_success, naver_fail = 0, []

    # 카페24: (channel, order_id, item_code) 튜플 키로 dedup
    seen_cafe24, cafe24_conflicts = _dedup_by_order(
        cafe24_items, channel="cafe24",
        order_idx=0, item_idx=1, tracking_idx=2,
    )
    results.extend(cafe24_conflicts)
    for c in cafe24_conflicts:
        cafe24_fail.append(f"{c.order_id}: 송장번호 충돌 (수동 확인 필요)")

    # 카페24는 같은 order의 모든 item을 한 번에 등록 → order_id 단위로 묶음
    # H-1 fix: 2박스(multi-item) 주문은 전체 item을 먼저 수집한 뒤 등록.
    # 일부 item만 등록하는 문제를 방지하기 위해 order_id 단위로 그룹핑 후
    # API에서 order_item_codes 전체를 조회해 한 번에 등록.
    cafe24_orders_to_register: dict = {}
    for (_, order_id, item_code), (_, _, tracking) in seen_cafe24.items():
        cafe24_orders_to_register.setdefault(order_id, {"tracking": tracking, "item_codes": set()})
        if item_code:
            cafe24_orders_to_register[order_id]["item_codes"].add(item_code)

    for order_id, info in cafe24_orders_to_register.items():
        tracking = info["tracking"]
        excel_item_codes = sorted(info["item_codes"])
        try:
            # API로 order_item_code 조회 (엑셀 item_code는 product code일 수 있어 신뢰 불가)
            item_codes = cafe24_client.get_order_item_codes(order_id)
            if not item_codes:
                cafe24_fail.append(f"{order_id}: order_item_code 조회 실패")
                results.append(TrackingResult(
                    channel="cafe24", order_id=order_id,
                    item_code=",".join(excel_item_codes),
                    tracking_no=tracking, status="failed",
                    api_response_code="lookup_empty",
                    api_response_body="get_order_item_codes returned empty",
                ))
                continue
            r = register_tracking_cafe24(order_id, item_codes, tracking, CAFE24_LOGEN)
            api_codes_str = ",".join(item_codes) if isinstance(item_codes, list) else str(item_codes)
            if r.status_code in (200, 201):
                cafe24_success += 1
                results.append(TrackingResult(
                    channel="cafe24", order_id=order_id, item_code=api_codes_str,
                    tracking_no=tracking, status="sent",
                    api_response_code=str(r.status_code),
                    api_response_body=_truncate_body(r.text),
                ))
            elif r.status_code == 422 and "cannot change" in r.text:
                # 이미 배송중 등록된 건 — 성공 카운트엔 포함하되 status는 conflict_existing로 박제
                cafe24_success += 1
                results.append(TrackingResult(
                    channel="cafe24", order_id=order_id, item_code=api_codes_str,
                    tracking_no=tracking, status="conflict_existing",
                    api_response_code="422",
                    api_response_body=_truncate_body(r.text),
                ))
            else:
                cafe24_fail.append(f"{order_id}: {r.text[:80]}")
                results.append(TrackingResult(
                    channel="cafe24", order_id=order_id, item_code=api_codes_str,
                    tracking_no=tracking, status="failed",
                    api_response_code=str(r.status_code),
                    api_response_body=_truncate_body(r.text),
                ))
        except Exception as e:
            cafe24_fail.append(f"{order_id}: {e}")
            results.append(TrackingResult(
                channel="cafe24", order_id=order_id,
                item_code=",".join(excel_item_codes),
                tracking_no=tracking, status="failed",
                api_response_code="exception",
                api_response_body=_truncate_body(str(e)),
            ))

    # SS: 엑셀 주문번호 부동소수점 손실 보정 — string-dtype 강제 후엔 보정 불필요할 수 있으나
    # 과거 손실된 데이터 호환성 위해 매칭 로직은 유지
    actual_naver_orders = naver_client.orders_pending_dispatch(days_back=7)
    actual_ids = {
        o.get("productOrder", {}).get("productOrderId", ""): True
        for o in actual_naver_orders
    }

    def _fix_naver_id(excel_id):
        """이미 16자리 정상 ID면 그대로. 길이 부족 시 prefix 매칭."""
        if excel_id in actual_ids:
            return excel_id
        # 16자리 미만 (구 데이터 호환) — 앞 15자리로 prefix 매칭
        if len(excel_id) >= 15:
            prefix = excel_id[:15]
            for real_id in actual_ids:
                if real_id.startswith(prefix):
                    return real_id
        return excel_id

    # SS: (channel, order_id) item_code 없음 — order_id 단위 dedup
    seen_naver: dict = {}
    naver_conflicts: List[TrackingResult] = []
    naver_order_trackings: dict = {}
    for product_order_id, tracking in naver_items:
        fixed_id = _fix_naver_id(product_order_id)
        prev = naver_order_trackings.setdefault(fixed_id, set())
        prev.add(tracking)
        if len(prev) > 1:
            naver_conflicts.append(TrackingResult(
                channel="naver", order_id=fixed_id, item_code="",
                tracking_no=tracking, status="skipped",
                api_response_code="conflict_multi_tracking",
                api_response_body=f"order has multiple trackings: {sorted(prev)}",
            ))
            continue
        if fixed_id not in seen_naver:
            seen_naver[fixed_id] = tracking
    results.extend(naver_conflicts)
    for c in naver_conflicts:
        naver_fail.append(f"{c.order_id}: 송장번호 충돌 (수동 확인 필요)")

    import time as _time
    for product_order_id, tracking in seen_naver.items():
        last_status = "failed"
        last_code = ""
        last_body = ""
        for attempt in range(3):  # RATE_LIMIT 시 최대 3회 재시도
            try:
                r = register_tracking_naver(product_order_id, tracking, NAVER_LOGEN)
                last_code = str(r.status_code)
                last_body = _truncate_body(r.text)
                if r.status_code == 200:
                    result = r.json().get("data", {})
                    if result.get("successProductOrderIds"):
                        naver_success += 1
                        last_status = "sent"
                        break
                    else:
                        fail_info = result.get("failProductOrderInfos", [{}])
                        msg = fail_info[0].get("message", "fail") if fail_info else "fail"
                        if "RATE_LIMIT" in str(r.text) and attempt < 2:
                            _time.sleep(3)
                            continue
                        naver_fail.append(f"{product_order_id}: {msg}")
                        last_body = _truncate_body(msg)
                        break
                elif "RATE_LIMIT" in r.text and attempt < 2:
                    _time.sleep(3)
                    continue
                else:
                    naver_fail.append(f"{product_order_id}: {r.text[:80]}")
                    break
            except Exception as e:
                naver_fail.append(f"{product_order_id}: {e}")
                last_code = "exception"
                last_body = _truncate_body(str(e))
                break
        results.append(TrackingResult(
            channel="naver", order_id=product_order_id, item_code="",
            tracking_no=tracking, status=last_status,
            api_response_code=last_code, api_response_body=last_body,
        ))
        _time.sleep(0.5)  # 호출 간격

    # 쿠팡: order_id 단위 dedup
    coupang_success, coupang_fail = 0, []
    seen_coupang: dict = {}
    coupang_conflicts: List[TrackingResult] = []
    coupang_order_trackings: dict = {}
    for order_id, tracking in coupang_items:
        prev = coupang_order_trackings.setdefault(order_id, set())
        prev.add(tracking)
        if len(prev) > 1:
            coupang_conflicts.append(TrackingResult(
                channel="coupang", order_id=order_id, item_code="",
                tracking_no=tracking, status="skipped",
                api_response_code="conflict_multi_tracking",
                api_response_body=f"order has multiple trackings: {sorted(prev)}",
            ))
            continue
        if order_id not in seen_coupang:
            seen_coupang[order_id] = tracking
    results.extend(coupang_conflicts)
    for c in coupang_conflicts:
        coupang_fail.append(f"{c.order_id}: 송장번호 충돌 (수동 확인 필요)")

    if seen_coupang:
        print("[쿠팡] shipmentBoxId/vendorItemId 조회 중 (fetch_orders)...")
        for order_id, tracking in seen_coupang.items():
            try:
                info = coupang_client.get_order_shipping_info(order_id)
                if not info or not info["vendorItemIds"]:
                    coupang_fail.append(f"{order_id}: 주문 정보 조회 실패 (INSTRUCT 상태 아닐 수 있음)")
                    results.append(TrackingResult(
                        channel="coupang", order_id=order_id, item_code="",
                        tracking_no=tracking, status="failed",
                        api_response_code="lookup_empty",
                        api_response_body="get_order_shipping_info returned empty",
                    ))
                    continue
                vendor_items_str = ",".join(str(v) for v in info["vendorItemIds"])
                r = coupang_client.register_tracking(
                    order_id, info["shipmentBoxId"], info["vendorItemIds"], tracking
                )
                if r.status_code in (200, 201):
                    coupang_success += 1
                    results.append(TrackingResult(
                        channel="coupang", order_id=order_id,
                        item_code=vendor_items_str,
                        tracking_no=tracking, status="sent",
                        api_response_code=str(r.status_code),
                        api_response_body=_truncate_body(r.text),
                    ))
                else:
                    coupang_fail.append(f"{order_id}: {r.text[:100]}")
                    results.append(TrackingResult(
                        channel="coupang", order_id=order_id,
                        item_code=vendor_items_str,
                        tracking_no=tracking, status="failed",
                        api_response_code=str(r.status_code),
                        api_response_body=_truncate_body(r.text),
                    ))
            except Exception as e:
                coupang_fail.append(f"{order_id}: {e}")
                results.append(TrackingResult(
                    channel="coupang", order_id=order_id, item_code="",
                    tracking_no=tracking, status="failed",
                    api_response_code="exception",
                    api_response_body=_truncate_body(str(e)),
                ))

    # 5) 결과 CSV 영속화 (idempotency ledger 역할)
    csv_path = None
    try:
        csv_path = _write_run_csv(results)
    except Exception as e:
        print(f"⚠️ 결과 CSV 저장 실패: {e}")

    # 6) 완료 알림
    result_msg = (
        f"✅ 송장 등록 완료\n\n"
        f"카페24: {cafe24_success}/{len(cafe24_orders_to_register)}건 성공\n"
        f"스마트스토어: {naver_success}/{len(seen_naver)}건 성공\n"
        f"쿠팡: {coupang_success}/{len(seen_coupang)}건 성공"
    )
    if cafe24_fail:
        result_msg += "\n\n카페24 실패:\n" + "\n".join(f"  - {e}" for e in cafe24_fail[:5])
    if naver_fail:
        result_msg += "\n\n스마트스토어 실패:\n" + "\n".join(f"  - {e}" for e in naver_fail[:5])
    if coupang_fail:
        result_msg += "\n\n쿠팡 실패:\n" + "\n".join(f"  - {e}" for e in coupang_fail[:5])
    if csv_path:
        result_msg += f"\n\n📄 결과 로그: {csv_path}"

    telegram_client.send_message(result_msg, channel="ops")
    print(result_msg)


def pluscl_to_cafe24(pluscl_code):
    """PlusCL tran_comp_code를 카페24 shipping_company_code로 변환.
    헤비로버는 로젠만 쓰므로 전부 로젠(0004)으로 매핑."""
    return CAFE24_LOGEN

def pluscl_to_naver(pluscl_code):
    """PlusCL tran_comp_code를 네이버 deliveryCompanyCode로 변환."""
    return NAVER_LOGEN

# 호환성 유지
CARRIER_MAP_CAFE24 = {"DEFAULT": CAFE24_LOGEN}
CARRIER_MAP_NAVER = {"DEFAULT": NAVER_LOGEN}


def _get_pluscl_config():
    load_dotenv(ENV_PATH, override=True)
    return {
        "auth_key": os.getenv("PLUSCL_AUTH_KEY"),
        "company_code": os.getenv("PLUSCL_COMPANY_CODE"),
        "warehouse_code": os.getenv("PLUSCL_WAREHOUSE_CODE"),
        "seller_code": os.getenv("PLUSCL_SELLER_CODE"),
        "user_id": os.getenv("PLUSCL_USER_ID"),
    }


def fetch_pluscl_shipments(hours_back=24):
    """PlusCL에서 최근 출고 완료 건 조회 (주문 출고내역)

    Returns:
        list[dict]: 출고 완료된 주문 리스트
            각 항목: {ord_no1, tran_comp_code, invoice_no, ord_comp_code, ...}
    """
    cfg = _get_pluscl_config()
    if not cfg["auth_key"]:
        print("⚠️ PLUSCL_AUTH_KEY 환경변수 미설정 — PlusCL 연동 불가")
        return []

    now = datetime.now()
    # 조회 범위: hours_back 시간 전부터 지금까지
    end = now
    start = datetime.fromtimestamp(now.timestamp() - hours_back * 3600)

    body = {
        "company_code": cfg["company_code"],
        "user_id": cfg["user_id"],
        "warehouse_code": cfg["warehouse_code"],
        "warehouse_type_code": "0000",
        "seller_code": cfg["seller_code"],
        "job_type": "search",
        "type": "doc",
        "IsOld": "Y",
        "data": {
            "begin_date": start.strftime("%Y%m%d"),
            "end_date": end.strftime("%Y%m%d"),
            "warehouse_type_code": "",
            "stock_no": "",
            "stock_kind": "",
        },
    }

    # 출고서 조회 API
    r = requests.post(
        f"{PLUSCL_BASE}/open/item_out",
        headers={"auth_key": cfg["auth_key"], "Content-Type": "application/json"},
        json=body,
        timeout=30,
    )
    if r.status_code != 200:
        print(f"PlusCL 조회 실패: {r.status_code} - {r.text[:200]}")
        return []

    data = r.json().get("data", [])
    # invoice_no가 있는 건만 (= 출고 완료)
    return [d for d in data if d.get("invoice_no")]


def register_tracking_cafe24(order_id, item_codes, tracking_no, carrier_code):
    """카페24에 송장번호 등록 (배송중 전환)

    item_codes: list[str] — API 조회로 얻은 order_item_code 목록
    """
    if isinstance(item_codes, str):
        item_codes = [item_codes]
    body = {
        "shop_no": 1,
        "request": {
            "order_item_code": item_codes,
            "tracking_no": tracking_no,
            "shipping_company_code": carrier_code,
            "status": "shipping",
        },
    }
    return cafe24_client._api_post(f"/api/v2/admin/orders/{order_id}/shipments", body)


def register_tracking_naver(product_order_id, tracking_no, carrier_code):
    """네이버에 송장번호 등록 (배송중 전환)

    POST /pay-order/seller/product-orders/dispatch
    """
    token = naver_client.get_access_token()
    from datetime import timezone, timedelta
    kst = timezone(timedelta(hours=9))
    dispatch_date = datetime.now(kst).isoformat(timespec="milliseconds")

    body = {
        "dispatchProductOrders": [{
            "productOrderId": product_order_id,
            "deliveryMethod": "DELIVERY",
            "deliveryCompanyCode": carrier_code,
            "trackingNumber": tracking_no,
            "dispatchDate": dispatch_date,
        }]
    }
    r = requests.post(
        f"{naver_client.API_BASE}/v1/pay-order/seller/product-orders/dispatch",
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        proxies=naver_client._get_proxies(),
    )
    return r


def run():
    print(f"=== 송장 자동 등록 시작 ({datetime.now():%Y-%m-%d %H:%M:%S}) ===\n")

    # 1) PlusCL에서 출고 완료 건 조회
    print("[1/4] PlusCL 출고 완료 조회...")
    shipments = fetch_pluscl_shipments(hours_back=24)
    print(f"  - 출고 완료: {len(shipments)}건")

    if not shipments:
        print("처리할 송장 없음. 종료.")
        return

    # 2) 출처별로 분류 (카페24 vs 스마트스토어)
    cafe24_items = []
    naver_items = []
    for s in shipments:
        ord_no1 = s.get("ord_no1", "")
        carrier = s.get("tran_comp_code", "")
        invoice = s.get("invoice_no", "")
        # 주문번호 형식으로 출처 판별
        # 카페24: YYYYMMDD-NNNNNNN 형식
        # 스마트스토어: 16자리 숫자
        if "-" in ord_no1:
            cafe24_items.append(s)
        else:
            naver_items.append(s)

    # 3) 텔레그램 승인 요청
    print("[2/4] 텔레그램 승인 요청 중...")
    msg = (
        f"📦 송장 도착 알림 ({datetime.now():%H:%M})\n\n"
        f"PlusCL 출고 완료: {len(shipments)}건\n"
        f"- 카페24: {len(cafe24_items)}건\n"
        f"- 스마트스토어: {len(naver_items)}건\n\n"
        f"/done → 카페24/스마트스토어 송장 자동 등록\n"
        f"/cancel → 오늘 등록 취소 (수동 처리)"
    )
    telegram_client.send_message(msg, channel="ops")

    print("[3/4] 응답 대기 중 (최대 8시간)...")
    cmd = telegram_client.wait_for_command(["/done", "/cancel"], timeout_seconds=28800, channel="ops")
    if cmd == "/cancel":
        telegram_client.send_message("❌ 송장 등록 취소됨. 수동으로 처리해주세요.", channel="ops")
        return
    if cmd is None:
        telegram_client.send_message("⏰ 응답 대기 타임아웃. 송장 등록 건너뜀.", channel="ops")
        return
    print(f"  - 승인 받음 ({cmd})")

    # 4) 송장 등록 실행
    print("[4/4] 송장 등록 중...")
    cafe24_success = 0
    cafe24_fail = []
    naver_success = 0
    naver_fail = []

    for s in cafe24_items:
        order_id = s.get("ord_no1")
        item_code = s.get("ord_item_code") or f"{order_id}-{s.get('item_seq',1):02d}"
        tracking = s.get("invoice_no")
        pluscl_carrier = s.get("tran_comp_code")
        carrier_code = pluscl_to_cafe24(pluscl_carrier)
        try:
            r = register_tracking_cafe24(order_id, item_code, tracking, carrier_code)
            if r.status_code in (200, 201):
                cafe24_success += 1
            else:
                cafe24_fail.append(f"{order_id}: {r.text[:100]}")
        except Exception as e:
            cafe24_fail.append(f"{order_id}: {e}")

    for s in naver_items:
        product_order_id = s.get("ord_no1")
        tracking = s.get("invoice_no")
        pluscl_carrier = s.get("tran_comp_code")
        carrier_code = pluscl_to_naver(pluscl_carrier)
        try:
            r = register_tracking_naver(product_order_id, tracking, carrier_code)
            if r.status_code == 200:
                result = r.json().get("data", {})
                if result.get("successProductOrderIds"):
                    naver_success += 1
                else:
                    naver_fail.append(f"{product_order_id}: {result.get('failProductOrderInfos', [{}])[0].get('message','fail')}")
            else:
                naver_fail.append(f"{product_order_id}: {r.text[:100]}")
        except Exception as e:
            naver_fail.append(f"{product_order_id}: {e}")

    # 완료 알림
    result_msg = (
        f"✅ 송장 등록 완료\n\n"
        f"카페24: {cafe24_success}/{len(cafe24_items)}건 성공"
    )
    if cafe24_fail:
        result_msg += "\n실패:\n" + "\n".join(f"  - {e}" for e in cafe24_fail[:5])
    result_msg += f"\n\n스마트스토어: {naver_success}/{len(naver_items)}건 성공"
    if naver_fail:
        result_msg += "\n실패:\n" + "\n".join(f"  - {e}" for e in naver_fail[:5])

    telegram_client.send_message(result_msg, channel="ops")
    print(result_msg)


if __name__ == "__main__":
    run()
