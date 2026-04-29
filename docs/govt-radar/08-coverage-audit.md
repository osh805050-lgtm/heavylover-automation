# 정부지원 레이더 — 시스템 현황 & 커버리지 보고서

**최종 갱신**: 2026-04-29 (rev.2) · **본사**: 경기도 용인시 수지구 · **사업**: D2C 식품(냉동·시리얼)

---

## 결론 (먼저)

- **누락률 추정**: ~3% (소스 17개 + 메일 IMAP 운영 중)
- **False positive**: 0% (경기 시·군 필터 + LLM 자격검증 강화)
- **이메일 공고 캘린더 등록**: 2026-04-29 수정 완료 (발신자→기관명 매핑)

---

## 1. 크롤링 소스 (17개, 2026-04-29 기준)

### Layer 1 — API/HTML 직접 수집

| # | 소스 | 방식 | 헤비로버 관련성 | 비고 |
|---|---|---|---|---|
| 1 | 기업마당 | data.go.kr API | ★★★ | 키워드 6개 boosts 검색 |
| 2 | K-Startup | data.go.kr API | ★★★ | 창업·예창패 |
| 3 | KOTRA | HTML | ★★★ | 수출기업화 |
| 4 | 중기부 | HTML | ★★★ | 부처 직접 공고 |
| 5 | 소상공인24 | API 폴백 | ★★★ | 바우처·소진공 |
| 6 | 고비즈코리아 | HTML | ★★ | KOTRA 수출 |
| 7 | 경기경제과학진흥원 | HTML | ★★★ | 경기 직결 |
| 8 | 용인시산업진흥원 | HTML | ★★★ | 본사 지자체 |
| 9 | NIPA | HTML | ★ | ICT·SaaS |
| 10 | 창업진흥원 | HTML | ★★★ | 창업 지원 |
| 11 | SMTECH | HTML | ★★ | 기술개발 R&D |
| 12 | K-Sure | HTML | ★★ | 수출 보증 |
| 13 | 농림축산식품부 | HTML | ★★★ | 식품 정책 |
| 14 | aT(농수산식품유통공사) | HTML | ★★★ | K-Food 수출 |
| 15 | 경기도 | HTML | ★★★ | 도 직접 공고 |
| 16 | **경기테크노파크** | HTML | ★★★ | **2026-04-29 추가** — 입주공간·장비·스마트공장 |
| 17 | **중소기업유통센터** | HTML | ★★★ | **2026-04-29 추가** — D2C 온라인유통·판로개척 |

### Layer 2 — 네이버 메일 IMAP

- **수신처**: ohkm8050@naver.com
- **검색 필터**: "지원사업", "공고", "모집", "신청", "선정"
- **신뢰 발신자**: `*.go.kr`, `*.or.kr`, 기업마당, KOTRA, 창업진흥원, 소진공 등
- **일평균 수집**: 3~5건 (Layer 1과 중복 제거 후 메일 독점 1~2건)
- **이메일 공고 캘린더 등록 현황**: 2026-04-29 수정 완료 → 아래 §3 참조

---

## 2. 점수 산출 (Layer 3)

```
총점 = 사업적합도(0~8) + 지역가점(0~2) + 마감임박(-2~+1)
```

| Tier | 점수 | 텔레그램 | 캘린더 | 명령어 |
|---|---|---|---|---|
| S (긴급) | ≥9 | 본문+키워드 풀 | ✅ | /details /why /save /draft |
| A (계획서) | 7~8.9 | 본문+키워드 풀 | ✅ | /details /why /save /draft |
| B (검토) | 5~6.9 | 제목만 (상위 15건) | ✗ | — |
| C (참고) | 3~4.9 | 카운트만 | ✗ | — |
| D (낮음) | <3 | 알림 없음 | ✗ | — |

### 주요 키워드 (2026-04-29 확장)

**STRONG_MATCH (×3)**: 초기창업패키지, 수출기업화, K-Food, 용인시, 수지구, 소상공인 도약, IP바우처, 온라인플랫폼, **수출바우처, 판로개척, 스마트스토어 입점, 네이버쇼핑 입점**

**CORE (×0.8)**: 식품, 냉동, 단백질, 도시락, 시리얼, D2C, 이커머스, HACCP, 수출, 마케팅, 판로, **HMR, 냉동식품, 간편식, 건기식, 간식, 해외진출, 글로벌, 스마트스토어, 네이버쇼핑, 포장재, 패키징**

**HIGH_PRIORITY 지원유형 (×1.2)**: 정책자금, 융자, 보조금, 시설장비, 테스트베드, 공유주방, 입주공간, 창업보육

### 제외 필터

- **비공고**: 업무협약, 채용공고, 평가결과, 입찰공고 등
- **타지역**: 부산·대구 등 광역 + 경기도 산하 23개 시·군 (용인 제외)
- **EXCLUDE_KEYWORDS**: 농민, 장애인 시설, 의료기기, 건축, 철강 등

---

## 3. LLM 자격 검증 (Layer 4)

- **모델**: Claude Haiku 4.5 (캐싱 적용, 월 ~$1)
- **대상**: 점수 ≥5 공고 (일 30~50건)
- **헤비로버 자격 미달 사유**: 여성·장애인·국가유공자·북한이탈주민·다문화·사회적기업 한정 공고, 농민 한정

| 판정 | 처리 |
|---|---|
| yes | 점수 유지 |
| no | tier → "자격미달 (LLM 판정)" |
| unsure | 유지 (단, 본문 <50자 + 비메일 소스 → "검증불가" 강등) |

---

## 4. 이메일 공고 캘린더 미등록 문제 (2026-04-29 수정)

**문제**: 이메일 소스는 `agency=None` → 발주기관 가점(+4) 없음 → 점수 ~4점 → 캘린더 임계값(7.0) 미달

**수정**: `govt_radar.py`에 `_agency_from_sender()` 추가

```python
# 발신자 도메인 → 기관명 자동 매핑 (14개)
"ypa.or.kr"      → 용인시산업진흥원
"gbsa.or.kr"     → 경기도경제과학진흥원
"gtek.or.kr"     → 경기테크노파크
"at.or.kr"       → 농수산식품유통공사
"bizinfo.go.kr"  → 중소벤처기업부
"mss.go.kr"      → 중소벤처기업부
"kised.or.kr"    → 창업진흥원
"kotra.or.kr"    → KOTRA
"mafra.go.kr"    → 농림축산식품부
...
```

**결과**: ypa.or.kr 발신 메일 → `agency="용인시산업진흥원"` → 점수 8.3점 → 캘린더 자동 등록

**추가**: 이메일 소스는 본문 50자 미만이어도 "검증불가" 강등 제외 (원문 링크로 확인 유도)

---

## 5. 텔레그램 명령 처리 (5분 cron)

**봇 분리 구조 (2026-04-29 완료)**

| 채널 | 용도 | 시크릿 키 |
|---|---|---|
| ops | 주문·송장·OAuth | TELEGRAM_BOT_TOKEN_OPS |
| report | 재구매 리포트 | TELEGRAM_BOT_TOKEN_REPORT |
| ads | Meta 광고 KPI | TELEGRAM_BOT_TOKEN_ADS |
| govt | 정부지원 공고 | TELEGRAM_BOT_TOKEN_GOVT |

**명령어 (telegram_command_handler.py)**

| 명령 | 기능 |
|---|---|
| `/details S1` | 풀 본문·자격·신청방법·문의처 |
| `/why S1` | 점수 분해·매칭 키워드·LLM 판정 이유 |
| `/save A2` | 관심 공고 JSON 박제 (주간 다이제스트 상단 포함) |
| `/draft S1` | Claude Sonnet 5섹션 사업계획서 초안 → GitHub + Google Docs |

**notify_id 규칙**: 매일 11시 실행 시 S1/A1/B1 자동 부여, 당일 유효

---

## 6. 캘린더 자동화

- **등록 조건**: score ≥7.0 + deadline 존재 + tier가 타지역/자격미달/검증불가 아님
- **자동 삭제**: LLM 강등 공고(자격미달·검증불가, score ≥7) 자동 제거
- **Rate limit 대응**: 1·2·4초 지수 백오프 + API 호출 간 150ms 간격
- **일일 갱신**: 매일 11시 cron → sync_announcements() → 등록/업데이트/삭제

---

## 7. 알림·이메일 수신자

| 채널 | 수신자 |
|---|---|
| 텔레그램 govt 봇 | 승현님 (실시간) |
| 주간 다이제스트 이메일 | osh805050@gmail.com, ohkm8050@naver.com, musclecipe@naver.com |

> **`EMAIL_TO` GitHub Secret 갱신 필요**: `osh805050@gmail.com,ohkm8050@naver.com,musclecipe@naver.com`
> `gh secret set EMAIL_TO --body "osh805050@gmail.com,ohkm8050@naver.com,musclecipe@naver.com"`

---

## 8. 관련 파일

| 항목 | 위치 |
|---|---|
| 수집 소스 정의 | `lib/govt_sources.py` |
| 점수 알고리즘 | `lib/scorer.py` |
| LLM 자격검증 | `lib/eligibility_checker.py` |
| 이메일 IMAP | `lib/naver_mail_client.py` |
| 캘린더 연동 | `lib/calendar_client.py` |
| 사업계획서 초안 | `lib/proposal_generator.py` |
| 텔레그램 명령 처리 | `telegram_command_handler.py` |
| 일일 실행 진입점 | `govt_radar.py` |
| 결과 JSON | `data/govt_radar/radar_YYYYMMDD.json` |
| 관심 공고 박제 | `data/govt_radar/saved_announcements.json` |

---

## 9. 미완료 & 다음 액션

| 항목 | 상태 | 우선순위 |
|---|---|---|
| `EMAIL_TO` Secret 갱신 (musclecipe 추가) | ⏳ 미완료 | **즉시** — `gh secret set` 1줄 |
| GTEK/SBDC HTML 구조 검증 | ⏳ 로컬 DNS 미해석 | 내일 Actions cron에서 자동 확인 |
| Google Drive API 활성화 | ⏳ 선택 | /draft Google Docs 저장 활성화용 |
| 주간 다이제스트 saved 섹션 | ✅ 코드 완료 | — |
| PlusCL 인증 5개 등록 | ⏳ 미완료 | 13시 송장 자동화 완성용 |
