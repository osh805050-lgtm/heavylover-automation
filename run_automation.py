"""
헤비로버 주문 자동화 - 전체 파이프라인 (텔레그램 승인 플로우 포함)

평일 오전 11시 실행:
  1. 카페24 + 네이버 + 쿠팡 주문 조회
  2. 신규/특이사항 있으면 → 텔레그램 알림 + 승인 대기
  3. 사장님 /done → 엑셀 생성
  4. 사장님 /cancel → 오늘 취소
  5. 주말엔 자동 스킵
"""

import io
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# Windows cp949 콘솔에서도 유니코드 출력 가능하게
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 로컬 모듈
sys.path.insert(0, str(Path(__file__).parent))
import cafe24_client
import coupang_client
import naver_client
import telegram_client
from dada_excel import create_dada_file, validate_dada_file, DADA_COLUMNS


def _summarize_specials(cafe24_specials, naver_specials, coupang_specials=None):
    lines = []
    if cafe24_specials:
        lines.append(f"[카페24] {len(cafe24_specials)}건")
        for s in cafe24_specials[:5]:
            lines.append(f"  - {s['order_id']}: {s['reason']}")
        if len(cafe24_specials) > 5:
            lines.append(f"  ...외 {len(cafe24_specials)-5}건")
    if naver_specials:
        lines.append(f"[스마트스토어] {len(naver_specials)}건")
        for s in naver_specials[:5]:
            lines.append(f"  - {s['order_id']}: {s['reason']}")
        if len(naver_specials) > 5:
            lines.append(f"  ...외 {len(naver_specials)-5}건")
    if coupang_specials:
        lines.append(f"[쿠팡] {len(coupang_specials)}건")
        for s in coupang_specials[:5]:
            lines.append(f"  - {s['order_id']}: {s['reason']}")
        if len(coupang_specials) > 5:
            lines.append(f"  ...외 {len(coupang_specials)-5}건")
    return "\n".join(lines)


def _fetch_all():
    """카페24 + 네이버 + 쿠팡 주문 조회 후 정리

    카페24: 7일치 조회 후 N20(배송준비중)만 필터 (상태 기반)
    네이버: 14일 윈도우로 PAYED 전수 조회 (며칠 전 결제·발송기한 초과 포함)
    쿠팡: 2일치 INSTRUCT(상품준비중) 조회. API 키 미설정 시 자동 스킵.
    """
    cafe24_orders = cafe24_client.fetch_orders(days_back=7)
    naver_orders = naver_client.orders_pending_dispatch(days_back=14)

    coupang_orders = []
    try:
        coupang_orders = coupang_client.fetch_orders(days_back=14)
    except RuntimeError as e:
        if "미설정" in str(e):
            print("  - 쿠팡: API 키 미설정, 스킵")
        else:
            print(f"  - 쿠팡 조회 오류 (스킵): {e}")

    return cafe24_orders, naver_orders, coupang_orders


def _is_weekday():
    """평일(월~금)이면 True"""
    return datetime.now().weekday() < 5


def run(skip_weekend_check=False):
    now = datetime.now()
    print(f"=== 헤비로버 주문 자동화 시작 ({now:%Y-%m-%d %H:%M:%S}) ===\n")

    # 주말 스킵
    if not skip_weekend_check and not _is_weekday():
        print("오늘은 주말이라 건너뜁니다.")
        return None, True

    # 1) 주문 조회
    print("[1/5] 주문 조회 중...")
    cafe24_orders, naver_orders, coupang_orders = _fetch_all()

    cafe24_df = cafe24_client.orders_to_dada_rows(cafe24_orders)
    # 네이버는 발주확인 완료된 주문(배송준비)만 엑셀에 포함
    naver_ready_orders = [
        w for w in naver_orders
        if w.get("productOrder", {}).get("placeOrderStatus") == "OK"
    ]
    naver_df = naver_client.orders_to_dada_rows(naver_ready_orders)
    coupang_df = coupang_client.orders_to_dada_rows(coupang_orders)
    cafe24_specials = cafe24_client.detect_special_orders(cafe24_orders)
    naver_specials = naver_client.detect_special_orders(naver_orders)
    coupang_specials = coupang_client.detect_special_orders(coupang_orders)

    # 네이버 진짜 신규주문 = placeOrderStatus=NOT_YET (발주확인 안 된 것)
    naver_new_count = sum(
        1 for w in naver_orders
        if w.get("productOrder", {}).get("placeOrderStatus") == "NOT_YET"
    )
    # 발송기한 초과 (당일 미발송 누적분)
    naver_overdue_count = sum(
        1 for w in naver_orders
        if naver_client.is_shipping_overdue(w.get("productOrder", {}))
    )

    # 전화번호 기준 구매자 수
    cafe24_buyers = cafe24_df["받는분전화번호"].nunique() if len(cafe24_df) else 0
    naver_buyers = naver_df["받는분전화번호"].nunique() if len(naver_df) else 0
    coupang_buyers = coupang_df["받는분전화번호"].nunique() if len(coupang_df) else 0

    print(f"  - 카페24 배송준비: {cafe24_buyers}명")
    print(f"  - 스마트스토어 배송준비: {naver_buyers}명 (신규 {naver_new_count}건, 발송기한초과 {naver_overdue_count}건)")
    print(f"  - 쿠팡 배송준비: {coupang_buyers}명")
    print(f"  - 특이사항: 카페24 {len(cafe24_specials)}건 / 스마트스토어 {len(naver_specials)}건 / 쿠팡 {len(coupang_specials)}건")

    # 2) 신규 주문 or 특이사항 있으면 승인 받기
    need_approval = naver_new_count > 0 or cafe24_specials or naver_specials or coupang_specials
    if need_approval:
        print("\n[2/5] 텔레그램으로 승인 요청 중...")
        ss_line = f"스마트스토어: {naver_buyers}명 (신규 {naver_new_count}건"
        if naver_overdue_count > 0:
            ss_line += f", ⚠️ 발송기한초과 {naver_overdue_count}건"
        ss_line += ")"
        summary_parts = [
            f"📋 주문 자동화 ({now:%Y-%m-%d %H:%M})",
            "",
            f"카페24 배송준비: {cafe24_buyers}명",
            ss_line,
        ]
        specials_text = _summarize_specials(cafe24_specials, naver_specials, coupang_specials)
        if specials_text:
            summary_parts.append("")
            summary_parts.append("⚠️ 확인 필요")
            summary_parts.append(specials_text)

        summary_parts.append("")
        if naver_new_count > 0:
            summary_parts.append(
                f"스마트스토어 신규 주문 {naver_new_count}건을 "
                "수동으로 발주확인 처리한 후 명령어를 보내주세요."
            )
        summary_parts.append("")
        summary_parts.append("/done → 처리 완료, 엑셀 생성")
        summary_parts.append("/cancel → 오늘 자동화 취소")

        telegram_client.send_message("\n".join(summary_parts), channel="ops")

        print("  - 사장님 응답 대기 중 (최대 2시간)...")
        cmd = telegram_client.wait_for_command(["/done", "/cancel"], timeout_seconds=7200, channel="ops")
        if cmd == "/cancel":
            telegram_client.send_message("❌ 자동화 취소됨. 오늘은 엑셀 생성 안 함.", channel="ops")
            print("  - 취소됨")
            return None, True
        if cmd is None:
            telegram_client.send_message("⏰ 2시간 대기 타임아웃. 엑셀 생성 건너뜀.", channel="ops")
            print("  - 타임아웃")
            return None, True
        print(f"  - 승인 받음 ({cmd})")

        # 승인 후 주문 재조회 (사장님이 발주확인 처리했으므로)
        print("  - 처리 완료된 주문 재조회 중...")
        cafe24_orders, naver_orders, coupang_orders = _fetch_all()
        cafe24_df = cafe24_client.orders_to_dada_rows(cafe24_orders)
        naver_ready_orders = [
            w for w in naver_orders
            if w.get("productOrder", {}).get("placeOrderStatus") == "OK"
        ]
        naver_df = naver_client.orders_to_dada_rows(naver_ready_orders)
        coupang_df = coupang_client.orders_to_dada_rows(coupang_orders)
        cafe24_buyers = cafe24_df["받는분전화번호"].nunique() if len(cafe24_df) else 0
        naver_buyers = naver_df["받는분전화번호"].nunique() if len(naver_df) else 0
        coupang_buyers = coupang_df["받는분전화번호"].nunique() if len(coupang_df) else 0
        print(f"  - 재조회 결과: 카페24 {cafe24_buyers}명 / 스마트스토어 {naver_buyers}명 / 쿠팡 {coupang_buyers}명")
    else:
        print("\n[2/5] 특이사항 없음 → 승인 생략, 바로 진행")

    # 3) 엑셀 생성
    print("\n[3/5] 더다 양식 엑셀 생성 중...")
    combined = pd.concat([cafe24_df, naver_df, coupang_df], ignore_index=True)
    combined = combined[DADA_COLUMNS]

    if len(combined) == 0:
        telegram_client.send_message("⚠️ 처리할 주문이 없어서 엑셀 생성 안 함.", channel="ops")
        print("  - 주문 0건, 종료")
        return None, True

    try:
        output_path = create_dada_file(combined)
    except Exception as e:
        msg = f"❌ 엑셀 생성 실패\n{e}\n\n확인: DADA_TEMPLATE 경로 또는 템플릿 파일 존재 여부"
        telegram_client.send_message(msg, channel="ops")
        print(f"  - 엑셀 생성 실패: {e}")
        return None, False
    print(f"  - 파일: {output_path}")
    print(f"  - 총 {len(combined)}행 (카페24 {len(cafe24_df)} + 네이버 {len(naver_df)} + 쿠팡 {len(coupang_df)})")

    # 4) 검증
    print("\n[4/5] 파일 검증 중...")
    is_valid, issues = validate_dada_file(output_path, expected_count=len(combined))
    if is_valid:
        print("  - 검증 통과 ✓")
    else:
        print(f"  - 검증 실패 ({len(issues)}개 이슈)")
        for issue in issues[:5]:
            print(f"    · {issue}")

    # 5) OneDrive 업로드 + 텔레그램으로 완료 알림 + 엑셀 파일 전송
    print("\n[5/5] OneDrive 업로드 + 텔레그램 전송 중...")

    onedrive_ok = False
    onedrive_target = os.getenv(
        "ONEDRIVE_REMOTE",
        "heavylover_onedrive:바탕 화면/사업/더다 3pl/더다 양식/",
    )
    try:
        r = subprocess.run(
            ["rclone", "copy", str(output_path), onedrive_target],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode == 0:
            onedrive_ok = True
            print(f"  - OneDrive 업로드 성공: {onedrive_target}")
        elif "423" in r.stderr or "resourceLocked" in r.stderr or "Locked" in r.stderr:
            # 파일 잠김 → 시간 붙인 백업 파일명으로 재시도
            backup_name = f"{output_path.stem}_{datetime.now():%H%M}{output_path.suffix}"
            backup_local = output_path.parent / backup_name
            import shutil
            shutil.copy2(output_path, backup_local)
            r2 = subprocess.run(
                ["rclone", "copy", str(backup_local), onedrive_target],
                capture_output=True, text=True, timeout=120,
            )
            if r2.returncode == 0:
                onedrive_ok = True
                print(f"  - OneDrive 업로드 성공 (파일 잠김 회피, 이름변경: {backup_name})")
            else:
                print(f"  - OneDrive 재시도도 실패: {r2.stderr[:200]}")
        else:
            print(f"  - OneDrive 업로드 실패: {r.stderr[:200]}")
    except Exception as e:
        print(f"  - OneDrive 업로드 오류: {e}")

    coupang_line = f"\n- 쿠팡: {coupang_buyers}명" if coupang_buyers > 0 else ""
    result_msg = (
        f"✅ 엑셀 생성 완료\n"
        f"- 카페24: {cafe24_buyers}명\n"
        f"- 스마트스토어: {naver_buyers}명"
        f"{coupang_line}\n"
        f"- 총: {cafe24_buyers + naver_buyers + coupang_buyers}명\n"
        f"- 검증: {'통과' if is_valid else '실패 - 확인 필요'}\n"
        f"- OneDrive: {'✓ 업로드 완료' if onedrive_ok else '✗ 실패 (텔레그램만 전송)'}"
    )
    telegram_client.send_document(str(output_path), caption=result_msg, channel="ops")
    print("  - 텔레그램 전송 완료")

    # 6) 송장 등록 단계 (당일 23:59까지 대기, 미응답 시 자동 종료)
    print("\n[6/6] 송장 등록 대기 중...")
    import tracking_register

    midnight = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
    secs_until_midnight = max(60, int((midnight - datetime.now()).total_seconds()))

    telegram_client.send_message(
        "📦 송장 등록할까요?\n"
        "/tracking → 송장 엑셀로 즉시 등록\n"
        "/skip → 오늘 송장 등록 안 함\n\n"
        "(오늘 23:59까지 대기, 미응답 시 자동 종료)",
        channel="ops",
    )

    cmd2 = telegram_client.wait_for_command(
        ["/tracking", "/skip"],
        timeout_seconds=secs_until_midnight,
        channel="ops",
    )
    if cmd2 == "/tracking":
        print("  - /tracking 받음 → 송장 등록 시작")
        try:
            tracking_register.run_from_excel()
        except Exception as e:
            telegram_client.send_message(f"❌ 송장 등록 오류: {e}", channel="ops")
            print(f"  - 송장 등록 오류: {e}")
    elif cmd2 == "/skip":
        telegram_client.send_message("✅ 오늘 송장 등록 건너뜀", channel="ops")
        print("  - /skip → 송장 등록 건너뜀")
    else:
        telegram_client.send_message("⏰ 송장 등록 자동 종료 (자정 도달)", channel="ops")
        print("  - 자정 도달 타임아웃")

    print(f"\n=== 완료 ===")
    print(f"생성 파일: {output_path}")
    return output_path, is_valid


if __name__ == "__main__":
    # 수동 실행 시 주말 체크 건너뛰기 옵션
    skip = "--force" in sys.argv
    run(skip_weekend_check=skip)
