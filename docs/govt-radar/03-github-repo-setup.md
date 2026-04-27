# GitHub 저장소 만들기 + 로컬 폴더 연결

**왜 필요한가**: 헤비로버 자동화 코드를 GitHub 클라우드에 올려야 GitHub Actions(매일 자동 실행)가 동작합니다. 지금은 로컬 폴더에만 있어서 자동화가 안 돌고 있는 상태.

**소요 시간**: 약 20분

**사전 준비**: GitHub 계정, Git 설치 확인

---

## STEP 0: Git 설치 확인

PowerShell 열고:

```powershell
git --version
```

- `git version 2.x.x` 같은 게 나오면 ✅ STEP 1로
- `'git'은(는) 명령으로 인식되지 않습니다` 나오면 ❌ → https://git-scm.com/download/win 에서 설치 (다음·다음·완료 누르면 됨, 옵션 다 기본값) → PowerShell 닫고 재실행 후 다시 확인

---

## STEP 1: GitHub에서 새 저장소 만들기

1. https://github.com/new 접속
2. **Repository name**: `heavylover-automation` 입력
3. **Description** (선택): `헤비로버 자동화 — 주문, 광고, 정부지원, CRM`
4. **Public / Private**: **Private** 선택 ⚠️ (코드에 비즈니스 로직 들어있음)
5. ❌ **Add a README file** 체크 안 함 (이미 로컬에 있음)
6. ❌ **Add .gitignore** 체크 안 함
7. ❌ **Choose a license** 체크 안 함
8. **Create repository** 클릭

✅ **확인 포인트**: `https://github.com/{내아이디}/heavylover-automation` 페이지 열림. "Quick setup" 화면이 나옴.

⚠️ Quick setup 화면의 명령어들이 보일 텐데, **그냥 두고 STEP 2로 넘어가세요.** 우리가 따로 진행합니다.

---

## STEP 2: 로컬 폴더를 git 저장소로 초기화

PowerShell에서:

```powershell
cd "C:\Users\osh80\OneDrive\바탕 화면\heavylover-automation"
git init
git branch -M main
```

✅ **확인 포인트**: `Initialized empty Git repository in ...` 메시지

---

## STEP 3: Git 사용자 정보 등록 (처음 한 번만)

```powershell
git config --global user.name "osh80"
git config --global user.email "osh805050@gmail.com"
```

(이름·이메일은 GitHub 가입할 때 쓴 거랑 일치하면 좋지만 꼭 같을 필요는 없음)

✅ **확인 포인트**: 에러 없으면 OK

---

## STEP 4: .gitignore 만들기 ⚠️ 매우 중요

비밀번호·API 키 파일이 GitHub에 실수로 올라가면 안 되므로, **올라가면 안 되는 파일 목록**을 만듭니다.

PowerShell에서:

```powershell
cd "C:\Users\osh80\OneDrive\바탕 화면\heavylover-automation"
notepad .gitignore
```

(메모장이 열림. 새 파일 만들지 묻거든 "예")

아래 내용 그대로 붙여넣기:

```gitignore
# 환경변수·비밀번호
.env
.env.local
.env.*.local
*.key
*.pem

# Python
__pycache__/
*.pyc
*.pyo
venv/
.venv/
*.egg-info/

# 로컬 데이터
data/raw/
data/temp/
*.xlsx
*.xls

# OS
.DS_Store
Thumbs.db

# IDE
.vscode/
.idea/

# Claude Code 로컬 설정
.claude/settings.local.json

# OneDrive 임시
~$*
```

저장(Ctrl+S)하고 닫기.

✅ **확인 포인트**: 폴더에 `.gitignore` 파일 생김. PowerShell에서 `ls .gitignore` 로 확인 가능.

---

## STEP 5: 어떤 파일이 올라가는지 미리보기

⚠️ **이 단계 절대 건너뛰지 마세요.** 비밀번호 들어간 파일이 섞여 있는지 확인하는 단계.

```powershell
cd "C:\Users\osh80\OneDrive\바탕 화면\heavylover-automation"
git status
```

출력 예시:
```
On branch main
Untracked files:
        .claude/
        .github/
        CLAUDE.md
        apps_script_main.gs
        cafe24_client.py
        docs/
        naver_client.py
        ...
```

### 점검 체크리스트
- [ ] `.env` 파일이 목록에 **없는지** 확인 (있으면 .gitignore가 안 먹은 것 — 알려주세요)
- [ ] `.claude/settings.local.json`이 **없는지** 확인
- [ ] 비밀번호·토큰 들어간 파일 없는지 (예: `cafe24_token.json` 같은 거 있다면 .gitignore에 추가)

다른 의심스러운 파일 있으면 멈추고 알려주세요.

---

## STEP 6: 첫 커밋 만들기

```powershell
git add .
git status
```

이번엔 모든 파일이 `Changes to be committed:` 아래 초록색으로 보일 겁니다.

```powershell
git commit -m "초기 커밋: 헤비로버 자동화 로컬 코드 GitHub 이전"
```

✅ **확인 포인트**: `[main (root-commit) abc1234] 초기 커밋: ...` + 변경된 파일 수 메시지

---

## STEP 7: GitHub 저장소와 연결

STEP 1에서 만든 저장소 주소를 사용. 본인 GitHub ID가 `osh805050`이면:

```powershell
git remote add origin https://github.com/osh805050/heavylover-automation.git
git remote -v
```

✅ **확인 포인트**: 다음 두 줄이 나옴
```
origin  https://github.com/osh805050/heavylover-automation.git (fetch)
origin  https://github.com/osh805050/heavylover-automation.git (push)
```

⚠️ **GitHub ID가 다르면**: `osh805050` 자리에 본인 ID 넣어주세요. 모르면 https://github.com 우측 상단 프로필 아이콘 클릭해서 보이는 이름.

---

## STEP 8: GitHub로 푸시 (업로드)

```powershell
git push -u origin main
```

이때 **로그인 창이 뜹니다.**

### 인증 방법 (둘 중 하나)

**방법 A: 브라우저 인증 (쉬움)**
- "Sign in with your browser" 버튼 클릭 → GitHub 로그인 창 → 승인
- PowerShell로 돌아오면 자동으로 푸시 진행됨

**방법 B: Personal Access Token (PAT)**
- 비밀번호 대신 토큰을 사용
- 발급: https://github.com/settings/tokens → **Generate new token (classic)** → 권한 `repo` 체크 → 생성 → 토큰 복사
- PowerShell에서 비밀번호 자리에 토큰 붙여넣기

✅ **확인 포인트**:
```
Enumerating objects: ...
Writing objects: 100% (...)
...
 * [new branch]      main -> main
branch 'main' set up to track 'origin/main'.
```

GitHub 저장소 페이지 새로고침하면 파일들이 올라와 있을 겁니다.

---

## STEP 9: 자동으로 살아나는 것들

푸시 직후 **GitHub Actions가 자동으로 활성화**됩니다. 저장소 페이지 → **Actions** 탭 가보면:

- `Meta 광고 일일 리포트` 워크플로가 보임 (아직 실행은 안 함, 매일 09:00 KST에 자동 실행)
- "수동 실행" 가능: 워크플로 클릭 → **Run workflow** 버튼

⚠️ **단, GitHub Secrets가 등록 안 된 상태에서 실행하면 실패합니다.** 먼저 [02-github-secrets-setup.md](02-github-secrets-setup.md) 가이드 따라 Secrets 등록 후 테스트하세요.

---

## STEP 10: 다음에 코드 수정하면?

앞으로 코드 수정 후 GitHub에 반영하려면:

```powershell
cd "C:\Users\osh80\OneDrive\바탕 화면\heavylover-automation"
git add .
git commit -m "변경 내용 설명"
git push
```

3줄이면 끝. 자주 쓰게 됩니다.

---

## 자주 발생하는 문제

### `git push` 시 인증 실패 (Authentication failed)
→ 비밀번호 자리에 GitHub 일반 비밀번호를 넣었을 가능성. 2021년부터 GitHub는 비밀번호 인증 막아둠. **방법 B(PAT)** 또는 **방법 A(브라우저)** 써야 함.

### "OneDrive에 동기화 중" 충돌
→ OneDrive 폴더라 가끔 동기화 충돌 발생. 푸시 전에 OneDrive 동기화가 다 끝났는지(트레이 아이콘 ✅) 확인.

### 파일이 너무 많아서 푸시 느림
→ 정상. 첫 푸시는 5~10분 걸릴 수 있음. 진행 표시 뜨면 기다리기.

### "fatal: refusing to merge unrelated histories"
→ STEP 1에서 README/gitignore 체크했을 가능성. 그러면 GitHub 저장소를 삭제하고 다시 만들거나 (체크 해제), 또는 `git pull origin main --allow-unrelated-histories` 후 다시 push.

### 잘못된 파일 (예: .env) 이미 푸시함
→ 멈추고 알려주세요. **단순히 삭제하면 안 됩니다** — git history에 남기 때문에 누구나 볼 수 있음. 별도 절차로 삭제 + 노출된 키 즉시 폐기 필요.

---

## 다음 단계 체크리스트

- [ ] STEP 8까지 완료 — GitHub 저장소에 코드 올라감
- [ ] [02-github-secrets-setup.md](02-github-secrets-setup.md) 진행 — Secrets 등록
- [ ] [01-naver-mail-setup.md](01-naver-mail-setup.md) 진행 — 네이버 메일 IMAP

세 개 다 끝나면 알려주세요. 코드 작업(Layer 1·2) 시작합니다.
](<스크린샷 2026-04-27 144812.png>)