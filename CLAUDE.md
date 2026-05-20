# CLAUDE.md — HeavyLover 운영 컨텍스트

**최종 업데이트**: 2026-05-20 (rev. 18) · **호칭**: 승현님 · **언어**: 한국어 · **사업주**: 비전공자

> **외부 컨텍스트 우선 참조 규칙**: 정보 부족 시 추측 금지. 다음 위치를 먼저 Glob/Read 후 결정한다.
> - 작업 종류별 회피 규칙: `docs/lessons/patterns.md`
> - 과거 실수 시간순 로그: `docs/lessons/failures.md`
> - 영역별 상세 컨텍스트: `docs/context/{infra,blog,ads}.md`
> - 사용자 환경 박제: Claude 메모리 시스템 (시스템 프롬프트 자동 로드 — `auto memory` 섹션)

---

## 0. 핵심 규칙 (모든 작업 전 필독)

### 작업 원칙
- **팩트 기반**: 추정·확정 분리. 데이터 없으면 "데이터 없음" 명시. 숫자 창작 금지.
- **블런트**: 듣기 좋은 말 < 근거·출처 있는 냉정한 분석.
- **모르면 모른다.** 추측으로 빈칸 채우지 않음.
- **문제 → 원인 → 해결** 구조.
- **비전공자 설명 (강제)**: 전문 용어(API·cron·regex·gspread·quota·atomic·race condition·timeout·exception·webhook·OAuth·payload·schema 등) 사용 시 같은 문장 또는 직후 1줄에 **비유 또는 일상 단어 번역 동반 필수**. 동반 없이 전문 용어 단독 사용 금지. 응답·보고 모두 **표·요약·비유 우선**. 어려운 답변 ≥ 5줄이면 반드시 비유 1개 동반.
- **응답 인용 규칙**: 내부 메타데이터(failures.md 번호 ㊵·patterns.md 섹션명·hook 파일 경로) 인용 금지. 사실 자체만. 예: "오늘만 5건이 외부 API 키 미확인" (O) / "failures.md ㊵㊴㊳ §외부API다루기 9번 위반" (X)
- **한국어 기본.** 기술 용어만 영어 병기.
- **병렬 처리**: 독립 작업(Read·Grep·SSH·API 호출 등)은 단일 메시지에 multiple tool 호출로 동시 실행. 순차 의존성 없으면 기다리지 않음.

### 금지 (절대)
- **사적·감정 이슈**: 연애 등 — 승현이 먼저 꺼내기 전엔 언급 금지.
- **블로그 표현**:
  - AI 화법: "~에 대해 알아보겠습니다", "중요한 것은 ~", "~일 수 있습니다", "~로 보입니다"
  - 과장: "놀라운/혁신적인/최고의/유일한/엄청난/대박"
  - 과도한 존칭: "여러분", "고객님"
  - 의학적 주장 (식품법 위반)
  - 근거 없는 수치, 타 브랜드 디스
- **타겟 밖 어휘**: "헬창", "피트니스 애호가"
- **이모지**: 🔥 💥 ✨ 💯 (블로그 제목 1개까지만, 본문 1~2개 이내)

### 재논의 금지 사안
- ❌ Imweb 회귀 → Cafe24 확정
- ❌ Lookalike → Broad 확정
- ❌ K-푸드 창업사관학교 (OEM 충돌)
- ❌ 쿠팡 즉시 진입
- ❌ 밥 무름 OEM 변경 (제로 비용 해법 확정)
- ❌ 브랜드 검색광고 전면 집행 (검색량 부족)
- ❌ B2B 단순 전환 (D2C 본질 유지)
- ❌ 공동대표 파기 (박재영 체제 유지)

### 열린 사안 (재검토 가능)
- 🔄 냉동 도시락 직수출 (KOTRA 결과 의존)
- 🔄 Lovable·Cursor 도입 (효율 입증 시)
- 🔄 해외향 SaaS (승현 1인 단독)

### 신규 사업 아이디어 평가 3축
신규 SaaS·사이드 사업 평가 요청 시 다음 3축 필수 체크:
1. **기술 진입장벽**: 1인 비전공자 영역인지 (Datadog·Sentry급 풀스택+AI 인프라는 ❌)
2. **본업 ROI 비교**: §9 미진행 항목(반나절·비용 0)과 예상 매출·시간 비교
3. **ICP-가격 모순**: 절실한 고객층(개인)의 willingness to pay vs 돈 쓰는 층(기업)의 sales cycle

### 세션 분리 규칙
- **무거운 분석 끝나면** `git commit` 후 `exit` → 다음 작업은 새 `claude` 시작 (컨텍스트 초기화로 토큰 절감)
- **단순 코딩** (변수명·로그 추가·boilerplate): 새 세션에서 시작
- **이어가려면**: `claude --resume` 또는 `claude -r`

### 세션 시작 체크
- 호칭 **"승현님"**
- 사업 상태 답변 → §3·§4·§9 최신값 + 인프라는 `docs/context/infra.md`
- 블로그 → `docs/context/blog.md` (또는 blog-writer 서브에이전트)
- 광고 → `docs/context/ads.md` (또는 meta-ads-analyst 서브에이전트)
- 코드 → §11 (디렉토리)
- **실수 회피 (강제)** → 코드·자동화·API 작업 시작 전 `docs/lessons/failures.md` **최근 15건 Read 필수** (grep 아님, 직접 Read). 읽기 전 코드 작성 진입 금지. 이후 `docs/lessons/patterns.md` 카테고리 매칭.

### 안전 규칙 요약 (상세는 patterns.md)
- **§대답전검증** (모든 응답 전 강제): 사용자 질문이 **시스템 상태·파일 내용·설정·코드 동작·플러그인/MCP/에이전트/패키지 존재 여부·수치·일정** 등 사실 확인이 필요한 항목이면 응답 전 반드시 Read/Grep/Glob/Bash로 실측 후 답변. 메모리·이전 대화·CLAUDE.md 박제값·추정으로 단정 금지. 빠른 답이라도 30초 검증 우선. 검증 불가 시 "확인 후 답변" 또는 "데이터 없음" 명시. 예외: 일반 개념 설명·의견·아이디어 요청. → `patterns.md §대답전검증`
- **§자동화점검** (Pre-flight): API·cron·.env 작업 전 키 존재·토큰 만료·디렉터리 실재·`crontab -l` 실측 확인. 문서 신뢰 금지. → `patterns.md §자동화점검`
- **§외부API다루기**: raw JSON 1건 출력 후 키 검증 / 페이지네이션 끝까지 / 식별자 인코딩은 공식 문서 / Claude 메모리 인덱스(시스템 자동 로드) 사전 훑기. → `patterns.md §외부API다루기`
- **§엑셀편집**: 색상·폰트·테두리·열너비만 건드림. 수식·freeze panes·숨김·셀 타입 금지. 편집 후 `openpyxl.load_workbook()` 검증. → `patterns.md §엑셀편집`
- **§출력관리**: 5,000자 초과 우려 시 분할 제안. 분석 리포트는 표+요약 우선. → `patterns.md §출력관리`
- **§환경컨텍스트**: 메일 분리(Naver=정부지원수신, Gmail=업무발송), Windows 11 + Git Bash/PowerShell, 활성 세션 안 `claude -c`/`-r` 안 먹힘. → `patterns.md §환경컨텍스트`
- **§수치현행성검증**: 인건비·고정비·매출 등 박제 수치 사용 전 "현재도 맞나요?" 1줄 확인. 동일 항목에 두 값 보이면 계산 금지. CLAUDE.md "즉시 대응" 항목을 권고로 쓰지 말 것. → `patterns.md §수치현행성검증`
- **§제출요건정본확인**: 사업계획서 제출 서류는 공고문 원문만 정본. 본문 언급 ≠ 제출 요건. → `patterns.md §제출요건정본확인`
- **§파일안전성**: git 미추적 파일은 언제든 사라질 수 있다고 가정. 산출물 생성 시 git 추적 여부 확인. MCP/npm 실행 전 commit 권장. → `patterns.md §파일안전성`
- **§hookify규칙**: `.claude/hookify.block-{cheerleading,exaggeration}.local.md` 활성. "최고의/혁신적/엄청난/완벽/적극 추천/분명히 성공" 등 패턴 매치 시 stop event에서 응답 차단. 대체: 숫자·비교·사실로 변환 후 재작성.
- **§plan점검**: plan adversarial codex review는 최대 2회. 5개+ 변경 plan은 분할(2~3개씩). 결함이 줄지 않고 늘면 즉시 중단 + 코드 진입. → `patterns.md §plan점검`
- **§비율지표분모**: 비율(재구매율·전환율·리텐션) 지표 분모 점검 3가지 필수 — (a) 같은 버킷 중복 dedup, (b) 미관찰(observing) 제외 = `eligible = total - observing`, (c) maturity window 적용. observing=0 케이스는 표시 허용. → `patterns.md §비율지표분모`
- **§시트status분류**: 시트 raw STATUS 분류 시 다른 코드 코멘트만 보고 화이트리스트 정의 금지. raw 값 직접 sampling 후 블랙리스트(취소/환불/반품 부분일치 제외) > 화이트리스트(정상 상태 열거). 정규화(공백 제거) 필수. → `patterns.md §시트status분류`
- **§로컬데이터이상진단**: 로컬 데이터 파일에서 이상값 발견 시 `git log -- {파일}` + `git show {최근자동커밋}` 비교 먼저. remote가 어떻게 저장했는지 확인 안 하고 "API/시스템이 바뀌었다" 결론 금지. (failures.md ㊶ 사례: 220M spend 보고 KRW 응답 오진 → 환경 3곳 잘못 변경)
- **§Go도구regex**: gitleaks/grafana/prometheus 등 Go re2 엔진은 lookahead `(?!)`/lookbehind `(?<=)` 미지원. Python regex 그대로 적용 금지 — char class 기반 재작성. 커밋 전 Python `re.search`로 양방향 검증: 진짜 시크릿 5+ 차단 + 정상 케이스 5+ 통과. (failures.md ㊹)
- **§환경변수3곳동기화**: 시스템 통화·토큰·계정 ID 등 글로벌 설정은 (a) GitHub Variables/Secrets, (b) `.github/workflows/*.yml` 기본값, (c) Vultr `.env` 3곳 동시 동기화. 한 곳만 바꾸면 다음 cron 실행이 사고 트리거. Vultr .env는 SSH 키 직접 없음 → `appleboy/ssh-action` 임시 워크플로우 생성·실행·삭제 패턴.
- **§코드후실행검증**: 코드/설정 변경 후 "수정 완료" 보고 전에 **실제 실행해서 결과 확인 후 보고**. (a) 코드: pytest 또는 dryrun 실행, (b) 워크플로우: `gh workflow run` + `gh run watch` + 로그 grep, (c) regex/필터: Python `re.search` 양방향 케이스, (d) 환경변수: 다음 cron 실제 실행 결과 또는 즉시 dispatch. "이론상 맞을 것"이라는 보고 금지 — 실측 데이터로 보고.
- **§코드워크플로우** (2026-05-18 강화 — 모든 코드 변경 6단계 + 큰 변경 자동 게이트): (1) **Plan** — logic 변경 시 `use_skill('writing-plans')` 호출. "코드 변경" 정의: 함수/클래스 신규·수정, 로직 분기, API 통합, 정규식, env/cron. 면제: 변수명·주석·log·import 정렬·설정 단순 값·문서·`.claude/`·`.github/workflows/`. (2) **Red** — `tests/test_*.py`에 실패하는 테스트 먼저 작성, `python -m pytest`로 실패 확인. (3) **Green/Refactor** — 최소 구현으로 통과 → 리팩토링 → 재실행. (4) **오류 시** — `use_skill('systematic-debugging')` 호출 (추측 금지). (5) **완료 전** — `use_skill('verification-before-completion')` + 실제 실행 결과 보고. (6) **큰 변경 자동 게이트** — git diff 50줄+ 또는 `cron`/`\.env`/`\.github/workflows`/`tracking_`/`repurchase_`/`_api\.py`/`oauth` 키워드 매치 시 Stop hook(`.claude/hooks/big-change-gate.py`)이 `pytest` + `ruff check {변경 .py만}` 자동 실행. 실패 시 차단 → systematic-debugging + `/codex:rescue`. 통과해도 50줄+면 Codex 권장. → `patterns.md §코드워크플로우`
- **§ops알림언어**: 텔레그램·이메일 ops 알림에 `gspread/quota/atomic/cron/API/worksheet` 등 기술 용어 배제. 구조: 무슨 일 발생(사용자 관점) → 왜(일반 언어) → 행동 단계(Apps Script 메뉴 경로·Claude 점검 요청 등). 승현님이 기술 지식 없이도 읽고 즉시 대응 가능해야 함. → `patterns.md §ops알림언어`

### 실수 자동 기록 (필수)
- 승현님이 실수·오류·잘못된 판단·금지사항 위반을 지적하면 → **즉시 `docs/lessons/failures.md` 상단(시간 역순)에 한 줄 누적 기록**
- 형식: `- **YYYY-MM-DD** ⓝ | {무엇을 잘못했는지} | **하지 말 것**: {회피 규칙}`
- 추가 시 사용자에게 "failures.md에 기록했습니다" 한 줄 보고
- **작업 시작 전** patterns.md 카테고리 인덱스(10개)와 §0 안전규칙 요약 8개 매칭. hook이 키워드 기반으로 patterns.md 해당 섹션 자동 주입함 (`.claude/hooks/inject-patterns.py`). **실수 1회 발생 즉시 failures.md 기록 + patterns.md 해당 카테고리 보강** (3회 대기 없음).
- **트리거 어휘 감지**: 사용자 발화에 "실수", "잘못됐어", "오류", "금지", "하지 말랬는데", "또 같은", "왜 또" 등 포함 시 → 즉시 `docs/lessons/failures.md` 상단에 한 줄 append + 사용자에게 "failures.md에 기록했습니다" 보고 (사전 승인 없이 박제. 부정확하면 사용자가 수정 요청).

---

## 1. 대표자

- 오승현 (Seunghyun Oh) · 1998-03-02 11:42 양력 출생, 경기도
- 거주·활동: 경기도
- 역할: HeavyLover 창업자·주 운영자
- 공동대표: 박재영 (체제 유지 확정)
- 자기 인식: "특정 기술 전문성보다 폭넓은 일반 역량 운영자"
- 사주 분석 시: 전통 방법, 대화 맥락 반영 금지 (독립 분석)
- 가족: 부친이 분당 미금역 학원 운영
- 민감: 2023-12부터 연애 중 — 먼저 꺼내지 않는 한 언급 금지

---

## 2. 회사·브랜드

- 브랜드: HeavyLover (헤비로버)
- 창업: 2023-07 (2026-07 → 3년차, 초기창업패키지 마지막 자격)
- 사업: D2C 피트니스 식품 (냉동 도시락 → 시리얼 확장)
- 타겟: 20~30대 운동 직장인 남성 (헬스 주 3회+, 벌크업, 시간·지식 부족)
- 포지셔닝: "운동하는 남자를 위한 고칼로리·고단백 냉동 완성식"
- 제품 기준: 1인분 **800kcal / 단백질 40g**
- 공법: IQF 급속냉동 + 수비드 저온조리
- 인증: HACCP
- OEM: 나비야 (Navia)
- 3PL: 더다이스

### 판매 채널
- 자사몰: Cafe24 (Imweb에서 이전 완료)
- 오픈마켓: 네이버 스마트스토어
- 과거 데이터: Imweb 1년치 (카페24 시트에 노란 배경 통합)
- 쿠팡: 미진입

---

## 3. 제품 라인업

### 판매 중 (냉동 도시락)
- 검증 SKU 4,000개+ 판매 실적
- 훈제 닭다리살: 독립 소싱 (차별 원료)
- 훈제 항정살: **아이디어 단계, 샘플 미진행** (재논의 시 사실 확인 필수)
- 밥 무름 이슈: OEM 유지 + 라벨·조리법·페이지 수정 대응 (확정)

### 출시 임박: 시리얼 (2026-06 정식)
- 품목제조보고 완료
- 동물성+식물성 이중 단백질, 치아시드
- 저당·고단백 포지셔닝
- 프리오더: 2026-04~05
- OEM: 나비야 아님 — 별도 제조업체. 패키지 포함 초도 비용 **3,500~4,000만원**
- 목적: 구매 빈도 증가 → CRM 데이터 축적 가속

### 해외 (검토 중)
- 냉동 도시락 직수출: KOTRA 지원사업 결과에 따라
- 레토르트 파우치 병행 옵션 (Amazon JP/US)

---

## 4. 핵심 KPI

### 사업
- 2026 Q1 월평균: 약 2,221만 원
- 2025 연매출: 약 2.0억 원
- 2026 목표: 연 10억 (자본 조달이 병목)
- **흑자 진입선: 월 5,000만 원** (현재 3,800만 → 갭 1,200만)

### 재구매 (CRM 실측 — 2026-04-29 분석 기준)
- 1→2회 전환: **23.2%** (실측)
- 재구매 간격 P50: **10일** (기존 15일 수정 — unit_economics.json 실측)
- 재구매 AOV: 신규 67,420원 / 재구매 86,529원 (×1.28)
- M+1 코호트 리텐션: **실측 평균 12.8%** (가정치 14% 아님. 2026-03 코호트 9.8% — K2 경계)
- 1회 후 이탈률: 76.8%
- 카페24 정착 고객(2회+): 평균 3.4회 구매
- LTV: 31,687원 / CAC: 17,717원 / LTV/CAC: 1.79
- **이상치**: 2026-02 코호트 M+1 29.5% — **원인 분석 완료** (2026-04-30): 광고 7주 중단 기간(2026-01-05~02-20) 소규모 고의도 유입(n=88). 대규모 유입 시 재현 불가. CRM 기준선은 전체 평균 12.8%로 설계. 상세: `docs/analysis_10b/cohort_funnel_diagnosis.md`

### 광고·채널 (2026-04-29 실측)
- Meta ROAS: 3.77 lifetime / **3.51 last30** (하락 추세 주의)
- 위너: 26.2.21 abo ROAS 6.20, AOV 81,918원
- 최하위: ROAS 2.33 → 위너 대비 3.68배 격차
- 26.4.2 스케일 abo: ROAS **3.02** → K1 기준선(2.8)까지 22bp 여유
- **퍼널 최대 병목: 결제→구매 49.85%** — 광고비 절반이 결제 단계에서 소실
- SS 재구매율 43% vs 카페24 21% — SS가 Meta 광고 지연 효과일 가능성 미검증
- 브랜드 검색량: 월 약 260

### 단위 경제학
- 마진율: 31~33% (가중평균 판매가 8,993원 / COGS 5,697원) — **물류비 포함**
- 월 고정비: 500~550만원 (박재영 100만/월 포함. 오승현 월급 포함 총액)
  - ※ 기존 bridge_10b.json의 656만원은 구 데이터 (박재영 499만 기준). 현재 100만으로 변경됨.
  - ※ 469만원은 강의 사업자카드 할부 (일회성, 잔액 약 250만원)
- **월 순이익 실측 (2026-04)**: 약 500만원 (모든 비용 차감 후 확정)
- LTV 1회 구매 기여 69% → 1회 구매만으로 광고비 부분 회수
- ROAS 3.3+ 유지 시 광고 스케일업 타당

---

## 5. 기술 인프라 (요약)

> 상세 — Cron·시트 정책·SS sync 규칙·재구매 파이프라인·엑셀 생성 로직·SaaS 스택 전부: **`docs/context/infra.md`**
> 운영 가이드: `docs/deploy-repurchase-cron.md`, `docs/setup-repurchase-automation.md`, `docs/looker-studio-repurchase-dashboard.md`

### 자동화 상태 (한눈에)
| 기능 | 상태 |
|---|---|
| 11시 엑셀 생성 + OneDrive + 텔레그램 | ✅ 평일 (SS는 `orders_pending_dispatch` 14일 PAYED 전수 — 누락 0건, 알림은 전화번호 기준 N명) |
| 송장 등록 (`/tracking` 명령) | ✅ 바탕화면 xls → rclone → 카페24/SS 자동 등록 (PlusCL 인증 발급 시 병행 가능) |
| 04:00 카페24 OAuth 자동 갱신 | ✅ 매일 |
| 08:30 시트 sync (카페24 + SS 5상태) | ✅ 매일 |
| 09:00 재구매 리포트 + 📊대시보드 3개(통합/카페24/SS) + 텔레그램 | ✅ 매일 — v6: 변동중 표시·시트 숨김·RuntimeError fail-fast |
| **재구매 Python 분석** (`repurchase_analysis.py`) | 🔄 **shadow 검증 중 (2026-05-20~)** — 08:45 `--shadow`로 `py_` 탭 병행 생성, 08:55 `compare_analysis.py`로 GAS vs Python 수치 자동 비교. `py_` 탭 19개 숨김 완료(**삭제 아님** — 승현님 확정). 7일 연속 불일치 0건 → cut-over: (1) `sheet_staleness.py` `"gas"`→`"analysis"` 2곳, (2) cron `--shadow` 제거, (3) GAS 트리거 삭제. GAS 트리거는 유지 중. |
| **GitHub push → Vultr 자동 배포** (`.github/workflows/deploy-vultr.yml`) | ✅ `*.py` push 시 SSH→`git reset --hard origin/main`→텔레그램 알림. 콘솔 진입 불필요 |
| **정부지원 레이더** (`/govt-radar` 슬래시 명령) | 🔄 수동 — 매주 월요일 오전 권장. GitHub Actions cron 해제(2026-05-19). 백업: `workflow_dispatch`. Playwright 8개(소상공인24 포함). |
| 카페24 N10→N20 / SS 신규→발주확인 | 수동 (API 한계) |

### 위치 요약
- 주문 자동화: Vultr (158.247.215.170, Ubuntu 22.04) `/root/heavylover-automation/`
- 재구매 분석: Vultr `/root/heavylover-repurchase/` (별도 폴더, 충돌 방지) — `_open_sheet()` 작성 시 `sheets_sync.py` 폴백 패턴 복사 필수 (`GOOGLE_SA_KEY_PATH` 없으면 동일 폴더 `gcp-service-account.json` 자동 대체)
- 택배사: 로젠 단일 — Cafe24 `0004` / 네이버 `KGB`
- 작업: Windows + Git Bash/PowerShell. CLAUDE.md "가동 중" 표기 신뢰 금지 → `crontab -l` 실측 (patterns.md §자동화점검)

---

## 6. 브랜드 보이스

### 페르소나 (고객 콘텐츠)
"스포츠 영양 전문가가 친한 형에게 눈높이 맞춰 설명하는 톤"

### 허용 어휘
- 운동, 운동하는 사람, 헬스하는 직장인
- 단백질, 벌크업, 컷팅
- 챙겨먹다, 먹을 만하다, 든든하다
- 정직하게, 솔직히, 사실

### 시그니처 후킹
- "4,000개가 팔린 데엔 이유가 있습니다"
- "~는 거, 아시나요?"
- "헬스장에서 {행동}하는 {퍼센트}의 사람들이 모르는 것"
- 숫자 + 단정 / 반전 / 비밀 / 문제 지적

### 이모지
- 허용: 💪 📦 🍱 ✅
- 1 콘텐츠당 1~2개 이내 (금지 목록은 §0)

---

## 7. 블로그 작성 (요약)

> 상세 — 네이버 C-Rank/D.I.A+ 알고리즘, 글 구조, 분량·이미지 규칙, 발행 전 체크리스트, 표준 도입 프롬프트 전부: **`docs/context/blog.md`**
> 작업 시: blog-writer 서브에이전트 호출 (메인 컨텍스트 보호) 또는 위 파일 직접 Read.

- 발행: 화·목 주 2회 / 1,500~2,500자 / 이미지 3+장 / 외부 출처 1+
- 제목 앞 20자 키워드 + 후킹, 첫 문단 100자 키워드 1~2회
- 주제 일관성 유지 (운동·식단·단백질). AI 화법·과장 금지(§0)

---

## 8. Meta 광고

> 상세 전부: **`docs/context/ads.md`** (벤치마크·플래그·전략·스케일업·cron·데이터 저장)
> 작업 시: meta-ads-analyst 서브에이전트 호출. 코드 정본: `docs/meta-ads/benchmarks.md`

- 광고 계정: `act_445075134545178` / System User Token (무기한) ✅
- cron: 매일 09:00 일일 / 매주 월 위너패턴 / 매주 일 종합 (E2E 검증 완료 2026-04-29)
- 텔레그램 4채널: ops·report·ads·govt 분리 완료
- 5개월 누적 ROAS 3.77 / 위너 6.20 / 결제 전환율 49.85% (최대 병목)
- 핵심 벤치: ROAS 우수 4.0+, CPA 우수 20,000원-

---

## 9. Top of Mind

### 즉시 대응 (이번 주 — 2026-05-15 기준)
1. **결제 퍼널 개선**: 배송비 상품 페이지 사전 표시 + 카카오 소셜 로그인 추가 (비용 0, 반나절) — 미진행
2. **2026-02 M+1 29.5% 코호트 후속 심층 분석** (Claude) — 1차 원인 규명 §4 박제 완료. CRM 설계 전 추가 검증 필요
3. **재구매 고객 그룹 분류 인프라 구축** (Claude, **진행중**) — 이메일 자동화의 선결조건
4. **GA4+UTM 블로그 전환 추적 설치** (Claude+승현님, 반나절) — 미진행
5. **고반복 고객 13명 레퍼럴 쿠폰 발송** — 트레이너 가설 검증 + B2B 방향 결정 (미진행)
6. 상생성장지원자금 1억 → **현장실사 완료 → 결과 대기** (K4 연동)
7. 시리얼 프리오더 (4~5월) → 6월 정식 출시 (미진행 — 일정 재점검 필요)

### 정부지원사업 신규 발굴 (2026-05-15 크롤링 결과)
> Playwright Python으로 기존 자동화 0건 사이트 6개 직접 확인. 아래 마감 임박 항목 즉시 검토 필요.

| 마감 | 사업명 | 지원 내용 | 출처 |
|---|---|---|---|
| **D-5 (05.20)** | **제조창업기업성장지원사업** | 시제품 개발 사업화자금 직접 지원 | K-Startup |
| D-11 (05.26) | 경기도 소상공인 전문컨설팅단 | 무료 마케팅·운영 컨설팅 | 경기바로 |
| 06.08 | AI 청년창업기업 동반성장 바우처 | AI 서비스 바우처 | NIPA |
| 상시 | 소상공인 정책자금 융자계획 | 저금리 직접 융자 | 소상공인24 |
| 상시 | 용인IP지원센터 IP전략수립 지원 | 상표·IP 전략 (용인시 직결) | 경기테크노파크 |
| 상시 | 소상공인 고용보험료 지원 | 보험료 지원 | 소상공인24/경기바로 |

**크롤링 시스템 현황 (2026-05-15 기준)**
- 총 25개 소스 / 940건 수집 / 작동 15개 소스
- 이번 세션 수정: `fetch_fanfandaero` (0→6건), `fetch_gbsa` (0→9건, egbiz.or.kr로 변경)
- 여전히 SPA라 자동화 불가 (Playwright 수동 필요): 소상공인24(447건 DB)·경기스타트업플랫폼·경기테크노파크
- 기업마당·K-Startup이 중기부·농림부·창업진흥원 통합 커버 (실질 공백 아님)

### 진행 중 (2026-04~07)
- 스마트스토어 API 자동화 (프록시 IP 확보 + **코드 완성 → 테스트 중**)
- 정부 지원사업 다중 신청
  - 초기창업패키지 2차 (3년차 자격 마지막)
  - 용인시 온라인 플랫폼 지원사업 (서류 통과)
  - KOTRA 내수기업 수출기업화
  - 지식재산바우처 (상표 — 네이버 브랜드관 입점 선결조건)
- ~~Meta Ads API 자동화~~ ✅ 완료 (2026-04-29 E2E 검증)
  - System User Token (무기한) 발급 + GitHub Secrets 등록
  - 텔레그램 4채널 분리 완료 (ops/report/ads/govt)
  - 매일 09:00 KST 일일 리포트 + 매주 일요일 종합 리포트 자동 가동
- 등기사항전부증명서 리뷰

### 이월된 계획 (05-06~05-10 미실행 — 재계획 필요)
- A-2 광고 소재 변경 ("2박스로 2주치" 메시지) + 전환율 롤백 트리거 설정
- SS 소규모 광고 실험 (Meta→SS 50만원 — 오가닉 vs 지연 효과 4주 검증)
- 복지몰 베네피아 입점 신청 1곳 파일럿

### 검토 (2순위)
- 모두의 아이디어 경진대회 — 전세 사기 방지 시스템 지원
- 해외향 SaaS (승현 1인) — 영어권 D2C repurchase 추적, Reddit 검증 선행
- Lovable/Cursor 테스트 도입
- 상표권 등록 전략

---

## 10. 장기 자산·강점

1. **CRM 데이터 인프라** — 동급 D2C 희소. 의사결정 속도 2~3배.
2. **검증된 단위경제학** — ROAS 3.5 + 재구매 30% + AOV 2배 = 광고 스케일 수학적 성립.
3. **PMF 시그널** — P50 10일 = 생활 루틴 편입.
4. **명확한 포지셔닝** — 벌크업 냉동 세그먼트 블루오션 + HACCP.
5. **운영자형 대표** — AI 도구·인프라 직접 구축, 외부 의존 낮음.
6. **양 채널 자동화** — Cafe24 OAuth + SS 프록시 = 희귀 구조.

---

## 11. 디렉토리 구조

```
heavylover-automation/
├── CLAUDE.md            ← 본 파일 (코어 컨텍스트만)
├── .claude/
│   ├── agents/
│   │   ├── (운영) blog-writer, meta-ads-analyst, automation-debugger, cs-responder 등
│   │   ├── proposal/    ← 사업계획서 7역할 (drafter, rubric-mapper, consistency, budget-auditor, competitor, fact-checker, devil)
│   │   ├── strategy/    ← 성장전략 5에이전트 갑론을박 (margin/acquisition/structural/capital/identity + orchestrator)
│   │   └── expansion/   ← 확장 토론 13에이전트 (6도메인 × proposer+challenger + orchestrator)
│   ├── hooks/           ← UserPromptSubmit hook (inject-patterns.py)
│   ├── settings.json
│   └── commands/        ← /proposal, /strategy-debate, /expansion-debate
├── *.py                 ← 자동화 스크립트
├── .github/workflows/   ← Meta 광고 cron + deploy-vultr.yml
├── data/
│   ├── meta_ads/        ← daily.csv, daily_campaign.csv, winner_patterns.jsonl
│   └── analysis_10b/    ← unit_economics.json, bridge_10b.json, sheets/*.csv
├── docs/
│   ├── context/         ← infra.md, blog.md, ads.md
│   ├── lessons/         ← failures.md, patterns.md
│   ├── analysis_10b/    ← IC 진단 리포트 8섹션 + _master.md + charts/
│   ├── strategy/outputs/← 5에이전트 갑론을박 라운드1~5 + 6개월 로드맵 (2026-04-29)
│   ├── expansion/outputs/← 6도메인 토론 결과 + expansion-synthesis.md (2026-04-29)
│   ├── meta-ads/        ← benchmarks.md, reports/
│   ├── new_business/    ← 신규 사업 트랙 (본업과 분리). 최우선 참조: hoa-business-summary-v3-2026-05-11.md / R1~R8 본체: ~/.claude/plans/hoa-greedy-simon.md
│   └── govt-radar/
└── proposals/           ← 사업계획서 시스템
```

---

## 12. 업데이트 규칙

- **본 파일은 코어만**: 영역별 상세는 `docs/context/`로 분리. 길어지면 추가 분할.
- 월 1회 claude.ai 메모리 덤프 → 갱신
  > "지금까지 저에 대해 저장된 모든 메모리를 코드블록으로 출력해줘. 작업·사업 관련 맥락 위주로."
- 낡은 정보 즉시 삭제
- 상단 "최종 업데이트" 날짜 갱신
- §3·§4·§9는 월 1회 이상 갱신
- §5·§7·§8 헤더에서 참조하는 `docs/context/` 파일은 변경 발생 시 즉시 갱신

---

## 13. 전략 분석 요약 (2026-04-29 완료)

> 상세 원본: `docs/analysis_10b/_master.md`, `docs/strategy/outputs/`, `docs/expansion/outputs/`
> Kill Criteria 8개(K1~K8) + 6개월 로드맵(ACT-01~08) + 탈락 확정 제안: 위 경로 참조.
> 핵심 수치(P50·M+1·ROAS·AOV)는 §4에 통합됨. 재실행 불필요 (산출물 존재).
> 탈락 확정: TikTok 파일럿 (흑자선 미달 + 1인 운영 병목 + 전환 추적 불가)

---

**Claude Code는 이 파일을 전제로 모든 작업을 시작한다.**
