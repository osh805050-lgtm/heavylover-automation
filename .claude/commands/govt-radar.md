---
description: 정부지원 공고 레이더 수동 실행 — Playwright + reconciliation + 텔레그램/이메일/캘린더 자동
argument-hint: [dry-run]
---

# /govt-radar — 정부지원 공고 수동 수집

사용자 입력 인자: **$ARGUMENTS** (비어있으면 정식 실행, "dry-run" 또는 "test"면 텔레그램·이메일·캘린더 발송 스킵)

## 배경

이 명령은 GitHub Actions 자동화(매일 08:00 KST)에서 데스크톱 수동 실행으로 전환된 워크플로다. 이유: 미국 클라우드 IP 차단으로 5개 한국 정부 사이트(소상공인24, K-Sure, 고비즈코리아, 경기도, 중소기업유통센터)가 매일 0건 반환됨. 데스크톱(한국 일반 IP)에서 실행하면 차단 없이 정상 수집된다.

작업 디렉토리: `c:\Users\osh80\OneDrive\바탕 화면\heavylover-automation`

---

## 실행 절차

### 1단계: 사전 점검 (Bash)

다음을 병렬로 확인:

1. `.env` 파일 존재 — `Glob` 또는 `Bash ls .env`
2. `gcp-service-account.json` 존재 확인
3. Playwright Chromium 설치 여부:
   - Bash: `python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(); b.close(); p.stop(); print('OK')"` 
   - 실패하면 `python -m playwright install chromium` 안내 후 사용자 승인 받고 1회 설치
4. govt_radar.py가 정상 import되는지 가벼운 syntax 체크:
   - `python -c "import ast; ast.parse(open('govt_radar.py', encoding='utf-8').read()); print('parse OK')"`

위 중 하나라도 실패 시 **명확한 한 줄 안내 후 중단**. 예: "`.env` 누락 → `c:\Users\osh80\OneDrive\바탕 화면\heavylover-automation\.env` 생성 필요. DATA_GO_KR_API_KEY, TELEGRAM_BOT_TOKEN_GOVT, GOOGLE_SA_KEY_JSON 필수."

### 2단계: 실행 (Bash)

$ARGUMENTS 값에 따라 분기:

- `$ARGUMENTS` ∈ {"dry-run", "test", "--dry-run"}:
  ```
  python govt_radar.py --days-back 2 --dry-run
  ```
- 그 외 (빈 값 포함):
  ```
  python govt_radar.py --days-back 2
  ```

timeout: 1800초 (30분). Playwright + 25개 소스 + Layer 4 자격검증 포함 최대치.

Bash 실행 시 환경변수 추가: `PYTHONIOENCODING=utf-8` (Windows 콘솔 한글 깨짐 방지).

### 3단계: 결과 보고 (Read + 사용자 채팅)

실행 후 다음 3가지 산출물을 읽고 요약:

#### 3-1. 실행 로그 핵심 지표
파일: `logs/govt_radar_{YYYY-MM-DD}.log` (오늘 날짜)

Grep 또는 Read tail로 다음 라인 추출:
- `Layer 1 완료:` → API 소스별 카운트
- `Layer 1 (PW) 완료:` → Playwright 소스별 카운트
- `Reconciliation:` → matched / playwright_only (API 누락) 건수
- `S xx / A xx / B xx / C xx` → 점수 등급별 분포
- `seen-key dedup: 신규 N · 갱신 N · 기존 N` → 신규 공고 개수
- `캘린더 등록:` → created / updated / errors
- 텔레그램 메시지 발송 결과 (dry-run이면 "DRY-RUN" 메시지 확인)

#### 3-2. 막힌 사이트 한국 IP 효과 검증
`data/govt_radar/radar_{YYYYMMDD}.json` 읽어서 소스별 카운트 추출.

다음 5개 소스 비교 표 (어제 GitHub Actions 결과 vs 오늘 데스크톱):
| 소스 | GitHub Actions (미국 IP) | 데스크톱 (한국 IP) | 효과 |
| 소상공인24 | 0 | ? | ✅/❌ |
| K-Sure | 0 | ? | ✅/❌ |
| 고비즈코리아 | 0 | ? | ✅/❌ |
| 경기도 | 0 | ? | ✅/❌ |
| 중소기업유통센터 | 0 | ? | ✅/❌ |

1개 이상 0건 탈출 시 → 한국 IP 우회 효과 ✅

#### 3-3. 고점수 신규 공고 Top 10
`radar_{YYYYMMDD}.json`에서 score ≥ 7 + 신규 공고 (seen_keys에 없던) 최대 10개:
- 점수, 제목, 발주기관, 마감, score breakdown(fit/region/deadline)

### 4단계: 최종 한 줄 보고

마지막에 사용자에게:
```
✅ /govt-radar 완료 — 신규 N건 (S{x}/A{y}/B{z}) · 텔레그램 발송 {ok/dry-run} · 캘린더 등록 {created N} · 막힌 사이트 {n}개 부활
```

---

## 실패 처리

- **.env 누락 키**: 누락된 키 이름 명시 후 중단
- **Playwright 미설치**: `python -m playwright install chromium` 1회 실행 권유 (사용자 승인)
- **govt_radar.py 실행 중 에러**: 로그 마지막 50줄 Bash로 읽어 ERROR/CRITICAL 라인 grep 후 보고
- **타임아웃**: 30분 초과 시 어느 Layer/소스에서 멈췄는지 로그로 확인
- **결과 JSON 없음**: 실행이 정상 종료됐는데 파일이 없으면 govt_radar.py의 save 로직 문제 — 다른 날짜로 저장됐을 가능성 점검

---

## 사용 예시

- 정식 실행 (월요일 오전):
  - `/govt-radar`
- dry-run (텔레그램·캘린더 발송 없이 결과만 확인):
  - `/govt-radar dry-run`

---

## 권장 일정

매주 월요일 오전 09:00 권장 (주말 누적 공고 확인). 평일은 마감 임박 공고 점검 차원에서 격일.
