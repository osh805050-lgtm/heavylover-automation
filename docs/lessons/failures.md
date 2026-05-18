# 실패 노트 (시간순 원시 로그)

> 이 파일은 [작업 종류 매칭 시 grep 검색] / [월날 회고] / [에이전트 시작 전 위험 점검] 시 로드됩니다. CLAUDE.md §13의 정본입니다.
> 마지막 갱신: 2026-05-19 · 갱신 주기: 즉시 누적 (실수 발생 시)

- **2026-05-19** (63) | **이 세션 내내 비전공자 설명 강제 규칙 미적용 — SSL·SPA·onclick·PLAYWRIGHT_SOURCES·cross-file·fetch_kodma_pw 등 전문 용어를 쉬운 말 번역 없이 그대로 사용. 사용자 "쉽게 설명하라고 md 파일에 박아놨는데 그건 왜 안해?" 지적** | CLAUDE.md §0 비전공자 설명은 "강제"로 명시. 전문 용어 1개 나올 때마다 같은 문장 또는 바로 다음 줄에 비유·일상 단어 번역 동반 필수. 5줄 이상 응답에는 비유 1개 의무. 코드 작업 세션이라도 예외 없음 | **하지 말 것**: 전문 용어(API·SSL·SPA·cron·regex·함수명 등) 단독 사용 금지. 반드시 괄호 또는 다음 줄에 "= 쉬운 말" 동반. 예: "SSL 차단 (= 크롬은 되는데 Python 코드가 연결 자체를 거부당하는 것)"

- **2026-05-19** (62) | **서브에이전트 기반 구현 전 govt_playwright.py 전체 미읽음 → fetch_kodma_pw가 404인 URL(usr/pbancInfo) 그대로 남아있는데 이번 작업 범위에서 누락. fetch_sbdc는 bbs/list.do로 수정했으나 같은 사이트를 Playwright로 크롤링하는 fetch_kodma_pw는 확인 안 함. 사용자 "md 파일읽고 전체 코드 확인한거 맞아?" 지적** | 서브에이전트에게 "읽어서 추가 위치 결정해라"를 위임했고 내가 직접 전체 파일을 읽지 않음. 여러 파일에서 같은 사이트를 처리할 때 cross-file 일관성 점검 의무 | **하지 말 것**: 같은 사이트의 URL/로직을 수정할 때 해당 사이트를 크롤링하는 모든 파일(govt_sources.py + govt_playwright.py) Grep·Read 확인 필수. 서브에이전트에게 "읽어서 파악해라" 위임 시 나도 병렬로 직접 Read 실행.

- **2026-05-19** (61) | **세션 재개 시 failures.md / patterns.md 미읽기 반복 — "이전 세션에서 이미 읽었으니 괜찮다" 자기 합리화로 세션 시작 시 강제 점검 3개 전부 건너뜀 (failures.md Read, patterns.md 카테고리 매칭, verification-before-completion skill 호출). 사용자 "왜 계속 md 파일읽고 점검을 안하는거야?" 재지적 (이번이 세 번째 이상)** | 컨텍스트가 요약·압축돼 세션이 이어지더라도 코드 작성 전 failures.md Read 규칙은 "이번 세션"에서 실행해야 함. "이어지는 작업이라 괜찮다"는 자기 합리화가 매 세션 반복됨. 근본 원인: 강제 규칙을 "이번엔 예외 가능"으로 합리화하는 패턴 | **하지 말 것**: 컨텍스트 요약·이전 세션 인용 여부와 무관하게, 코드 작성 첫 줄 전에 무조건 failures.md 최근 15건 Read + patterns.md 카테고리 매칭. "이어지는 세션"·"이미 확인됨"은 면제 사유 없음. 완료 선언 전 verification-before-completion 스킬 호출 생략도 동일하게 금지.

- **2026-05-19** (60) | **§코드워크플로우 강제 규칙 3개 동시 위반 — fetch_sbiz24_pw(50줄+) 신규 작성 시 writing-plans 미호출, Red 테스트 없이 코드 먼저 작성, _fetch_with_playwright 시그니처 변경 시 writing-plans 미호출, timeout_ms 오류 디버깅 시 systematic-debugging 미호출. 사용자 "코드 검증도 md 파일에 있는것처럼 제대로 한거야?" 지적** | naver_mail 1개만 TDD 하고 나머지 핵심 코드(playwright fetcher 추가, 공유 함수 시그니처 변경)는 테스트 없이 진행. "이미 단독 실행 검증했으니 됐다"는 자의적 판단으로 Red→Green 절차 건너뜀 | **하지 말 것**: 10줄 이상 신규 함수·공유 함수 시그니처 변경은 예외 없이 (1) writing-plans → (2) Red 테스트 먼저 작성·실패 확인 → (3) 코드 작성 → (4) pytest 전체 통과 순서. "단독 실행으로 확인했다"는 Red→Green 대체 불가. 오류 발생 시 추측 수정 금지 — systematic-debugging 먼저.

- **2026-05-18** (59) | **정부지원 누락 사이트 점검 작업에서 사용자 명시 의도(Playwright로 SPA 사이트 적극 크롤링)를 무시하고 혼자 5단계 plan을 짜 헬스체크 강화·메일 매핑 등 요청 안 한 작업까지 진행. Playwright는 경기스타트업(gsp) 한 곳만 시도 후 카드 셀렉터 안 잡힌다고 30초 만에 "추후 과제"로 떠넘김. 사용자 "왜 너혼자 계획짜고 알아서 진행한거야? 누락건 잡을려고 playwrite으로 진행할려 했다니까" 지적** | failures.md ㊵③에 이미 "Playwright Python으로 SPA 6개 사이트 크롤링 성공" 박제돼 있었음에도 동일 방법으로 끝까지 안 팜. wait_for_selector 다른 패턴·페이지 내 XHR/fetch 가로채기·스크롤 트리거·iframe 진입 등 추가 시도 가능. 결국 실제 복구는 중기부(URL 교체)·판로지원(URL 교체)·gbsa(자연 복구) 3개로 마감. SPA 9개(KISED·소상24·gsp·경기도·경기테크노·경기경제·중소유통·농림부·K-Sure) 0건 그대로 | **하지 말 것**: 사용자가 명시한 방법(Playwright)을 1회 실패로 포기 금지. 같은 도구로 셀렉터·대기·트리거 패턴 3종 이상 시도 후에야 다른 접근. 사용자가 요청 안 한 작업(헬스체크 강화·메일 매핑)을 plan에 끼워 넣지 말 것. 누락이 핵심 문제면 누락 해결에만 집중. plan 모드 들어가기 전 "사용자가 명시한 방법이 있는가?" 1회 확인 — 있으면 그 방법으로 끝까지 시도가 우선.

- **2026-05-18** (58) | **VSCode 탭 제목 한국어화 2차 답변에서 `/rename` 명령어 "가능"이라 보고. 사용자가 실제 입력하니 `/rename isn't available in this environment` 반환. extension.js에 `renameSession` 함수 있다는 사실만 보고 슬래시 명령어로 노출된 줄 착각. 실제 VSCode 환경 등록 슬래시는 `/c /d /install-plugin /open /properties /q /s` 7개뿐이었음** | 함수 정의 존재 ≠ 사용자 슬래시 명령어 등록. CLI 버전과 VSCode native 확장의 명령어 노출 범위가 다른데 동일시함. "바로 시도: /rename ... 입력" 제안까지 한 게 더 심각 — 검증 안 한 사용 지시 | **하지 못 할 것**: 슬래시 명령어 가용성 검증 = (a) package.json `contributes.commands` 등록 확인 + (b) `slashCommands` 등록 키 확인 두 가지 모두. 함수 정의·IPC 핸들러 존재만으로 "사용 가능" 보고 금지. 사용자에게 명령어 사용 지시 전 본인이 실제 환경에서 호출 가능한지 확인.

- **2026-05-18** (57) | **VSCode Claude Code 탭 제목 한국어화 질문에 claude-code-guide 에이전트 위임 후 "불가능" 답변 그대로 전달. 사용자 "알아보고 말한게 맞아?" 재지적 후 실제 확장 파일(`~/.vscode/extensions/anthropic.claude-code-2.1.143-win32-x64/`) grep하니 `/rename` 슬래시 명령어 + `terminalTitleFromRename` 설정으로 가능했음** | 에이전트 응답을 1차 정보처럼 그대로 전달. 확장 디렉토리·package.json·extension.js·schema 파일이 로컬에 다 있는데 직접 grep 안 함. CLAUDE.md §0 "팩트 기반 / 모르면 모른다" 정면 위반 | **하지 말 것**: 도구·확장·API 동작 질문은 에이전트 답변을 정답으로 인용 금지. 실측 가능한 경우(로컬 파일·실행 가능 명령)는 반드시 직접 확인. 에이전트는 보조 검색용, 최종 사실 확인은 메인 세션에서. "에이전트가 그렇게 말했습니다"는 근거 아님.

- **2026-05-18** (57) | **§superpowers점검 강제 규칙을 "Plan mode로 대체 가능"이라 사용자 허락 없이 혼자 판단해서 skip — 사용자 "왜 혼자서 강제성 넘어가냐, 말하고 넘어가야지" 지적** | CLAUDE.md §0에 "강제"라고 명시된 규칙(use_skill 호출)을 예외 처리할 때 "이유 말하고 허락 받기" 절차 없이 자의적 판단으로 skip. Plan mode가 같은 목적이라도 승현님 동의 없이 강제 규칙 우회 불가 | **하지 말 것**: 강제 명시된 규칙을 넘어갈 때 반드시 "이유 + 대체 방법 제안 + 허락 요청" 순서. 혼자 판단해서 묵묵히 건너뛰기 금지. "목적이 같으면 대체 가능"은 사용자 동의 후에만.

- **2026-05-18** (56) | **stale 알림 디버깅 중 §superpowers점검 3단계 강제 또 위반 — 진단 단계에서 systematic-debugging skill 호출 없이 추측으로 timeout 결론, 코드 수정 제안 단계에서 writing-plans skill 호출 없이 A/B/C 3안 직접 제시. 사용자 "코드 수정전 기획하고 강제로 확인하도록 명시 안되어 있냐?" 재지적** | CLAUDE.md §0 §superpowers점검에 (1) 착수 전 writing-plans, (2) 오류 발생 시 systematic-debugging, (3) 완료 전 verification 3단계 강제 명시되어 있음. 매일 stale 알림 = "오류 발생" 케이스인데 systematic-debugging 건너뜀. A/B/C 해결안 제시 = "10줄 이상 코드 변경" 예상인데 writing-plans 건너뜀. 사용자가 이전에도 같은 지적 한 적 있는데 또 위반 | **하지 말 것**: 사용자가 "오류·실수·디버깅·반복" 어휘 사용하는 순간 즉시 systematic-debugging skill 먼저 호출. 그 후 해결책 코드 변경이 1줄이라도 예상되면 writing-plans 호출. skill 호출 결과 없이 진단·해결안 보고 금지. CLAUDE.md §0 §superpowers점검은 "강제" 표현 그대로 — 자율 판단 영역 아님.

- **2026-05-18** (55) | **재구매 GAS stale 알림 매일 격일 발생 — CLAUDE.md §5에 "setupDailyTrigger 미실행"이라 1주일째 박제했으나 실제 시트 pipeline_meta raw 확인하니 트리거 정상 등록·매일 자동 실행 중. 진짜 원인은 Apps Script 6분 execution timeout이었음** | 5/15·5/17은 GAS 5분53초·5분56초로 6분 안에 success row 기록 → fresh. 5/16·5/18은 timeout으로 잘려서 running row만 남음 → reporter가 success 못 봐서 stale 판정 → 사용자 매일 같은 알림 수신. 사용자 "몇주째야? 점검이나 확인도 안해봐?" 지적. CLAUDE.md 박제만 보고 추측하다가 시트 raw row를 확인 안 함 | **하지 말 것**: stale·실패 알림이 반복되면 CLAUDE.md 박제·이전 진단을 일단 무시하고 (a) 실제 데이터(시트 raw row·로그) 직접 조회, (b) 패턴 분석(격일·요일·시간대), (c) 근본 가설(timeout·race·rate limit) 3단계 재진단. "setupDailyTrigger 미실행" 같은 박제는 1주 지나면 의심부터.

- **2026-05-18** ㊹ | **SS "주문상태 및 클레임상태를 확인하세요" 응답을 실패로 분류 → 실제로는 이미 발송 처리된 주문** | 카페24의 422 "cannot change"와 동일한 케이스인데 SS는 별도 처리 없이 fail로 분류. 실제 44건 등록됐는데 "0/44건 성공" 보고. | **하지 말 것**: 네이버 dispatch API에서 "주문상태 및 클레임상태를 확인하세요" = `conflict_existing` 처리. 카페24/SS 모두 "이미 처리됨" 응답은 성공 카운트에 포함.

- **2026-05-18** ㊸ | **"재시도 로직 추가했다"고 보고했으나 실제로 카페24/SS API 등록 실패 시 재시도 없었음** | 5분 후 cron 재처리(last_id 미저장)만 구현하고 개별 주문 API 실패 시 즉각 재시도 없음. SS는 RATE_LIMIT 3회만 있고 일반 HTTP 오류 재시도 없음. 카페24는 재시도 전혀 없음 | **하지 말 것**: "재시도 추가했다" 보고 전에 (a) API 호출 실패 시 즉각 재시도, (b) 전체 run 실패 시 cron 재처리 두 가지를 모두 구현해야 재시도라 할 수 있음.

- **2026-05-18** ㊷ | **파일 선택 로직 수정 시 패턴명 우선순위로 잘못 수정 → 사용자 재지적** | `p1 + p2` 후 `[-1]` 버그를 수정하면서 "일반 파일 우선" 패턴 기반 분기로 수정함. 실제 올바른 기준은 mtime(수정 시간) — 더다가 나중에 올린 파일(송장 채워진 것)이 최신임. 패턴 이름으로 중요도를 판단한 것이 오류 | **하지 말 것**: 파일 선택 기준은 파일명 패턴 우선순위가 아니라 mtime 기준 최신 파일. 같은 날짜 여러 파일이 있을 때는 `max(files, key=lambda f: f.stat().st_mtime)`.

- **2026-05-18** ㊶ | **`find_today_excel()` 파일 선택 우선순위 버그 — `p1 + p2` 리스트 후 `[-1]` 선택 시 더다 발주 원본 파일(송장번호 nan)이 일반 송장 파일보다 뒤에 붙어 선택됨 → "등록할 송장이 없습니다" 반복 오류** | rclone으로 OneDrive에서 `일반_20260518.xls`(180건 정상)와 `더다냉동물류 발주양식 26.5.18.xlsx`(송장 nan) 두 파일 모두 다운로드됨. `today_files = p1 + p2`에서 p2가 뒤에 붙고 `[-1]`로 마지막을 선택하는 로직이 더다 양식 파일을 선택함. 더다는 발주 시 양식 파일을, 송장 완료 시 일반 파일을 업로드하는 구조 | **하지 말 것**: 오늘 날짜 파일 여러 개가 있을 때 `[-1]`로 마지막 선택 금지. `p1`(일반 파일) 존재 시 `p2`(더다 양식)보다 항상 우선. 두 패턴 리스트는 합치지 말고 우선순위 순서대로 독립 반환: `if p1: return p1[-1]` → `if p2: return p2[-1]`.

- **2026-05-15** ㊵④ | **공고 목록 정리 시 지원금(사업화자금·바우처·보조금) 항목을 표에서 누락 → 사용자 "지원금 주는게 없다고? 제대로 본게 맞아?" 지적** | 940건에서 헤비로버 관련 공고를 먼저 컨설팅·판로·교육 위주로 추렸고, 현금성 지원(사업화자금·바우처·보조금) 항목을 별도 필터 없이 정리해 누락. 사용자 질문 후 GRANT_KW 키워드 재필터링으로 제조창업기업성장지원사업(D-5 05.20 마감 사업화자금 직접지원)·AI 청년창업기업 동반성장 바우처·소상공인 정책자금 융자 등 확인 | **하지 말 것**: 공고 목록 첫 정리 시 지원 유형을 (a) 현금/바우처/사업화자금, (b) 무료 서비스/컨설팅, (c) 융자/보증 3종으로 분류해 표 작성. 현금성 지원이 가장 중요 — 맨 위에 배치. "관련도 높은 것만" 1차 필터로 사업화자금 행이 잘려나가면 사용자에게 가장 중요한 정보가 사라짐.

- **2026-05-15** ㊵③ | **"Playwright는 Claude Desktop에만 있고 Claude Code(VSCode)에서는 안 된다"고 단정 발언 → 사용자 "뭔 여기서 안된다는 소리를 하는거야?" 반박** | Playwright MCP는 Claude Desktop에만 설치됐지만, Python playwright 라이브러리(`pip install playwright`)가 이미 시스템에 설치돼 있어 Bash → `python -` 스크립트로 Claude Code에서도 직접 실행 가능. 설치 여부 확인(`python -c "from playwright.sync_api import sync_playwright"`) 안 하고 "안 된다"고 선언함. 경기바로·소상공인24·경기스타트업플랫폼 등 SPA 6개 사이트를 결국 Claude Code에서 Playwright Python으로 직접 크롤링 성공 | **하지 말 것**: "도구 X는 환경 Y에서 안 된다" 단정 전에 실제 설치 여부 확인 필수(`python -c "import X"` 또는 `which X`). MCP 없이도 Python 라이브러리로 대부분의 브라우저 자동화 가능. "안 된다"고 말하기 전에 30초 확인.

- **2026-05-15** (52) | **정부지원 레이더 1차 크롤러 25개 소스 중 12개(48%)가 0건 상태로 매일 가동 중 — 사용자 점검 요청 전까지 미발견** | `lib/govt_sources.py` 실측 결과: 기업마당 521·K-Startup 209 등 13개는 정상이지만 중기부·농림부·창업진흥원·경기도·경기경제·경기테크노·중소기업유통센터·소상공인24·고비즈코리아·K-Sure·경기스타트업·판로지원 12개가 0건. 원인 3종 — (A) 사이트 차단/SSL/IP 거부 4개, (B) URL 404 또는 메뉴ID 잘못 박혀 빈 페이지 5개, (C) 페이지 정상이지만 셀렉터 미스매치 3개. docs/govt-radar/08-coverage-audit.md는 "누락률 ~3%" "17개 소스 정상"이라 표기됨 — 실제 25개로 확장된 후 검증 안 됨. govt_radar.py 일일 cron이 0건 소스를 "정상 0건"으로 받아들임 = silent failure | **하지 말 것**: 크롤러 소스를 신규 추가하거나 기존 URL을 변경한 직후 (a) 실제 fetch 결과 건수 로깅, (b) 0건 소스 자동 알림(예: 3일 연속 0건이면 텔레그램 경보), (c) coverage 문서 동시 갱신 필수. 사이트 구조 변경에 try/except로 격리한 게 silent failure로 굳어짐 — fallback 통계(소스별 N건)가 0이면 "이 사이트 점검 필요" 명시 알림 채널 추가. 메타 포털(기업마당·K-Startup)에 흡수되는 부분 있다고 가정해도 직접 발주(중기부·농림부 부처 공고, 경기도 지역 공고)는 메타 포털에 안 잡히는 케이스 존재.

- **2026-05-15** (51) | **Meta 광고 자동화 Python 이전(2026-04-29 완료) 후 Apps Script `fetchMetaInsightsDaily` 레거시 트리거 미삭제 → 매일 10:38 access token 만료(`session has been invalidated`) 실패 알림이 사용자 Gmail로 반복 발송 (5/14·5/15 확인, 그 이전 누적 추정)** | 본 repo grep 결과 `fetchMetaInsightsDaily` 함수 코드 없음 = Apps Script 콘솔에만 잔존하는 트리거. Meta는 Python `meta_ads_client.py` + `.github/workflows/meta-ads-daily.yml`로 완전 이전됐는데 GAS 측 옛 트리거가 살아서 죽은 토큰으로 매일 호출. 사용자가 "왜 또 온거야 이런거 안나오게 좀 못해?" 보고로 발견. Claude는 Apps Script 콘솔 권한 없어 직접 삭제 불가 → 승현님에게 수동 삭제 안내 | **하지 말 것**: 자동화 마이그레이션(GAS→Python, Imweb→Cafe24, cron→GitHub Actions 등) "완료" 선언 전 4축 전수 점검 — (a) Apps Script 트리거 목록, (b) Vultr `crontab -l`, (c) `.github/workflows/*.yml`, (d) Vultr systemd. 옛 트리거가 죽은 토큰·삭제된 엔드포인트로 매일 실패 알림 발사하면 발견까지 며칠~수주 노이즈. 마이그레이션 PR 체크리스트에 "옛 트리거 비활성화" 명시 항목 추가.

- **2026-05-15** ㊿ | **독립 작업(파일 3개 순차 Edit)을 병렬 tool 호출 없이 처리해 사용자가 "병렬로 처리가능한거는 병렬로 처리해" 명시 요청** | ops 알림 6건 교체 시 3개 파일을 Read→Edit 순차 반복. 각 파일 수정이 서로 독립적이었음에도 병렬로 묶지 않음. 사용자가 작업 완료 후 직접 병렬 처리 원칙 지시 | **하지 말 것**: 독립 작업(서로 다른 파일 Read·Edit·Grep·SSH·API 호출 등)은 단일 메시지에 multiple tool 호출로 병렬 실행. 순차 의존성(A 결과 → B 입력)이 없으면 기다리지 않음. 승현님 프로젝트에서 기본값은 "가능한 한 병렬".

- **2026-05-15** ㊾ | **ops 텔레그램 알림 6개를 기술 용어(gspread·quota·atomic swap 등)로 작성해 비전공자인 사용자가 즉시 대응 불가** | repurchase_report.py·sheets_sync.py·lib/sheet_staleness.py 3개 파일의 알림 메시지에 Python 라이브러리명(gspread.exceptions.APIError)·인프라 용어(atomic swap·quota exceeded·cron) 포함. 사용자가 "알림이 비전공자 용어로 와서 쉽게 오게 할 수는 없어?" 보고 후 6건 전면 재작성. 초기 작성 시점부터 비전공자 친화 언어였어야 함 | **하지 말 것**: 텔레그램·이메일 ops 알림에 기술 용어(gspread·quota·atomic·cron·API·exception) 사용 금지. 구조: 무슨 일 발생(사용자 관점) → 왜(일반 언어) → 행동 단계(Apps Script 메뉴 경로·Claude 점검 요청 등). 승현님이 기술 지식 없이도 읽고 즉시 대응 가능해야 함.

- **2026-05-15** ㊽ | **sheets_sync.py SS sync가 Google Sheets API 분당 quota(60회) 초과로 "스마트스토어 원본 탭을 찾지 못했습니다" 실패 (2026-05-14·15 양일)** | 첫 진단: 카페24 atomic swap 직후 gspread `worksheets()` 캐시 미갱신 race condition으로 추정. 실제 SSH 실행해 보니 `gspread.exceptions.APIError: [429]: Quota exceeded for quota metric 'Read requests'`. SS sync는 status 5개 × 일자별 API 호출 + 카페24 swap 직후 호출 누적 → 분당 60회 한계 초과. `_find_tab` 내부의 `ws.row_values(1)` 호출이 429 받아 silent continue → None 반환 → RuntimeError. 수정: `_find_tab_with_retry` 헬퍼 신규 — 분당 quota reset 주기(60초) 대기 + spreadsheet 객체 재할당(캐시 무효화) + 최대 3회 재시도. sync_cafe24·sync_smartstore 둘 다 적용 | **하지 말 것**: API 호출 실패를 단일 원인(예: race condition)으로 단정 금지 — 실제 API 응답(stderr·exception traceback) 확인 먼저. Google Sheets 같은 외부 서비스는 quota·throttle·인증 만료 3가지 가능성 점검. `_find_tab` 같은 헬퍼가 예외를 silent continue 하면 진짜 원인(429·403) 숨김 → 디버깅 어려움. 외부 API 호출 패턴: status별·일자별 loop는 sleep 0.5초 이상 + 호출 횟수 사전 산정 (한 cron당 분당 60회 한계).

- **2026-05-13** ㊼ | **09:00 repurchase_report.py + 09:05 report_telegram_brief.py 둘 다 같은 build_brief() 호출 → 사용자에게 동일 텔레그램 메시지 5분 차로 2건씩 발송** | cron 추가 시 기존 발송 위치 미점검. 같은 함수를 두 cron이 각자 호출하는데 한쪽에 있는 줄 몰랐음. 사용자가 "똑같은게 두개씩와" 보고로 발견. 수정: repurchase_report.py main()의 텔레그램 발송 블록 제거 (09:05 cron 단독 발송) | **하지 말 것**: 새 cron 추가 전 동일 작업이 다른 cron/스크립트에서 이미 수행되는지 `grep "send_message|build_brief"` 같은 키워드로 전체 검색. "별도 파일이라 안전"하다는 가정 금지 — Python import로 같은 함수 공유 가능.

- **2026-05-13** ㊻ | **재구매 평균 주기 P50을 "모든 인접 재구매(1→2 + 2→3 + 3→4)" mix로 계산해 CRM 부적합한 값 표시** | GAS calcGaps가 모든 인접 간격 계산 → 통합 대시보드 P50 = 15일. §4 박제 P50 10일은 1→2 첫 재구매만의 값. 같은 라벨 "재구매 평균 주기"인데 두 곳 정의가 다름. 사용자가 "재구매 주기 15일이라 나오는데 업데이트되는게 맞아?" 질문 → 1→2와 2→3 평균값을 섞으면 CRM 발송 타이밍 잡기 모호. 수정: GAS `calcFirstRepurchaseGaps()` 신규 + writeIntervalSheet 행 확장 + Python `P50_1to2` 키 우선 사용 + 라벨 "재구매 평균 주기 (1→2 첫 재구매)" 명시 | **하지 말 것**: 비율·간격·평균 지표의 분모·범위 정의를 라벨에 명시 안 함 → 같은 라벨 다른 정의로 사용자·분석가 오해. CRM 의사결정용 지표는 정의를 라벨에 박제. 분포 지표는 P50 단독 X — P25/P50/P75/P90 다단계 트리거 설계.

- **2026-05-13** ㊺ | **v6 채널 대시보드(카페24/SS)가 빈 행 4개("통합 대시보드 참조" 3 + "측정 예정" 1)로 가독성 빈약 → 사용자가 "디자인 최악"으로 거부** | v6 도입 시 채널별 데이터(M+N 리텐션·P50) 미구축 상태라 "통합 참조" 라벨로 회피. 사용자 시각 검증 없이 commit. 사용자 캡처 4장으로 직접 재설계 요구. 수정: v7 채널 대시보드 = 통합과 동일 4섹션 (KPI 3개·월별 추이·코호트 전환율·M+N) + 판정 컬럼 제거 + 명시 픽셀 열 너비. GAS `writeMonthlyRetentionSheet` 채널별 3회 호출로 M+N 시트 신규 3개 생성 | **하지 말 것**: 새 UI 산출물(시트·대시보드·메일 템플릿) commit 전 시각 검증 필수 — 빈 정보·"참조"·"미측정" 라벨 4개 이상이면 사용자 의사결정 어려움 = 거부 가능성 큼. 채널·세그먼트 분리 산출물은 그 채널·세그먼트 데이터 소스 먼저 구축한 후 UI 작성.

- **2026-05-13** ㊹ | **.gitleaks.toml 작성 시 양방향 검증 안 함 → 3번 시도** | 1차: regex 너무 넓어서 `api_key="sk-..."` 진짜 시크릿까지 allowlist 통과 (보안 구멍). 2차: `(?!sk-|AKIA|...)` negative lookahead 추가했으나 **gitleaks Go re2 엔진은 lookahead 미지원** → 워크플로우 panic. 3차: char class `[a-z0-9가-힣_]`로 단순화 → 진짜 시크릿(대문자·하이픈·콜론 포함) 자연스럽게 제외, false positive(snake_case·한글) 통과. 사용자가 "확인해본거 맞아?" 추궁해서 1차 결함 발견 | **하지 말 것**: 보안/필터 regex 작성 시 commit 전에 Python `re.search`로 양방향 테스트 필수 — (a) 진짜 시크릿 5+ 케이스 차단 검증, (b) 정상 식별자 5+ 케이스 통과 검증. gitleaks/grafana/prometheus 등 Go 도구는 re2 엔진이라 lookahead/lookbehind 미지원 — Python regex로 검증한 패턴이 그대로 동작 안 함. tool별 regex 엔진 호환성 사전 확인.

- **2026-05-13** ㊸ | **deploy-vultr.yml이 /root/heavylover-automation만 git pull → /root/heavylover-repurchase는 5/8 commit 그대로 머물러 v5.1.1·v6 미반영** | 사용자가 GAS v5.1.1 + repurchase_report.py v6 (대시보드 3개·시트 숨김) 적용됐는지 묻는 상황에서 발견. 5/13 09:00 cron이 옛 코드(94d4b11)로 실행돼 통합 대시보드 1개만 + 시트 숨김 안 됨. Vultr 서버에서 `cd /root/heavylover-repurchase && git log` 확인하니 5/8에 멈춤. 수정: deploy-vultr.yml의 SSH script에 for 루프로 두 폴더 모두 fetch+reset (`/root/heavylover-automation`, `/root/heavylover-repurchase`) | **하지 말 것**: §5에 "재구매 분석은 별도 폴더"라 박제만 해놓고 deploy 워크플로우에 반영 안 함. 새 폴더·새 서버 추가 시 deploy 워크플로우 paths·script 즉시 동기화. "git pull은 자동으로 돌겠지" 가정 금지.

- **2026-05-13** ㊷ | **GAS v5.1 VALID_STATUSES 화이트리스트가 카페24 시트 raw 값과 불일치 → 카페24 첫구매자 99% 제외** | sheets_sync.py:244 코멘트가 "카페24는 거래종료 고정"이라 명시했지만 시트 raw 값은 "배송 완료"(공백 포함)·"배송중"·"취소 완료"·"입금전 취소 - 관리자". v5.1에서 화이트리스트로 바꿀 때 시트 raw 값 직접 검증 안 함. 사용자가 2026-03 카페24 첫구매자 1명(raw 200건+)을 보고 발견. 수정: v5.1.1 — 블랙리스트 회귀(`isCanceledStatus_` 정규화+취소/환불/반품 부분일치 제외) | **하지 말 것**: 다른 코드 코멘트("거래종료 고정")만 보고 시트 raw 값 가정 금지. 시트 화이트리스트/블랙리스트 변경 시 raw STATUS 컬럼 unique 값 분포 직접 확인 후 적용. 가능하면 블랙리스트(취소 키워드 제외) > 화이트리스트(정상 상태 열거) 선호 — 시트 raw 값이 다양·변경 가능하면 화이트리스트는 silent drop 위험.

- **2026-05-13** ㊶ | **로컬 daily.csv의 220M spend를 보고 "API가 KRW로 응답한다"고 오진 → 전체 환경을 KRW로 변경 → cron 실패 + 다음 run에서 spend가 103원(USD가 KRW로 저장)으로 또 망가짐** → 실제로는 git의 cron 자동커밋(6731e84)이 spend=150,481로 정상 저장돼 있었음. 220M은 git에 없는 로컬 dryrun 흔적이었고, API는 줄곧 USD($103) 반환 중. 1차 진단 시 git log로 "remote가 어떻게 저장했는지" 확인 안 함. 2차 결과: GitHub Variables/workflow yml/Vultr .env 3곳 모두 USD로 환원, 잘못 저장된 5/12 행 두 번째 제거 후 재실행 → spend=150,611 정상 복구 | **하지 말 것**: 로컬 데이터 파일에서 이상 발견 시 즉시 `git log --oneline -- {파일}` + 최근 자동커밋 내용(`git show {hash} -- {파일}`) 확인 필수. 로컬과 git 본체 비교 안 하고 "API/시스템이 바뀌었다" 결론 금지. 통화 변환 같은 시스템 전역 설정 변경은 raw API 응답 단위 + 정상 저장 사례(다른 날짜) 양쪽 모두 검증.

- **2026-05-12** ㊵ | **GAS run_id에 'gas_' prefix 추가했다가 lib/sheet_staleness.py check_pipeline_freshness() startswith(today) 호환성 깨짐** → v5.1 작성 시 `gas_2026-05-12_HHmmss` 형식 명세. 그러나 lib/sheet_staleness.py:118이 `run_id.startswith(today)` 체크 → 매번 stale 판정. Codex 1회차 점검에서 발견. 수정: prefix를 suffix로 변경 (`2026-05-12_HHmmss_gas`) | **하지 말 것**: 다른 코드와 공유 데이터 포맷 변경 시 양쪽 코드 contract를 정확히 확인. 특히 string prefix/suffix matching.

- **2026-05-12** ㊴ | **카페24 amount 누적이 매출 부풀림 — sheets_sync.py [row]*n 패턴 미인지** → Claude 점검에서 "카페24 amount 첫 row만 사용 vs SS 누적" 정책 불일치로 판단. 그러나 sheets_sync.py:290이 item 개수만큼 `[row]*n` 복제하며 각 row의 amount는 order-level 동일값. v5.1에서 누적으로 바꾸면 3-item 주문 50,000원 → 150,000원으로 부풀려짐. Codex 1회차 점검에서 발견. 수정: 첫 row만 저장(v5_0 동작 유지) | **하지 말 것**: 데이터 소스 동작(특히 row 복제·item-level 여부) 확인 없이 "정책 불일치"로 단순 결론 금지. sheets_sync 같은 upstream 코드 패턴 먼저 점검.

- **2026-05-12** ㊳ | **GAS 재구매 분석 모듈 v5_0에서 수치 부정확 결함 10개 동시 존재** → 재구매율 분모 부풀림(같은 버킷 신규+재구매 dedup 안 됨), SS 0원 분석 제외, isCanceled 부분일치 오탐("취소가능"도 제외), 코호트 30/60/90일 분모에 미관찰 포함, 퍼널 분모에 미관찰 포함, 통합 식별자 비호환(카페24=휴대전화·SS=구매자ID), M+N 현재월 partial 처리, 0일 간격 제외, 기간 재구매율 sales-mix 의미. 모든 % 지표가 부정확한 상태로 5개월간 시트 발송 | **하지 말 것**: 비율 지표(재구매율·전환율·리텐션) 분모 정의 점검 필수. 특히 (a) 같은 버킷 중복 dedup, (b) 미관찰 고객 제외, (c) maturity window 적용 3가지.

- **2026-05-12** ㊲ | **Plan-level codex adversarial review 4회 반복으로 무한 루프 진입** → plan v1(4결함) → v2(4결함) → v3(6결함) → v4(needs-attention) — 결함이 줄지 않고 더 많아짐. plan이 클수록(7개 변경사항) codex가 정밀화 결함 끝없이 발견. v5에서 plan 분할(2개 변경만)로 codex 점검 1~2회로 단축 | **하지 말 것**: plan adversarial review는 plan이 작을 때만 수렴. 큰 plan(5+ 변경)은 분할 후 점검. iteration cap 2회로 고정.

- **2026-05-12** ㊱ | **Meta Advantage+ Creative를 "지금 당장 켜면 됨"으로 일반 추천** → 헤비로버 위너 계정(ROAS 6.20 위너 소재 존재)에서 Advantage+가 소재를 임의 변형해 위너 요소 희석·ROAS 하락 유발하는 알려진 문제 미검토. 계정 특성(위너 패턴 고정·소규모 데이터) 확인 없이 "무료니 켜라" 단순 권장 | **하지 말 것**: 광고 자동화 옵션 추천 시 헤비로버 위너 소재 보호 여부 먼저 확인. Advantage+ Creative는 위너 소재 계정엔 기본 OFF 권장.

- **2026-05-12** ㉝ | **주간 Meta 광고 리포트 USD→KRW 환산 누락으로 "지출 638원" 오표시** → `meta_ads_weekly_report.py`가 `meta_ads_report.py`의 환산 함수를 쓰지 않고 USD 원본 그대로 출력. 일일 리포트(693줄 `convert_metrics_to_krw`)와 달리 주간은 환산 단계 없음 | **하지 말 것**: 신규 리포트 작성 시 `lib.meta_currency`에서 환산 함수 import. 자체 계산 금지. §외부API다루기 9번.

- **2026-05-12** ㉞ | **weekly workflow에 System User Token 전환 후에도 60일 갱신 step 잔존** → `refresh_meta_token.py` step이 `META_APP_ID` 없다며 매주 월요일 텔레그램 경고 발송. 인증 메커니즘 변경 시 관련 step 미제거 | **하지 말 것**: 인증 방식 변경 시 workflow step도 동시 제거. §자동화점검 5번.

- **2026-05-12** ㉟ | **재구매 리포트 Vultr cron 중복 등록으로 하루 2회 이메일+텔레그램 발송** → crontab에 `repurchase_report.py` 동일 줄 2개 등록. 배포 후 `crontab -l` 실측 검증 없이 운영 | **하지 말 것**: cron 등록 후 반드시 `crontab -l` 실측 확인. §자동화점검 4번.

- **2026-05-04** ㉜ | **QARP 병렬 백테스트 중 parquet 캐시 경합으로 결손율 37~74% 발생** → 4프로세스가 동시에 `prices.parquet`를 읽기/쓰기하면서 파일이 절반만 써진 상태에서 다른 프로세스가 읽음. 결과 CAGR 차이 19%p → INCONSISTENT 판정. Monitor "OK" 집계도 "INCONSISTENT" 문자열을 grep해 오판 | **하지 말 것**: parquet 캐시 공유 프로세스는 병렬 실행 금지. 데이터 레이어를 1회 로드 후 백테스트만 N회 반복하는 구조로 설계. Monitor 완료 판정 grep 패턴은 성공+실패 모두 포함 확인.

- **2026-05-04** ㉛ | **QARP screener engine.py의 _stage3_value가 `max_peg` 키를 하드코딩으로 참조** → config yaml에 해당 키가 없는 변형 실행 시 `KeyError: 'max_peg'`로 즉시 실패. verify_run.py에서도 `--config` 인자를 `run_once()`에 전달 안 해 변형 config가 baseline과 동일하게 작동하는 silent bug 동시 발생 | **하지 말 것**: config dict에서 조건별 키를 `c["key"]`로 직접 참조 금지. 옵션 조건은 반드시 `c.get("key")` 또는 `if "key" in c:` 패턴 사용. 함수 인자 추가 시 호출 스택 전체(caller, caller의 caller)까지 전달 여부 확인.

- **2026-05-04** ㉚ | **GitHub Actions yml에 채널별 Secrets 주입 누락으로 텔레그램 채널 분리 미작동** → `TELEGRAM_CHAT_ID_ADS` 등 4개 Secrets가 GitHub에 등록되어 있었으나 yml env 블록에 추가 안 해서 코드가 읽지 못함. 서버 `.env`만 확인하고 yml 주입 여부 검증 안 해 "정상"으로 오판. 광고 리포트가 `Heavyrover_ads`가 아닌 기본 채팅으로 발송 지속 | **하지 말 것**: Secrets 등록 확인만으로 완료 판단 금지. yml `env:` 블록에 `${{ secrets.XXX }}` 실제 주입 여부까지 반드시 코드로 확인.

- **2026-05-01** ㉙ | **MCP google-sheets 활성 상태에서 OneDrive 동기화 폴더 안의 산출물 5개 동시 손실** (proposals/outputs, docs/analysis_10b/rounds, docs/strategy/outputs, docs/expansion/outputs, data/analysis_10b/sheets) → file-history 백업으로 37개 복원했으나 round-10·proposal 에이전트 7개·expansion domain 12개 등 미복원 | **하지 말 것**: OneDrive 동기화 폴더 안에서 npm/npx/MCP 서버 실행 시 .gitignore된 폴더 손실 위험. 산출물은 반드시 git 추적, 또는 비OneDrive 폴더로 프로젝트 이전.

- **2026-05-01** ㉘ | `/proposal` 강한소상공인 폴더 셋업 시 **KOTRA 합격통지서를 제출 서류 목록에 자동 포함** → 공고문 확인 안 하고 사업계획서 본문에 "KOTRA 합격" 언급 있다는 이유만으로 추가. 강한소상공인 제출 요건엔 없음 | **하지 말 것**: 사업별 제출 서류 목록은 **공고문 원문 직접 확인**한 항목만 포함. 사업계획서 본문 언급 ≠ 제출 요건. setup_proposal_folder.py 사업별 서류 맵 변경 시 공고문 PDF 재확인 후 추가.

- **2026-05-01** ㉗ | **고정비 656만원 구 데이터를 현행으로 가정** → bridge_10b.json 656만원(박재영 499만 기준)을 그대로 사용해 월 순이익 200만원으로 계산. 실제 박재영 100만 + 고정비 500~550만 + 4월 순이익 500만이 맞음. 사용자가 직접 정정 후에야 인지 | **하지 말 것**: bridge_10b.json·unit_economics.json 같은 분석 파일의 인건비·고정비 수치는 작성 시점이 박제된 값. 순이익 계산 등 의사결정용 수치 사용 전 사용자에게 "현재도 맞나요?" 1줄 확인 필수.

- **2026-05-01** ㉖ | **결제 퍼널 49.85% 원인을 "배송비·소셜로그인 추가 필요"로 진단** → 이미 둘 다 완료된 상태였음. CLAUDE.md §9 즉시 대응 목록의 과거 시점 표기를 현재로 오해 | **하지 말 것**: CLAUDE.md "즉시 대응" 항목을 권고로 사용하지 말고 **현재 상태**부터 사용자에게 확인. "이거 아직 안 했으면 하시고, 이미 했으면 다음 원인 봐야 합니다" 식으로 분기.

- **2026-05-01** ㉕ | **광고비 490만(unit_economics) vs 690만(CLAUDE.md §9)** 두 값 혼재한 채로 순이익 계산 → 동일 시뮬레이션 안에서 일관성 깨짐. cashflow_simulation.md 자체에 "불일치"가 박제됨 | **하지 말 것**: 동일 항목에 두 값이 보이면 **사용자에게 어느 게 정본인지 묻기 전에 계산 진행 금지**. 추정·실측 분리 원칙 준수.

- **2026-05-01** ㉔ | **박재영 469만원을 인건비 고정비로 잘못 분류** → 실제로는 강의 사업자카드 할부(일회성, 잔액 약 250만). 분석 4개 라운드 동안 잘못된 고정비로 시나리오 산출 | **하지 말 것**: 인건비·고정비 항목은 **명목 금액만으로 분류 금지**. "이게 매월 나가는 고정 인건비인지, 일회성 할부인지" 확인 후 분류.

- **2026-04-29** ㉓ | mart_* 탭을 회색 색상 처리만 하고 숨김은 빠뜨림 → 사용자가 여전히 탭이 노출된다고 지적. 색상 처리 ≠ 숨김. `_REDUNDANT_TABS`에 mart_* 추가 후 해결 | **하지 말 것**: 탭 정리 요청 시 색상 변경·이름 변경으로 대체하지 말고 반드시 `hidden: True` 처리까지 확인.

- **2026-04-28** ㉒ | 텔레그램 봇 토큰 4개를 채팅 평문으로 주고받아 텔레그램 보안 자동 무효화 → 4봇 401 Unauthorized, 자동화 알림 전체 침묵 | **하지 말 것**: 토큰·API 키를 채팅에 붙여넣지 말 것. 신규 봇 등록 시 사용자에게 "토큰을 채팅에 보내지 말고 .env 파일에 직접 입력 후 알려달라"고 먼저 안내.

## 사용 규칙

- 모든 실수는 발생 즉시 이 파일에 한 줄 append. CLAUDE.md §0의 "실수 자동 기록" 규칙과 연동.
- 같은 키워드 3회+ 등장 시 → `patterns.md` 카테고리로 승격 검토 (월말 회고).
- 형식: `- **YYYY-MM-DD** | {무엇을 잘못했는지 한 줄} | **하지 말 것**: {다음번 회피 규칙 한 줄}`
- 신규 항목은 시간 역순으로 추가 (최신이 위).

## 카테고리 인덱스 (patterns.md 매핑)

| 카테고리 | 적용 작업 | 본 파일 항목 번호 |
|---|---|---|
| §자동화점검 (Pre-flight) | API·cron·.env 의존 작업 시작 전 | ⑤, ⑪, ⑮ |
| §외부API다루기 | 카페24·SS·Meta·Anthropic 등 통합 | ②, ⑨, ⑩, ⑫, ⑭, ⑮, ⑯ |
| §시간중복처리 | 시간 윈도우·dedupe 로직 | ①, ④ |
| §데이터범위와분석분리 | 시트·DB 데이터 이전 정책 | ③ |
| §엑셀편집 | openpyxl·xlsx 작업 | ⑦ |
| §출력관리 | 5,000자 초과 우려 응답 | ⑥ |
| §지역자격필터 | govt-radar·정부지원 매칭 | ⑬ |
| §환경컨텍스트 | 메일·OS·세션 가정 | ⑧ |

회피 규칙 상세는 → `docs/lessons/patterns.md`

---

## 로그

- **2026-04-28** ㉑ | E2E 3회 검증 가설3에서 발견: `is_shipping_overdue`가 `placeOrderStatus`를 안 봐서 PAYED+CANCEL(취소 요청 중) 주문 7건이 "발송기한 초과"로 잘못 카운트. 텔레그램 알림에 "발송기한초과 7건" 표시되어 사용자가 발송 못 한 걸로 오인 가능. 보강: `placeOrderStatus=='OK'` 체크 추가 + `detect_special_orders`에 PAYED+CANCEL 분기 추가. | **하지 말 것**: 외부 API 상태 enum이 두 종류(`productOrderStatus`, `placeOrderStatus`) 이상이면 둘 다 함께 평가. 한쪽만 보고 판정하면 의미 왜곡 발생.
- **2026-04-28** ⑳ | 11시 발주 자동화 알림은 텔레그램 봇만 인식. 콘솔 직접 입력 `/cancel`은 bash가 명령어로 해석해 `No such file or directory`. | **하지 말 것**: 봇 승인 플로우는 항상 텔레그램 메시지로 응답. 콘솔에서 강제 중단할 일 있으면 `Ctrl+C` 사용.
- **2026-04-28** ⑲ | Vultr 서버 `run.sh`엔 `./venv/bin/python`로 잘 들어가지만, 사람이 콘솔에서 직접 실행 시 `python` 명령이 없어 실패. 서버 기본 PATH에 `python` 미존재 (Ubuntu 22.04는 `python3`만). | **하지 말 것**: 서버 디버그 명령 안내 시 `source venv/bin/activate && python ...` 또는 `./venv/bin/python ...` 형식 우선. 운영 cron의 venv 호출 방식과 동일하게.
- **2026-04-28** ⑱ | Vultr `/root/heavylover-automation/`이 git clone이 아닌 단순 복사 폴더라 `git pull` 자체가 불가능. 그래서 어제 패치 GitHub push 후에도 서버 코드 갱신 안 됨 → 오늘 11시 cron이 옛 코드로 SS 26건 누락. 해결: `/tmp`에 git clone → `.git` 폴더만 본 디렉터리로 이식 (`mv /tmp/heavylover-tmp/.git ./.git`) → `git fetch + reset --hard origin/main` → 자동 배포 워크플로우(`deploy-vultr.yml`) 신설. | **하지 말 것**: 신규 서버에 코드 배포 시 처음부터 `git clone`. scp/rsync 단순 복사는 코드 갱신 추적 불가 + 자동 배포 차단. 같은 패턴 적용 후보: 향후 신규 워크로드 폴더는 모두 GitHub 원격에서 clone.
- **2026-04-28** ⑰ | 코드 패치 GitHub push 했다고 보고 후 `git log origin/main` 미검증 — 다른 워크트리/세션이 끼어들면서 커밋이 reflog에서 사라짐. 다행히 누군가 다시 origin에 반영했지만 Vultr는 별도 git pull 없어 옛 코드 유지 → SS 누락 재발. | **하지 말 것**: push 직후 `git fetch && git log origin/main --oneline -3`으로 원격 SHA·메시지 확인. 배포 끝났다고 보고 전 서버에서도 `git log -1 --format="%h %s"` 실측. "push 결과 200 OK" ≠ "원격 main 반영".
- **2026-04-28** ⑯ | Meta 광고 계정이 USD 통화인데 분석 코드는 KRW 가정으로 작성. 첫 실행에서 `지출 84원`(실제 84 USD = 약 12만원), `CPC 0원`(실제 405원) 표시되어 모든 벤치 비교 무의미. 광고 계정 통화 사전 확인 누락. | **하지 말 것**: 외부 API 통합 첫 응답에서 `currency`·`account_currency`·통화 단위 필드 즉시 확인. KRW 외 계정이면 환산 함수(`convert_metrics_to_krw`)를 모든 단가성 필드에 일관 적용 — 환율은 변동 안 쓰고 고정값(1,450원/USD) 박제 후 단일 출처(`CURRENCY_KRW_PER_USD`)로 관리.
- **2026-04-28** ⑮ | Meta User Access Token (Graph API Explorer 발급) 만료 시간을 60일로 가정하고 자동화 일정 설계. 실제 short-lived token은 **수 시간**만 유효. 백필 도중 만료, 일일 자동화도 가동 못 함. long-lived 60일은 `fb_exchange_token` API + 앱 시크릿 필요. | **하지 말 것**: 외부 API 토큰 종류·수명을 공식 문서로 확인 후 자동화 설계. 토큰 만료 가능성을 자동화 헬스체크에 박제 — `meta_ads_report.py`에 만료 키워드(`Session has expired`, `OAuthException`, `code:190/463`) 감지 시 텔레그램에 명확한 재발급 안내 메시지 자동 발송.
- **2026-04-28** ⑭ | CLAUDE.md·patterns.md 리팩터링 시 `memory/...` 상대경로를 검증 없이 그대로 옮겨 6곳에서 깨진 링크 발생. 실제 메모리 위치는 `~/.claude/projects/{프로젝트}/memory/`로 시스템 프롬프트 `auto memory` 섹션이 절대경로를 자동 주입. 본문에 박힌 상대경로는 동작하지 않음. | **하지 말 것**: 외부 파일·디렉터리 경로를 문서에 박제할 때 표기 직후 `ls`/`Read`로 실재 검증. 시스템이 자동 로드하는 자원(메모리·skills 등)은 경로 박제 대신 추상 명칭("Claude 메모리 시스템") 사용.
- **2026-04-28** ① | 11시 발주 엑셀에서 SS 33건 통째 누락 (당일 발주 못 한 7건은 발송기한 초과로 전환, 판매자 점수 차감 위험). 원인: `orders_by_status(PAYED, hours_back=24)` + 평일 cron(`1-5`) 조합 — 금 11시~일 23:59 결제분이 변경 윈도우 밖, 며칠 전 결제 후 가만히 있던 주문도 24h 윈도우에 안 잡힘. 카페24는 N20 상태 기반이라 안전. 해결: `orders_pending_dispatch(days_back=14)` 신설 — sheets_sync 패턴(1일 분할 N회 + dedupe) 재사용, 상세 후 `productOrderStatus=='PAYED'`만 반환. `shippingDueDate < now` = 발송기한 초과 별도 카운트. | **하지 말 것**: 시간 윈도우 방식은 cron 갭과 만나면 누락 영구화. 채널이 상태 기반 조회를 지원하면 그걸 우선. 변경 윈도우 강제면 cron 주기보다 충분히 넓게(14일+) + dedupe + 상세 응답 상태 재필터 3중 안전망.
- **2026-04-28** ② | SS sync 코드가 `productOrder.paymentDate`를 보고 있었는데 실제 결제일은 `order.paymentDate`에 있어서, 4월 신규 행 전체가 결제일 컬럼 비어있는 채로 들어감. 시트 진단 전엔 발견 못 함. | **하지 말 것**: 외부 API 응답 매핑 코드는 작성 직후 raw JSON 1건 출력해서 키 경로 검증. 한 달 가동된 자동화도 실제 시트 데이터가 비어있는지 점검할 것.
- **2026-04-28** ③ | SS sync가 PURCHASE_DECIDED만 시트에 넣어, 결제됐지만 자동확정(7일) 안 된 PAYED·DISPATCHED·DELIVERING·DELIVERED 주문이 시트에서 누락. 4월 후반 데이터 빈 것처럼 보였음. | **하지 말 것**: "구매확정만"이라는 분석 정책과 "데이터 이전 범위"는 분리. 시트엔 5상태 모두 보관 + 분석 시 주문상태 컬럼으로 필터.
- **2026-04-28** ④ | sync_cafe24가 매 실행마다 9건씩 누적 중복. 원인은 cutoff='YYYY-MM-DD' vs 결제일시 'YYYY-MM-DD HH:MM:SS' 문자열 비교에서 cutoff 당일 시간대 행이 keep에 남고 새 행이 또 추가. | **하지 말 것**: 시간 포함 컬럼 cutoff 비교 시 cutoff에 ` 00:00` 명시. 시트 dedupe는 자연 키(주문번호+결제일시+...) 기반으로 1회 더 적용.
- **2026-04-28** ⑤ | 카페24 OAuth refresh_token 2주 만료를 사람이 매번 재발급 — 작업 도중 만료 발견. | **하지 말 것**: 외부 API refresh_token 만료 정책 있는 서비스는 만료 전 자동 갱신 cron 신설(매일 04:00 `refresh_cafe24_token.py`). 같은 패턴 적용 후보: Meta long-lived token, 네이버 커머스.
- **2026-04-27** ⑥ | `/insights` 1·2차 리포트 통합 결과, 과거 한 세션 전체가 출력 토큰 한도(500) 초과 에러 반복으로 손실됨. 큰 파일·다중 모듈을 한 응답에 다 토하려 한 것이 원인. | **하지 말 것**: 5,000자 초과 우려 시 단계 분할 출력. 분석 리포트는 표+요약 우선. (§0 "출력 길이 제어" 참조)
- **2026-04-27** ⑦ | `/insights` 1·2차 리포트 통합 결과, 과거 Excel "디자인" 요청에서 freeze panes·hidden rows·invalid cell types·duplicate columns·orphaned panes를 임의 추가해 파일 손상 반복. 사용자 frustration 발생. | **하지 말 것**: 디자인 요청은 색상·폰트·테두리·열너비만. 수식·freeze·숨김·셀 타입·구조 일체 금지. 편집 후 `openpyxl.load_workbook()` 검증 후 보고. (§0 "스프레드시트 편집 규칙" 참조)
- **2026-04-27** ⑧ | 메인 메일이 Naver(`ohkm8050@naver.com`)인데 Gmail로 가정하고 IMAP 코드 작성 → 재계획 발생. 또한 활성 Claude 세션 안에 `claude -c`·`claude -r` CLI 명령을 사용자가 직접 타이핑해도 인식 안 됨을 즉시 안내 못함. | **하지 말 것**: 세션 시작 시 메일·OS·배포 상태를 먼저 확인. CLI스러운 입력 들어오면 즉시 위치 안내. (§0 "환경 컨텍스트" 참조)
- **2026-04-27** ⑨ | govt-radar `lib/scorer.py` 작성 시 memory/MEMORY.md를 안 보고 키워드 정해서 "강한 소상공인" 명칭 변경(→ 소상공인 도약)을 반영 못함. 이미 `project_grant_renames.md`에 기록돼 있던 사항. 사용자가 텔레그램 알림 누락 발견 후 지적. | **하지 말 것**: 키워드 매칭·검색 로직 작성 전 memory/MEMORY.md 1회 훑고 관련 항목(명칭 변경·본사 위치·발신자 화이트리스트) 반영.
- **2026-04-27** ⑩ | govt-radar 1차 데이터 진단 시 "100건 샘플"만 보고 "소진공 직접 발주는 기업마당 API에 안 옴"이라고 결론. 500건 펼쳐보니 8건 들어있었음. | **하지 말 것**: API 커버리지 판단할 때 첫 페이지만 보고 결정하지 말 것. 페이지네이션 끝까지 또는 키워드 직접 검색으로 확인.
- **2026-04-27** ⑪ | CLAUDE.md §5에 "08:30 sync, 09:00 report cron 가동 중"이라고 적혀 있어 사실로 전제하고 마트 플랜을 짰으나 실제 Vultr `crontab -l`엔 11시·13시 자동화만 있었음 (재구매 cron 미배포). | **하지 말 것**: 자동화 가동 여부는 문서가 아니라 `crontab -l` + 서버 파일 존재로 1차 검증한 뒤 작업 시작. (§0 "Pre-flight Checks" 참조)
- **2026-04-27** ⑫ | Google Calendar 이벤트 ID를 `base64.b32encode`로 만들어서 19/19 이벤트가 "Invalid resource id" 400 에러로 모두 실패. RFC2938 base32hex(0-9, a-v)만 허용되는데 일반 base32(a-z, 2-7)는 'w'~'z'가 들어가서 거부됨. | **하지 말 것**: 외부 API의 식별자 포맷 규칙은 추측 말고 공식 문서 확인. Calendar event_id는 `b32hexencode` 사용. 새 외부 API 첫 통합 시 에러 메시지 보고 즉시 다른 인코딩 후보 시도.
- **2026-04-28** ⑬ | govt-radar 지역 필터에서 "경기도 산하 시·군"(파주·화성·부천·시흥 등) 한정 공고 19건이 [경기] prefix만 보고 통과. 본사가 용인이라 다른 시·군 한정은 지원 불가인데, NON_ELIGIBLE_REGIONS에 광역지자체만 있고 시·군이 없었음. | **하지 말 것**: 지역 필터는 광역(시·도) + 산하(시·군·구) 모두 차단 목록 작성. 본사 prefix가 없는 한 타 시·군 prefix·발주기관·본문 자격 한정(`관내 본사` 등) 모두 차단. 회귀 테스트(`tests/scorer_scenarios.py`)에 19건 케이스 박제.

<!-- 신규 항목은 이 줄 위에 시간 역순(최신이 위)으로 추가. 형식 예: `- **YYYY-MM-DD** ⑭ | ... | **하지 말 것**: ...` -->
