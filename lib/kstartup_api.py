"""K-Startup 공식 Open API 클라이언트 (공공데이터포털)

엔드포인트: getAnnouncementInformation01 (사업공고 조회)
인증: data.go.kr 발급 인증키 (DATA_GO_KR_API_KEY)
응답: JSON, 풍부한 메타데이터 (공고명, 모집기간, 자격, 신청방법, 상세URL)

사용:
    from lib.kstartup_api import fetch_announcements
    items = fetch_announcements(per_page=50, only_recruiting=True)
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent.parent / ".env"
API_URL = "https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01"
KST = timezone(timedelta(hours=9))

log = logging.getLogger(__name__)


def _get_key():
    load_dotenv(ENV_PATH, override=True)
    key = os.getenv("DATA_GO_KR_API_KEY")
    if not key:
        raise RuntimeError(
            "DATA_GO_KR_API_KEY가 .env에 없습니다. "
            "docs/govt-radar/04-public-data-api.md 참고."
        )
    return key


def _yyyymmdd_to_iso(s):
    """20260517 → 2026-05-17"""
    if not s or not isinstance(s, str) or len(s) != 8:
        return None
    try:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    except (ValueError, IndexError):
        return None


def _normalize(item):
    """K-Startup API 응답 → 공통 스키마"""
    title = item.get("biz_pbanc_nm") or item.get("intg_pbanc_biz_nm") or ""
    deadline = _yyyymmdd_to_iso(item.get("pbanc_rcpt_end_dt"))
    posted = _yyyymmdd_to_iso(item.get("pbanc_rcpt_bgng_dt"))
    detail_url = item.get("detl_pg_url") or ""

    # 상세 본문 (적합도 점수에 활용)
    body_parts = []
    for k in ["pbanc_ctnt", "aply_trgt_ctnt", "supt_biz_clsfc", "biz_enyy"]:
        v = item.get(k)
        if v:
            body_parts.append(str(v))
    body = " ".join(body_parts)

    agency = item.get("pbanc_ntrp_nm") or item.get("biz_prch_dprt_nm") or "창업진흥원"

    return {
        "source": "K-Startup(API)",
        "title": title.strip(),
        "url": detail_url,
        "agency": agency,
        "deadline": deadline,
        "posted_date": posted,
        "body_excerpt": body[:1000],
        "raw": {
            "pbanc_sn": item.get("pbanc_sn"),
            "supt_regin": item.get("supt_regin"),
            "supt_biz_clsfc": item.get("supt_biz_clsfc"),
            "biz_enyy": item.get("biz_enyy"),
            "rcrt_prgs_yn": item.get("rcrt_prgs_yn"),
        },
    }


def fetch_announcements(per_page=100, max_pages=3, only_recruiting=True):
    """K-Startup 사업공고 조회.

    Args:
        per_page: 페이지당 건수 (최대 100 권장)
        max_pages: 최대 페이지 수 (300건이면 충분)
        only_recruiting: rcrt_prgs_yn=Y만 (모집 진행 중)

    Returns:
        list[dict]: 공통 스키마 형식
    """
    key = _get_key()
    results = []
    seen_sn = set()

    for page in range(1, max_pages + 1):
        try:
            r = requests.get(
                API_URL,
                params={
                    "serviceKey": key,
                    "page": page,
                    "perPage": per_page,
                    "returnType": "json",
                },
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning(f"K-Startup API 페이지 {page} 실패: {e}")
            break

        items = data.get("data", [])
        if not items:
            break

        for it in items:
            if only_recruiting and it.get("rcrt_prgs_yn") != "Y":
                continue
            sn = it.get("pbanc_sn")
            if sn and sn in seen_sn:
                continue
            seen_sn.add(sn)
            results.append(_normalize(it))

        if len(items) < per_page:
            # 마지막 페이지
            break

    return results


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    items = fetch_announcements(per_page=100, max_pages=3, only_recruiting=True)
    print(f"=== K-Startup 모집 진행 중 공고 {len(items)}건 ===\n")
    for it in items[:10]:
        print(f"[{it['deadline'] or '?'}] {it['title'][:70]}")
        print(f"  지역: {it['raw'].get('supt_regin') or '-'} | 분류: {it['raw'].get('supt_biz_clsfc') or '-'}")
        print(f"  자격: {it['raw'].get('biz_enyy') or '-'}")
        print(f"  URL: {it['url']}")
        print()
