# Gmail 주간 다이제스트 셋업

**왜 필요한가**: 매주 월요일 08:00 KST에 osh805050@gmail.com으로 지난 7일 정부지원 레이더 다이제스트가 자동 발송됩니다. 즉시 액션·S/A 등급·추이 그래프 포함.

**소요 시간**: 약 7분

---

## 코드는 이미 다 작성됐습니다

작성 완료된 파일:
- `lib/email_digest.py` — HTML 다이제스트 생성·발송
- `email_sender.py` — Gmail SMTP (이미 존재, 재사용)
- `.github/workflows/govt-radar-weekly.yml` — 매주 월요일 자동 실행

**승현님이 직접 해야 하는 건 Gmail 앱 비밀번호 발급 + GitHub Secrets 등록 두 가지뿐.**

---

## STEP 1: Gmail 2단계 인증 확인 (1분)

앱 비밀번호 발급은 2단계 인증이 켜져 있어야 가능.

1. https://myaccount.google.com/security 접속
2. **2단계 인증** 항목 확인
   - "사용 중" → STEP 2로
   - 미설정 → 설정 (휴대폰 번호 등록 + SMS 인증)

---

## STEP 2: 앱 비밀번호 발급 (3분)

1. https://myaccount.google.com/apppasswords 접속
2. (재로그인 요구 가능)
3. 앱 이름: `heavylover-automation` 입력
4. **만들기**
5. **16자리 비밀번호** 표시됨 — 메모장에 복사 (한 번만 보여줌!)
   - 예: `abcd efgh ijkl mnop` (띄어쓰기 있어도 OK)

⚠️ 이 16자리는 절대 다른 사람에게 공유하지 마세요.

---

## STEP 3: GitHub Secrets 등록 (2분)

GitHub 저장소 → **Settings** → **Secrets and variables** → **Actions**

### Secret 1: `SMTP_USER`
- Name: `SMTP_USER`
- Value: `osh805050@gmail.com` (Gmail 주소)

### Secret 2: `SMTP_PASSWORD`
- Name: `SMTP_PASSWORD`
- Value: STEP 2의 16자리 (띄어쓰기 있어도 OK, 자동 처리)

### Secret 3: `EMAIL_FROM`
- Name: `EMAIL_FROM`
- Value: `osh805050@gmail.com`

### Secret 4: `EMAIL_TO`
- Name: `EMAIL_TO`
- Value: `osh805050@gmail.com,ohkm8050@naver.com`
  (둘 다 받기. 콤마 구분, 띄어쓰기 ❌)

---

## STEP 4: 로컬 `.env`에도 등록 (선택)

```powershell
cd "C:\Users\osh80\OneDrive\바탕 화면\heavylover-automation"
notepad .env
```

맨 아래 추가:
```
SMTP_USER=osh805050@gmail.com
SMTP_PASSWORD=abcdefghijklmnop
EMAIL_FROM=osh805050@gmail.com
EMAIL_TO=osh805050@gmail.com,ohkm8050@naver.com
```

---

## STEP 5: 테스트 (지금 즉시 발송)

```powershell
python lib/email_digest.py
```

성공 시:
```json
{"ok": true, "items": 582, "actionable": 11}
```

→ Gmail 받은편지함 확인. "[정부지원 레이더] MM/DD 주간 다이제스트" 메일 도착.

---

## STEP 6: 자동 실행 일정

GitHub 푸시 후 자동 활성화:
- **매주 월요일 08:00 KST** 자동 발송
- GitHub Actions → "정부지원 레이더 주간 다이제스트" 워크플로
- 수동 실행 가능: Actions 페이지 → **Run workflow**

---

## 자주 발생하는 문제

### "Authentication failed"
→ SMTP_PASSWORD가 일반 Gmail 비밀번호임. **앱 비밀번호 16자리** 사용해야 함.

### "less secure app blocked"
→ 일반 비밀번호 사용 시 발생. STEP 2에서 발급한 앱 비밀번호로 교체.

### 메일이 스팸함으로 감
→ 첫 발송 시 Gmail이 자기 자신에게 보내는 거라 가끔 스팸. 받은편지함으로 옮기면 다음부터 정상.

### "no_data" 에러
→ `data/govt_radar/radar_*.json` 파일이 없음. govt_radar.py가 며칠 안 돌았거나 Actions가 결과를 커밋 안 했을 가능성.

---

## 다이제스트 내용 미리보기

매주 월요일 메일에 다음 포함:

1. **헤더**: 기간 + 7일 누적 수집/S/A/즉시액션 KPI
2. **🚨 즉시 액션 (D-7 이내)**: 마감 임박 공고 전체 — 점수 분해, 본문 400자, 발주, 대상, 분야
3. **⭐ 이번주 S·A 등급**: 상위 15건 (마감 임박 제외)
4. **📈 7일 추이**: 일자별 수집량/S/A/B 표
5. **푸터**: 데이터 출처, 본사 정보

HTML 디자인:
- 색상 등급 (S=빨강 / A=주황 / B=초록)
- 모바일·PC 둘 다 가독성 OK
- 마감 D-3 긴급 빨강 배지
- 직접 클릭으로 공고 원문 이동

---

## 다음 단계

✅ Gmail 다이제스트 셋업 완료 → 운영 시작!

다음에 하실 일:
- 월요일까지 자동으로 첫 다이제스트 발송 확인
- 다이제스트 받아보고 추가 개선 사항 알려주시면 반영
