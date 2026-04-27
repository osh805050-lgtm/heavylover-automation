"""부트스트랩 — 토큰 등록 후 한 번에 1년 백필 + 종합 리포트 + 일일 리포트.

사용:
    python bootstrap_meta_yearly.py

순서:
1. 토큰 검증 (Meta API 1회 호출)
2. 1년치 백필 (meta_ads_yearly_backfill.py)
3. 일일 리포트 (오늘 데이터 + 누적 14일 시 자사 P50 활성)
4. 1년 종합 리포트 (4역할 + 퍼널 + 계절성 + 위너/패배)

승현님이 자고 일어나서 토큰 새로 받으시면, 이거 한 번 실행하면 다 됨.
"""
import io
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def main():
    print("=" * 60)
    print("Meta 광고 부트스트랩 — 토큰 검증 → 1년 백필 → 일일 → 종합")
    print("=" * 60)

    # 1. 토큰 검증
    print("\n[1/4] Meta API 토큰 검증")
    from meta_ads_client import fetch_account_insights
    raw = fetch_account_insights()
    if not raw["ok"]:
        print(f"❌ 토큰 검증 실패: {raw['error']}")
        print("\nGraph API Explorer에서 새 토큰 발급 후 .env에 저장하고 다시 실행해주세요.")
        return 1
    print(f"✅ 토큰 OK (어제 데이터: spend={raw['data'][0].get('spend')})")

    # 2. 1년 백필
    print("\n[2/4] 1년치 백필 (시간 좀 걸림)")
    from meta_ads_yearly_backfill import backfill
    rc = backfill(days=365)
    if rc != 0:
        print(f"⚠️ 백필 일부/전체 실패 (계속 진행)")

    # 3. 일일 리포트
    print("\n[3/4] 오늘 일일 리포트 + 텔레그램 + 이메일")
    from meta_ads_report import run as run_daily
    rc = run_daily()
    print(f"일일 리포트: rc={rc}")

    # 4. 1년 종합 리포트
    print("\n[4/4] 1년 종합 심층 리포트 + 텔레그램 + 이메일")
    from meta_ads_yearly_report import main as run_yearly
    rc = run_yearly()
    print(f"종합 리포트: rc={rc}")

    print("\n" + "=" * 60)
    print("✅ 부트스트랩 완료 — 텔레그램·이메일 확인하세요")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
