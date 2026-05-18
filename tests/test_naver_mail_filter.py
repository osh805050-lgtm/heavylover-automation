"""naver_mail_client._is_govt_mail 필터 단위 테스트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.naver_mail_client import _is_govt_mail


def test_self_radar_mail_is_excluded():
    """자기 발송 정부지원 레이더 일일요약 메일은 공고 아님 — 재파싱 방지."""
    assert not _is_govt_mail(
        subject="[정부지원 레이더] 2026-05-18 일일요약 — 총 887건 / S·A 60건",
        sender="osh805050@gmail.com",
        body="오늘 S등급 12건 A등급 48건 수집됐습니다.",
    )


def test_self_weekly_digest_is_excluded():
    """자기 발송 주간 다이제스트도 제외."""
    assert not _is_govt_mail(
        subject="[정부지원 레이더] 05/18 주간 다이제스트 — 즉시 액션 30건, S·A 62건",
        sender="noreply@example.com",
        body="이번 주 신규 지원사업 공고 요약입니다.",
    )


def test_real_govt_mail_passes():
    """실제 공고 메일은 통과."""
    assert _is_govt_mail(
        subject="2026년 용인시 청년 창업 지원사업 모집공고",
        sender="info@ypa.or.kr",
        body="용인시산업진흥원에서는 청년 창업 지원사업을 모집합니다. 신청기한: 2026-06-30",
    )


def test_noise_ad_mail_excluded():
    """광고·프로모션 메일 제외."""
    assert not _is_govt_mail(
        subject="(광고) 특가 할인 쿠폰 안내",
        sender="promo@tason.com",
        body="이번 주 최대 50% 할인 쿠폰 지원사업 공고",
    )


def test_trusted_domain_passes_despite_keyword():
    """신뢰 도메인(.go.kr)은 노이즈 키워드 없으면 통과."""
    assert _is_govt_mail(
        subject="2026년 소상공인 정책자금 지원사업 공고",
        sender="notice@mss.go.kr",
        body="소상공인을 위한 정책자금 신청을 받습니다.",
    )
