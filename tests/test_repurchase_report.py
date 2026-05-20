"""repurchase_report.py 단위 테스트 — 분모 통일(cumulative) 검증."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from repurchase_report import _extract_stage_flat, _build_action_points


# ── 공통 fixture: 충분히 오래된 코호트 (2024) — date.today() 무관하게 gate 통과 ─

def _mock_rows():
    """3개 코호트 — 30일·60일 합산 cumulative 비교용 mock 데이터.

    cumulative 30일 = (20 + 30 + 10) / (100 + 200 + 100) * 100 = 60/400 = 15.0%
    eligible-mean 30일 = (25.0 + 18.0 + 12.5) / 3 = 18.5% (기존 산식)
    → 두 값이 명확히 다름 = 산식 변경이 적용됐는지 검증 가능.

    cumulative 60일 = (30 + 40 + 30) / (100 + 200 + 100) * 100 = 100/400 = 25.0%
    eligible-mean 60일 = (35.0 + 25.0 + 40.0) / 3 = 33.33% (기존 산식)
    """
    return [
        {"코호트월": "2024-01", "첫구매자수": 100,
         "30일_전환수": 20, "30일_전환율": 25.0,
         "60일_전환수": 30, "60일_전환율": 35.0,
         "1→2_전환율": 35.0, "2→3_전환율": None},
        {"코호트월": "2024-02", "첫구매자수": 200,
         "30일_전환수": 30, "30일_전환율": 18.0,
         "60일_전환수": 40, "60일_전환율": 25.0,
         "1→2_전환율": 25.0, "2→3_전환율": None},
        {"코호트월": "2024-03", "첫구매자수": 100,
         "30일_전환수": 10, "30일_전환율": 12.5,
         "60일_전환수": 30, "60일_전환율": 40.0,
         "1→2_전환율": 40.0, "2→3_전환율": None},
    ]


# ── _extract_stage_flat cumulative 산식 검증 ────────────────────

def test_stage_flat_30day_cumulative():
    """30일 평균이 cumulative (sum/sum)이어야 한다."""
    with patch('repurchase_report._extract_cohort_stage', return_value=_mock_rows()):
        result = _extract_stage_flat(None)
    s30 = next(s for s in result if s["단계"] == "1→2_30일")
    assert s30["전환율"] == 15.0, f"expected 15.0%, got {s30['전환율']}"
    assert s30["기준고객수"] == 400
    assert s30["전환고객수"] == 60


def test_stage_flat_60day_cumulative():
    """60일 평균이 cumulative여야 한다. base_60도 last3_60 기준이어야 한다."""
    with patch('repurchase_report._extract_cohort_stage', return_value=_mock_rows()):
        result = _extract_stage_flat(None)
    s60 = next(s for s in result if s["단계"] == "1→2")
    assert s60["전환율"] == 25.0, f"expected 25.0%, got {s60['전환율']}"
    assert s60["기준고객수"] == 400
    assert s60["전환고객수"] == 100


def test_stage_flat_empty_input():
    """빈 시트 입력 시 빈 리스트 반환."""
    with patch('repurchase_report._extract_cohort_stage', return_value=[]):
        assert _extract_stage_flat(None) == []


def test_stage_flat_small_sample_excluded():
    """첫구매자수 < 5 코호트는 분모에서 제외."""
    rows = [
        {"코호트월": "2024-01", "첫구매자수": 3,  # < 5 제외
         "30일_전환수": 99, "30일_전환율": 99.0,
         "60일_전환수": 99, "60일_전환율": 99.0,
         "1→2_전환율": 99.0, "2→3_전환율": None},
        {"코호트월": "2024-02", "첫구매자수": 100,
         "30일_전환수": 20, "30일_전환율": 20.0,
         "60일_전환수": 30, "60일_전환율": 30.0,
         "1→2_전환율": 30.0, "2→3_전환율": None},
    ]
    with patch('repurchase_report._extract_cohort_stage', return_value=rows):
        result = _extract_stage_flat(None)
    s30 = next(s for s in result if s["단계"] == "1→2_30일")
    # 99% 코호트가 평균에 들어가면 cumulative ≥ 59%. 제외되면 20.0%.
    assert s30["전환율"] == 20.0


# ── _build_action_points 라벨 검증 ──────────────────────────────

def test_action_point_conv_rate_label():
    """60일 재구매율 메시지에 '(완결 코호트 누적)' 라벨이 박제돼야 한다."""
    points = _build_action_points(
        conv_rate=25.0, m1_recent=None, p50_num=None,
        mom_pct=None,
        cohort_trend={"최근3개월_평균": 25.0, "이전3개월_평균": 22.0},
    )
    msg = next((p for p in points if "60일" in p), "")
    assert "(완결 코호트 누적)" in msg, f"라벨 누락: {msg}"


def test_action_point_conv_rate_label_low():
    """conv_rate < 20% (🔴 케이스)에도 라벨 박제."""
    points = _build_action_points(
        conv_rate=15.0, m1_recent=None, p50_num=None,
        mom_pct=None, cohort_trend={},
    )
    msg = next((p for p in points if "60일" in p), "")
    assert "(완결 코호트 누적)" in msg


def test_action_point_m1_label_separate():
    """M+1 메시지와 60일 메시지는 분모가 다르므로 라벨로 구분돼야 한다."""
    points = _build_action_points(
        conv_rate=25.0, m1_recent=10.0, p50_num=None,
        mom_pct=None, cohort_trend={},
    )
    # M+1 메시지: '한 달 안' 포함, 라벨은 (M+1 코호트)
    m1_msg = next((p for p in points if "한 달 안" in p), "")
    assert "(M+1 코호트)" in m1_msg, f"M+1 라벨 누락: {m1_msg}"
    # 60일 메시지: '60일' 포함, 라벨은 (완결 코호트 누적)
    conv_msg = next((p for p in points if "60일" in p), "")
    assert "(완결 코호트 누적)" in conv_msg
