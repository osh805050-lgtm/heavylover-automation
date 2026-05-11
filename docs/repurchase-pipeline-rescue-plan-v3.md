# 재구매 분석 파이프라인 안정화 계획 v3 (3단계 통합본)

> **작성일**: 2026-05-12  · **상태**: codex 점검 대기 중
> **이전 버전**: `docs/repurchase-pipeline-rescue-plan.md` (v2, codex approve)
> **v3 추가**: ① 3단계 구조 관점 ② 1·3단계 silent failure 추가 발견 ③ Phase 1 병렬 실행 가능성 ④ 환경 사전 점검 체크리스트

---

## Context — 무엇이 멈췄나

매일 아침 9시 텔레그램에 재구매 요약이 도착하기까지, 다음 3단계가 순서대로 돕니다:

```
[1단계 수집] 08:30  카페24/스마트스토어 주문 → 구글 시트 raw 탭
                    (Vultr Python: sheets_sync.py)
                              ↓
[2단계 분석] 08:45  raw 주문 → 재구매율·코호트·P50 등 19개 분석 탭
                    (Google Sheets 내부 GAS)
                              ↓
[3단계 발송] 09:00  분석 탭 → 텔레그램 + 이메일
                    (Vultr Python: repurchase_report.py)
```

**현재 사고**: 2단계 GAS가 2026-05-05 10:11 이후 6일째 안 돔 → 분석 19개 탭 멈춤 → 3단계가 같은 숫자 반복 발송. 1단계 raw 동기화는 정상.

**증거**:
- `재구매_통합_월별` 메타 "업데이트: 2026-05-05 10:11" (5-12 현재 6일 stale)
- `재구매_간격분석` P50 = 15일 (CLAUDE.md 실측 10일 vs 시트 옛값)
- Apps Script 실행 이력: 5-05 10:11 "유형: 편집기" 1건 (수동 1회만), 시간 트리거 0건

---

## 단계별 점검 결과: 봤는가 / 문제 / 해결안

### 1단계 — 수집 (카페24·스마트스토어 → 시트)

| 항목 | 내용 |
|---|---|
| **확인 완료** | `sheets_sync.py` 코드 전체 흐름. raw 탭 카페24/SS 양방향 atomic swap 작동 |
| **미확인** | Vultr 서버 매일 08:30 실제 실행 여부(로그 직접 안 봄), raw 탭에 2026-05-12 데이터 차 있는지 |
| **발견된 문제** | sheets_sync 실패 silent — 오류는 `result["errors"]` dict에만 쌓이고 텔레그램 알림 0건 (`sheets_sync.py:605-615`) |
| **해결안** | (a) sheets_sync main() 끝에 `result["errors"]` 비어있지 않으면 ops 채널 알림 발송 (b) 매 실행 후 `pipeline_meta` 시트 탭에 `run_id`, `started_at`, `finished_at`, `source_rows_cafe24`, `source_rows_ss`, `status` 기록 |

### 2단계 — 분석 (GAS → 19개 분석 탭) ← 이번 사고의 진짜 원인

| 항목 | 내용 |
|---|---|
| **확인 완료** | Apps Script 트리거 화면(스크린샷) = 시간 기반 트리거 미설정, 시트 분석 탭 raw 값 직접 fetch |
| **미확인** | GAS `.gs` 코드 본문 — 시트 안 Apps Script 에디터에만 존재. repo 백업 없음(단일 실패점) |
| **발견된 문제** | (a) 시간 트리거 자체가 설정 안 됨 → 6일 무가동 (b) GAS 코드가 repo에 없어 시트 손상·권한 변경 시 영구 손실 (c) Google 정책상 GAS는 또 죽을 수 있음 (90일 권한 만료·6분 한도·연속 실패 자동 비활성화) |
| **해결안** | (a) GAS 코드 git 백업이 **가장 먼저** — `scripts/gas/repurchase_v5_4.gs` (b) 트리거 매일 08:45 KST로 재설정 + 권한 재승인 (c) Phase 2에서 Python이 같은 계산을 독립 수행하는 백업 모듈 작성 → GAS 죽어도 대체 |

### 3단계 — 발송 (분석 탭 → 텔레그램·이메일)

| 항목 | 내용 |
|---|---|
| **확인 완료** | `repurchase_report.py:1397 run()` 흐름, `report_telegram_brief.py` 발송 로직(실패 시 ops 알림 정상), `report_email_daily.py` Anthropic 401 fallback |
| **미확인** | `.env`의 `EMAIL_TO` 실제 값 — ohkm8050@naver.com(정부지원)인지 osh805050@gmail.com(개인)인지 |
| **발견된 문제** | (a) 시트가 stale이어도 같은 숫자 그대로 발송 (stale 체크 0건) — 6일 사고의 직접 원인 (b) 이메일은 Anthropic API 실패만 ops 알림 — 다른 실패(SMTP·수신자 거부 등)는 무음 (`report_email_daily.py:376-386`) |
| **해결안** | (a) `repurchase_report.py:run()` 진입 시 staleness 체크 → stale 시 텔레그램·이메일 prefix에 `[⚠️ 시트 멈춤 — N일 전 데이터]` (b) Phase 2 fallback 활성화 후엔 Python 재계산 결과로 자동 대체 (c) 이메일 발송 실패 시 ops 알림 1건 추가 |

---

## 단계별 해결 로드맵 (3주)

### Phase 1 — 오늘 (1.5~2시간 · 응급 처치)

| # | 작업 | 대상 단계 | 효과 |
|---|---|---|---|
| 1-1 | GAS `.gs` 코드 git 백업 (`scripts/gas/repurchase_v5_4.gs` + sha256 README) | 2단계 | 단일 실패점 제거 |
| 1-2 | Apps Script 시간 트리거 재설정(매일 08:45 KST) + 수동 1회 실행 | 2단계 | 오늘 시트 즉시 정상화 |
| 1-3 | `pipeline_meta` 시트 탭 신설 + **writer별 row 분리** (아래 구조 참조) | 1·2·3 공통 | 각 단계가 자기 row만 기록 — GAS row 없으면 stale |
| 1-4 | `lib/sheet_staleness.py` (3-state: fresh/stale/unknown, **GAS row 기준**으로만 2단계 freshness 판단) + ops 채널 알림 + alert dedup (`data/alert_state.json`) | 1·2 감지 | 24h 안 멈춤 자각 |
| 1-5 | `sheets_sync.py` main() 끝에 실패 알림 추가 | 1단계 | silent failure 제거 |
| 1-6 | Vultr cron 주말 포함 (`1-5` → `*`) + `docs/deploy-repurchase-cron.md` 동기화 | 1·3 | 토·일 누락 제거 |
| 1-7 | `report_email_daily.py:376-386` 최상위 except에 ops 채널 알림 추가 + `repurchase_report.run()`에서 `email_main()` return code 확인 | 3단계 | 이메일 silent failure 제거 |

**`pipeline_meta` writer별 row 구조** (Codex High 결함 반영):

| 컬럼 | sheets_sync row | GAS row | reporter row |
|---|---|---|---|
| `run_id` | `sync_2026-05-12_083001` | `gas_2026-05-12_084523` | `report_2026-05-12_090012` |
| `writer` | `sheets_sync` | `gas` | `reporter` |
| `status` | `success`/`fail` | `success`/`fail` | `success`/`fail` |
| `finished_at` | 동기화 완료 시각 | **19탭 모두 완료 후** | 발송 완료 시각 |
| `source_rows_*` | 카페24·SS 행수 | — | — |
| `output_tab_count` | — | 갱신된 탭 수(19) | — |

→ `sheet_staleness.py`는 **`writer=gas`인 최신 row**의 `run_id`가 오늘 날짜이고 `status=success`인지만 확인. reporter row는 staleness 판단에 사용하지 않음.
→ **검증**: GAS 트리거 비활성화 상태에서 reporter cron 실행 → `stale` 반환 확인 (not fresh)

**Phase 1 단일 commit 메시지**: `fix(repurchase): GAS 트리거 복구 + pipeline_meta writer 분리 + 3단계 알림 보강`

### Phase 2 — 1주 (검증 · Python 섀도우 계산)

| # | 작업 | 효과 |
|---|---|---|
| 2-1 | `repurchase_recompute.py` — Python이 GAS와 같은 5개 지표 독립 계산 | GAS 결과와 무관한 truth source 확보 |
| 2-2 | 08:55 Vultr cron 실행 + GAS run_id 기반 completion barrier(최대 5분 폴링) | GAS 완료 확인 후에만 비교(race 차단) |
| 2-3 | 메트릭별 허용오차 표 (재구매율 ±2%p / 30·60일 전환율 ±2%p / M+1 ±3%p / P50 ±2일 / 매출 ±3% / 재구매자수 ±2명 절대값 + ±5% 상대값) | unit-blind 10% 게이트 결함 차단 |
| 2-4 | 7일 cross-check + golden fixture 4케이스(2025-12 정상 / 2026-02 광고중단 소규모 / 빈 날 / 취소 100% 날) 통과 시 fallback 활성화 | stale 시 Python 결과 자동 대체 |

### Phase 3 — 2~3주 (이관 · GAS 제거)

| # | 작업 | 효과 |
|---|---|---|
| 3-1 | 핵심 4탭 Python in-place write (atomic swap 금지 — worksheet ID 보존 → Looker Studio 연결 보존) | Looker 차트 깨짐 차단 |
| 3-2 | Dual-write 1주 (GAS = prod, Python = `_python` suffix) + cutover 전 Looker 리허설 | 안전 cutover |
| 3-3 | 3일 100% 일치 시 GAS 시간 트리거 비활성화 + Python prod 단독 | "안 멈춤" 근본 달성 |
| 3-4 | 나머지 15탭 처리(Looker 연결 점검 후 이관 또는 폐기) + GAS 아카이브 | 정리 |

---

## 병렬 실행 가능 여부 (Phase 1 작업 6개)

| 작업 | 병렬 가능? | 이유 |
|---|---|---|
| 1-1. GAS 코드 백업 | **반드시 단독 첫번째** | F4 결함 재발 위험 — 백업 전 트리거 만지면 코드 영구 손실 |
| 1-2. GAS 트리거 재설정 | 1-1 후 / 승현님 UI 작업 | Claude 자동화 불가 (사용자 직접) |
| 1-3. pipeline_meta 탭 코드 | △ 부분 병렬 | sheets_sync.py 수정 — 1-5와 같은 파일 |
| 1-4. lib/sheet_staleness.py | ⭕ 병렬 OK | 신규 파일 — 충돌 0 |
| 1-5. sheets_sync 실패 알림 | △ 부분 병렬 | 1-3과 같은 파일이라 같은 줄 충돌 가능 |
| 1-6. Vultr cron 수정 | ⭕ 병렬 OK | 완전 별개 시스템 |

**충돌 위험 3가지**:
1. **HIGH** — 1-1 빼고 1-2부터 시작 → F4 결함 재발 (GAS 코드 손실 위험)
2. **MEDIUM** — 1-3과 1-5가 sheets_sync.py 같은 줄 동시 수정 → Edit 충돌
3. **LOW** — 1-3 pipeline_meta 첫 생성 시 GAS와 동시 실행 → race condition

**추천 순서**:
```
[step 1] 단독: 1-1 GAS 백업 → git commit
[step 2] 병렬: 1-2 (승현님 UI) || 1-4 staleness.py || 1-6 cron 수정
[step 3] 순차: 1-3 pipeline_meta → 1-5 sheets_sync 알림 (같은 파일이라 묶거나 순차)
```
예상 시간: 1.5~2시간 (전 순차 3~4시간 대비 단축).

---

## 사전 환경 점검 (§자동화점검 hook 반영)

코드 작성 전 5가지 검증 — 작업 도중 막힘 방지:

| # | 점검 | 방법 | 필요 시점 |
|---|---|---|---|
| 1 | `.env` 필수 키 — `GOOGLE_SA_KEY_PATH`, `REPURCHASE_SHEET_ID`, `TELEGRAM_BOT_TOKEN_OPS`, `EMAIL_TO` | 로컬 `.env` grep (마스킹 출력) | 1-3·1-4 작업 직전 |
| 2 | Vultr SSH 접근 가능 | `ssh root@158.247.215.170 "uptime"` | 1-5·1-6 직전 |
| 3 | 실제 crontab 내용 vs `docs/deploy-repurchase-cron.md` 일치 | `ssh ... "crontab -l"` 비교 | 1-6 직전 |
| 4 | Google Service Account `pipeline_meta` 탭 쓰기 권한 | 1-3 코드 작성 후 dry-run | 1-3 작성 직후 |
| 5 | Telegram ops 채널 정상 작동 | 테스트 메시지 1건 발송 | 1-4 작성 직후 |

→ 1·3은 Claude가 즉시 가능. 2·4·5는 작업 첫 단계에서 1회 검증 후 통과 시 진행.

---

## 결함 추적 (Codex adversarial 진화 이력)

| 회차 | 대상 | verdict | 발견 |
|---|---|---|---|
| 1차 (v1, 2회 병렬) | rescue-plan v1 | needs-attention | F1~F5 (5건 — staleness 계약, completion barrier, Looker 보존, 백업 순서, 메트릭 tolerance) |
| 2차 (v2, 2회) | rescue-plan v2 | approve (본문 캡처 짧음) | 0건 — 결함 없어 본문 짧음으로 추정 |
| 3차 (v3, 본 파일) | rescue-plan v3 | **대기 중** | TBD |

**v1→v2 반영**:
- F1: A1 셀 파싱 폐기 → `pipeline_meta` 탭 + 3-state(fresh/stale/unknown)
- F2: 08:55 cross-check에 run_id 기반 completion barrier 추가
- F3: Phase 3 atomic swap 금지 → in-place write로 Looker Studio 차트 보존
- F4: GAS `.gs` 백업이 Phase 1 첫 번째 작업으로 이동
- F5: 메트릭별 허용오차 표 + alert dedup (incident key + 24h cooldown + recovery notification)

**v3 추가 (본 파일)**:
- 3단계 구조 관점에서 점검 — 1·3단계 silent failure 추가 발견(sheets_sync 실패 알림 부재, 이메일 비-Anthropic 실패 무음)
- Phase 1 병렬 실행 가능성 분석 + 추천 순서
- 사전 환경 점검 5가지 체크리스트

---

## Critical files

**신규 (작성)**:
- `lib/sheet_staleness.py` (Phase 1-4)
- `repurchase_recompute.py` (Phase 2-1)
- `scripts/gas/repurchase_v5_4.gs` (Phase 1-1, 가장 먼저)
- `scripts/gas/README.md` (Phase 1-1, sha256 + 줄 수)
- `data/alert_state.json` (Phase 1-4 alert dedup)
- `tests/test_recompute_fixtures.py` (Phase 2-4 golden fixture)
- `scripts/gas/archive/` (Phase 3-4 종료 시점)

**수정**:
- `sheets_sync.py` 끝부분 (Phase 1-5: 실패 알림 + pipeline_meta 기록)
- `repurchase_report.py:1397 run()` (Phase 1-4: staleness 체크 + Phase 2-4: fallback 분기)
- `report_telegram_brief.py` (Phase 3단계: stale prefix 표기)
- `report_email_daily.py:376-386` (Phase 1-5 응용: 이메일 실패 ops 알림 추가)
- `docs/deploy-repurchase-cron.md:82-99` (Phase 1-6: cron 주말 포함)
- Vultr crontab (Phase 1-6: 실제 라인 수정)

**참조 only** (수정 금지):
- `telegram_client.py` (VALID_CHANNELS 상수만 사용)
- `docs/context/infra.md`
- `docs/repurchase_code_reference.md:20-36`

---

## Verification (실행 후 검증)

### Phase 1 끝났을 때
- [ ] `scripts/gas/repurchase_v5_4.gs` git에 존재 + sha256 기록 (1-1 증거)
- [ ] **GAS 비활성화 상태에서 reporter cron 실행 → `stale` 반환** (not fresh) — High 결함 검증
- [ ] 시트 `pipeline_meta` 탭에 오늘 run_id 행 + status=success
- [ ] `python lib/sheet_staleness.py` 단독 실행 → `fresh` 반환
- [ ] 강제 stale 모의 (pipeline_meta 최신 run_id를 `2000-01-01_000000`으로 임시 변조) → `stale` + ops 알림 1건 도착
- [ ] 강제 unknown 모의 (`pipeline_meta` 탭 임시 삭제) → `unknown` + ops 알림 도착 (fail-closed)
- [ ] sheets_sync 강제 실패 모의 (Service Account 키 임시 무효화) → ops 알림 도착
- [ ] SMTP 실패 모의 (잘못된 `EMAIL_TO` 또는 `SMTP_PASSWORD`) → ops 채널 알림 1건 도착 + report 로그에 "email success" 없음 (Medium 결함 검증)
- [ ] Vultr crontab 주말 포함 확인 (`crontab -l | grep -E "(sheets_sync|repurchase_report)"` 출력에 `*` 또는 0-6)
- [ ] 다음날 09:00 cron 결과: `logs/report.log`에 staleness 통과 + 시트 메타 시각 오늘

### Phase 2 끝났을 때
- [ ] 7일 연속 cross-check 통과 로그 (`logs/cross_check_YYYYMMDD.log`)
- [ ] golden fixture 4케이스 통과 (`pytest tests/test_recompute_fixtures.py`)
- [ ] 강제 stale 모의 + fallback 활성화 상태 → Python 결과가 report 채널에 발송 (dry-run)
- [ ] `data/alert_state.json`에 incident key dedup 작동 확인 (같은 day key 중복 발송 0)

### Phase 3 끝났을 때
- [ ] dual-write 3일 100% 일치 로그
- [ ] in-place write 리허설 후 Looker Studio 차트 정상 확인
- [ ] GAS off 전환 후 다음날 `pipeline_meta` 최신 row의 `writer=python`
- [ ] `python repurchase_recompute.py --write` 단독 실행 → 4탭 정상 갱신

---

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| GAS 트리거 다시 죽음 (권한·한도·자동 비활성화) | pipeline_meta staleness 감지 → 24h 안 자각 + Phase 2 Python fallback |
| Python 재계산이 GAS와 수치 차이 (고객ID 정의·취소 처리 등) | 메트릭별 tolerance 표 + 7일 cross-check + golden fixture 4케이스 |
| cross-check race (GAS 늦게 종료) | run_id completion barrier + 5분 폴링 후 gas_run_missing 플래그 |
| Looker Studio 차트 끊김 (Phase 3 cutover) | in-place write (worksheet ID 보존) + cutover 전 staging copy 리허설 |
| GAS 코드 손실 (Phase 1-2 트리거 변경 도중) | 1-1 백업이 Phase 1 **첫 번째** 작업 (단독, 비병렬) |
| alert 스팸 (매일 같은 stale 알림) | incident key dedup + 24h cooldown + recovery notification |
| 카페24/SS 고객ID 정의 차이 (휴대전화 vs ordererId) | 두 채널 분리 집계 + 통합은 합산 노트 |
| cron 주말 누락 (현재 `1-5`) | Phase 1-6 주말 포함으로 변경 |
| sheets_sync silent failure | Phase 1-5 main() 끝 실패 알림 추가 |
| 이메일 비-Anthropic 실패 무음 | Phase 1-5 응용 — report_email_daily.py 376-386 ops 알림 추가 |

---

## 실행 순서 요약 (한 눈에)

```
[사전 점검]
  - .env 키 5개 grep + crontab 실측 (Claude 즉시 가능)

[Phase 1 — 오늘]
  step 1 단독: 1-1 GAS 백업 → commit
  step 2 병렬: 1-2 (승현님 UI) || 1-4 staleness.py || 1-6 cron 수정
  step 3 순차: 1-3 pipeline_meta → 1-5 sheets_sync 알림
  → 단일 commit

[Phase 2 — 1주]
  2-1 recompute.py → 2-2 cross-check cron → 2-3 tolerance → 2-4 fallback 활성화

[Phase 3 — 2~3주]
  3-1 in-place write → 3-2 dual-write + 리허설 → 3-3 GAS off → 3-4 정리
```
