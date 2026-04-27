# Meta 광고 업계 벤치마크 (2026년, 한국 D2C 식품)

리포트 비교 기준. `meta_ads_report.py`의 `BENCHMARK` 상수와 동기화 유지.

| 지표 | 업계 평균 | 우수 기준 |
|------|-----------|-----------|
| CTR | 1.2% | 2.0%+ |
| CPC | 700원 | 500원 이하 |
| ROAS | 2.5 | 4.0+ |
| CPA | 30,000원 | 20,000원 이하 |
| Frequency | 2~4 | 1.5~3 |

## 자동 플래그 조건

- Frequency > 5 → 크리에이티브 피로
- CPA > 벤치마크 × 1.5 → 오디언스·크리에이티브 재검토
- ROAS < 2.0 → 캠페인 일시 정지 검토
- 노출 < 1,000 + 지출 발생 → Learning Limited 의심

## 리포트 주기

- 매일 09:00 KST (GitHub Actions cron `0 0 * * *` UTC)
- 전일 데이터 기준 (KST 자정~자정)
- 출력: `docs/meta-ads/reports/{YYYY-MM-DD}.md` + 텔레그램 요약
