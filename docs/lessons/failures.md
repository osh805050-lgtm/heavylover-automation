# 실패 노트 (시간순 원시 로그)

> 이 파일은 [작업 종류 매칭 시 grep 검색] / [월말 회고] / [에이전트 시작 전 위험 점검] 시 로드됩니다. CLAUDE.md §13의 정본입니다.
> 마지막 갱신: 2026-05-13 · 갱신 주기: 즉시 누적 (실수 발생 시)

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
