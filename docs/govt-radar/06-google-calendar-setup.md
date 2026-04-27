# Google Calendar 자동등록 셋업

**왜 필요한가**: 적합도 ≥ 7 공고가 자동으로 Google Calendar에 D-7/D-3/마감일 3개 이벤트로 등록됩니다. 09:00 알람 작동.

**소요 시간**: 약 15분

**최종 결과**: 헤비로버 정부지원 마감일이 캘린더에 자동 누적

---

## 코드는 이미 다 작성됐습니다

작성 완료된 파일:
- `lib/calendar_client.py` — Calendar API 클라이언트
- `govt_radar.py` — 자동 호출 통합
- `.github/workflows/govt-radar-daily.yml` — Secrets 추가
- `requirements.txt` — `google-api-python-client` 추가

**승현님이 직접 해야 하는 건 Google Cloud 발급 + GitHub Secrets 등록 두 가지뿐.**

---

## STEP 1: Google Cloud 프로젝트 생성 (3분)

1. https://console.cloud.google.com 접속 (구글 로그인)
2. 좌측 상단 프로젝트 드롭다운 → **새 프로젝트**
3. 프로젝트 이름: `heavylover-automation`
4. 만들기 → 약 30초 대기 → 생성된 프로젝트 선택

---

## STEP 2: Calendar API 활성화 (1분)

1. 좌측 메뉴 **API 및 서비스** → **라이브러리**
2. 검색창에 `Google Calendar API` 입력 → 클릭
3. **사용** 버튼 클릭

---

## STEP 3: 서비스 계정 + JSON 키 발급 (3분)

1. **API 및 서비스** → **사용자 인증 정보**
2. 상단 **+ 사용자 인증 정보 만들기** → **서비스 계정**
3. 서비스 계정 이름: `heavylover-radar`
4. **만들고 계속하기** → 권한 단계 **건너뛰기**(역할 추가 안 해도 됨) → **완료**
5. 만들어진 서비스 계정 클릭 (목록에서)
6. 상단 **키** 탭 → **키 추가** → **새 키 만들기** → **JSON** → **만들기**
7. JSON 파일이 자동 다운로드됨

⚠️ 다운로드된 JSON은 비밀키 — GitHub에 절대 올리면 안 됩니다 (`.gitignore`로 보호 중)

서비스 계정 이메일 메모 (예: `heavylover-radar@xxxxx.iam.gserviceaccount.com`) — STEP 4에서 사용

---

## STEP 4: 본사 캘린더 생성 + 공유 (3분)

1. https://calendar.google.com 접속
2. 좌측 **다른 캘린더** 옆 **+** → **새 캘린더 만들기**
3. 이름: `헤비로버 정부지원 마감`
4. **캘린더 만들기**
5. 만들어진 캘린더 → **설정 및 공유**
6. 좌측 **특정 사용자 또는 그룹과 공유** → **사용자 추가**
7. STEP 3에서 메모한 서비스 계정 이메일 입력
8. 권한: **변경 권한** (이벤트 추가/수정 가능)
9. **보내기**
10. 같은 페이지 좌측 **캘린더 통합** → **캘린더 ID** 복사 (예: `abc123@group.calendar.google.com`)

---

## STEP 5: GitHub Secrets 등록 (3분)

GitHub 저장소 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

### Secret 1: `GOOGLE_CALENDAR_ID`
- Name: `GOOGLE_CALENDAR_ID`
- Value: STEP 4에서 복사한 캘린더 ID
- **Add secret**

### Secret 2: `GOOGLE_SA_KEY_JSON`
- Name: `GOOGLE_SA_KEY_JSON`
- Value: STEP 3에서 다운로드한 JSON 파일을 메모장으로 열어서 **전체 내용 그대로** 복사 붙여넣기 (`{` 부터 `}` 까지)
- **Add secret**

⚠️ 줄바꿈이 많아서 GitHub Secrets에서 깨질 수 있는데, 코드는 자동으로 처리합니다. 단, 따옴표·중괄호 다 포함해서 복사하세요.

---

## STEP 6: 로컬 `.env`에도 등록 (선택 — 로컬 테스트용)

PowerShell:
```powershell
cd "C:\Users\osh80\OneDrive\바탕 화면\heavylover-automation"
notepad .env
```

맨 아래 추가:
```
GOOGLE_CALENDAR_ID=abc123@group.calendar.google.com
```

JSON 키는 파일로 저장하는 게 편합니다:
- 다운로드된 JSON 파일을 `gcp-key.json` 이름으로 헤비로버 폴더에 저장
- `.env`에 `GOOGLE_SA_KEY_PATH=./gcp-key.json` 추가 (또는 그냥 두기 — 자동 폴백)

---

## STEP 7: 테스트

PowerShell:
```powershell
python lib/calendar_client.py test
```

**성공 시**:
```json
{
  "ok": true,
  "calendar_id": "abc123@group.calendar.google.com",
  "summary": "헤비로버 정부지원 마감",
  "time_zone": "Asia/Seoul"
}
```

**실패 시** 출력에 `error: ...` 메시지 있음. 가능한 원인:
- 캘린더 공유 권한 안 줬음 (STEP 4 다시)
- JSON 파일 잘못된 위치
- Calendar API 비활성화 (STEP 2 다시)

---

## STEP 8: 진짜로 캘린더에 등록

```powershell
python govt_radar.py --days-back 2
```

자동으로:
1. 텔레그램 알림 발송
2. 캘린더에 적합도 ≥ 7 공고 D-7/D-3/마감 3개 이벤트 등록
3. https://calendar.google.com 가서 "헤비로버 정부지원 마감" 캘린더 확인

같은 공고는 재실행해도 중복 등록 안 됨 (멱등성).

---

## 자주 발생하는 문제

### "Permission denied" 에러
→ STEP 4에서 서비스 계정에게 **변경 권한** 안 줬을 가능성. 다시 확인.

### "Calendar not found"
→ `GOOGLE_CALENDAR_ID` 잘못 입력. STEP 4에서 복사한 ID 다시 확인.

### "JSON parse error"
→ GitHub Secrets에 붙여넣을 때 일부 글자 누락. 다시 전체 복사.

### 이벤트가 안 보임
→ 다른 캘린더 보고 있을 수 있음. 좌측에서 "헤비로버 정부지원 마감" 체크박스 확인.

---

## 다음 단계

✅ 캘린더 셋업 완료 → [07-gmail-digest-setup.md](07-gmail-digest-setup.md)로 이동
