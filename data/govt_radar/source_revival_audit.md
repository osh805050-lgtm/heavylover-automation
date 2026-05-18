# 정부지원 레이더 — 소스 부활 감사 (Source Revival Audit)

**작성일**: 2026-05-18
**근거 데이터**: `data/govt_radar/radar_20260512.json` ~ `radar_20260518.json` (7일치) + `data/govt_radar/probe_result.json`
**작성 목적**: Playwright Reconciliation 업그레이드 plan 단계 1 산출물. 어느 소스를 Playwright로 살려야 하는지·왜 죽었는지·우선순위 결정.

---

## 1. 한눈에 보는 현황

| 상태 | 정의 | 개수 | 비율 |
|---|---|---:|---:|
| **OK** | 7일 14건+ 안정 | 7 | 28% |
| **WEAK** | 7일 1~13건 (불안정) | 2 | 8% |
| **DEAD** | 7일 0건 | **16** | **64%** |
| 합계 | | 25 | 100% |

> CLAUDE.md §9 "12개(48%) 0건"은 2026-04-27 기준. **현재 16개(64%)로 악화**. `docs/lessons/failures.md`에 회귀 반영 필요.

---

## 2. 소스별 진단 (7일 카운트 + 부활 가능성)

### A. OK (7개) — Playwright는 reconciliation 용도로만
| 소스 | 7일합 | 일별 | 비고 |
|---|---:|---|---|
| 기업마당 | 3524 | [488,489,492,505,517,517,516] | 공공데이터포털 API. Playwright로 화면 cross-check해서 API 누락분 검출 |
| K-Startup | 1349 | [199,204,188,209,186,185,178] | 공공데이터포털 API. 동일하게 cross-check |
| KOTRA | 98 | [14,14,14,14,14,14,14] | 14건 고정 — 페이지 크기 limit 가능성. Playwright로 전수 확인 |
| 중기부 | 20 | [0,0,0,0,0,10,10] | **2026-05-17부터 부활** (누군가 fix). 안정성 관찰 필요 |
| NIPA | 70 | [10,10,10,10,10,10,10] | 10건 고정 — page limit 의심 |
| SMTECH | 98 | [14,14,14,14,14,14,14] | 14건 고정 — page limit 의심 |
| aT | 77 | [11,11,11,11,11,11,11] | 11건 고정 — page limit 의심 |

### B. WEAK (2개) — Playwright 우선 + 1주일 관찰
| 소스 | 7일합 | 일별 | 진단 |
|---|---:|---|---|
| 용인시산업진흥원 | 1 | [1,0,0,0,0,0,0] | 5/12 1건 후 침묵 — 셀렉터 또는 URL 변경 의심 |
| 창업진흥원 | 5 | [0,0,0,2,2,1,0] | probe에선 25건 보임. **셀렉터 미스매치 확정** |

### C. DEAD (16개) — Playwright로 살려야 함

#### C1. probe에서 공고가 보이는데 fetcher만 0건 (셀렉터 미스매치) — **즉시 부활 가능**
| 소스 | probe match_count | 비고 |
|---|---:|---|
| **농림축산식품부** | 24 | 셀렉터·URL 파싱 문제 — 화면엔 공고·채용·입법예고 가득 |
| **경기테크노파크** | 51 | 가장 큰 공백. `pms.gtp.or.kr/web/business/webBusinessView.do` 화면에 매일 신공고 |
| **중소기업유통센터(KODMA)** | 47 | D2C 판로지원 핵심 — TOPS·라이브커머스·온라인쇼핑몰 다 들어있음 |
| **경기스타트업플랫폼** | 10 | SPA지만 probe가 카드 추출 성공함 — Playwright로 동일하게 가능 |
| **창업진흥원(KISED)** | 36 | (WEAK에 포함) K-Startup과 별도 공고 다수 |

#### C2. probe에서도 0건 (실제 SPA + 로그인 벽) — **Playwright 헤드리스 가능성 의심**
| 소스 | probe match_count | 비고 |
|---|---:|---|
| 소상공인24 | 0 | `sbiz24.kr/landing/`로 리다이렉트 — 로그인 안 한 상태로는 공고 미노출. API 폴백 또는 로그인 우회 필요 |
| 소상공인판로지원(fanfandaero) | 0 | `portal/v2/introV2.do` 메인 화면만 — 공고 페이지 URL 변경 의심. 새 URL 찾아야 함 |

#### C3. probe 미실행 — Playwright로 1차 시도 필요
| 소스 | 추정 원인 |
|---|---|
| 고비즈코리아 | KOTRA 산하 — 메뉴 URL 변경 의심 |
| 경기경제과학진흥원(GBSA) | 2026-05-15 fetcher fix 시도(failures 52번)했으나 0건 지속 |
| K-Sure | 8443 포트 SSL 또는 셀렉터 문제 |
| 국가식품클러스터(foodpolis) | 식품 7천만원 사업 — 헤비로버 직결, 우선순위 높음 |
| 한국식품산업협회(KFIA) | 식품업종 전용 |
| 경기바로(ggbaro) | 경기도 소상공인 — `apply/biz-announce.do` 정적 사이트 의심 |
| 중진공(KOSMES) | 정책자금 융자 — 헤비로버 1억 신청 트랙과 직결 |
| 경기신용보증재단(GCGF) | 메인 페이지만 긁고 있을 가능성 |
| 중소벤처24(SMES24) | 중기부 통합 포털 — 셀렉터가 너무 generic (`li, .item, .card, article, tr`)로 0건 |
| 경기도(gg.go.kr) | ciIdx 변경 의심 |

---

## 3. 우선순위 (Playwright 모듈 작성 순서)

`lib/govt_playwright.py`에서 다음 순서로 fetcher 작성:

| 순위 | 소스 | 이유 |
|---:|---|---|
| 1 | 경기테크노파크 | probe 51개 가장 큼 + 용인시 IP지원센터(헤비로버 상표권) 포함 |
| 2 | 중소기업유통센터 | D2C 판로지원 = 헤비로버 본질 |
| 3 | 농림축산식품부 | 식품 직결 |
| 4 | 국가식품클러스터 | 식품 전용 최대 7천만원 |
| 5 | 창업진흥원(KISED) | probe 36개 + WEAK 회복 |
| 6 | 중진공(KOSMES) | 정책자금 1억 트랙 |
| 7 | 경기스타트업플랫폼 | SPA지만 카드 명확 |
| 8 | 경기바로 | 경기도 소상공인 |
| 9 | 경기경제과학진흥원 | 경기 기업비서 |
| 10~16 | 나머지 DEAD | probe부터 다시 |

**최소 성공 기준** (plan 검증 §3): 1~10번 중 **8개 이상**에서 다음 cron 실행 후 1건 이상 수집.

---

## 4. C1 그룹 (즉시 부활 가능) — Playwright 셀렉터 후보

probe_result.json의 `selector_candidates`를 토대로 한 1차 셀렉터 가설. 실제 작성 시 추가 검증 필요.

### 농림축산식품부
- 정답 URL: `https://www.mafra.go.kr/bbs/mafra/68/list.do` (현재 fetch_mafra 사용 중) → 화면 표시 확인되나 결과 0건 = **list.do 페이지 자체가 비어있고 메인 페이지 recentBbsInnerUl이 진짜 공고**
- 셀렉터 후보: `li.recentBbsInnerUl li`, 또는 `.notice li a[href*="/bbs/home/791/"]`
- 후처리: 텍스트 줄바꿈·탭 제거, `[공지공고]`/`[채용공고]` prefix 필터링

### 경기테크노파크
- 정답 URL: `https://pms.gtp.or.kr/web/business/webBusinessList.do` (메인 도메인 `gtp.or.kr`가 아니라 `pms.gtp.or.kr` 서브도메인)
- 현재 `fetch_gtek()`가 `https://www.gtp.or.kr` 메인만 긁고 있음 — **URL부터 잘못됨**
- 셀렉터: `a[href*="webBusinessView.do?b_idx="]`

### 중소기업유통센터(KODMA)
- 현재 URL `https://www.kodma.or.kr/usr/pbancInfo/selectPbancInfoList.do` — probe는 메인 `kodma.or.kr/index.do`로 갔는데 공고 페이지는 따로 있음
- 정답 URL 후보: `kodma.or.kr` 검색 메뉴에서 공고/모집 페이지 찾기
- 셀렉터: `li.board-list` (probe에서 13개 발견)

### 창업진흥원(KISED)
- 정답 URL: `https://www.kised.or.kr/misAnnouncement/index.es?mid=a10302000000` (probe final_url과 동일)
- 셀렉터 후보: `li.lstyle_list` (probe에서 25개 발견)
- 현재 0건 원인 추정: BS4 lxml 파싱이 `.es` 확장자에서 잘못된 인코딩 처리

### 경기스타트업플랫폼
- 정답 URL: `https://gsp.or.kr/supportProject/UVSL0001.do` (현재 fetch_gsp 사용 중) — Playwright 호출은 하나 셀렉터가 안 맞음
- 셀렉터: `li a[href*="UVSD0001.do?sportSeq="]` (probe에서 5개 발견)

---

## 5. Reconciliation 가치 추정 (Playwright primary 전환 후 예상)

| 측정 | 현재 | 예상 (1~10번 부활 후) |
|---|---:|---:|
| 일일 평균 수집 건수 | ~756 | **900~1,100** (+150~350) |
| 헤비로버 적합 공고 발견율 | 미측정 | 신규 식품·D2C 직결 사업 5~10개 추가 |
| API 누락 검출 가능 | 불가 | 가능 (기업마당 API vs Playwright cross-check) |
| 죽은 소스 silent failure | 16개 | 0~3개 (즉시 알림 작동 시) |

---

## 6. 다음 단계

1. ✅ 본 audit.md 작성 완료 (plan 단계 1)
2. ⏭ `lib/govt_playwright.py` — 우선순위 1~10번 fetcher 작성 (plan 단계 2)
3. ⏭ `lib/reconciler.py` — API vs Playwright cross-check
4. ⏭ `lib/source_health.py` — 8회 연속 0건 알림
5. ⏭ `govt_radar.py` 통합 + dry-run
6. ⏭ 워크플로우 timeout 45분 + playwright install
7. ⏭ 1주일 운영 후 본 audit 재실행하여 회귀 검증
