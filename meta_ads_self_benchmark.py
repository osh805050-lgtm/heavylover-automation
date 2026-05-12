"""자사 동적 벤치마크 — daily.csv에서 P25/P50/P75."""

import statistics
from datetime import datetime, timedelta, timezone

import meta_ads_history

KST = timezone(timedelta(hours=9))
MIN_DAYS_FOR_BENCHMARK = 14
METRICS = ["ctr_pct", "cpc_krw", "frequency", "cpa_krw", "roas"]


def _parse_float(v):
    if v in ("", None):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _quantile(values, q):
    if len(values) < 2:
        return None
    qs = statistics.quantiles(values, n=4, method="inclusive")
    if q == 0.25:
        return qs[0]
    if q == 0.5:
        return qs[1]
    if q == 0.75:
        return qs[2]
    return None


def compute(metric, window=30):
    rows = meta_ads_history.load_recent_account(days=window)
    zero_excl = metric in ("roas", "cpa_krw")
    values = [v for v in (_parse_float(r.get(metric)) for r in rows)
              if v is not None and (not zero_excl or v > 0)]
    n = len(values)

    if n < MIN_DAYS_FOR_BENCHMARK:
        return {
            "ok": False, "n": n,
            "p25": None, "p50": None, "p75": None,
            "window": window, "metric": metric,
            "reason": f"데이터 누적 중 ({n}/{MIN_DAYS_FOR_BENCHMARK}일)",
        }

    return {
        "ok": True, "n": n,
        "p25": _quantile(values, 0.25),
        "p50": _quantile(values, 0.5),
        "p75": _quantile(values, 0.75),
        "window": window, "metric": metric,
        "reason": None,
    }


def compute_all(window=30):
    return {m: compute(m, window=window) for m in METRICS}


def format_self_bench_cell(metric, actual, bench, higher_better=True):
    if not bench["ok"]:
        return bench["reason"]
    p50 = bench.get("p50")
    if p50 is None or actual is None:
        return f"P50 없음 (n={bench['n']})"

    suffix_map = {
        "ctr_pct": "%", "cpc_krw": "원", "cpa_krw": "원",
        "frequency": "", "roas": "",
    }
    suffix = suffix_map.get(metric, "")
    if metric in ("ctr_pct", "frequency", "roas"):
        p50_str = f"{p50:,.2f}{suffix}"
    else:
        p50_str = f"{int(round(p50)):,}{suffix}"

    if actual is None:
        verdict = ""
    else:
        ratio = actual / p50 if p50 else 1.0
        if higher_better:
            if ratio >= 1.1:
                verdict = " 평균↑"
            elif ratio <= 0.9:
                verdict = " 평균↓"
            else:
                verdict = " 평균"
        else:
            if ratio <= 0.9:
                verdict = " 평균↑"
            elif ratio >= 1.1:
                verdict = " 평균↓"
            else:
                verdict = " 평균"

    return f"{p50_str} (자사 P50, n={bench['n']}{verdict})"


if __name__ == "__main__":
    for m, b in compute_all(window=30).items():
        if b["ok"]:
            print(f"  {m}: P25={b['p25']:.3f} P50={b['p50']:.3f} P75={b['p75']:.3f} (n={b['n']})")
        else:
            print(f"  {m}: {b['reason']}")
