# 재구매 분석 자동화 셋업 가이드

이 가이드는 **승현님이 직접** 진행해야 하는 셋업입니다. 아래 4단계만 하면 됩니다.

---

## 1. Google 서비스 계정 생성 (한 번만)

Vultr 서버가 구글 시트를 읽고 쓰려면 인증서가 필요합니다. 구글 계정 내 "봇 계정" 같은 개념입니다.

### 1-1. GCP 프로젝트 만들기

1. https://console.cloud.google.com 접속 (승현님 구글 계정으로 로그인)
2. 상단 프로젝트 선택 드롭다운 클릭 → "새 프로젝트"
3. 프로젝트 이름: `heavylover-automation` (아무거나 OK)
4. "만들기" 클릭 → 생성까지 10초 정도

### 1-2. Google Sheets API 활성화

1. 상단 검색창에 "Google Sheets API" 입력 → 클릭
2. "사용 설정" 버튼 클릭

### 1-3. 서비스 계정 생성

1. 좌측 메뉴 → "IAM 및 관리자" → "서비스 계정"
2. 상단 "+ 서비스 계정 만들기" 클릭
3. 서비스 계정 이름: `heavylover-sheets`
4. "만들고 계속하기" → 역할 선택 없이 "계속" → "완료"

### 1-4. JSON 키 다운로드

1. 방금 만든 서비스 계정 클릭 → "키" 탭
2. "키 추가" → "새 키 만들기" → "JSON" 선택 → "만들기"
3. JSON 파일이 자동 다운로드됨 → 파일명을 `gcp-service-account.json`으로 변경
4. 이 파일을 `C:\Users\osh80\OneDrive\바탕 화면\heavylover-automation\` 폴더에 저장

### 1-5. 서비스 계정 이메일 복사

서비스 계정 페이지에서 방금 만든 계정의 **이메일 주소**를 복사해두세요.
형식: `heavylover-sheets@heavylover-automation-xxxxxx.iam.gserviceaccount.com`

---

## 2. 구글 시트 공유 권한 부여

1. 재구매 분석 시트 열기: https://docs.google.com/spreadsheets/d/1DEEz2iSa_REKUsYetyZMSqZsVm6_LFbOAasrzXjYU5s
2. 우상단 "공유" 버튼 클릭
3. 위에서 복사한 **서비스 계정 이메일 주소**를 붙여넣기
4. 권한: "편집자" 선택
5. "알림 보내기" 체크 해제 (봇 계정이라 이메일 못 받음)
6. "전송" 클릭

---

## 3. Anthropic API 키 발급 (리포트 생성용)

Claude 분석 리포트를 위해 API 키가 필요합니다.

1. https://console.anthropic.com 접속 → 로그인
2. "API Keys" 메뉴 → "Create Key"
3. 키 이름: `heavylover-repurchase-report`
4. 키 복사 (한 번만 표시됨, 놓치면 재생성)
5. 결제 수단 등록 필수 (선불 $5 정도면 한 달 충분 — 리포트 1회당 약 $0.05)

---

## 4. .env 파일에 추가

`C:\Users\osh80\OneDrive\바탕 화면\heavylover-automation\.env` 파일 열고 **맨 아래에 추가**:

```
# 재구매 분석 자동화
GOOGLE_SA_KEY_PATH=/root/heavylover-automation/gcp-service-account.json
REPURCHASE_SHEET_ID=1DEEz2iSa_REKUsYetyZMSqZsVm6_LFbOAasrzXjYU5s
ANTHROPIC_API_KEY=sk-ant-여기에-붙여넣기
```

주의: `GOOGLE_SA_KEY_PATH`는 **Vultr 서버 기준 경로**입니다. 로컬에서도 테스트하려면 별도의 Windows 경로 지정이 필요한데, 코드가 자동으로 로컬/서버를 구분합니다.

---

## 5. Apps Script 자동 실행 트리거 (선택)

`repurchase_v5_4.gs`를 매일 아침 자동 실행하려면 Apps Script 편집기에서 한 번만 설정:

1. 구글 시트 열고 → 상단 메뉴 "확장 프로그램" → "Apps Script"
2. 좌측 메뉴 시계 아이콘 "트리거" 클릭
3. 우하단 "+ 트리거 추가" 버튼
4. 설정:
   - 실행할 함수: (19개 시트 생성하는 메인 함수 — 평소 수동으로 눌렀던 그 버튼의 함수명)
   - 이벤트 소스: "시간 기반"
   - 트리거 유형: "일 단위 타이머"
   - 시간: "오전 8시~9시"
5. "저장"

이렇게 하면 매일 아침 8~9시 사이에 자동으로 분석 시트가 갱신됩니다. 이걸 안 해도 리포트는 돌아가지만, **전날 수동으로 버튼 누른 시점의 분석값**이 리포트에 반영됩니다.

---

## 완료 체크리스트

- [ ] GCP 프로젝트 생성 + Sheets API 활성화
- [ ] 서비스 계정 JSON 키 다운로드 → `gcp-service-account.json`으로 heavylover-automation 폴더에 저장
- [ ] 구글 시트를 서비스 계정 이메일에 편집자로 공유
- [ ] Anthropic API 키 발급 + 결제 수단 등록
- [ ] `.env`에 3개 값 추가
- [ ] (선택) Apps Script 시간 트리거 설정

위 5개 끝나면 테스트 실행부터 Vultr cron 등록까지 이어서 진행합니다.
