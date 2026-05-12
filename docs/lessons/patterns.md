# 회피 패턴 (작업 종류별 재사용 규칙)

> 이 파일은 [위험 작업 시작 전 / 에이전트 자동 참조] 시 로드됩니다. `failures.md` 시간순 로그에서 **1회 발생 즉시** 해당 카테고리에 회피 규칙을 반영합니다 (3회 대기 없음).
> 마지막 갱신: 2026-05-01 · 갱신 주기: 신규 패턴 발생 시 / 월말 회고

## 작업 종류별 빠른 매칭

| 지금 하려는 작업 | 먼저 읽을 카테고리 |
|---|---|
| API·cron·.env 의존 자동화 | §자동화점검 + §외부API다루기 |
| 카페24·SS·Meta·Anthropic 등 외부 API 통합 | §외부API다루기 |
| 시간 윈도우·dedupe 로직 | §시간중복처리 + §데이터범위와분석분리 |
| Excel·xlsx·openpyxl | §엑셀편집 |
| 5,000자 이상 응답·다중 모듈 | §출력관리 |
| 정부지원·govt-radar·지역 매칭 | §지역자격필터 |
| 메일·OS·세션 가정 | §환경컨텍스트 |
| **재무·KPI 수치 사용 / 의사결정 분석** | **§수치현행성검증** |
| **사업계획서·정부지원 제출 서류 목록** | **§제출요건정본확인** |
| **산출물 생성·MCP/npm 실행·OneDrive 작업** | **§파일안전성** |

---

## §자동화점검 (Pre-flight Checks)

**목적**: 자격증명·서비스 상태 미확인으로 작업 도중 막히는 패턴 차단.

코드 작성 **전에** 다음을 검증한다:
1. **`.env` 필수 키 존재**: 작업에 필요한 키가 비어있으면 → 코드 작성 보류, 발급 가이드부터 안내
2. **외부 토큰 만료 여부**: Cafe24·Meta·Anthropic·Naver IMAP·Gmail SMTP — 만료 의심 시 갱신부터
3. **대상 디렉터리·파일 실재**: `Glob`·`ls`로 검증. 비존재면 작업 중단하고 사용자에게 알림
4. **배포 상태는 문서가 아니라 실측**: `crontab -l`, 서버 파일 존재, `gh workflow list`로 1차 검증. CLAUDE.md에 "가동 중"이라 적혀 있어도 실제 가동 여부 별개로 확인

**연관 실패**: failures.md ⑤(OAuth 만료), ⑪(crontab 문서 신뢰)

**자동화 후보**:
- 외부 API refresh_token 만료 정책 있는 서비스는 만료 전 자동 갱신 cron 신설 (예: `04:00 refresh_cafe24_token.py`). 같은 패턴 적용 후보: Meta long-lived token, 네이버 커머스.

---

## §외부API다루기

**목적**: 카페24·스마트스토어·Meta·Anthropic·Google 등 외부 API 통합 시 추측·샘플 결론·키 경로 가정으로 인한 데이터 무결성 사고 방지.

### 규칙
1. **응답 매핑은 raw JSON 1건 출력 후 키 검증**: 코드 작성 직후 실제 응답을 print해 키 경로 (`order.paymentDate` vs `productOrder.paymentDate`) 확인. 한 달 가동된 자동화도 시트 데이터가 비어있는지 점검.
2. **API 커버리지 판단은 페이지네이션 끝까지**: "100건 샘플"로 결론 금지. 키워드 직접 검색 또는 전수 페이지 펼침으로 확인.
3. **식별자·인코딩 포맷은 공식 문서 확인**: 추측 금지. 예) Google Calendar event_id는 base32hex(0-9, a-v)만 허용 → `b32hexencode` 사용. 일반 `base64.b32encode`(a-z, 2-7)는 거부됨.
4. **새 외부 API 첫 통합 시 에러 메시지 보고 즉시 다른 인코딩·포맷 후보 시도**.
5. **Claude 메모리 시스템 (사용자 환경 박제 인덱스) 코드 작성 전 1회 훑기**: 명칭 변경·본사 위치·발신자 화이트리스트 등 박제 정보 누락 방지. 메모리는 시스템 프롬프트 `auto memory` 섹션이 자동 로드.
6. **토큰 종류·수명은 공식 문서로 확인**: short-lived/long-lived/system-user 등 종류별 만료 시간 다름. Meta User Access Token (Graph API Explorer)은 수 시간, long-lived는 60일 (`fb_exchange_token` + 앱 시크릿). 자동화 일정은 토큰 수명 검증 후 설계.
7. **토큰 만료 자동 감지 + 텔레그램 안내 박제**: 만료 키워드(`Session has expired`, `OAuthException`, `code:190/463`, `401`) 감지 시 명확한 재발급 단계 안내 메시지 자동 발송. fallback이 침묵하면 안 됨.
8. **외부 API 첫 응답에서 통화·시간대·단위 즉시 확인**: 광고 계정 통화(USD vs KRW), 응답 시간대(UTC vs 로컬), 금액 단위(원 vs 달러 vs 1/100) 가정 금지. KRW 외 계정이면 환산 함수를 단가성 필드에 일관 적용 — 환율은 변동값 안 쓰고 고정 상수(`CURRENCY_KRW_PER_USD`)로 단일 출처 관리.
9. **신규 리포트·스크립트 작성 시 환산 함수는 `lib.meta_currency`에서만 import**: 자체 구현·재계산 금지. 환산은 단일 진입점(`summarize_row`류)에만 적용. `aggregate_totals` 같은 합산 함수에 환산 추가 금지 (이중 환산 ×1450² 사고).

**연관 실패**: failures.md ②(paymentDate 키 경로), ⑨(memory 미참조), ⑩(100건 샘플 결론), ⑫(Calendar event_id 인코딩), ⑭(memory 경로 박제), ⑮(Meta 토큰 수명 가정), ⑯(통화 단위 가정), ㉝(주간 리포트 환산 누락)

---

## §시간중복처리

**목적**: 시간 윈도우·dedupe 로직에서 cron 갭·문자열 비교·24시간 한계로 인한 누락·중복 차단.

### 규칙
1. **시간 윈도우 방식은 cron 갭과 만나면 누락 영구화**. 채널이 상태 기반 조회를 지원하면 그것을 우선 사용.
2. **변경 윈도우 강제 시 3중 안전망**:
   - cron 주기보다 충분히 넓게 (14일+)
   - 자연 키 dedupe (주문번호+결제일시+...)
   - 상세 응답 상태 재필터 (`productOrderStatus=='PAYED'`만)
3. **24시간 윈도우 한계 우회**: 1일 분할 N×5번 호출 + RATE_LIMIT 시 5초 대기 재시도 (sheets_sync 패턴).
4. **시간 포함 컬럼 cutoff 비교 시 cutoff에 ` 00:00` 명시**. 'YYYY-MM-DD' vs 'YYYY-MM-DD HH:MM:SS' 문자열 비교는 당일 시간대 행 dedupe 실패 원인.
5. **시트 dedupe는 자연 키 기반 1회 추가 적용**.
6. **발송기한 초과 분 별도 카운트**: `shippingDueDate < now`는 텔레그램 알림에 명시 노출.

**연관 실패**: failures.md ①(SS 33건 누락), ④(Cafe24 9건 dedupe)

---

## §데이터범위와분석분리

**목적**: "어떤 데이터를 저장할지(이전 범위)"와 "어떤 데이터를 쓸지(분석 정책)"를 혼동해 발생하는 누락 차단.

### 규칙
1. **저장은 넓게, 분석은 컬럼 필터로**: "구매확정만 분석" 정책이라도 시트엔 5상태 (PURCHASE_DECIDED·PAYED·DISPATCHED·DELIVERING·DELIVERED) 모두 보관. 분석 쿼리에서 주문상태 컬럼으로 필터.
2. **취소/반품/미결제는 원천 제외**: 데이터 이전 단계에서 제외해야 추후 분석 부담 감소.
3. **상태 변화 가능한 주문은 reverse-dedupe (최신 상태 우선)**: productOrderId 기준.

**연관 실패**: failures.md ③(SS 5상태 누락)

---

## §엑셀편집

**목적**: 과거 디자인 요청에서 freeze panes·hidden rows·invalid cell types·duplicate columns·orphaned panes 임의 추가로 파일 손상 반복 방지.

### 규칙
1. **"디자인/포맷팅" 요청 시 건드릴 것**: 색상·폰트·테두리·열 너비만.
2. **건드리지 말 것**: 수식·freeze panes·숨김 행/열·셀 타입·시트 구조·행 높이.
3. **편집 후 반드시 검증**: `python -c "import openpyxl; openpyxl.load_workbook('파일')"` 통과 확인 후 보고.
4. **"이거 추가하면 좋겠는데"는 사용자 확인 후 진행**, 자체 판단 금지.

**연관 실패**: failures.md ⑦(Excel freeze panes 등 임의 추가)

**자동화 후보**: settings.json `PostToolUse` hook으로 openpyxl 편집 후 자동 `load_workbook()` 검증.

---

## §출력관리

**목적**: 큰 파일·다중 모듈을 한 응답에 몰아서 출력 토큰 한도 초과로 세션 손실 방지.

### 규칙
1. **단계 분할 출력**: ① 파일 구조 → ② 핵심 로직 → ③ 통합 → ④ 테스트.
2. **분석 리포트는 표 + 요약 우선**, 문장 나열 지양.
3. **한 응답 5,000자 초과 우려 시 사용자에게 분할 제안 후 진행**.

**연관 실패**: failures.md ⑥(/insights 출력 토큰 한도 초과)

---

## §지역자격필터

**목적**: 정부지원·govt-radar 매칭에서 본사 위치(용인) 기준 비자격 공고가 통과해 텔레그램 노이즈·잘못된 신청 검토 방지.

### 규칙
1. **차단 목록은 광역(시·도) + 산하(시·군·구) 모두 작성**: NON_ELIGIBLE_REGIONS에 광역지자체만 있으면 경기도 산하 시·군(파주·화성·부천·시흥 등) 한정 공고가 [경기] prefix만 보고 통과.
2. **본사 prefix가 없는 한 차단**: 타 시·군 prefix · 발주기관 · 본문 자격 한정 (`관내 본사`·`해당 지자체에 본사 위치` 등) 모두 차단.
3. **회귀 테스트로 박제**: `tests/scorer_scenarios.py`에 케이스 추가.
4. **Claude 메모리 hq_location 항목 참조**: 헤비로버 본사 = 경기도 용인시 수지구.

**연관 실패**: failures.md ⑬(시·군 한정 19건 통과)

---

## §환경컨텍스트

**목적**: 메일 계정·OS·세션 경계 가정으로 인한 재계획·잘못된 안내 방지.

### 규칙
1. **메일 분리** (가정 금지):
   - 사적 (Naver IMAP): `ohkm8050@naver.com` — 정부지원 레이더 Layer 2 교차검증 수신
   - 업무 (Gmail SMTP): `osh805050@gmail.com` — 자동화 발송 + 주간 리포트 수신
   - **Gmail이 메인이라고 가정 금지.** 둘 다 사용 중. 작업 시 어느 쪽인지 명시.
2. **알림 채널 우선순위**: Telegram(승인·일일 알림) > 이메일(주간 리포트) > 카카오(추후 도입)
3. **OS·셸**: Windows 11 + Git Bash + PowerShell 병행. 경로는 백슬래시·슬래시 혼용 가능.
4. **사용자 자질**: 비전공자 한국어 사용자. 기술 용어는 비유·예시로 풀어서. "뭔소린지 모르겠어" 류 발화 시 즉시 더 쉬운 비유로 재설명.
5. **세션 경계 안내**: 활성 Claude 세션 안에 `claude -c`·`claude -r` CLI 명령을 사용자가 직접 타이핑해도 인식 안 됨. CLI스러운 입력 들어오면 즉시 위치 안내.

**연관 실패**: failures.md ⑧(Naver vs Gmail 가정)

**연관 메모리**: Claude 메모리 항목 — govt_radar_mail, feedback_session_boundaries

---

## 패턴 승격 절차

**실시간 (실수 발생 즉시):**
1. `failures.md` 상단에 한 줄 추가
2. 해당 실수가 속하는 카테고리(§자동화점검·§외부API다루기 등)를 즉시 보강 — 3회 대기 없음
3. 기존 카테고리에 해당 없으면 신규 §카테고리 추가

**월말 회고 (매월 1일):**
1. `grep -c "^- \*\*" docs/lessons/failures.md` 로 누적 항목 수 확인
2. 가장 빈번한 4건 (현재: §출력관리·§엑셀편집·§환경컨텍스트·§자동화점검)은 CLAUDE.md §0에 1줄 요약 + 포인터 갱신

---

## §수치현행성검증 (Number Freshness Check)

**목적**: CLAUDE.md·bridge_10b.json·unit_economics.json 등에 박제된 수치를 **현재값으로 가정**하다가 의사결정용 분석이 통째로 틀리는 패턴 차단.

**핵심 원칙**: 박제된 수치는 *작성 시점의 사실*이지 *현재의 사실*이 아니다.

**작업 시작 전 점검**:
1. 사용하려는 수치의 **마지막 갱신 시점** 확인 (파일 상단 메타 또는 git log)
2. 30일 이상 경과 + 인건비·고정비·매출·운영자금 같은 **변동성 큰 항목**이면 → 사용 전 사용자에게 1줄 확인: "현재 ◯◯◯ 맞나요?"
3. 동일 항목에 **두 개 이상의 값이 보이면** (예: 광고비 490만 vs 690만) → 계산 진행 금지. 정본부터 확인.
4. 명목 금액만으로 항목 분류 금지 (예: "박재영 469만"이 인건비인지 할부인지 등). **성격(고정/일회성/변동) 확인 후 사용**.

**관련 데이터의 신뢰도 등급**:
- 🟢 **실측 즉시 확인 가능**: Meta Ads Manager API, 카페24 시트 sync — 그대로 사용
- 🟡 **박제 + 변동성 큼**: bridge_10b.json·unit_economics.json·CLAUDE.md §4 KPI — **사용자 1줄 확인 필수**
- 🔴 **추정·가정값**: bridge_10b.json `assumed`, "현재상태" 표기 — 의사결정 사용 금지, 실측 선행

**자가 검증 체크**:
- [ ] 인건비·고정비·순이익 사용 시 사용자에게 "현재도 맞나요?" 1줄 확인했는가
- [ ] 같은 항목에 두 값 보이면 정본 확인 후 계산했는가
- [ ] CLAUDE.md "즉시 대응" 항목을 권고로 사용하지 않고 **현재 상태**부터 확인했는가
- [ ] 분석 결과에 "(추정)" / "(실측, 2026-XX-XX 기준)" 표기 분리했는가

**연관 실패**: failures.md ㉔(박재영 469만 오분류), ㉕(광고비 490 vs 690 혼재), ㉖(결제 퍼널 이미 완료된 항목 권고), ㉗(고정비 656만 구 데이터)

**자동화 후보**:
- bridge_10b.json·unit_economics.json 상단에 "마지막 갱신일" + "변동성 ⚠️" 메타 자동 삽입
- CLAUDE.md §9 "즉시 대응" 항목에 완료/진행/대기 상태 컬럼 추가

---

## §제출요건정본확인 (Submission Requirements Source-of-Truth)

**목적**: 정부지원·사업계획서 제출 서류 목록을 **사업계획서 본문 언급**이나 **추정**으로 결정하다가 불필요한 작업·누락 발생하는 패턴 차단.

**핵심 원칙**: **공고문 원문 = 정본**. 사업계획서 본문에 등장한 협력사·파트너사 언급 ≠ 제출 요건.

**작업 시작 전 점검**:
1. 사업별 제출 서류 목록은 반드시 **공고문 PDF/HWP 원본 직접 읽기** (`사업/지원사업/{사업명}/공고문*.pdf`)
2. `psst-rubric.json`의 `programs.{사업명}` 블록에 "submission_docs" 필드 있는지 확인
3. 없으면 사용자에게 "공고문 어디 있나요?" 묻기. 절대 추정으로 채우지 않기
4. `setup_proposal_folder.py`의 사업별 서류 맵 변경 시 → 공고문 PDF 재확인 후 추가/삭제 + 변경 이유 주석

**자주 혼동하는 두 가지**:
| 본문 강화용 (자발적 첨부) | 제출 요건 (필수) |
|---|---|
| 파트너사 합격 통지서·MOU | 사업자등록증·납세증명서·통장사본 |
| OEM 견적서·계약서 | 등기사항전부증명서·중소기업확인서 |
| 자체 데이터·KPI 캡처 | 부가가치세과세표준증명원·소득금액증명원 |

→ 좌측은 사업계획서 신뢰도 강화용, 우측은 자격 검증용. **둘은 다른 카테고리**.

**자가 검증 체크**:
- [ ] 공고문 PDF/HWP 원본을 직접 읽었는가
- [ ] "본문에 언급됐으니 첨부 필요"라는 논리로 추가하지 않았는가
- [ ] 사업별 서류 맵 변경 시 변경 이유를 주석으로 박제했는가

**연관 실패**: failures.md ㉘(KOTRA 합격통지서 자동 추가)

**자동화 후보**:
- `psst-rubric.json` programs 블록에 `submission_docs: [...]` 필드 정식 추가
- 공고문 PDF에서 "제출 서류" 섹션 자동 추출 → 서류 맵 갱신 cron

---

## §코드수정전체크 (Pre-Edit Checklist)

**목적**: 코드 수정 전 현재 상태를 확인하지 않아 발생하는 실수 차단.

**핵심 원칙**: 코드를 쓰기 전에 반드시 현재 상태를 실측한다.

**작업 시작 전 점검**:
1. **파일은 반드시 Read 후 수정**: 파일 내용 가정 금지. 수정 전 Read 도구로 먼저 읽기.
2. **함수/인자 변경 시 호출 스택 전체 확인**: 바꾼 함수를 호출하는 곳이 어디인지 Grep으로 찾아서 전달 여부까지 확인. "이 함수만 고치면 끝"은 없음.
3. **config dict 키 참조는 `.get()` 사용**: `c["key"]` 직접 참조 금지. 키가 없는 변형 config 실행 시 즉시 KeyError. 옵션 키는 `c.get("key")` 또는 `if "key" in c:` 패턴.
4. **CLAUDE.md 수치는 현재값 아님**: CLAUDE.md·json 파일의 수치는 작성 시점 스냅샷. 인건비·고정비·매출·완료 여부 등은 사용자에게 "현재도 맞나요?" 1줄 확인 후 사용.
5. **"가동 중" 표기는 문서 신뢰 금지**: crontab·서버 파일·배포 상태는 `crontab -l`·`git log`·`gh workflow list` 실측 후 판단.

**자가 검증 체크**:
- [ ] 수정할 파일을 Read로 먼저 읽었는가
- [ ] 변경한 함수를 호출하는 곳을 Grep으로 찾아 전달 여부 확인했는가
- [ ] config 키 참조를 `.get()` 또는 `if "key" in c:`로 작성했는가
- [ ] CLAUDE.md 수치를 그대로 쓰지 않고 사용자에게 확인했는가

**연관 실패**: failures.md ㉛(config KeyError + 호출 스택 누락), ㉗(고정비 구 데이터), ㉖(결제 퍼널 이미 완료), ⑪(crontab 문서 신뢰)

---

## §파일안전성 (File Safety)

**목적**: 외부 도구(MCP·npm·OneDrive·백신)에 의한 의도치 않은 파일 손실 차단.

**핵심 원칙**: git에 추적되지 않는 파일은 언제든 사라질 수 있다고 가정.

**작업 시작 전 점검**:
1. 새로 생성하는 산출물이 `.gitignore`로 차단되는지 확인 (`git check-ignore -v {파일경로}`)
2. 차단된다면 → 정책 결정: ① 추적 활성화 ② 외부 백업 ③ 위험 감수 — 기본은 ①
3. OneDrive 동기화 폴더에서 npm/npx/MCP 서버 실행 시 추가 주의 — 실행 전 주요 산출물 git add·commit 권장
4. 세션 시작 전 복원 불가 산출물 목록을 `git status`로 확인

**자가 검증 체크**:
- [ ] 이번 작업 산출물이 `git status`에 tracked로 표시되는가
- [ ] MCP 서버·npm 실행 전 최근 산출물 commit 완료했는가
- [ ] file-history 복원에 의존하지 않아도 되는가 (git이 보장하는가)

**연관 실패**: failures.md ㉙(MCP 활성 중 산출물 5폴더 동시 손실)

**2026-05-01 이후 정책 변경**:
- `docs/analysis_10b/`, `proposals/outputs/`, `docs/strategy/outputs/`, `docs/expansion/outputs/`, `data/analysis_10b/sheets/` → git 추적 활성화
- `.gitignore`에 추적 제외 대상 명시: `data/raw/`, `data/meta_ads/raw/`, 비밀파일 계열만


## §plan점검 (Plan Adversarial Review Loop Prevention)

**목적**: plan-level codex adversarial review에서 결함이 끝없이 발견되는 무한 루프 차단.

**핵심 원칙**: codex는 adversarial 도구라 plan이 정밀해질수록 새 결함을 끝없이 찾음. 큰 plan일수록 결함 발견량이 줄지 않고 늘어남.

**작업 시작 전 점검**:
1. plan의 변경 사항 개수 카운트 → **5개 이상이면 분할 검토**
2. 분할 기준: (a) 멈춤 방지/수치 정확성 — 우선, (b) UI·UX — 다음 plan, (c) 운영 프로세스 — 별도 plan
3. plan 작성 직후 codex review 1회만 — 2회차는 1회차 결함 수정 후
4. **iteration cap 2회 고정** — 3회차 진입 전에 사용자 결정 받기

**무한 루프 신호**:
- v1(N결함) → v2(N결함) → v3(N결함) — 결함 수가 줄지 않음 → 즉시 중단
- 새 결함이 점점 정밀해짐 (구현 디테일·메타데이터 누락 등) → 코드 진입 권고
- "이게 v5 패턴 재현" 같은 사용자 발화 → 즉시 옵션 제시 (분할 vs HIGH만 처리)

**의사결정 가이드**:
- 5개+ 변경 plan = 분할 (각 codex 1~2회면 충분)
- 2~3개 변경 plan = 단일 plan OK
- 의존성 강하면 순차 plan, 독립이면 병렬 plan

**자가 검증 체크**:
- [ ] 이 plan 변경 사항이 5개 미만인가
- [ ] codex 점검을 2회 이상 돌렸을 때 결함 줄어드는 추세인가
- [ ] iteration cap 2회 명시했는가
- [ ] HIGH/CRITICAL만 block, MEDIUM은 residual-risk로 진행 정책 있는가

**연관 실패**: failures.md ㊲(plan v1→v4 4회 무한 루프), v5/v6 분할로 해소

**hookify 보강**: `.claude/hookify.warn-plan-codex-loop.local.md` + `.claude/hookify.warn-large-plan-split.local.md`


## §비율지표분모 (Ratio Denominator Validation)

**목적**: 재구매율·전환율·리텐션·M+N 등 비율 지표 분모 정의 오류로 인한 가짜 수치 차단.

**핵심 원칙**: 분모 정의 따라 같은 데이터가 1.5~3배 차이. 비율 지표 점검 시 항상 3가지 확인.

**분모 점검 3가지** (필수):
1. **같은 버킷 중복 dedup** — 한 고객이 같은 일/주/월 안에서 신규 + 재구매 둘 다 했을 때 1명으로 카운트
   - `totalCust = new Set([...newCust, ...repurchaseCust]).size`
2. **미관찰(observing) 고객 제외** — 첫 구매 후 N일 미경과 고객은 분모에서 제외
   - `eligible = total - observing`
   - 비율 = `c / eligible`
3. **maturity window 적용** — 코호트 첫 구매월 + N일 경과해야 확정
   - 코호트 30/60/90일은 각 윈도우 경과 후만 확정
   - 진행 중인 월의 M+1·M+N은 진행중 라벨 (🔄 변동중)

**partial 가드 규칙**:
- observing > 0일 때만 가드 적용 (eligible < 30 또는 observing/total > 50% → 관찰중)
- **observing = 0**이면 시간 다 지난 옛 코호트 → 표본 작아도 표시 OK
- 가드 너무 엄격하면 옛 코호트도 가려져 사용자 의사결정 못 함

**partial 100% 가짜 수치 차단**:
- eligible 분모가 너무 작으면 c/eligible ≈ 100% (가짜)
- 사례: 2026-04 60일 전환율 53/53 = 100% — 60일 다 지난 사람 53명, 그 모두 재구매 (실제는 표본 부족)
- 해결: observing > 0이면 eligible<30 또는 observing 비율 50%+ 일 때 partial 표시

**기간 재구매율 = sales-mix 지표 명시**:
- `repurchaseCust / (repurchaseCust + newCust)` 는 진짜 재구매율 아닌 sales-mix
- 신규 많은 달은 기계적으로 낮음
- 시트 헤더에 `재구매율%(sales-mix)` 또는 별도 라벨

**자가 검증 체크**:
- [ ] 이 비율 지표의 분모에 dedup·미관찰 제외·maturity 적용했는가
- [ ] partial 케이스(observing > 0 + 작은 eligible)는 관찰중 표시인가
- [ ] observing = 0 옛 코호트는 표시 허용했는가
- [ ] sales-mix 지표를 진짜 재구매율로 오해할 위험 차단 (헤더 라벨)했는가

**연관 실패**: failures.md ㊳(GAS v5_0 수치 결함 10개), ㊵(GAS run_id contract), ㊴(sheets_sync row 복제 패턴)

**hookify 보강**: 없음 (코드 작성 시 자가 점검 + codex review로 잡음)

---

## §시트status분류 (Sheet Status Whitelist vs Blacklist)

**목적**: 시트 raw 데이터에서 정상/취소 주문 분류 시 silent drop(정상 주문 다수가 누락) 사고 차단.

**핵심 원칙**: 시트 raw STATUS 컬럼 unique 값 분포를 직접 확인하지 않고 다른 코드 코멘트만 보고 화이트리스트/블랙리스트 정의 금지.

**사례 (2026-05-13 ㊷)**: GAS v5.1에서 `VALID_STATUSES = {'거래종료', '결제완료', ...}` 화이트리스트 도입.
- 근거: sheets_sync.py:244 코멘트가 "카페24는 거래종료 고정"이라 명시
- 실제 시트 raw 값: "배송 완료"(공백 포함)·"배송중"·"취소 완료"·"입금전 취소 - 관리자"
- 결과: 카페24 2026-03 첫구매자 200건+ 중 1명만 통과. 99% silent drop
- 사용자 발견 (코드 자가 점검·codex로 못 잡음)

**규칙**:
1. **시트 raw 값 직접 확인 우선** — `sheet.getRange('C2:C100').getValues()` 등으로 STATUS 컬럼 unique 값 sampling
2. **블랙리스트 > 화이트리스트** 선호
   - 블랙리스트: '취소'·'환불'·'반품' 키워드 부분일치 시 제외
   - 화이트리스트: 정상 상태 모두 열거 → 누락 시 silent drop
   - 시트 raw 값이 다양·변경 가능하면 화이트리스트는 위험
3. **정규화 필수** — `String(status).trim().replace(/\s+/g, '')` 후 비교
   - "배송 완료" vs "배송완료" 같은 공백 차이로 silent drop
4. **부분일치 오탐 검증** — '취소' 키워드가 정상 상태에도 들어가는지 확인
   - 가상 예: "취소가능" 상태가 있으면 정상인데 제외됨. 시트 raw 값 sampling 후 안전 확인

**자가 검증 체크**:
- [ ] 시트 raw STATUS 컬럼 unique 값을 직접 확인했는가
- [ ] 정규화(공백 제거)했는가
- [ ] 블랙리스트 키워드가 정상 상태에 우연히 포함되는지 확인했는가
- [ ] 신규 도입 후 1주 sampling으로 silent drop 비율 점검했는가

**연관 실패**: failures.md ㊷(GAS v5.1 화이트리스트 silent drop)

**hookify 보강**: 없음 (시트 raw 값 직접 확인은 코드 작성 시 자가 점검 필요. hook은 자동 트리거 어려움)
