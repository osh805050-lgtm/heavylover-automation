# 기술 인프라

> 이 파일은 [automation-debugger 시작 시 / 자동화 코드 수정 시 / crontab 관련 작업 시 / "재구매 분석 파이프라인" 질의 시] 로드됩니다. CLAUDE.md §5의 정본입니다.
> 마지막 갱신: 2026-04-29 · 갱신 주기: 자동화 변경 발생 시 즉시
> 운영 가이드 상세: `docs/deploy-repurchase-cron.md`, `docs/setup-repurchase-automation.md`, `docs/looker-studio-repurchase-dashboard.md`

## CRM (자체 구축, 핵심 자산)
- 파일: `repurchase_v5_4.gs` (Google Apps Script)
- 19개 분석 시트: 원본·시계열(일/주/월)·코호트(30/60/90일, M+1~M+12)·간격(P50/75/90/95)
- 고객 식별:
  - Cafe24: 주문자 휴대전화번호 (5컬럼 포맷 col 5)
  - 스마트스토어: 구매자ID (col 9)
  - Imweb: 수동 import (노란색 배경)
- 날짜 기준: 결제일
- 금액 기준: **총 상품구매금액** (네이버 포인트·자체 쿠폰은 판매자 비용)
- 취소 필터: 취소/환불/반품 (교환은 유지)

## 플랫폼 API (2026-04-23)
- **Cafe24**: OAuth 완료 (`mall.read_order` + `mall.write_order`)
- **스마트스토어**: Vultr 프록시(158.247.215.170:8443) 경유
- **PlusCL**: Open API 존재. `/open/item_out` 출고서 조회. 인증값 5개 발급 대기
- **Meta Ads**: API → Apps Script 트리거 → 시트 append (구축 예정)

## 주문 자동화 파이프라인
- 실행: Vultr (158.247.215.170, Ubuntu 22.04) 24시간
- 코드: 로컬 `heavylover-automation/`, 서버 `/root/heavylover-automation/`
- 핵심 파일: `run_automation.py`, `cafe24_client.py`, `naver_client.py`, `dada_excel.py`, `telegram_client.py`, `tracking_register.py`
- Cron:
  - `0 11 * * 1-5` → 엑셀 + OneDrive + 텔레그램
  - `0 13 * * 1-5` → PlusCL 송장 → 카페24/SS 자동 등록
- OneDrive: rclone "더다 양식" 폴더 자동 업로드
- 텔레그램: `@heavyrover_order_osh_bot`, `/done`·`/cancel` 승인
- 프록시: Squid 8443, 자동 재시작
- 택배사: 로젠 (단일)
  - 카페24: `0004` (이 몰에서 `0001`은 자체배송)
  - 네이버: `KGB` (합병 이력으로 `LOGEN` 무효)
  - PlusCL `tran_comp_code` 사용 불필요

## 자동화 상태
| 기능 | 상태 |
|---|---|
| 11시 엑셀 생성 | ✅ |
| OneDrive 업로드 | ✅ |
| 텔레그램 승인 | ✅ |
| 13시 송장 등록 | ⏳ PlusCL 인증 5개 대기 |
| 카페24 N10→N20 전환 | 수동 (API 불가) |
| SS 신규→발주확인 | 수동 (API 한계) |
| 08:30 시트 sync (Vultr `/root/heavylover-repurchase/`) | ✅ **매일** (주말 포함). 카페24 + SS 5상태(구매확정·결제완료·발송·배송중·배송완료) |
| 09:00 재구매 리포트 + 마트 4종 갱신 | ✅ **매일** mart_monthly/cohort/stage/summary 시트 자동 갱신 + 텔레그램 (Anthropic 401 시 fallback 원시 숫자) |
| 04:00 카페24 OAuth 자동 갱신 | ✅ **매일** refresh_token 만료 방지. 실패 시 텔레그램 알림 |

## 재구매 분석 자동화 파이프라인 (2026-04-28 검증 완료)

**위치**: Vultr `/root/heavylover-repurchase/` (GitHub clone, git pull로 코드 동기화)
**별도 폴더 이유**: 11시 발주·13시 송장 자동화(`/root/heavylover-automation/`)와 분리 — 한쪽 깨져도 영향 X

**Cron (매일, 주말 포함)**:
- `0 4 * * *` → `refresh_cafe24_token.py` (OAuth 자동 갱신, 실패 시 텔레그램)
- `30 8 * * *` → `sheets_sync.py` (카페24 + SS 시트 갱신)
- `0 9 * * *` → `repurchase_report.py` (분석 탭 추출 + 마트 4종 갱신 + 텔레그램)

**카페24 sync 정책**:
- 컬럼 5개: 주문번호 / 결제일시 / 주문상태 / 실결제금액 / 휴대전화
- 고객 식별 = 휴대전화 (col 5)
- 윈도우 7일, cutoff에 ` 00:00` 부착해 시간대 누락 방지
- 5튜플 키로 완전중복 dedupe
- **0원 주문 정가 대체** (2026-04-29): 100% 할인 주문은 `payment_amount=0` → `items[].product_price × quantity` 합산으로 정가 기록. `embed=items` 이미 사용 중이라 추가 API 호출 없음. AOV·재구매 매출 왜곡 방지.

**SS sync 정책**:
- 컬럼 46개 (상세)
- 고객 식별 = 구매자ID (col 9)
- 5상태 모두 수집: PURCHASE_DECIDED · PAYED · DISPATCHED · DELIVERING · DELIVERED
- 취소/반품/미결제는 원천 제외
- 24시간 윈도우 한계 우회: 1일씩 잘라 N×5번 호출 + RATE_LIMIT 시 5초 대기 재시도
- productOrderId 기준 reverse-dedupe (최신 상태 우선)
- 결제일은 `order.paymentDate` (productOrder 아님 — 과거 버그 원인)

**시트 탭 구조 (2026-04-29 정리 완료)**:

| 탭 | 상태 | 용도 |
|---|---|---|
| `카페24 재구매매출` | 숨김 (맨 뒤) | 원본 보존용 |
| `스마트스토어 재구매매출` | 숨김 (맨 뒤) | 원본 보존용 |
| `재구매_통합_월별` | 표시 | 월별 매출 KPI |
| `코호트_통합_전환율` | 표시 | 1→2 코호트 전환 |
| `코호트_월별잔존율` | 표시 | M+N 리텐션 히트맵 |
| `재구매_간격분석` | 표시 | P50/P90 |
| `재구매_카페24_월별` 外 채널별 6개 | 숨김 | 중복, 통합 탭으로 커버 |
| `코호트_고객마스터` | 숨김 | 원본 보존용 |
| `Meta_Ads_Daily/Campaign/Winners` | 숨김 | 별도 Meta 시트에서 관리 |
| `mart_monthly/cohort/stage/summary` | 숨김 | 내부 BI용 (대시보드로 대체) |
| **`📊 대시보드`** | **표시 (맨 앞)** | **경영자용 — 매일 09:00 자동 갱신** |

**`📊 대시보드` 탭 구성**:
- KPI 카드 4개: 재구매 매출(전월 대비 ▲▼) · 첫 구매→재구매 전환율 · 한 달 후 재구매율 · 재구매 평균 주기
- 월별 재구매 추이 6개월 (만원 단위, 전월 대비 % 자동 계산)
- 첫 구매→재구매 전환율 6개월 (30일/60일, 판정 색상)
- 재구매 유지율 3코호트 히트맵 (각 셀 🟢/🟡/🔴 배경색)
- 지금 봐야 할 것 (KPI 기반 액션 포인트 자동 생성, 전문용어 없이 한글 문장)
- 섹션 헤더: 연파란 배경 볼드, 열 너비 자동 조정

**`repurchase_report.py` 09:00 실행 순서**:
1. 마트 4종 갱신 (mart_monthly/cohort/stage/summary)
2. 숨김 대상 탭 일괄 처리 (batch_update 1회)
3. `📊 대시보드` 갱신 + 셀 포맷 적용 (배경색·볼드·autoResize)

**검증 (3회 연속 실행)**: 카페24 2272행 안정, SS 6644행 안정, productOrderId 중복 0, 누락·오류 없음.

**알려진 한계**:
- Anthropic API 401 (결제 카드 미등록) → 매일 09:00 텔레그램은 Claude 분석 대신 fallback 원시 숫자
- Apps Script 19개 분석 탭은 시간 트리거 미설정 → 승현님이 가끔 수동 ▶ 실행 (또는 시트 → 확장 프로그램 → Apps Script → 트리거 추가로 자동화 가능)
- 카페24 + SS 통합 분석 시 같은 사람이 두 채널에서 산 건 다른 사람으로 잡힘 (식별 체계 다름)

## 엑셀 생성 로직 (상태 기반 전수 — 누락 0건 보장)
- **카페24**: `fetch_orders(days_back=7)` → `order_status=N20`만 포함
- **스마트스토어**: `orders_pending_dispatch(days_back=14)` — PAYED 상태 전수 조회
  - 14일 1일 분할 N회 호출 + productOrderId dedupe (24h 윈도우 한계 우회)
  - 상세 후 `productOrderStatus=='PAYED'`만 (이미 발송된 건 자동 배제)
  - 며칠 전 결제분·발송기한 초과(`shippingDueDate < now`)분 모두 포함 → 텔레그램에 별도 카운트 노출
- 템플릿 복제 (`shutil.copy2`) → 서식·열너비·숨김컬럼 보존
- 파일명: `더다냉동물류 발주양식 YY.M.D.xlsx`

## 코딩 도구
- 메인: Claude Code + Google Apps Script
- 검토: Lovable (0→1), Cursor (1→프로덕션) — 효율 입증 시 도입
- SaaS 스택 확정: Next.js + Supabase + Stripe + Vercel

## 작업 환경
- OS: Windows (WSL2 권장 받음)
- 폴더: `heavylover-automation`
- 실행: PowerShell/.bat → `cd {폴더}` → `claude`
