"""reconciler.py 단위 테스트 — 매칭·분류·URL/title 정규화 검증."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib import reconciler


def test_url_normalize_drops_tracking():
    n1 = reconciler._normalize_url("https://example.com/path/?utm_source=x&id=1")
    n2 = reconciler._normalize_url("https://example.com/path?id=1")
    assert n1 == n2, f"{n1} != {n2}"


def test_url_normalize_preserves_identifier():
    n1 = reconciler._normalize_url(
        "https://www.bizinfo.go.kr/web/lay1/bbs/S1T122C159/AS/74/view.do?pblancId=PBN12345"
    )
    n2 = reconciler._normalize_url(
        "https://www.bizinfo.go.kr/web/lay1/bbs/S1T122C159/AS/74/view.do?pblancId=PBN12345&utm_medium=email"
    )
    assert n1 == n2
    # pblancId가 유지되는지 확인
    assert "pblancId=PBN12345" in n1


def test_url_normalize_fragment_drop():
    n1 = reconciler._normalize_url("https://gsp.or.kr/supportProject/UVSL0001.do#card1")
    n2 = reconciler._normalize_url("https://gsp.or.kr/supportProject/UVSL0001.do")
    assert n1 == n2


def test_title_normalize_year_and_paren():
    a = reconciler._normalize_title("2026년 식품 사업화 지원사업(추가공고)")
    b = reconciler._normalize_title("식품 사업화 지원사업")
    assert a == b, f"{a} != {b}"


def test_reconcile_url_match():
    api = [{"source": "기업마당", "title": "A 사업", "url": "https://x.kr/view?id=1", "agency": "농림부"}]
    pw = [{"source": "농림축산식품부", "title": "A 사업 안내", "url": "https://x.kr/view/?id=1&utm_source=mail", "agency": "농림부"}]
    rec = reconciler.reconcile(api, pw)
    assert rec["stats"]["matched_count"] == 1
    assert rec["stats"]["playwright_only_count"] == 0
    assert rec["stats"]["api_only_count"] == 0


def test_reconcile_title_match_diff_url():
    api = [{"source": "기업마당", "title": "2026년 식품 사업화 지원사업", "url": "https://api.go.kr/a/1", "agency": "농림부"}]
    pw = [{"source": "농림축산식품부", "title": "식품 사업화 지원사업", "url": "https://mafra.go.kr/b/2", "agency": "농림부"}]
    rec = reconciler.reconcile(api, pw)
    assert rec["stats"]["matched_count"] == 1, f"stats={rec['stats']}"
    assert rec["stats"]["playwright_only_count"] == 0


def test_reconcile_playwright_only_detected():
    api = [{"source": "기업마당", "title": "다른 사업", "url": "https://a.kr/1", "agency": "중기부"}]
    pw = [{"source": "경기테크노파크", "title": "드론산업 육성 지원", "url": "https://pms.gtp.or.kr/view?b_idx=1", "agency": "경기테크노파크"}]
    rec = reconciler.reconcile(api, pw)
    assert rec["stats"]["playwright_only_count"] == 1
    assert rec["stats"]["matched_count"] == 0
    assert rec["stats"]["api_only_count"] == 1
    # merged는 두 항목 다 포함
    assert rec["stats"]["merged_count"] == 2


def test_reconcile_pw_dedup_within_self():
    api = []
    pw = [
        {"source": "A", "title": "공고1", "url": "https://x.kr/1", "agency": "A"},
        {"source": "A", "title": "공고1", "url": "https://x.kr/1?utm_source=mail", "agency": "A"},
    ]
    rec = reconciler.reconcile(api, pw)
    # PW 내부 중복(URL 정규화 후 동일) 1건은 dedup
    assert rec["stats"]["playwright_only_count"] == 1, f"stats={rec['stats']}"


def test_select_missing_alerts_score_threshold():
    items = [
        {"title": "high", "score": 7},
        {"title": "mid", "score": 5},
        {"title": "low", "score": 3},
        {"title": "noscore"},
    ]
    selected = reconciler.select_missing_alerts(items, min_score=5.0)
    assert {it["title"] for it in selected} == {"high", "mid"}


def test_format_alert_text_truncates():
    items = [{"source": "X", "title": f"공고{i}", "url": f"https://x.kr/{i}", "deadline": "2026-06-01"} for i in range(15)]
    txt = reconciler.format_alert_text(items, max_show=5)
    assert "Playwright에서만 발견된 공고 15건" in txt
    assert "외 10건" in txt
    assert "공고0" in txt
    assert "공고14" not in txt  # truncated


if __name__ == "__main__":
    import traceback
    tests = [
        test_url_normalize_drops_tracking,
        test_url_normalize_preserves_identifier,
        test_url_normalize_fragment_drop,
        test_title_normalize_year_and_paren,
        test_reconcile_url_match,
        test_reconcile_title_match_diff_url,
        test_reconcile_playwright_only_detected,
        test_reconcile_pw_dedup_within_self,
        test_select_missing_alerts_score_threshold,
        test_format_alert_text_truncates,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERR   {t.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failed += 1
    print(f"\n총 {passed + failed}개: PASS {passed} · FAIL {failed}")
    sys.exit(0 if failed == 0 else 1)
