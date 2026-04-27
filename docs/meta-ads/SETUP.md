# Meta 광고 일일 리포트 — 설정 가이드

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

| Name | Value |
|------|-------|
| `META_ACCESS_TOKEN` | 1단계에서 발급한 System User 토큰 |
| `META_AD_ACCOUNT_ID` | 숫자만 (예: `123456789`, `act_` 제외) |
| `TELEGRAM_BOT_TOKEN` | `.env`와 동일 (`8728802755:...`) |
| `TELEGRAM_CHAT_ID` | `.env`와 동일 (`8692519285`) |

(선택) Variables 탭에서 `META_API_VERSION=v21.0` 설정. 미설정 시 기본값 사용.

## 3. 로컬 테스트

`.env`에 동일한 키를 추가:

```
META_ACCESS_TOKEN=...
META_AD_ACCOUNT_ID=123456789
```

실행:

```bash
python meta_ads_client.py   # 연결 테스트
python meta_ads_report.py   # 실제 리포트 생성
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
