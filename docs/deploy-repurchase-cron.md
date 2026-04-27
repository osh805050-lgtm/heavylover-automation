# Vultr 배포 + cron 등록

셋업(`setup-repurchase-automation.md`) 완료 후 진행.

---

## 1. 로컬 테스트 (Windows에서 먼저)

Vultr에 올리기 전에 Windows에서 한 번 돌려봐서 동작 확인.

```powershell
cd "C:\Users\osh80\OneDrive\바탕 화면\heavylover-automation"
python sheets_sync.py
```

정상이면 "카페24 N행, SS M행" 출력. 구글 시트에서 두 원본 탭 확인.

이어서 리포트 테스트:
```powershell
python repurchase_report.py
```

텔레그램으로 리포트가 와야 정상. 실패 시 콘솔 오류 확인.

---

## 2. Vultr 서버에 배포

### 2-1. 코드 업로드 (로컬 → Vultr)

Windows PowerShell에서:
```powershell
cd "C:\Users\osh80\OneDrive\바탕 화면\heavylover-automation"

# 새 파일만 업로드 (scp 사용 — Git for Windows 또는 OpenSSH 필요)
scp sheets_sync.py repurchase_report.py gcp-service-account.json root@158.247.215.170:/root/heavylover-automation/
scp .env root@158.247.215.170:/root/heavylover-automation/
```

scp가 안되면 SFTP 클라이언트(FileZilla, WinSCP) 써서 같은 파일 업로드.

### 2-2. 서버에서 의존성 설치

Vultr SSH 접속 후:
```bash
cd /root/heavylover-automation
pip install gspread google-auth anthropic
```

### 2-3. 서버에서 테스트

```bash
cd /root/heavylover-automation
python sheets_sync.py
python repurchase_report.py
```

둘 다 정상 동작 확인.

---

## 3. cron 등록

Vultr SSH에서:
```bash
crontab -e
```

에디터가 열리면 맨 아래에 추가:

```cron
# 재구매 분석 자동화
30 8 * * * cd /root/heavylover-automation && /usr/bin/python3 sheets_sync.py >> /root/heavylover-automation/logs/sync.log 2>&1
0 9 * * * cd /root/heavylover-automation && /usr/bin/python3 repurchase_report.py >> /root/heavylover-automation/logs/report.log 2>&1
```

저장하고 나오기. 확인:
```bash
crontab -l
mkdir -p /root/heavylover-automation/logs
```

---

## 4. 동작 확인

다음날 09:00~09:05에 텔레그램에 리포트가 와야 정상.

### 로그 확인
```bash
tail -f /root/heavylover-automation/logs/sync.log
tail -f /root/heavylover-automation/logs/report.log
```

### ground_truth 감사
리포트 실행 시마다 ground truth JSON이 저장됨. 숫자 근거 추적 가능:
```bash
ls /root/heavylover-automation/logs/gt_*.json
cat /root/heavylover-automation/logs/gt_2026-04-24.json
```

---

## 5. 문제 발생 시

### 탭이 식별 안 됨
`repurchase_report.py` 실행 로그에서 `누락: ['xxx', ...]` 확인. 해당 탭이 .gs로 재생성 안 되어 있거나, 탭 이름에 "카페24" / "스마트스토어" / "통합" 키워드가 없으면 분류 실패.

→ 대응: `sheets_sync.py`의 `_classify_tabs`에서 탭 이름 매칭 조건 조정.

### Claude 분석이 계속 검증 실패
로그에 `시도 #3 검증 실패` 나오면 fallback(원시 숫자)만 발송됨. 이건 **의도된 안전장치**.

→ 반복되면 `repurchase_report.py`의 `SYSTEM_PROMPT`를 조정하거나 `BANNED_PHRASES` 재조정.

### 시트 권한 오류
`google.auth.exceptions.RefreshError` 또는 `403 Forbidden` 나오면 서비스 계정 이메일이 시트에 편집자로 공유되어 있는지 재확인.
