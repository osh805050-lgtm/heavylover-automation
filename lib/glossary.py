"""리포트 용어 풀이 — 텔레그램·이메일 공용.

약어를 처음 보는 비전공자도 즉시 이해할 수 있도록
모든 리포트에서 이 모듈을 통해 표기를 통일한다.
"""
from __future__ import annotations

# 약어 → (한국어 표기, 괄호 풀이)
# 표·카드 등 공간 좁은 곳: 한국어 표기만
# 본문 첫 등장 시: "한국어 표기(약어)" 형식
TERMS: dict[str, tuple[str, str]] = {
    "MoM":   ("전월대비",          "지난달과 이번달 비교"),
    "WoW":   ("전주대비",          "지난주와 이번주 비교"),
    "P50":   ("재구매 간격 중앙값", "고객 절반이 이 기간 안에 다시 구매"),
    "P25":   ("빠른 재구매 25%",   "상위 25% 고객의 재구매 간격"),
    "P75":   ("느린 재구매 25%",   "하위 25% 고객의 재구매 간격"),
    "M+1":   ("한달 재구매율",     "첫 구매 후 한 달 안에 다시 산 고객 비율"),
    "M+2":   ("두달 재구매율",     "첫 구매 후 두 달 안에 다시 산 고객 비율"),
    "벤치":  ("업계 평균",         "동종 D2C 식품 업계 기준값"),
    "ROAS":  ("광고 수익률",       "광고 1원을 쓸 때 돌아오는 매출"),
    "CPA":   ("고객 확보 비용",    "고객 1명을 사는 데 드는 광고비"),
    "CPC":   ("클릭 비용",         "광고를 클릭 1번 받는 데 드는 비용"),
    "CTR":   ("클릭률",            "광고를 본 사람 중 클릭한 비율"),
    "AOV":   ("평균 주문금액",     "고객 1회 구매 평균 금액"),
    "LTV":   ("고객 생애가치",     "고객 1명이 평생 가져다 줄 예상 매출"),
    "CAC":   ("고객 획득 비용",    "고객 1명 유치에 드는 전체 비용"),
    "D2C":   ("자체 직판",         "중간 유통 없이 브랜드가 소비자에게 직접 판매"),
}


def label(key: str) -> str:
    """표·카드용 한국어 짧은 표기. 없으면 key 그대로."""
    return TERMS.get(key, (key, ""))[0]


def inline(key: str) -> str:
    """본문 첫 등장용 — '한국어(약어)' 형식."""
    if key not in TERMS:
        return key
    ko, _ = TERMS[key]
    return f"{ko}({key})"


def tooltip(key: str) -> str:
    """풀이 설명 문장. 없으면 빈 문자열."""
    return TERMS.get(key, ("", ""))[1]


def glossary_details_html() -> str:
    """이메일 본문에 삽입할 접이식 용어 안내 박스 HTML.
    <details> 태그 — 이미 아는 사람은 무시, 처음 보는 사람은 클릭해서 확인.
    """
    rows = []
    priority = ["MoM", "WoW", "P50", "M+1", "벤치", "ROAS", "CPA", "AOV"]
    for k in priority:
        if k not in TERMS:
            continue
        ko, desc = TERMS[k]
        rows.append(
            f"<tr>"
            f"<td style='padding:4px 10px;font-weight:bold;color:#2c3e50;white-space:nowrap;'>{k}</td>"
            f"<td style='padding:4px 10px;color:#444;'>{ko} — {desc}</td>"
            f"</tr>"
        )
    table = (
        "<table style='border-collapse:collapse;width:100%;font-size:13px;'>"
        + "".join(rows)
        + "</table>"
    )
    return (
        "<details style='margin:8px 0 16px 0;'>"
        "<summary style='cursor:pointer;font-size:12px;color:#888;padding:4px 0;'>"
        "📖 이 메일에 나오는 용어 (클릭하면 펼쳐집니다)</summary>"
        f"<div style='background:#f8f9fa;border-radius:4px;padding:8px;margin-top:6px;'>{table}</div>"
        "</details>"
    )
