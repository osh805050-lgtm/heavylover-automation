# HeavyLover 자동화 시스템 전체 요약

> 최종 업데이트: 2026-04-29 · 상태: 전체 가동 중 (3회 점검 통과)

---

## 1. 자동화 파이프라인 전체 구조

```
매일 04:00  →  카페24 OAuth 자동 갱신
매일 08:30  →  주문 시트 동기화 (카페24 + 스마트스토어)
매일 09:00  →  재구매 마트 4종 갱신 + ground truth 저장
매일 09:05  →  텔레그램 📊리포트봇: 재구매 30초 요약
매일 09:10  →  이메일 3명: 일일 심층 분석 (4블록 + 차트 4장 + KPI 카드)
일요일 21:00 → 이메일 3명: 주간 멀티 에이전트 분석 (4회 왕복)
매월 1일 09:30 → 이메일 3명: 월간 액션 권고 (5회 왕복)
평일 11:00  →  🛒운영봇: 발주 엑셀 생성 + 텔레그램 승인 플로우
평일 13:00  →  🛒운영봇: 송장 자동 등록 (카페24 + 스마트스토어)
```

---

## 2. 서버 구조

| 항목 | 내용 |
|---|---|
| 서버 | Vultr 158.247.215.170 (Ubuntu 22.04) |
| 재구매 자동화 | `/root/heavylover-repurchase/` |
| 운영 자동화 | `/root/heavylover-automation/` |
| 배포 방식 | GitHub push → `.github/workflows/deploy-vultr.yml` 자동 배포 |
| Python 환경 | 각 폴더별 `venv/` |

---

## 3. 이메일 수신자

| 주소 | 용도 |
|---|---|
| osh805050@gmail.com | 업무 주력 |
| ohkm8050@naver.com | 정부지원 알림 수신 전용 |
| musclecipe@naver.com | 2026-04-29 추가 |

`.env` `EMAIL_TO` 키에 콤마 구분으로 3개.

---

## 4. 텔레그램 봇 4채널

| 채널 키 | 봇 이름 | 받는 알림 |
|---|---|---|
| `ops` | @heavyrover_order_osh_bot | 발주·송장·OAuth 갱신·자동화 오류. 승인 응답(`/done`, `/cancel`) 전용 |
| `report` | @Heavyrover_purchase_report_bot | 매일 09:05 재구매 30초 요약 |
| `ads` | @Heavyrover_ads_bot | Meta 광고 일일/주간 KPI |
| `govt` | @heavyrover_gov_bot | 정부지원 레이더 적합 공고 |

**신규 봇 추가 시**: BotFather `/newbot` → 봇 채팅창에 메시지 1통 → `.env`에 토큰 추가 → `python tools/setup_telegram_bots.py` (로컬에서 실행) → Vultr `.env` 2곳 동기화.

**토큰 보안**: 토큰은 채팅에 절대 붙여넣지 말 것. `.env` 파일 직접 수정 후 알려주면 Claude가 Vultr 동기화 처리.

---

## 5. 재구매 분석 리포트

### 일일 메일 (매일 09:10)
- **구조**: 📌핵심 1줄 → 📊숫자 현황 → 🤔이유 → ✅오늘 할 일
- **특징**: 비전공자 친화적 (전문 용어 풀어쓰기), 800~1200자
- **차트 4장**: 월별 코호트, 채널별 전환율, M+1 리텐션 곡선, 지난주 대비 변화
- **KPI 카드**: 메일 상단 4지표 카드 (🟢🟡🔴 색상 자동 판정)
- **약어 규칙**: WoW·MoM·YoY·P50·MTD는 풀어쓰기. M+1·CAC·LTV·AOV·CTR·CPA는 약어 유지.

### 주간 메일 (일요일 21:00)
- **구조**: 4회 왕복 멀티 에이전트 (전략가 → 회의주의자 → 전략가 → 회의주의자 → 전략가 최종)
- **포함 섹션**: 핵심 변화 3개, 원인 가설, 다음 주 우선순위 3개, 의사결정 트리(IF-THEN), 다음 주 추적 KPI 대시보드
- **차트 5장**: 일일 4장 + 주간 매출 시계열

### 월간 메일 (매월 1일 09:30, 첫 발송 2026-05-01)
- **구조**: 5회 왕복 (전월 vs 이번달 현재까지 심층 분석)
- **포함 섹션**: 전월 마감 vs 전전월 비교, 이번달 현재 신호, 3대 액션 (예상효과·검증방법·실패시 대안·재무영향)

---

## 6. 운영 자동화 (발주·송장)

### 발주 자동화 (평일 11:00)
1. 카페24(7일치 N20) + 스마트스토어(14일치 PAYED 전수) 주문 조회
2. 신규 주문 또는 특이사항 있으면 🛒운영봇으로 알림 + 승인 대기
3. `/done` 응답 시 더다 엑셀 자동 생성 → OneDrive 업로드 + 텔레그램 파일 전송

### 송장 자동화 (평일 13:00)
1. `/tracking` 명령 폴링 → 바탕화면 OneDrive에서 더다 엑셀 자동 감지
2. 운영봇 승인 요청 → `/done` 응답 시 카페24·스마트스토어 자동 등록

---

## 7. Google Sheets 구조

### 데이터 탭 (sync 대상)
| 탭 이름 | 내용 |
|---|---|
| 카페24 재구매매출 | 카페24 주문 원본 (5상태 전체) |
| 스마트스토어 재구매매출 | SS 주문 원본 (5상태 전체) |

### 마트 탭 (Looker Studio 연결용, 매일 09:00 자동 갱신)
| 탭 이름 | 내용 |
|---|---|
| mart_monthly | 월별 재구매 매출·전환율 |
| mart_cohort | 코호트별 M+1~M+6 잔존율 |
| mart_stage | 채널별 1→2·2→3 전환율 |
| mart_summary | 핵심 지표 요약 + 벤치마크 |

---

## 8. Anthropic API 비용 (월 기준)

| 항목 | 빈도 | 월 비용 |
|---|---|---|
| 일일 4블록 분석 (1회 호출) | 매일 | ~$3.0 |
| 주간 멀티 에이전트 (4회 왕복) | 주 1회 | ~$2.1 |
| 월간 액션 (5회 왕복) | 월 1회 | ~$1.7 |
| 텔레그램 30초 요약 | 매일 | $0 (API 호출 없음) |
| **합계** | | **~$6.8/월** |

모델: `claude-opus-4-7`

---

## 9. 점검 결과 (2026-04-29)

3회 반복 점검 결과:

| 항목 | 결과 |
|---|---|
| Vultr cron 9개 | ✅ 전체 등록 |
| Google Sheets 연결 | ✅ 27탭, 카페24 2,275건·SS 6,637건 |
| 카페24 OAuth | ✅ 정상 |
| 스마트스토어 API | ✅ 정상 |
| Anthropic API | ✅ 정상 |
| 시트 sync 3회 (행수 안정) | ✅ errors=[] |
| 마트 4종 갱신 3회 | ✅ issues=[] |
| 텔레그램 brief 3회 | ✅ 4채널 모두 발송 |
| 일일 메일 3회 | ✅ 3명 수신 확인 |

---

## 10. 주요 파일 위치

```
heavylover-automation/
├── sheets_sync.py          ← 주문 시트 동기화 (카페24 + SS)
├── repurchase_report.py    ← 마트 4종 갱신 + ground truth 저장
├── report_telegram_brief.py ← 텔레그램 30초 요약 (09:05)
├── report_email_daily.py   ← 일일 심층 메일 (09:10)
├── report_email_weekly.py  ← 주간 멀티 에이전트 메일 (일요일 21:00)
├── report_email_monthly.py ← 월간 액션 메일 (매월 1일 09:30)
├── run_automation.py       ← 발주 자동화 (평일 11:00)
├── tracking_register.py    ← 송장 자동화 (평일 13:00)
├── refresh_cafe24_token.py ← OAuth 자동 갱신 (매일 04:00)
├── telegram_client.py      ← 4채널 봇 라우터
├── email_sender.py         ← SMTP 멀티캐스트 (inline_images 지원)
├── lib/
│   ├── charts.py           ← matplotlib 차트 5종 (PNG bytes)
│   ├── kpi_cards.py        ← KPI 카드 HTML (🟢🟡🔴)
│   ├── historical_data.py  ← 7일 누적 + 이상치 감지
│   └── recommendation_log.py ← 액션 권고 누적 (JSONL)
└── tools/
    └── setup_telegram_bots.py ← 봇 chat_id 자동 추출 (로컬 실행)
```

---

## 11. 장애 대응

| 증상 | 원인 | 해결 |
|---|---|---|
| 텔레그램 메시지 안 옴 | 토큰 401 | BotFather `/revoke` → 새 토큰 → `.env` 직접 수정 → Vultr 동기화 |
| 메일 안 옴 | SMTP 앱 비밀번호 만료 | Gmail 앱 비밀번호 재발급 → `.env` SMTP_PASSWORD 갱신 |
| 시트 sync 실패 | Cafe24 OAuth 만료 | `python refresh_cafe24_token.py` 수동 실행 |
| 재구매 마트 0행 | 시트 탭 이름 변경 | `repurchase_report.py` `name_map` 딕셔너리 탭 이름 수정 |
| Anthropic 401 | API 크레딧 소진 | console.anthropic.com 충전 → fallback(원시 숫자) 자동 발송 중 |
