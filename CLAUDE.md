# CLAUDE.md — HeavyLover 운영 컨텍스트

**최종 업데이트**: 2026-04-28 (rev. 7) · **호칭**: 승현님 · **언어**: 한국어 · **사업주**: 비전공자

> **외부 컨텍스트 우선 참조 규칙**: 정보 부족 시 추측 금지. 다음 위치를 먼저 Glob/Read 후 결정한다.
> - 작업 종류별 회피 규칙: `docs/lessons/patterns.md`
> - 과거 실수 시간순 로그: `docs/lessons/failures.md`
> - 영역별 상세 컨텍스트: `docs/context/{infra,blog,ads}.md`
> - 사용자 환경 박제: `memory/MEMORY.md` 인덱스

---

## 0. 핵심 규칙 (모든 작업 전 필독)

### 작업 원칙
- **팩트 기반**: 추정·확정 분리. 데이터 없으면 "데이터 없음" 명시. 숫자 창작 금지.
- **블런트**: 듣기 좋은 말 < 근거·출처 있는 냉정한 분석.
- **모르면 모른다.** 추측으로 빈칸 채우지 않음.
- **문제 → 원인 → 해결** 구조.
- **비전공자 설명**: 비유 + 실행 예시. 전문 용어는 풀어서.
- **한국어 기본.** 기술 용어만 영어 병기.

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

### 세션 시작 체크
- 호칭 **"승현님"**
- 사업 상태 답변 → §3·§4·§9 최신값 + 인프라는 `docs/context/infra.md`
- 블로그 → `docs/context/blog.md` (또는 blog-writer 서브에이전트)
- 광고 → `docs/context/ads.md` (또는 meta-ads-analyst 서브에이전트)
- 코드 → §11 (디렉토리)
- **실수 회피** → `docs/lessons/patterns.md` 카테고리 매칭 → 필요 시 `failures.md` grep

### 안전 규칙 요약 (상세는 patterns.md)
- **§자동화점검** (Pre-flight): API·cron·.env 작업 전 키 존재·토큰 만료·디렉터리 실재·`crontab -l` 실측 확인. 문서 신뢰 금지. → `patterns.md §자동화점검`
- **§외부API다루기**: raw JSON 1건 출력 후 키 검증 / 페이지네이션 끝까지 / 식별자 인코딩은 공식 문서 / memory/MEMORY.md 사전 훑기. → `patterns.md §외부API다루기`
- **§엑셀편집**: 색상·폰트·테두리·열너비만 건드림. 수식·freeze panes·숨김·셀 타입 금지. 편집 후 `openpyxl.load_workbook()` 검증. → `patterns.md §엑셀편집`
- **§출력관리**: 5,000자 초과 우려 시 분할 제안. 분석 리포트는 표+요약 우선. → `patterns.md §출력관리`
- **§환경컨텍스트**: 메일 분리(Naver=정부지원수신, Gmail=업무발송), Windows 11 + Git Bash/PowerShell, 활성 세션 안 `claude -c`/`-r` 안 먹힘. → `patterns.md §환경컨텍스트`

### 실수 자동 기록 (필수)
- 승현님이 실수·오류·잘못된 판단·금지사항 위반을 지적하면 → **즉시 `docs/lessons/failures.md` 상단(시간 역순)에 한 줄 누적 기록**
- 형식: `- **YYYY-MM-DD** ⓝ | {무엇을 잘못했는지} | **하지 말 것**: {회피 규칙}`
- 추가 시 사용자에게 "failures.md에 기록했습니다" 한 줄 보고
- 매 세션 시작 시 `patterns.md` 카테고리 인덱스 훑고 작업 종류 매칭. 같은 키워드 3회+ 반복 시 `patterns.md` 카테고리 보강.

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
- 목적: 구매 빈도 증가 → CRM 데이터 축적 가속

### 해외 (검토 중)
- 냉동 도시락 직수출: KOTRA 지원사업 결과에 따라
- 레토르트 파우치 병행 옵션 (Amazon JP/US)

---

## 4. 핵심 KPI

### 사업
- 2026-04 MTD 매출 (4/22 기준): **3,000만 원**
- 2026 Q1 월평균: 약 2,221만 원
- 2025 연매출: 약 2.0억 원
- 2026 목표: 연 10억 (자본 조달이 병목)

### 재구매 (CRM 실측, repurchase_v5_4.gs)
- 1→2회 전환: 23~30%
- 2→3회 전환: 약 40%
- 90일 전환 (3개월 평균): 35.0%
- 재구매 간격 P50: 약 15일
- 재구매 간격 P90: 31~62일
- 재구매 AOV: 초구매 대비 약 2배
- M+1 코호트 리텐션: 약 14% (벤치 20~30% 미달, **개선 1순위**)
- 1회 후 이탈률: 약 76.6%

### 광고·채널
- Meta ROAS: 약 3.5 (글로벌 F&B 평균 1.85~2.0 상회)
- Cafe24 유입: 100% Meta 광고 (오가닉 미미)
- 스마트스토어: 오가닉, 광고 없음
- 브랜드 검색량: 월 약 260 → 파워링크 집중

### 단위 경제학
- 신규 획득: 손익분기 근처
- 마진 회수: 재구매 (LTV 기반)
- ROAS 3.3+ 유지 시 광고 스케일업 타당

---

## 5. 기술 인프라 (요약)

> 상세 — Cron·시트 정책·SS sync 규칙·재구매 파이프라인·엑셀 생성 로직·SaaS 스택 전부: **`docs/context/infra.md`**
> 운영 가이드: `docs/deploy-repurchase-cron.md`, `docs/setup-repurchase-automation.md`, `docs/looker-studio-repurchase-dashboard.md`

### 자동화 상태 (한눈에)
| 기능 | 상태 |
|---|---|
| 11시 엑셀 생성 + OneDrive + 텔레그램 | ✅ 평일 |
| 13시 PlusCL 송장 → 카페24/SS 등록 | ⏳ PlusCL 인증 5개 대기 |
| 04:00 카페24 OAuth 자동 갱신 | ✅ 매일 |
| 08:30 시트 sync (카페24 + SS 5상태) | ✅ 매일 |
| 09:00 재구매 리포트 + 마트 4종 + 텔레그램 | ✅ 매일 (Anthropic 401 시 fallback) |
| 카페24 N10→N20 / SS 신규→발주확인 | 수동 (API 한계) |

### 위치 요약
- 주문 자동화: Vultr (158.247.215.170, Ubuntu 22.04) `/root/heavylover-automation/`
- 재구매 분석: Vultr `/root/heavylover-repurchase/` (별도 폴더, 충돌 방지)
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

## 8. Meta 광고 (요약)

> 상세 — 벤치마크 표, 자동 플래그, CBO/ABO 전략, ASC 활성화 조건, 스케일업 정책 전부: **`docs/context/ads.md`**
> 자동화 코드 동기 정본: `docs/meta-ads/benchmarks.md` (`meta_ads_report.py` 상수와 동기). 작업 시: meta-ads-analyst 서브에이전트 호출.

### 자동화 (2026-04-28 가동, 4역할 심층 격상 완료)
- 매일 09:00 KST GitHub Actions cron — `meta_ads_report.py`
- 데이터 흐름: Graph API → 일일 metrics 계산 → KRW 환산 (1,450원/USD 고정) → CSV+Sheets 누적 → 자사 P50 계산 (14일+ 누적 시 활성) → Claude 분석 → 텔레그램 요약 + 이메일 4역할 심층
- **텔레그램 prefix `📈 [Meta광고]`** + 구분선 — 다른 자동화(발주·재구매·정부지원)와 명확히 구분
- **이메일 = 재구매 일일 리포트와 동일 수준** (`meta_ads_email_daily.py`):
  - 4역할 페르소나 (분석가/전략가/회의주의자/의사결정자) 1회 호출, claude-opus-4-7
  - 차트 PNG 3개 인라인 (`lib/charts_meta.py`): 7일 추세, 벤치 비교, 캠페인 ROAS
  - Anthropic 401 시 fallback (원시 숫자 표)
- 매주 월요일 09:00 KST — 위너 광고 패턴 식별(`meta_ads_winner_patterns.py`) + Meta 토큰 자동 갱신(`refresh_meta_token.py`, 60일 만료 회피)
- 광고 계정: `act_445075134545178` (HEAVY ROVER, 통화 USD → 1,450원/USD 환산)
- 토큰: User Access Token (60일 만료, 주간 자동 연장 — `META_APP_ID`/`META_APP_SECRET` 등록 후 가동)
- 데이터 저장:
  - `data/meta_ads/daily.csv` (계정 합계, 1일 1행)
  - `data/meta_ads/daily_campaign.csv` (캠페인별, 1일 N행)
  - `data/meta_ads/raw/{date}.json` (감사용 원본, .gitignore)
  - `data/meta_ads/winner_patterns.jsonl` (위너 광고 누적)
  - Google Sheets — **재구매 시트와 공유** (`GOOGLE_SHEETS_ID=REPURCHASE_SHEET_ID`):
    - `Meta_Ads_Daily` (계정 합계 워크시트)
    - `Meta_Ads_Daily_Campaign` (캠페인별 워크시트)
    - `Meta_Ads_Winners` (위너 패턴, 30일+ 데이터 누적 후 활성)

### 필수 비교 지표
- CPC·CTR·전환율·ROAS·CPA — 각 지표 업계 평균 대비 + 자사 P50 듀얼 표기
- 핵심 벤치: ROAS 평균 2.5 / 우수 4.0+, CPA 평균 30,000원 / 우수 20,000원-

### 광고 카피 자동 생성 (장기, 60일 누적 후)
- 위너 광고 기획 패턴 누적 → Claude가 약점 보완 카피 5개 변형 생성
- 이미지·영상 AI 생성 제외 (식품 D2C 효과 미달)
- 자동 광고매니저 푸시 제외 (광고비 사고 위험, 사람 승인 유지)

---

## 9. Top of Mind

### 즉시 대응
1. 상생성장지원자금 1억 신청 → 현장실사 예정
2. 스마트스토어 API 자동화 (프록시 IP 확보 완료, 코드 작업 단계)
3. 시리얼 프리오더 (4~5월) → 6월 정식 출시

### 진행 중 (2026-04~07)
4. 정부 지원사업 다중 신청
   - 초기창업패키지 2차 (3년차 자격 마지막)
   - 용인시 온라인 플랫폼 지원사업 (서류 통과)
   - KOTRA 내수기업 수출기업화
   - 지식재산바우처 (상표)
5. M+1 리텐션 14% → 20~25% 개선 (자본 효율 최고 레버)
6. 등기사항전부증명서 리뷰
7. ~~Meta Ads API → Apps Script 자동 수집~~ ✅ 완료 (2026-04-28, GitHub Actions cron 가동)

### 검토 (2순위)
- 모두의 아이디어 경진대회 — 전세 사기 방지 시스템 지원
- 해외향 SaaS (승현 1인) — 영어권 D2C repurchase 추적, Reddit 검증 선행
- Lovable/Cursor 테스트 도입
- 상표권 등록 전략

---

## 10. 장기 자산·강점

1. **CRM 데이터 인프라** — 동급 D2C 희소. 의사결정 속도 2~3배.
2. **검증된 단위경제학** — ROAS 3.5 + 재구매 30% + AOV 2배 = 광고 스케일 수학적 성립.
3. **PMF 시그널** — P50 15일 = 생활 루틴 편입.
4. **명확한 포지셔닝** — 벌크업 냉동 세그먼트 블루오션 + HACCP.
5. **운영자형 대표** — AI 도구·인프라 직접 구축, 외부 의존 낮음.
6. **양 채널 자동화** — Cafe24 OAuth + SS 프록시 = 희귀 구조.

---

## 11. 디렉토리 구조

```
heavylover-automation/
├── CLAUDE.md            ← 본 파일 (코어 컨텍스트만)
├── .claude/
│   ├── agents/          ← 서브에이전트 8개 (blog-writer, meta-ads-analyst, automation-debugger 등)
│   ├── commands/        ← 슬래시 커맨드 (현재 미생성, 다음 작업)
│   └── skills/          ← heavylover-voice 등
├── *.py                 ← 자동화 스크립트 (run_automation, cafe24_client, naver_client 등)
├── apps_script_main.gs / repurchase_v5_4.gs
├── .github/workflows/   ← Meta 광고 일일·주간 리포트
├── data/{raw,reports}/
└── docs/
    ├── context/         ← 영역별 상세 컨텍스트 (infra, blog, ads)
    ├── lessons/         ← 실수 누적·승격 (failures.md, patterns.md)
    ├── brand-guide/blog-history.md  ← 미존재 (첫 발행 시 신설)
    ├── blog-drafts/
    ├── meta-ads/{benchmarks.md, reports/, weekly/, SETUP.md}
    ├── govt-radar/      ← 정부지원 레이더 (Layer 1·2·4)
    ├── deploy-repurchase-cron.md / setup-repurchase-automation.md
    ├── looker-studio-repurchase-dashboard.md
    └── competitors/
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

## 13. 실험 노트 (요약)

> 정본 — 시간순 원시 로그(13건+): **`docs/lessons/failures.md`**
> 회피 패턴 — 작업 종류별 카테고리 8개 (§자동화점검·§외부API다루기·§시간중복처리·§데이터범위와분석분리·§엑셀편집·§출력관리·§지역자격필터·§환경컨텍스트): **`docs/lessons/patterns.md`**

### 활용 흐름
1. 작업 시작 전 → 작업 종류 매칭으로 `patterns.md` 카테고리 1~3개 Read
2. 깊게 들어갈 필요 시 → `failures.md` grep (예: `grep "SS sync" docs/lessons/failures.md`)
3. 신규 실수 발생 시 → `failures.md` 상단에 한 줄 추가 + 사용자에게 "failures.md에 기록했습니다" 보고
4. 같은 키워드 3회+ → `patterns.md` 카테고리 보강 또는 신설

### 최근 5건 (전체는 failures.md)
- **2026-04-28** ⑬ | govt-radar 시·군 한정 19건 통과 — 광역+산하 모두 차단 필요
- **2026-04-28** ⑤ | 카페24 OAuth refresh_token 만료 사람이 매번 재발급 — 04:00 자동 갱신 cron 신설
- **2026-04-28** ④ | sync_cafe24 매 실행 9건 누적 중복 — cutoff에 ` 00:00` 명시 + 자연키 dedupe
- **2026-04-28** ③ | SS sync가 PURCHASE_DECIDED만 시트 저장 — 5상태 모두 보관 + 분석 시 컬럼 필터
- **2026-04-28** ② | SS sync `productOrder.paymentDate` 오매핑 — raw JSON 1건 출력 후 키 검증

---

**Claude Code는 이 파일을 전제로 모든 작업을 시작한다.**
