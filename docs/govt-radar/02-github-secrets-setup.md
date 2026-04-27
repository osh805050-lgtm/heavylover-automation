# GitHub Secrets 등록 가이드

**왜 필요한가**: 자동화 시스템이 GitHub 클라우드에서 매일 자동 실행됩니다. 이때 비밀번호·API 키를 코드에 적어두면 보안 사고가 나니, GitHub의 **Secrets**라는 금고에 따로 보관합니다.

**소요 시간**: 약 15분

---

## 0. 내 GitHub 저장소 찾기

이미 Meta 광고 일일 리포트가 GitHub Actions에서 돌고 있으므로, 저장소는 분명 있습니다. 찾는 법:

### 방법 A: GitHub 웹사이트
1. https://github.com 접속 → 로그인
2. 우측 상단 프로필 아이콘 → **Your repositories**
3. 목록에서 `heavylover-automation` 또는 비슷한 이름 찾기

### 방법 B: 로컬 폴더에서 확인
PowerShell 열고:
```powershell
cd "C:\Users\osh80\OneDrive\바탕 화면\heavylover-automation"
git remote -v
```

`origin  https://github.com/{사용자명}/{저장소명}.git` 같은 줄이 나오면 그게 저장소 주소입니다.

⚠️ **저장소가 없거나 모르겠으면**: 일단 STEP 1로 넘어가지 말고 알려주세요. 저장소 만드는 단계부터 같이 해야 합니다.

---

## STEP 1: Secrets 페이지 들어가기

1. GitHub에서 본인 저장소 페이지 열기 (예: `github.com/osh80/heavylover-automation`)
2. 상단 탭에서 **Settings** 클릭 (우측 끝 톱니바퀴 옆)
3. 좌측 메뉴 스크롤 → **Secrets and variables** → **Actions** 클릭
4. 가운데 화면에 **Repository secrets** 섹션 보임

⚠️ **Settings 탭이 안 보이면**: 본인이 저장소 소유자가 아니거나, 권한이 없는 상태. 저장소 주소 확인하세요.

---

## STEP 2: 기존에 등록된 Secrets 확인

화면에 이미 들어가 있는 것들이 있을 겁니다 (Meta 광고 자동화 때문):
- `META_ACCESS_TOKEN`
- `META_AD_ACCOUNT_ID`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

✅ 이건 그대로 두면 됩니다. 정부지원 자동화도 텔레그램 두 개를 재사용합니다.

---

## STEP 3: 정부지원 자동화용 Secrets 추가

각 항목마다 **New repository secret** 버튼 클릭 → Name·Secret 입력 → **Add secret**.

### 3-1. 네이버 메일 (Layer 2: 메일 교차검증)

| Name | Secret 값 | 비고 |
|---|---|---|
| `NAVER_MAIL_USER` | `osh805050` (예시) | @naver.com 앞부분만 |
| `NAVER_MAIL_APP_PASSWORD` | `abcdefghijklmnop` | [01-naver-mail-setup.md](01-naver-mail-setup.md) STEP 3 결과 |

### 3-2. Claude API (Layer 4: 사업계획서 초안 생성)

| Name | Secret 값 | 비고 |
|---|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-api03-...` | console.anthropic.com에서 발급 |

**Claude API 키 발급법**:
1. https://console.anthropic.com 접속 → 로그인
2. 좌측 메뉴 **API Keys** 클릭
3. **Create Key** → 이름 입력(`heavylover-govt-radar`) → **Create**
4. `sk-ant-api03-...` 형태의 키 복사 (한 번만 보여줌!)
5. 결제 카드 등록 (사용량 만큼만 청구. 정부지원 자동화는 월 $5~10 예상)

### 3-3. Google Workspace (Layer 1·3: 시트·캘린더)

| Name | Secret 값 | 비고 |
|---|---|---|
| `GOOGLE_SHEETS_ID` | (시트 URL의 `/d/` 다음 긴 문자열) | 정부공고 마스터 시트 |
| `GOOGLE_CALENDAR_ID` | `primary` 또는 캘린더 주소 | 기본 캘린더면 `primary` |
| `SHEETS_SA_KEY_JSON` | 서비스 계정 키 JSON 전체 | 별도 발급 필요 |

⚠️ **이 3개는 지금 당장 안 넣어도 됩니다.** Layer 1·3 코드 만들 때 함께 셋업합니다. 일단 STEP 3-1, 3-2까지만 끝내면 1차 작업 완료.

### 3-4. (선택) 네이버 검색 API — Layer 3차 백업

지금은 **건너뛰어도 됩니다.** 1차+2차로 누락이 없으면 안 만들어도 됨. 나중에 필요하면 추가.

| Name | Secret 값 | 비고 |
|---|---|---|
| `NAVER_SEARCH_CLIENT_ID` | (개발자센터에서 발급) | developers.naver.com |
| `NAVER_SEARCH_SECRET` | (위와 같이) | |

---

## STEP 4: 등록 확인

Secrets 페이지로 돌아오면 추가한 것들이 목록에 보입니다. 단, **값은 절대 다시 안 보여줍니다** (보안). 이름과 마지막 수정 시각만 보여요.

```
NAVER_MAIL_USER          Updated 30 seconds ago
NAVER_MAIL_APP_PASSWORD  Updated 1 minute ago
ANTHROPIC_API_KEY        Updated 2 minutes ago
META_ACCESS_TOKEN        Updated 2 months ago    ← 기존
TELEGRAM_BOT_TOKEN       Updated 2 months ago    ← 기존
...
```

✅ **확인 포인트**: 위 3개가 목록에 있으면 STEP 4 통과.

---

## STEP 5: 비밀번호 잊어버리면?

GitHub Secrets는 **저장된 값을 다시 볼 수 없습니다.** 잊어버리면:

- **네이버 앱 비밀번호**: STEP 1 가이드 다시 → 새로 발급 → GitHub Secrets에서 **Update** 클릭
- **Claude API 키**: console.anthropic.com에서 새 키 발급 → 기존 키는 **Revoke** → GitHub Secrets **Update**

값을 안전한 곳(예: 비밀번호 매니저, 개인 메모장)에 따로 백업해두면 좋습니다.

---

## 자주 발생하는 문제

### Settings 탭이 안 보여요
→ 저장소 소유자가 아니에요. 본인 계정이 맞는지 확인.

### `Secrets and variables` 메뉴가 없어요
→ 저장소가 너무 오래된 설정일 수 있음. **Settings → Secrets** 으로도 같은 페이지 접근 가능.

### Secret 이름에 띄어쓰기 넣고 싶어요
→ 안 됩니다. 영문 대문자 + 숫자 + 언더바(`_`)만 허용. `NAVER_MAIL_USER` ✅, `Naver Mail User` ❌

### 값에 특수문자가 들어가요
→ OK. 값에는 어떤 문자든 가능. 단, 앞뒤 공백은 자동 제거됨.

---

## 다음 단계

✅ STEP 3-1, 3-2까지 등록 완료 → 승현님이 알려주시면 코드 작업 시작합니다.

다음에 할 것:
1. `lib/naver_mail_client.py` — 네이버 메일 IMAP 접속 모듈
2. `apps_script_main.gs` 확장 — 공고 소스 8개로 확장
3. `govt_radar.py` — 1차+2차 교차검증

작업 전 알려주실 것:
- [ ] 네이버 메일 IMAP 사용 ON 했음
- [ ] 2단계 인증 켰음
- [ ] 16자리 앱 비밀번호 발급 완료
- [ ] GitHub 저장소 주소: `github.com/_______/_______`
- [ ] GitHub Secrets에 `NAVER_MAIL_USER`, `NAVER_MAIL_APP_PASSWORD`, `ANTHROPIC_API_KEY` 등록 완료
