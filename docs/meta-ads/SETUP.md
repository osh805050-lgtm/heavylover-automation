# Meta 광고 일일 리포트 — 설정 가이드

## 0. 자동화 전체 구조 (2026-04-27 갱신)

```
[Meta Graph API]
   ↓ 매일 09:00 KST
[meta_ads_report.py] ── 캠페인별 fetch ─→ [meta_ads_history]
   │                                        ├─ data/meta_ads/daily.csv
   │                                        ├─ data/meta_ads/daily_campaign.csv
   │                                        ├─ data/meta_ads/raw/{date}.json
   │                                        └─ Google Sheets (Meta_Ads_Daily 등)
   ├─ self_benchmark (자사 P25/P50/P75, 14일+ 누적 시 활성)
   ├─ claude_comment (Anthropic API 호출)
   ├─→ 텔레그램: 5줄 요약 + Claude 액션 3개
   └─→ 이메일: HTML 심층 분석 (벤치 비교 + 캠페인별 + 추세 + Claude 분석)

[매주 월요일 09:00 KST]
[meta_ads_winner_patterns.py]
   ├─ ROAS 상위 25% 식별
   ├─ 캠페인명에서 타겟·후킹 추출
   ├─ Claude가 "기획 가설" 1줄 생성
   └─→ data/meta_ads/winner_patterns.jsonl + Meta_Ads_Winners 시트
        (Phase 5 자동 카피 생성의 컨텍스트로 누적 활용)
```

## 0.5. 사전 체크리스트 (필수 먼저 확인)

- [ ] **Meta Pixel 5종 발화 확인**: Events Manager → 지난 7일에 PageView·ViewContent·AddToCart·InitiateCheckout·Purchase 모두 들어오는지. **Purchase 없으면 ROAS·CPA가 전부 "데이터 없음"으로 떨어진다.**
- [ ] **Anthropic API 키 보유** (정부지원 레이더용 키 그대로 재사용 가능)
- [ ] **Google Sheets 1장 준비** (제목 자유, 예: "HeavyLover Meta Ads")
- [ ] **GCP 서비스 계정 키** (재구매 분석용 키와 별개로 관리하려면 새로 발급, 같이 써도 무방)

---


## 1. Meta Marketing API 토큰 발급

1. https://developers.facebook.com/apps/ 에서 앱 생성 (또는 기존 앱 사용)
2. **Marketing API** 제품 추가
3. **System User** 생성 (비즈니스 관리자 → 시스템 사용자)
   - 권한: `ads_read` (리포트만 필요)
   - 광고 계정 할당 (HeavyLover 광고 계정)
4. System User에서 **장기 토큰** 발급 (만료 없음 권장)
5. 광고 계정 ID 확인 (광고 관리자 URL의 `act_123456789` 중 숫자 부분)

## 2. GitHub Secrets 등록

GitHub 저장소 → Settings → Secrets and variables → Actions → **New repository secret**

| Name | Value | 용도 |
|------|-------|------|
| `META_ACCESS_TOKEN` | System User 토큰 | Meta API 호출 |
| `META_AD_ACCOUNT_ID` | 숫자만 (예: `123456789`) | 광고 계정 |
| `TELEGRAM_BOT_TOKEN` | `.env`와 동일 | 일일 요약 알림 |
| `TELEGRAM_CHAT_ID` | `.env`와 동일 | 일일 요약 알림 |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Claude 액션 코멘트 (없으면 코멘트 생략, 워크플로우는 정상) |
| `GOOGLE_SHEETS_ID` | 시트 URL의 /d/{ID}/edit 부분 | 일별 데이터 누적 |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | 서비스 계정 키 JSON 통째로 (또는 Base64) | 시트 인증 |
| `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`, `EMAIL_TO` | Gmail 앱 비밀번호 등 | 일일 심층 이메일 |

(선택) Variables 탭에서 `META_API_VERSION=v21.0` 설정. 미설정 시 기본값 사용.

### `GOOGLE_SERVICE_ACCOUNT_JSON` 등록 팁
- GitHub Secrets에 JSON 원본을 붙여넣을 때 줄바꿈이 깨지면 인증 실패. **Base64 인코딩 권장.**
- Windows PowerShell에서:
  ```powershell
  [Convert]::ToBase64String([IO.File]::ReadAllBytes("gcp-key.json"))
  ```
  결과 문자열을 Secret에 그대로 등록. 코드가 자동으로 Base64 디코딩 시도.
- **시트 공유 권한**: 서비스 계정 JSON의 `client_email` (예: `xxx@yyy.iam.gserviceaccount.com`) 을 시트 공유 권한(편집자)에 추가 필수. 안 하면 "시트 연결 실패: PERMISSION_DENIED".

## 3. 로컬 테스트

`.env`에 모든 키 추가 (`.env.example` 참고):

```
META_ACCESS_TOKEN=...
META_AD_ACCOUNT_ID=123456789
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_SHEETS_ID=...
GOOGLE_SERVICE_ACCOUNT_JSON=./gcp-key.json   # 또는 JSON 원본 또는 Base64
EMAIL_TO=osh805050@gmail.com
SMTP_USER=osh805050@gmail.com
SMTP_PASSWORD=...
```

단계별 검증:

```bash
# 1. Meta API 연결
python meta_ads_client.py
# → ok=True, valid=True 떠야 정상

# 2. 시트 연결
python meta_ads_sheets_client.py
# → "OK — '시트명' / 워크시트: [...]" 떠야 정상

# 3. 자사 벤치 (초기엔 데이터 부족 표시 정상)
python meta_ads_self_benchmark.py
# → 각 지표마다 "데이터 누적 중 (0/14일)"

# 4. 풀 리포트 (텔레그램 + 이메일 + 시트 + CSV 모두)
python meta_ads_report.py
# → 마지막에 "텔레그램 전송: True" + "이메일 전송 완료" 둘 다 떠야 정상
```

### 위너 패턴 식별 (수동 실행 — 데이터 7일+ 누적 후 의미 있음)
```bash
python meta_ads_winner_patterns.py
# → "위너 N개 식별" 또는 "비교 가능한 캠페인 부족" (정상 폴백)
```

## 4. GitHub Actions 실행

- **자동**: 매일 KST 09:00 (UTC 00:00)
- **수동**: 저장소 Actions 탭 → "Meta 광고 일일 리포트" → Run workflow

## 5. 결과물

- `docs/meta-ads/reports/YYYY-MM-DD.md` — 전일 리포트 (원본 응답 포함)
- 텔레그램 메시지 — 핵심 지표 요약 + 플래그

---

## 주간 리포트 (이메일)

매주 월요일 KST 09:00에 전주 성과를 캠페인별로 집계하여 이메일 발송.

### 추가 Secrets

| Name | Value | 비고 |
|------|-------|------|
| `SMTP_USER` | 발송 Gmail 주소 (예: `osh805050@gmail.com`) | |
| `SMTP_PASSWORD` | Gmail **앱 비밀번호** (16자) | 일반 비밀번호 불가 |
| `EMAIL_FROM` | 발신자 주소 (미설정 시 SMTP_USER 사용) | 선택 |
| `EMAIL_TO` | 수신자 주소 (쉼표로 여러 명) | |

### Gmail 앱 비밀번호 발급

1. Google 계정 → 보안 → **2단계 인증 활성화** (필수)
2. https://myaccount.google.com/apppasswords 접속
3. 앱 이름 "HeavyLover Automation" 등으로 생성 → 16자 비밀번호 복사
4. 해당 값을 `SMTP_PASSWORD` Secret에 등록

### 실행 확인

- **자동**: 매주 월요일 KST 09:00
- **수동**: Actions 탭 → "Meta 광고 주간 리포트" → Run workflow
- **이메일 제목**: `[주별 메타 광고 성과 리포트] YYYY-MM-DD ~ YYYY-MM-DD`

### 결과물

- `docs/meta-ads/weekly/{since}_to_{until}.html` / `.txt` / `.json`
- 이메일 (HTML + 텍스트 멀티파트)

### 변동 플래그 기준

캠페인별 지출·CPA·ROAS·CTR 중 **|변동률| ≥ 20%** 또는 신규/종료 시 하이라이트.

## 6. 토큰 만료 시

System User 토큰은 기본 만료 없음. 단, 권한 변경/앱 비활성화 시 무효화될 수 있음.
워크플로우가 실패하면 텔레그램에 `[Meta 광고 워크플로우 실패]` 알림이 자동 발송됨.
