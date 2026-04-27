# 재구매 자동화 Vultr 배포 (GitHub clone 방식)

전제: [setup-repurchase-automation.md](setup-repurchase-automation.md)의 Phase 0(GCP 키·시트 공유·Anthropic API 키) 완료.

기존 11시 엑셀·13시 송장 자동화는 `/root/heavylover-automation/`에서 그대로 돈다. 재구매는 격리를 위해 **별도 폴더 `/root/heavylover-repurchase/`** 에 GitHub clone으로 배포한다. 한쪽이 깨져도 다른 쪽 영향 없음.

---

## 1. 로컬 테스트 (선택, Windows에서 먼저)

GCP 키를 윈도우 폴더에 두면 로컬에서도 1회 검증 가능. 코드가 자동으로 로컬/서버 키 경로를 찾는다.

```powershell
cd "C:\Users\osh80\OneDrive\바탕 화면\heavylover-automation"
python sheets_sync.py
python repurchase_report.py
```

정상이면 텔레그램 리포트 도착 + 시트에 `mart_*` 4개 탭 생성.

로컬 테스트 안 하고 바로 서버로 가도 문제 없음.

---

## 2. Vultr 배포 (GitHub clone)

### 2-1. SSH 접속 후 clone

```bash
ssh root@158.247.215.170
cd /root
git clone https://github.com/osh805050-lgtm/heavylover-automation.git heavylover-repurchase
cd /root/heavylover-repurchase
```

폴더명을 `heavylover-repurchase`로 명시 → 기존 `/root/heavylover-automation/`(11시·13시 자동화)와 충돌 없음.

### 2-2. venv + 의존성 설치

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

`gspread`, `google-auth`, `anthropic` 등이 설치된다.

### 2-3. GCP 키 + .env 업로드

로컬 PowerShell(새 창)에서:

```powershell
cd "C:\Users\osh80\OneDrive\바탕 화면\heavylover-automation"

# GCP 서비스 계정 키
scp gcp-service-account.json root@158.247.215.170:/root/heavylover-repurchase/

# .env (로컬에 만든 .env에 재구매 3개 키가 추가돼 있어야 함)
scp .env root@158.247.215.170:/root/heavylover-repurchase/
```

서버 .env에서 `GOOGLE_SA_KEY_PATH=/root/heavylover-repurchase/gcp-service-account.json`인지 확인.

### 2-4. 수동 실행 검증

```bash
cd /root/heavylover-repurchase
source venv/bin/activate
python sheets_sync.py
python repurchase_report.py
```

검증 통과 기준:
- `sheets_sync.py`: "카페24 N행, SS M행" 출력
- `repurchase_report.py`: 텔레그램에 리포트 도착
- 시트 좌하단에 `mart_monthly`, `mart_cohort`, `mart_stage`, `mart_summary` 4개 탭이 생김
- `mart_summary` 갱신시각 셀에 KST 시각 기록

---

## 3. cron 등록

```bash
mkdir -p /root/heavylover-repurchase/logs
crontab -e
```

기존 cron 2줄(11시·13시) 아래에 추가:

```cron
# 재구매 분석 자동화
30 8 * * 1-5 cd /root/heavylover-repurchase && /root/heavylover-repurchase/venv/bin/python sheets_sync.py >> logs/sync.log 2>&1
0 9 * * 1-5 cd /root/heavylover-repurchase && /root/heavylover-repurchase/venv/bin/python repurchase_report.py >> logs/report.log 2>&1
```

핵심:
- **평일만** (`1-5` = 월~금) — 기존 자동화와 동일 패턴
- **venv의 python 절대경로** — cron 환경에서 시스템 python을 잘못 잡아 의존성 못 찾는 사고 방지
- 로그는 `logs/sync.log`, `logs/report.log`로 누적

확인:
```bash
crontab -l
```

---

## 4. 동작 확인

다음 평일 09:00~09:05에 텔레그램 리포트 도착하면 정상.

```bash
tail -f /root/heavylover-repurchase/logs/sync.log
tail -f /root/heavylover-repurchase/logs/report.log
ls /root/heavylover-repurchase/logs/gt_*.json
```

`gt_2026-04-28.json` 같은 ground_truth 파일이 매일 생기면 데이터 추적 가능.

---

## 5. 앞으로 코드 갱신은 git pull 1줄

로컬에서 코드 수정 → GitHub push 후 서버에서:

```bash
cd /root/heavylover-repurchase
git pull
# 의존성 추가했으면:
source venv/bin/activate && pip install -r requirements.txt
```

scp로 파일 하나하나 올리던 시절 끝.

---

## 6. 문제 해결

### `cannot find module gspread` 등 ImportError
cron이 venv를 안 쓰는 경우. crontab의 python 경로가 `/root/heavylover-repurchase/venv/bin/python`인지 확인.

### `403 Forbidden` 또는 `RefreshError`
서비스 계정 이메일이 시트에 편집자로 공유 안 됨. [setup-repurchase-automation.md §2](setup-repurchase-automation.md) 재확인.

### 탭 식별 실패 (`누락: ['xxx', ...]`)
시트 탭 이름에 "카페24" / "스마트스토어" / "통합" 키워드가 없어서 분류 실패. 탭 이름 수정 또는 [repurchase_report.py:44](../repurchase_report.py#L44) `_classify_tabs`의 매칭 조건 조정.

### Claude 분석이 매번 검증 실패
로그에 `시도 #3 검증 실패` → fallback(원시 숫자만) 발송됨. 의도된 안전장치. 반복되면 [repurchase_report.py](../repurchase_report.py) `SYSTEM_PROMPT`나 `BANNED_PHRASES` 조정.

---

## 7. 롤백

```bash
crontab -e
# 재구매 분석 자동화 2줄 삭제 후 저장
```

이걸로 재구매 자동화만 멈춤. 11시·13시 기존 자동화는 영향 없음. 폴더 통째 제거하려면 `rm -rf /root/heavylover-repurchase/`.
