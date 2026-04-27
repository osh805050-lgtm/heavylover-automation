# Meta 광고 일일 리포트

> 이 파일은 [meta-ads-analyst 서브에이전트 시작 시 / Meta 광고 분석·전략 결정 시 / 일일 09:00 자동 리포트 검토 시] 로드됩니다. CLAUDE.md §8의 정본입니다.
> 마지막 갱신: 2026-04-28 · 갱신 주기: 분기 1회 (벤치마크 변동 시 즉시)
> 자동화 코드 동기 정본: `docs/meta-ads/benchmarks.md` (`meta_ads_report.py`의 `BENCHMARK` 상수와 동기화), 설정: `docs/meta-ads/SETUP.md`, 일일 출력: `docs/meta-ads/reports/{YYYY-MM-DD}.md`

## 스케줄
- 매일 오전 11:00 요약 (수동 검토용 — Claude Code 작업 시)
- 자동 09:00 KST 텔레그램 요약 (GitHub Actions cron `0 0 * * *` UTC, 전일 KST 자정~자정 데이터)

## 필수 지표
- CPC, CTR, 전환율, ROAS, CPA — 각각 **업계 평균 대비 비교 컬럼** 필수

## 벤치마크 (2026, 한국 D2C 식품)
| 지표 | 평균 | 우수 |
|---|---|---|
| CTR | 1.2% | 2.0%+ |
| CPC | 700원 | 500원- |
| ROAS | 2.5 | 4.0+ |
| CPA | 30,000원 | 20,000원- |
| Frequency | 2~4 | 1.5~3 |

> 벤치마크 수치 변경 시 `docs/meta-ads/benchmarks.md` + `meta_ads_report.py` `BENCHMARK` 상수 함께 갱신.

## 자동 플래그
- Learning Limited → 예산·타겟 확장 제안 (노출 < 1,000 + 지출 발생 시 의심)
- Frequency > 5 → 크리에이티브 피로
- CPA > 벤치 ×1.5 → 오디언스·크리에이티브 재검토
- ROAS < 2.0 → 일시 정지 검토
- CAPI ↔ Pixel 편차 > 20% → 이벤트 정합성 점검

## 전략
- CBO Broad (메인) + ABO (크리에이티브 테스트)
- Broad > Lookalike (확정)
- CAPI 서버사이드 (Cafe24) 우선
- ASC 활성화: 주 50+ 전환, CAPI 중복 제거, 10~15 크리에이티브, 30일 ROAS 안정 시
- 스케일업: 월 500만 → 5,000만

## 기록
- 일일: Google Sheets (마스터 DB)
- 액션·이유: Notion 결정 로그
