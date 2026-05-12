// ============================================================
// 헤비로버 재구매 분석 모듈 v5.1
// ============================================================
// [v5.1 변경 — Codex/Claude 5회 점검 결과 통합]
//
// 운영 안정성:
//   B-1a. runAll try/catch + GAS-native appendPipelineMeta_()
//   B-1b. 소스 시트·헤더 검증 (없으면 fail-fast + status=fail row)
//
// 수치 정확성 10개:
//   1. 재구매율 분모 dedup — new Set([...new, ...rep]).size
//   2. SS 0원 분석 제외 — sheets_sync.py SS 정가 fallback으로 자동 해결
//   3. isCanceled exact match — allow-list 기반 정상 상태 화이트리스트
//   4. 카페24 amount 누적 — 같은 orderNo 다중 row 합산
//   5. 코호트 30/60/90일 분모 eligible = total - observing
//   6. 기간 재구매율 sales-mix 명시 (분모 dedup으로 부분 해결 + 시트 헤더 라벨)
//   7. 퍼널 maturity window — P50(10일) 미경과 고객 분모 제외
//   8. 통합 식별자 비호환 — 경고 메시지 강화 (옵션 B)
//   9. M+N 현재월 partial — targetMonth >= currentMonth 면 진행중 라벨
//   10. 0일 간격 포함 — calcGaps d >= 0 (같은 날 재구매 포함)
//
// pipeline_meta 헤더 (lib/sheet_staleness.py와 정확히 일치):
//   run_id | writer | status | started_at | finished_at | extra
// ============================================================

const HL = {
  SHEET: {
    CAFE24: '카페24 재구매매출',
    SS:     '스마트스토어 재구매매출',
  },

  // ▼ 카페24: 결제일 기준, 총 상품구매금액 기준
  CAFE24_COL: {
    CUSTOMER: 5,  // 주문자 휴대전화
    DATE:     2,  // 결제일시(입금확인일)
    AMOUNT:   4,  // 총 상품구매금액
    STATUS:   3,  // 주문 상태
    ORDER_NO: 1,  // 주문번호
  },

  SS_COL: {
    CUSTOMER: 9,   // 구매자ID
    DATE:     40,  // 결제일
    AMOUNT:   29,  // 최종 상품별 총 주문금액
    STATUS:   5,   // 주문상태
    ORDER_NO: 2,   // 주문번호
  },

  // [v5.1.1] status 비교 — 블랙리스트 방식 (취소/환불/반품 키워드 포함 시 제외)
  // v5.1 화이트리스트 폐기 이유: 카페24 시트의 raw 상태값이 "배송 완료"(공백 포함)·"배송중"·"취소 완료"·
  //   "입금전 취소 - 관리자" 등 다양했고 화이트리스트가 좁아서 정상 주문 99%가 제외됨 (2026-05-13 발견).
  // 새 규칙: 정규화(trim+공백제거) 후 '취소'·'환불'·'반품' 부분일치 시에만 제외.
  // 부분일치 오탐 (예: "취소가능"이라는 상태가 만약 있다면 정상인데 제외됨)은 현재 카페24/SS 시트
  //   상태값 목록에 존재하지 않으므로 안전. (만약 미래에 그런 상태 추가되면 별도 예외 처리.)
  CANCEL_KEYWORDS: ['취소', '환불', '반품'],

  OUT: {
    CAFE24_D:      '재구매_카페24_일별',
    CAFE24_W:      '재구매_카페24_주별',
    CAFE24_M:      '재구매_카페24_월별',
    SS_D:          '재구매_SS_일별',
    SS_W:          '재구매_SS_주별',
    SS_M:          '재구매_SS_월별',
    ALL_D:         '재구매_통합_일별',
    ALL_W:         '재구매_통합_주별',
    ALL_M:         '재구매_통합_월별',
    COHORT_CAFE24: '코호트_카페24_전환율',
    COHORT_SS:     '코호트_SS_전환율',
    COHORT_ALL:    '코호트_통합_전환율',
    FUNNEL_CAFE24: '구매횟수_퍼널_카페24',
    FUNNEL_SS:     '구매횟수_퍼널_SS',
    FUNNEL_ALL:    '구매횟수_퍼널_통합',
    INTERVAL:      '재구매_간격분석',
    MONTHLY_RET:   '코호트_월별잔존율',
  },

  SHEET_ORDER: [
    // [v5.1] 대시보드 시트는 항상 맨 앞 — repurchase_report.py:758-763이 매일 index=0 적용하므로 GAS reorderSheets()도 이를 존중
    '📊 대시보드',
    '카페24 재구매매출',
    '스마트스토어 재구매매출',
    '재구매_카페24_일별',
    '재구매_카페24_주별',
    '재구매_카페24_월별',
    '재구매_SS_일별',
    '재구매_SS_주별',
    '재구매_SS_월별',
    '재구매_통합_일별',
    '재구매_통합_주별',
    '재구매_통합_월별',
    '코호트_카페24_전환율',
    '코호트_SS_전환율',
    '코호트_통합_전환율',
    '구매횟수_퍼널_카페24',
    '구매횟수_퍼널_SS',
    '구매횟수_퍼널_통합',
    '재구매_간격분석',
    '코호트_월별잔존율',
  ],
};

const COHORT_WINDOWS = [30, 60, 90];
const MAX_MONTHS     = 12;

// [v5.1 #7] 퍼널 maturity window — P50(10일) 기반
// 첫 구매 후 N일 미경과 고객은 다음 단계 전환 기회가 없으므로 분모 제외
const FUNNEL_MATURITY_DAYS = 10;

// pipeline_meta 헤더 (lib/sheet_staleness.py:25 PIPELINE_META_HEADER 정확히 일치)
const PIPELINE_META_TAB = 'pipeline_meta';
const PIPELINE_META_HEADER = ['run_id', 'writer', 'status', 'started_at', 'finished_at', 'extra'];


// ============================================================
// ── [v5.1 B-1a] pipeline_meta writer (GAS-native)
// ============================================================

/**
 * pipeline_meta 탭에 한 row append. lib/sheet_staleness.py의 PIPELINE_META_HEADER와 정확히 일치.
 * 헤더 변경 금지 — Python check_pipeline_freshness()가 컬럼 순서로 파싱.
 */
function appendPipelineMeta_(runId, writer, status, startedAt, finishedAt, extra) {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let ws = ss.getSheetByName(PIPELINE_META_TAB);
    if (!ws) {
      ws = ss.insertSheet(PIPELINE_META_TAB);
      ws.appendRow(PIPELINE_META_HEADER);
    }
    ws.appendRow([runId, writer, status, startedAt, finishedAt, extra || '']);
  } catch (e) {
    Logger.log('⚠️ appendPipelineMeta_ 실패 (무시): ' + e);
  }
}

function _kstNow_() {
  return Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd HH:mm:ss');
}


// ============================================================
// ── 실행 함수 (v5.1: try/catch + pipeline_meta + 소스 검증)
// ============================================================

/**
 * [매일 실행] 전체 업데이트
 * - 시작 시 pipeline_meta에 status=running row
 * - 성공 시 status=success
 * - 실패 시 status=fail + 에러 메시지를 extra에 기록
 * - Python lib/sheet_staleness.py가 writer=gas 최신 row를 보고 freshness 판정
 */
function runAll() {
  // [v5.1 — Codex 점검 반영] run_id는 yyyy-MM-dd로 시작해야 함.
  // lib/sheet_staleness.py check_pipeline_freshness()가 run_id.startswith(today)로 체크.
  // writer 컬럼이 이미 'gas'이므로 prefix 불필요.
  const runId = Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd_HHmmss') + '_gas';
  const startedAt = _kstNow_();
  appendPipelineMeta_(runId, 'gas', 'running', startedAt, '', '');

  try {
    Logger.log('▶ 전체 분석 시작: ' + new Date());

    // [v5.1 B-1b] 소스 시트·헤더 검증 (fail-fast)
    const cafe24Sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(HL.SHEET.CAFE24);
    const ssSheet     = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(HL.SHEET.SS);
    if (!cafe24Sheet && !ssSheet) {
      throw new Error('소스 시트 모두 없음: ' + HL.SHEET.CAFE24 + ', ' + HL.SHEET.SS);
    }
    if (cafe24Sheet) {
      const cafeHeaderLen = cafe24Sheet.getLastColumn();
      if (cafeHeaderLen < 5) {
        throw new Error('카페24 시트 컬럼 부족: ' + cafeHeaderLen + ' < 5');
      }
    }
    if (ssSheet) {
      const ssHeaderLen = ssSheet.getLastColumn();
      if (ssHeaderLen < 40) {
        throw new Error('SS 시트 컬럼 부족: ' + ssHeaderLen + ' < 40');
      }
    }

    const cafe24 = loadCafe24Orders();
    const ss     = loadSSOrders();
    const all    = [...cafe24, ...ss];

    if (all.length === 0) {
      Logger.log('❌ 데이터 없음');
      const finishedAt = _kstNow_();
      appendPipelineMeta_(runId, 'gas', 'fail', startedAt, finishedAt, 'no_data');
      return;
    }
    Logger.log('카페24: ' + cafe24.length + '건 / 스마트스토어: ' + ss.length + '건');

    // 1. 재구매 지표 시트 (일/주/월 × 플랫폼)
    writeRepurchaseSheet(cafe24, HL.OUT.CAFE24_D, 'D', '카페24',      false);
    writeRepurchaseSheet(cafe24, HL.OUT.CAFE24_W, 'W', '카페24',      false);
    writeRepurchaseSheet(cafe24, HL.OUT.CAFE24_M, 'M', '카페24',      false);
    writeRepurchaseSheet(ss,     HL.OUT.SS_D,     'D', '스마트스토어', false);
    writeRepurchaseSheet(ss,     HL.OUT.SS_W,     'W', '스마트스토어', false);
    writeRepurchaseSheet(ss,     HL.OUT.SS_M,     'M', '스마트스토어', false);
    writeRepurchaseSheet(all,    HL.OUT.ALL_D,    'D', '통합',         true);
    writeRepurchaseSheet(all,    HL.OUT.ALL_W,    'W', '통합',         true);
    writeRepurchaseSheet(all,    HL.OUT.ALL_M,    'M', '통합',         true);

    // 2. 코호트 전환율 (30/60/90일) — eligible 분모 적용
    writeCohortSheet(cafe24, HL.OUT.COHORT_CAFE24, '카페24');
    writeCohortSheet(ss,     HL.OUT.COHORT_SS,     '스마트스토어');
    writeCohortSheet(all,    HL.OUT.COHORT_ALL,    '통합');

    // 3. 구매횟수 퍼널 + 단계별 전환율/소요일 — maturity window 적용
    writePurchaseFunnelSheet(cafe24, HL.OUT.FUNNEL_CAFE24, '카페24');
    writePurchaseFunnelSheet(ss,     HL.OUT.FUNNEL_SS,     '스마트스토어');
    writePurchaseFunnelSheet(all,    HL.OUT.FUNNEL_ALL,    '통합');

    // 4. 코호트 월별 잔존율 — 현재월 진행중 라벨
    writeMonthlyRetentionSheet(all);

    // 5. 재구매 간격 분석 — 0일 간격 포함
    writeIntervalSheet(all);

    reorderSheets();

    const finishedAt = _kstNow_();
    appendPipelineMeta_(runId, 'gas', 'success', startedAt, finishedAt, '');
    Logger.log('✅ 전체 완료: ' + new Date());
  } catch (e) {
    const finishedAt = _kstNow_();
    appendPipelineMeta_(runId, 'gas', 'fail', startedAt, finishedAt, String(e));
    Logger.log('❌ runAll 실패: ' + e);
    throw e;
  }
}


// ============================================================
// ── 데이터 로드 (v5.1 #3: isCanceled→VALID_STATUSES allow-list, #4: 카페24 amount 누적)
// ============================================================

function loadCafe24Orders() {
  const sheet = getSheet(HL.SHEET.CAFE24);
  if (!sheet) return [];
  const data     = sheet.getDataRange().getValues();
  const c        = HL.CAFE24_COL;
  const orderMap = {};

  for (let i = 1; i < data.length; i++) {
    const row      = data[i];
    const customer = String(row[c.CUSTOMER - 1] || '').trim().replace(/\D/g, '');
    const rawDate  = row[c.DATE - 1];
    const amount   = Number(String(row[c.AMOUNT - 1]).replace(/[^0-9.-]/g, ''));
    const status   = String(row[c.STATUS - 1] || '').trim();
    const orderNo  = String(row[c.ORDER_NO - 1] || '').trim();

    if (!customer || !rawDate || !orderNo) continue;
    // [v5.1.1] 블랙리스트 방식 — 정규화(공백 제거) 후 취소/환불/반품 포함 시 제외
    if (isCanceledStatus_(status)) continue;
    const orderDate = parseDate(rawDate);
    if (!orderDate) continue;

    const amt = isNaN(amount) ? 0 : amount;

    // [v5.1 #4 — Codex 점검 반영] 카페24는 첫 row만 저장 (v5_0 동작 유지)
    // 이유: sheets_sync.py:290이 `[row] * n` 으로 item 개수만큼 row 복제하는데
    //       각 row의 amount는 order-level 동일값 (item-level 아님).
    //       누적하면 3-item 주문 50,000원 → 150,000원으로 부풀려짐.
    // 0원 주문도 구매 이력으로 인정 (쿠폰/적립금 전액 사용 — sheets_sync.py fallback이 정가 채움)
    if (!orderMap[orderNo]) {
      orderMap[orderNo] = { customer, orderDate, amount: amt, platform: 'cafe24', orderNo };
    }
  }

  return Object.values(orderMap)
    .sort((a, b) => a.orderDate - b.orderDate);
}

function loadSSOrders() {
  const sheet = getSheet(HL.SHEET.SS);
  if (!sheet) return [];
  const data     = sheet.getDataRange().getValues();
  const c        = HL.SS_COL;
  const orderMap = {};

  for (let i = 1; i < data.length; i++) {
    const row      = data[i];
    const customer = String(row[c.CUSTOMER - 1] || '').trim();
    const rawDate  = row[c.DATE - 1];
    const amount   = Number(String(row[c.AMOUNT - 1]).replace(/[^0-9.-]/g, ''));
    const status   = String(row[c.STATUS - 1] || '').trim();
    const orderNo  = String(row[c.ORDER_NO - 1] || '').trim();

    if (!customer || !rawDate || !orderNo) continue;
    // [v5.1.1] 블랙리스트 방식 — 정규화(공백 제거) 후 취소/환불/반품 포함 시 제외
    if (isCanceledStatus_(status)) continue;
    const orderDate = parseDate(rawDate);
    if (!orderDate) continue;

    if (!orderMap[orderNo]) {
      orderMap[orderNo] = { customer, orderDate, amount: 0, platform: 'ss', orderNo };
    }
    orderMap[orderNo].amount += isNaN(amount) ? 0 : amount;
  }

  // [v5.1 #2] sheets_sync.py가 정가 fallback 적용했으므로 100% 할인 주문도 amount > 0
  // 그래도 안전을 위해 amount > 0 유지 (음수 등 이상치 차단)
  return Object.values(orderMap).filter(o => o.amount > 0)
    .sort((a, b) => a.orderDate - b.orderDate);
}


// ============================================================
// ── 재구매 지표 시트 (v5.1 #1: 분모 dedup, #6: sales-mix 명시, #8: 통합 경고 강화)
// ============================================================

function writeRepurchaseSheet(orders, sheetName, period, platformLabel, isUnified) {
  if (!orders || orders.length === 0) return;

  const globalHistory = buildHistory(orders);
  Object.values(globalHistory).forEach(list =>
    list.sort((a, b) => a.orderDate - b.orderDate));

  const buckets    = buildBuckets(orders, period);
  const sortedKeys = Object.keys(buckets).sort();

  const rows = sortedKeys.map(key => {
    const bucketOrders   = buckets[key];
    let repurchaseRev    = 0;
    let repurchaseOrders = 0;
    let newRevenue       = 0;
    const repurchaseCust = new Set();
    const newCust        = new Set();

    bucketOrders.forEach(order => {
      const allOrders  = globalHistory[order.customer] || [];
      const orderIndex = allOrders.findIndex(
        o => o.orderDate.getTime() === order.orderDate.getTime() &&
             o.orderNo === order.orderNo
      );
      if (orderIndex <= 0) {
        newRevenue += order.amount;
        newCust.add(order.customer);
      } else {
        repurchaseRev += order.amount;
        repurchaseOrders++;
        repurchaseCust.add(order.customer);
      }
    });

    const repurchaseCustCnt = repurchaseCust.size;
    // [v5.1 #1] 분모 dedup — 같은 버킷 신규+재구매 동일 고객은 1명으로 카운트
    const totalCust = new Set([...newCust, ...repurchaseCust]).size;
    const aov      = repurchaseOrders > 0
                     ? Math.round(repurchaseRev / repurchaseOrders) : 0;
    const freq     = repurchaseCustCnt > 0
                     ? Math.round((repurchaseOrders / repurchaseCustCnt) * 10) / 10 : 0;
    const repRate  = totalCust > 0
                     ? Math.round(repurchaseCustCnt / totalCust * 1000) / 10 : 0;

    return [key, repurchaseCustCnt, repurchaseOrders, repurchaseRev,
            aov, freq, repRate, newCust.size, newRevenue];
  });

  const sheet       = getOrCreateSheet(sheetName);
  const periodLabel = { D: '일별', W: '주별', M: '월별' }[period];
  const updatedAt   = Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd HH:mm');

  sheet.clearContents();
  sheet.clearFormats();

  sheet.getRange(1, 1)
       .setValue('📈 재구매 | ' + platformLabel + ' | ' + periodLabel)
       .setFontWeight('bold').setFontSize(12);
  sheet.getRange(1, 6)
       .setValue('업데이트: ' + updatedAt)
       .setFontColor('#888888').setFontSize(10);

  const dataStartRow = isUnified ? 4 : 3;
  if (isUnified) {
    // [v5.1 #8] 통합 식별자 경고 강화 (옵션 B)
    sheet.getRange(2, 1, 1, 9).merge()
         .setValue('⚠️ 통합 수치 부정확 가능: 카페24(휴대전화)와 SS(구매자ID)의 식별 체계가 달라 동일 고객이 양 채널에서 구매 시 2명으로 중복 카운트됩니다. 통합 재구매율·재구매자수는 실제보다 부풀려질 수 있으니 의사결정 시 카페24·SS 각각의 수치를 참조하세요.')
         .setFontColor('#b71c1c').setFontStyle('italic')
         .setFontSize(10).setBackground('#fce4ec').setWrap(true);
  }

  // [v5.1 #6] 기간 재구매율은 cohort 기반 재구매율 아닌 "그 기간 sales-mix" 지표
  // 헤더에 명시해 잘못된 의사결정 방지
  sheet.getRange(dataStartRow, 1, 1, 9)
       .setValues([['기간', '재구매자수', '재구매건수', '재구매매출(원)',
                    'AOV(원)', '재구매빈도', '재구매율%(sales-mix)', '신규구매자수', '신규매출(원)']])
       .setFontWeight('bold').setBackground('#1a73e8')
       .setFontColor('#ffffff').setHorizontalAlignment('center').setFontSize(10);

  const colWidths = [period === 'D' ? 100 : 85, 80, 80, 110, 90, 80, 130, 90, 110];
  colWidths.forEach((w, i) => sheet.setColumnWidth(i + 1, w));

  if (rows.length > 0) {
    const dr = dataStartRow + 1;
    sheet.getRange(dr, 1, rows.length, 9).setValues(rows).setFontSize(10);
    sheet.getRange(dr, 2, rows.length, 3).setNumberFormat('#,##0');
    sheet.getRange(dr, 5, rows.length, 1).setNumberFormat('#,##0');
    sheet.getRange(dr, 6, rows.length, 1).setNumberFormat('0.0');
    sheet.getRange(dr, 7, rows.length, 1).setNumberFormat('0.0"%"');
    sheet.getRange(dr, 8, rows.length, 1).setNumberFormat('#,##0');
    sheet.getRange(dr, 9, rows.length, 1).setNumberFormat('#,##0');
    sheet.getRange(dr, 1, rows.length, 9).setHorizontalAlignment('center');

    for (let i = 0; i < rows.length; i++) {
      if (i % 2 === 0) sheet.getRange(dr + i, 1, 1, 9).setBackground('#f8f9fa');
    }
    sheet.getRange(dr + rows.length - 1, 1, 1, 9)
         .setBackground('#e8f5e9').setFontWeight('bold');
  }

  sheet.setFrozenRows(dataStartRow);
  Logger.log('✅ ' + sheetName + ': ' + rows.length + '행');
}


// ============================================================
// ── 코호트 전환율 시트 (v5.1 #5: eligible 분모)
// ============================================================

function writeCohortSheet(orders, sheetName, platformLabel) {
  if (!orders || orders.length === 0) return;

  const today   = new Date();
  const history = buildHistory(orders);
  Object.values(history).forEach(list =>
    list.sort((a, b) => a.orderDate - b.orderDate));

  const master = {};
  Object.entries(history).forEach(([custId, custOrders]) => {
    const firstDate      = custOrders[0].orderDate;
    const secondOrder    = custOrders.length >= 2 ? custOrders[1] : null;
    const cohortMonth    = fmt(firstDate, 'yyyy-MM');
    const secondDate     = secondOrder ? secondOrder.orderDate : null;
    const daysToSecond   = secondDate
      ? Math.round((secondDate - firstDate) / 86400000) : null;
    const daysSinceFirst = Math.round((today - firstDate) / 86400000);

    const conv = {};
    COHORT_WINDOWS.forEach(w => {
      conv['c' + w] = daysToSecond !== null && daysToSecond <= w;
      conv['o' + w] = daysToSecond === null && daysSinceFirst < w;
    });
    master[custId] = { cohortMonth, ...conv };
  });

  const cohortMap = {};
  Object.values(master).forEach(c => {
    if (!cohortMap[c.cohortMonth]) {
      cohortMap[c.cohortMonth] = { total: 0 };
      COHORT_WINDOWS.forEach(w => {
        cohortMap[c.cohortMonth]['c' + w] = 0;
        cohortMap[c.cohortMonth]['o' + w] = 0;
      });
    }
    cohortMap[c.cohortMonth].total++;
    COHORT_WINDOWS.forEach(w => {
      if (c['c' + w]) cohortMap[c.cohortMonth]['c' + w]++;
      if (c['o' + w]) cohortMap[c.cohortMonth]['o' + w]++;
    });
  });

  const sortedMonths = Object.keys(cohortMap).sort();
  const sheet        = getOrCreateSheet(sheetName);
  const updatedAt    = Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd HH:mm');

  sheet.clearContents();
  sheet.clearFormats();

  sheet.getRange(1, 1).setValue('📊 코호트 전환율 | ' + platformLabel)
       .setFontWeight('bold').setFontSize(12);
  sheet.getRange(1, 7).setValue('업데이트: ' + updatedAt)
       .setFontColor('#888888').setFontSize(10);
  // [v5.1 #5] 분모 정의 명시 — eligible = total - observing
  sheet.getRange(2, 1, 1, 11).merge()
       .setValue('🔧 분모 = 첫구매자수 − 관찰중(아직 N일 미경과) | ⏳ 관찰중 표시는 별도 컬럼 | ✅ = 확정')
       .setFontColor('#0d47a1').setBackground('#e3f2fd').setFontSize(10).setFontStyle('italic');

  sheet.getRange(3, 1, 1, 11)
       .setValues([['코호트월', '첫구매자수',
                    '30일 전환수', '30일 전환율(eligible)', '30일 관찰중',
                    '60일 전환수', '60일 전환율(eligible)', '60일 관찰중',
                    '90일 전환수', '90일 전환율(eligible)', '90일 관찰중']])
       .setFontWeight('bold').setBackground('#1a73e8')
       .setFontColor('#ffffff').setHorizontalAlignment('center')
       .setFontSize(10).setWrap(false);

  sheet.getRange(3, 3, 1, 3).setBackground('#1565c0');
  sheet.getRange(3, 6, 1, 3).setBackground('#0d47a1');
  sheet.getRange(3, 9, 1, 3).setBackground('#1565c0');

  [90, 80, 85, 110, 60, 85, 110, 60, 85, 110, 60].forEach((w, i) =>
    sheet.setColumnWidth(i + 1, w));

  const rows = sortedMonths.map(month => {
    const d   = cohortMap[month];
    const row = [month, d.total];
    COHORT_WINDOWS.forEach(w => {
      // [v5.1 #5] eligible = total - observing
      const eligible = d.total - d['o' + w];
      // [v5.1 patch v2] partial 판정 완화 — observing=0이면 시간 다 지난 확정 데이터
      // (옛 코호트는 첫구매자 적어도 시간 충분히 경과 → 신뢰 가능)
      // partial = "아직 관찰중인 멤버가 있고, 표본 부족 OR 관찰중 비율 높음"
      let partial = false;
      if (d['o' + w] > 0) {
        partial = eligible < 30 || (d.total > 0 && d['o' + w] / d.total > 0.5);
      }
      const rate = (!partial && eligible > 0)
        ? Math.round(d['c' + w] / eligible * 1000) / 10
        : null;
      const observingLabel = d['o' + w] > 0 ? '⏳ ' + d['o' + w] : '✅';
      const rateCell = partial ? '⏳ 관찰중' : (rate !== null ? rate : '—');
      row.push(d['c' + w], rateCell, observingLabel);
    });
    return row;
  });

  if (rows.length > 0) {
    const dr = 4;
    sheet.getRange(dr, 1, rows.length, 11).setValues(rows)
         .setFontSize(10).setHorizontalAlignment('center');
    sheet.getRange(dr, 2, rows.length, 1).setNumberFormat('#,##0');
    [3, 6, 9].forEach(col => {
      sheet.getRange(dr, col, rows.length, 1).setNumberFormat('#,##0');
      sheet.getRange(dr, col + 1, rows.length, 1).setNumberFormat('0.0"%"');
    });
    for (let i = 0; i < rows.length; i++) {
      const hasObs = [5, 8, 11].some(col => String(rows[i][col - 1]).startsWith('⏳'));
      sheet.getRange(dr + i, 1, 1, 11)
           .setBackground(hasObs ? '#fff8e1' : (i % 2 === 0 ? '#f8f9fa' : '#ffffff'));
    }
    sheet.getRange(dr + rows.length - 1, 1, 1, 11)
         .setFontWeight('bold').setBackground('#e8f5e9');
  }

  sheet.setFrozenRows(3);
  Logger.log('✅ ' + sheetName + ': ' + sortedMonths.length + '개 코호트');
}


// ============================================================
// ── 구매횟수 퍼널 시트 (v5.1 #7: maturity window)
// ============================================================

function writePurchaseFunnelSheet(orders, sheetName, platformLabel) {
  if (!orders || orders.length === 0) return;

  const today = new Date();
  const history = buildHistory(orders);
  Object.values(history).forEach(list =>
    list.sort((a, b) => a.orderDate - b.orderDate));

  // ── 고객별 구매 횟수 + 첫구매일
  const custPurchaseCnt = {};
  const custFirstDate   = {};
  Object.entries(history).forEach(([custId, list]) => {
    custPurchaseCnt[custId] = list.length;
    custFirstDate[custId]   = list[0].orderDate;
  });

  const totalCust = Object.keys(custPurchaseCnt).length;
  const cnt1      = Object.values(custPurchaseCnt).filter(n => n === 1).length;
  const cnt2      = Object.values(custPurchaseCnt).filter(n => n === 2).length;
  const cnt3      = Object.values(custPurchaseCnt).filter(n => n === 3).length;
  const cnt4plus  = Object.values(custPurchaseCnt).filter(n => n >= 4).length;

  // [v5.1 #7] maturity window 적용 — 첫구매 후 FUNNEL_MATURITY_DAYS 미경과 고객 분모 제외
  // 1→2: 첫구매 10일 미경과 고객은 재구매 기회가 없으므로 1회만 한 게 아니라 "아직 관찰중"
  let observing12 = 0;  // 1회 구매 중 첫구매 10일 미경과
  Object.entries(history).forEach(([custId, list]) => {
    if (list.length !== 1) return;
    const daysSince = Math.round((today - list[0].orderDate) / 86400000);
    if (daysSince < FUNNEL_MATURITY_DAYS) observing12++;
  });

  // 2→3, 3→4도 동일: 마지막 구매 후 10일 미경과면 다음 단계 관찰중
  let observing23 = 0;
  let observing34 = 0;
  Object.entries(history).forEach(([custId, list]) => {
    if (list.length === 2) {
      const daysSince = Math.round((today - list[1].orderDate) / 86400000);
      if (daysSince < FUNNEL_MATURITY_DAYS) observing23++;
    } else if (list.length === 3) {
      const daysSince = Math.round((today - list[2].orderDate) / 86400000);
      if (daysSince < FUNNEL_MATURITY_DAYS) observing34++;
    }
  });

  // ── 단계별 소요일 계산
  const gapsByStage = { '1→2': [], '2→3': [], '3→4': [] };

  Object.values(history).forEach(list => {
    if (list.length >= 2) {
      gapsByStage['1→2'].push(
        Math.round((list[1].orderDate - list[0].orderDate) / 86400000)
      );
    }
    if (list.length >= 3) {
      gapsByStage['2→3'].push(
        Math.round((list[2].orderDate - list[1].orderDate) / 86400000)
      );
    }
    if (list.length >= 4) {
      gapsByStage['3→4'].push(
        Math.round((list[3].orderDate - list[2].orderDate) / 86400000)
      );
    }
  });

  // [v5.1 #7] 분모 eligible = total - observing
  const stageData = [
    {
      label:       '1→2',
      converted:   cnt2 + cnt3 + cnt4plus,
      eligible:    totalCust - observing12,
      observing:   observing12,
      gaps:        gapsByStage['1→2'],
    },
    {
      label:       '2→3',
      converted:   cnt3 + cnt4plus,
      eligible:    (cnt2 + cnt3 + cnt4plus) - observing23,
      observing:   observing23,
      gaps:        gapsByStage['2→3'],
    },
    {
      label:       '3→4',
      converted:   cnt4plus,
      eligible:    (cnt3 + cnt4plus) - observing34,
      observing:   observing34,
      gaps:        gapsByStage['3→4'],
    },
  ];

  // ── 월별 코호트 추이 (maturity window 적용 — stage와 동일 로직)
  const cohortFunnel = {};
  Object.entries(history).forEach(([custId, list]) => {
    const cohortMonth = fmt(list[0].orderDate, 'yyyy-MM');
    if (!cohortFunnel[cohortMonth]) {
      cohortFunnel[cohortMonth] = {
        total: 0,
        observing12: 0,  // 1회 구매 + 첫구매 10일 미경과 (1→2 분모에서 제외)
        observing23: 0,  // [v5.1 Codex cycle 1] 2회 구매 + 두번째 구매 10일 미경과 (2→3 분모에서 제외)
        converted12: 0, gaps12: [],
        converted23: 0, gaps23: [],
      };
    }
    const d = cohortFunnel[cohortMonth];
    d.total++;
    const daysSinceFirst = Math.round((today - list[0].orderDate) / 86400000);
    if (list.length === 1 && daysSinceFirst < FUNNEL_MATURITY_DAYS) {
      d.observing12++;
    }
    // 2회 구매했지만 두번째 구매 10일 미경과 — 2→3 분모에서 제외 (stage 로직과 동일)
    if (list.length === 2) {
      const daysSinceSecond = Math.round((today - list[1].orderDate) / 86400000);
      if (daysSinceSecond < FUNNEL_MATURITY_DAYS) d.observing23++;
    }

    if (list.length >= 2) {
      d.converted12++;
      d.gaps12.push(Math.round((list[1].orderDate - list[0].orderDate) / 86400000));
    }
    if (list.length >= 3) {
      d.converted23++;
      d.gaps23.push(Math.round((list[2].orderDate - list[1].orderDate) / 86400000));
    }
  });

  const sortedMonths = Object.keys(cohortFunnel).sort();

  // ── 시트 출력
  const sheet     = getOrCreateSheet(sheetName);
  const updatedAt = Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd HH:mm');

  sheet.clearContents();
  sheet.clearFormats();

  sheet.getRange(1, 1)
       .setValue('🛒 구매횟수 퍼널 | ' + platformLabel)
       .setFontWeight('bold').setFontSize(13);
  sheet.getRange(1, 6)
       .setValue('업데이트: ' + updatedAt)
       .setFontColor('#888888').setFontSize(10);

  // 섹션1: 전체 요약
  const SEC1_ROW = 3;

  sheet.getRange(SEC1_ROW, 1, 1, 6).merge()
       .setValue('■ 전체 구매횟수 분포 (누적)')
       .setFontWeight('bold').setFontSize(11)
       .setBackground('#e8eaf6').setFontColor('#1a237e');

  sheet.getRange(SEC1_ROW + 1, 1, 1, 6)
       .setValues([['구분', '고객수', '비율', '누적고객수', '누적비율', '설명']])
       .setFontWeight('bold').setBackground('#1a73e8')
       .setFontColor('#ffffff').setHorizontalAlignment('center').setFontSize(10);

  const pct = (n) => totalCust > 0 ? Math.round(n / totalCust * 1000) / 10 : 0;
  const summaryRows = [
    ['1회만 구매 (이탈)',  cnt1,     pct(cnt1),                  cnt1,                   pct(cnt1),                  '재구매 없이 이탈한 고객'],
    ['2회 구매',          cnt2,     pct(cnt2),                  cnt2 + cnt3 + cnt4plus, pct(cnt2 + cnt3 + cnt4plus), '1회 재구매 후 이탈'],
    ['3회 구매',          cnt3,     pct(cnt3),                  cnt3 + cnt4plus,        pct(cnt3 + cnt4plus),        '2회 재구매 후 이탈'],
    ['4회 이상 (단골)',    cnt4plus, pct(cnt4plus),              cnt4plus,               pct(cnt4plus),               '3회 이상 재구매 단골'],
    ['합계',              totalCust, 100.0,                     '-',                    '-',                         ''],
  ];

  sheet.getRange(SEC1_ROW + 2, 1, summaryRows.length, 6).setValues(summaryRows).setFontSize(10);
  sheet.getRange(SEC1_ROW + 2, 2, summaryRows.length - 1, 1).setNumberFormat('#,##0');
  sheet.getRange(SEC1_ROW + 2, 3, summaryRows.length - 1, 1).setNumberFormat('0.0"%"');
  sheet.getRange(SEC1_ROW + 2, 4, summaryRows.length - 2, 1).setNumberFormat('#,##0');
  sheet.getRange(SEC1_ROW + 2, 5, summaryRows.length - 2, 1).setNumberFormat('0.0"%"');
  sheet.getRange(SEC1_ROW + 2, 1, summaryRows.length, 6).setHorizontalAlignment('center');

  sheet.getRange(SEC1_ROW + 2, 1, 1, 6).setBackground('#ffcdd2').setFontColor('#b71c1c');
  sheet.getRange(SEC1_ROW + 5, 1, 1, 6).setBackground('#c8e6c9').setFontColor('#1b5e20');
  sheet.getRange(SEC1_ROW + 6, 1, 1, 6).setFontWeight('bold').setBackground('#f5f5f5');

  // 섹션2: 단계별 전환율 + 소요일 + maturity
  const SEC2_ROW = SEC1_ROW + summaryRows.length + 3;

  sheet.getRange(SEC2_ROW, 1, 1, 8).merge()
       .setValue('■ 단계별 전환율 + 재구매까지 소요일 (분모=eligible, ' + FUNNEL_MATURITY_DAYS + '일 미경과 관찰중 제외)')
       .setFontWeight('bold').setFontSize(11)
       .setBackground('#e8eaf6').setFontColor('#1a237e');

  sheet.getRange(SEC2_ROW + 1, 1, 1, 8)
       .setValues([['단계', '기준(eligible)', '관찰중', '전환고객수', '전환율', '평균소요일', '중앙값소요일', '해석']])
       .setFontWeight('bold').setBackground('#1a73e8')
       .setFontColor('#ffffff').setHorizontalAlignment('center').setFontSize(10);

  const stageRows = stageData.map(s => {
    // [v5.1 patch v2] partial 판정 — observing>0일 때만 가드. observing=0이면 확정.
    const baseTotal = s.eligible + s.observing;
    let partial = false;
    if (s.observing > 0) {
      partial = s.eligible < 30 || (baseTotal > 0 && s.observing / baseTotal > 0.5);
    }
    const rate    = (!partial && s.eligible > 0)
                    ? Math.round(s.converted / s.eligible * 1000) / 10
                    : null;
    const sorted  = s.gaps.slice().sort((a, b) => a - b);
    const avgDay  = sorted.length > 0
                    ? Math.round(sorted.reduce((a, b) => a + b, 0) / sorted.length) : '-';
    const medDay  = sorted.length > 0
                    ? sorted[Math.floor(sorted.length / 2)] : '-';

    let interpretation = '-';
    if (!partial && rate !== null) {
      if (rate >= 40) interpretation = '우수';
      else if (rate >= 25) interpretation = '양호';
      else if (rate >= 15) interpretation = '개선필요';
      else interpretation = '위험';
    } else if (partial) {
      interpretation = '⏳ 관찰중';
    }

    const rateCell = partial ? '⏳ 관찰중' : (rate !== null ? rate : '-');
    return [s.label, s.eligible, s.observing, s.converted, rateCell, avgDay, medDay, interpretation];
  });

  sheet.getRange(SEC2_ROW + 2, 1, stageRows.length, 8).setValues(stageRows).setFontSize(10);
  sheet.getRange(SEC2_ROW + 2, 2, stageRows.length, 3).setNumberFormat('#,##0');
  sheet.getRange(SEC2_ROW + 2, 5, stageRows.length, 1).setNumberFormat('0.0"%"');
  sheet.getRange(SEC2_ROW + 2, 1, stageRows.length, 8).setHorizontalAlignment('center');

  stageRows.forEach((row, i) => {
    const cell = sheet.getRange(SEC2_ROW + 2 + i, 8);
    const val  = row[7];
    if      (val === '우수')    cell.setBackground('#c8e6c9').setFontColor('#1b5e20');
    else if (val === '양호')    cell.setBackground('#fff9c4').setFontColor('#f57f17');
    else if (val === '개선필요') cell.setBackground('#ffe0b2').setFontColor('#e65100');
    else if (val === '위험')    cell.setBackground('#ffcdd2').setFontColor('#b71c1c');
  });

  // 섹션3: 월별 코호트 추이
  const SEC3_ROW = SEC2_ROW + stageRows.length + 4;

  sheet.getRange(SEC3_ROW, 1, 1, 8).merge()
       .setValue('■ 월별 코호트 1→2 / 2→3 전환율 추이 (eligible 분모)')
       .setFontWeight('bold').setFontSize(11)
       .setBackground('#e8eaf6').setFontColor('#1a237e');

  sheet.getRange(SEC3_ROW + 1, 1, 1, 8)
       .setValues([['코호트월', '첫구매자수', '1→2 관찰중',
                    '1→2 전환수', '1→2 전환율(eligible)', '1→2 평균소요일',
                    '2→3 전환수', '2→3 전환율']])
       .setFontWeight('bold').setBackground('#1a73e8')
       .setFontColor('#ffffff').setHorizontalAlignment('center').setFontSize(10);

  sheet.getRange(SEC3_ROW + 1, 3, 1, 4).setBackground('#1565c0');
  sheet.getRange(SEC3_ROW + 1, 7, 1, 2).setBackground('#0d47a1');

  const trendRows = sortedMonths.map(month => {
    const d          = cohortFunnel[month];
    const eligible12 = d.total - d.observing12;
    // [v5.1 Codex cycle 1] 2→3 분모도 maturity 적용 — stage 로직과 동일
    const eligible23 = d.converted12 - d.observing23;
    // [v5.1 patch v2] partial 판정 — observing>0일 때만 가드 적용
    const partial12  = d.observing12 > 0 && (eligible12 < 30 || (d.total > 0 && d.observing12 / d.total > 0.5));
    const partial23  = d.observing23 > 0 && (eligible23 < 30 || (d.converted12 > 0 && d.observing23 / d.converted12 > 0.5));
    const rate12     = (!partial12 && eligible12 > 0) ? Math.round(d.converted12 / eligible12 * 1000) / 10 : null;
    const rate23     = (!partial23 && eligible23 > 0) ? Math.round(d.converted23 / eligible23 * 1000) / 10 : null;
    const sorted12   = d.gaps12.slice().sort((a, b) => a - b);
    const avg12      = sorted12.length > 0
                       ? Math.round(sorted12.reduce((a, b) => a + b, 0) / sorted12.length) : '-';
    const rate12Cell = partial12 ? '⏳ 관찰중' : (rate12 !== null ? rate12 : '—');
    const rate23Cell = partial23 ? '⏳ 관찰중' : (rate23 !== null ? rate23 : '—');
    return [month, d.total, d.observing12, d.converted12, rate12Cell, avg12, d.converted23, rate23Cell];
  });

  if (trendRows.length > 0) {
    const dr = SEC3_ROW + 2;
    sheet.getRange(dr, 1, trendRows.length, 8).setValues(trendRows).setFontSize(10);
    sheet.getRange(dr, 2, trendRows.length, 3).setNumberFormat('#,##0');
    sheet.getRange(dr, 5, trendRows.length, 1).setNumberFormat('0.0"%"');
    sheet.getRange(dr, 7, trendRows.length, 1).setNumberFormat('#,##0');
    sheet.getRange(dr, 8, trendRows.length, 1).setNumberFormat('0.0"%"');
    sheet.getRange(dr, 1, trendRows.length, 8).setHorizontalAlignment('center');

    for (let i = 0; i < trendRows.length; i++) {
      if (i % 2 === 0) sheet.getRange(dr + i, 1, 1, 8).setBackground('#f8f9fa');
    }
    sheet.getRange(dr + trendRows.length - 1, 1, 1, 8)
         .setBackground('#e8f5e9').setFontWeight('bold');
  }

  [90, 80, 75, 85, 110, 90, 85, 90].forEach((w, i) =>
    sheet.setColumnWidth(i + 1, w));

  sheet.setFrozenRows(1);
  Logger.log('✅ ' + sheetName + ' 완료');
}


// ============================================================
// ── 간격 분석 시트 (v5.1 #10: 0일 간격 포함)
// ============================================================

function writeIntervalSheet(orders) {
  const gaps  = calcGaps(orders).sort((a, b) => a - b);
  const sheet = getOrCreateSheet(HL.OUT.INTERVAL);
  sheet.clearContents(); sheet.clearFormats();

  if (gaps.length === 0) {
    sheet.getRange(1, 1).setValue('재구매 데이터 없음'); return;
  }

  const stats = {
    count: gaps.length,
    mean:  Math.round(gaps.reduce((s, v) => s + v, 0) / gaps.length),
    p50:   pct2(gaps, 50), p75: pct2(gaps, 75),
    p90:   pct2(gaps, 90), p95: pct2(gaps, 95),
  };

  const updatedAt = Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd HH:mm');
  sheet.getRange(1, 1).setValue('📊 재구매 간격 분포 분석 (0일 간격 포함)').setFontWeight('bold').setFontSize(12);
  sheet.getRange(1, 2).setValue('업데이트: ' + updatedAt).setFontColor('#888888').setFontSize(10);
  sheet.setColumnWidth(1, 160); sheet.setColumnWidth(2, 80); sheet.setColumnWidth(3, 220);

  sheet.getRange(3, 1, 1, 3).setValues([['지표', '값', '의미']])
       .setFontWeight('bold').setBackground('#1a73e8').setFontColor('#ffffff').setFontSize(10);

  const summaryRows = [
    ['샘플 수',           stats.count + '건', '2회 이상 구매한 고객의 구매 간격 (0일 포함)'],
    ['평균',              stats.mean  + '일', ''],
    ['중앙값 (P50)',      stats.p50   + '일', '50% 고객이 이 일수 이내 재구매'],
    ['P75',               stats.p75   + '일', '75% 고객이 이 일수 이내 재구매'],
    ['P90 ← CRM 기준',   stats.p90   + '일', '▶ SMS 재구매 유도 발송 기준 추천'],
    ['P95',               stats.p95   + '일', ''],
  ];
  sheet.getRange(4, 1, summaryRows.length, 3).setValues(summaryRows).setFontSize(10);
  sheet.getRange(8, 1, 1, 3).setBackground('#fff8e1').setFontWeight('bold');

  const histStart = 11;
  sheet.getRange(histStart, 1, 1, 3).setValues([['구간', '건수', '비율']])
       .setFontWeight('bold').setBackground('#34a853').setFontColor('#ffffff').setFontSize(10);

  // [v5.1 #10] 0일 구간 추가 — 같은 날 재구매 별도 표시
  const bins   = [0, 30, 60, 90, 120, 180, 365, Infinity];
  const labels = ['0일 (같은 날)', '1~30일', '31~60일', '61~90일', '91~120일', '121~180일', '181~365일', '365일 초과'];
  let prev = -1;
  const histRows = bins.map((b, i) => {
    const cnt = gaps.filter(g => g > prev && g <= b).length;
    prev = b;
    return [labels[i], cnt, Math.round(cnt / gaps.length * 100) + '%'];
  });
  sheet.getRange(histStart + 1, 1, histRows.length, 3).setValues(histRows)
       .setFontSize(10).setHorizontalAlignment('center');
  for (let i = 0; i < histRows.length; i++) {
    if (i % 2 === 0) sheet.getRange(histStart + 1 + i, 1, 1, 3).setBackground('#f8f9fa');
  }
}


// ============================================================
// ── 코호트 월별 잔존율 시트 (v5.1 #9: 현재월 진행중 라벨)
// ============================================================

function writeMonthlyRetentionSheet(orders) {
  if (!orders || orders.length === 0) return;

  const history = buildHistory(orders);

  const cohortCustomers = {};
  Object.entries(history).forEach(([custId, custOrders]) => {
    const sorted      = custOrders.slice().sort((a, b) => a.orderDate - b.orderDate);
    const cohortMonth = fmt(sorted[0].orderDate, 'yyyy-MM');
    if (!cohortCustomers[cohortMonth]) cohortCustomers[cohortMonth] = [];
    cohortCustomers[cohortMonth].push(custId);
  });

  const custMonths = {};
  Object.entries(history).forEach(([custId, custOrders]) => {
    custMonths[custId] = new Set(custOrders.map(o => fmt(o.orderDate, 'yyyy-MM')));
  });

  const sortedCohorts = Object.keys(cohortCustomers).sort();
  const currentMonth  = fmt(new Date(), 'yyyy-MM');
  const sheet         = getOrCreateSheet(HL.OUT.MONTHLY_RET);
  const updatedAt     = Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd HH:mm');

  sheet.clearContents(); sheet.clearFormats();

  sheet.getRange(1, 1)
       .setValue('📊 코호트 월별 잔존율 — N월 신규 고객이 이후 각 달에도 구매했는가')
       .setFontWeight('bold').setFontSize(12);
  sheet.getRange(1, MAX_MONTHS + 4)
       .setValue('업데이트: ' + updatedAt).setFontColor('#888888').setFontSize(10);

  const totalCols = 2 + MAX_MONTHS + 1;
  // [v5.1 #9] 진행중 라벨 명시
  sheet.getRange(2, 1, 1, totalCols).merge()
       .setValue('🟢 30%↑  🟡 20~29%  🟠 10~19%  🔴 10%↓  🔵 진행중(현재월) — 색상·해석 제외  ─ = 미래월')
       .setFontColor('#1565c0').setBackground('#e3f2fd').setFontSize(10).setFontStyle('italic');

  const headerRow = ['코호트월', '첫구매자수'];
  for (let m = 1; m <= MAX_MONTHS; m++) headerRow.push('M+' + m);
  headerRow.push('M+1기준');

  sheet.getRange(3, 1, 1, headerRow.length)
       .setValues([headerRow])
       .setFontWeight('bold').setBackground('#1a73e8')
       .setFontColor('#ffffff').setHorizontalAlignment('center').setFontSize(10);

  sheet.getRange(3, headerRow.length, 1, 1).setBackground('#e65100');

  const dataRows = sortedCohorts.map(cohortMonth => {
    const customers = cohortCustomers[cohortMonth];
    const size      = customers.length;
    const row       = [cohortMonth, size];

    for (let m = 1; m <= MAX_MONTHS; m++) {
      const targetMonth = addMonthsStr(cohortMonth, m);
      if (targetMonth > currentMonth) {
        // 미래월
        row.push('─');
      } else if (targetMonth === currentMonth) {
        // [v5.1 #9] 현재 진행중인 월 — 계산은 하되 별도 마커
        const retained = customers.filter(id =>
          custMonths[id] && custMonths[id].has(targetMonth)
        ).length;
        const rate = Math.round(retained / size * 1000) / 10;
        // 진행중임을 표시하기 위해 별도 형식 (값은 유지하되 마커 prefix)
        row.push('🔵 ' + rate);
      } else {
        // 과거월 — 확정
        const retained = customers.filter(id =>
          custMonths[id] && custMonths[id].has(targetMonth)
        ).length;
        row.push(Math.round(retained / size * 1000) / 10);
      }
    }

    // M+1기준
    const m1 = row[2];
    let m1Final;
    if (m1 === '─' || (typeof m1 === 'string' && m1.startsWith('🔵'))) {
      m1Final = m1;  // 미래월 또는 진행중은 그대로
    } else {
      m1Final = m1;
    }
    row.push(m1Final);
    return row;
  });

  if (dataRows.length > 0) {
    const dr = 4;
    sheet.getRange(dr, 1, dataRows.length, headerRow.length)
         .setValues(dataRows).setFontSize(10).setHorizontalAlignment('center');

    dataRows.forEach((row, i) => {
      for (let m = 1; m <= MAX_MONTHS; m++) {
        const col = m + 2;
        const val = row[m + 1];
        const cell = sheet.getRange(dr + i, col);

        if (val === '─') {
          cell.setBackground('#f5f5f5').setFontColor('#bdbdbd');
        } else if (typeof val === 'string' && val.startsWith('🔵')) {
          // 진행중 — 회색 배경, 색상 해석 제외
          cell.setBackground('#e3f2fd').setFontColor('#1565c0').setFontStyle('italic');
        } else {
          const rate = Number(val);
          cell.setNumberFormat('0.0"%"');
          if      (rate >= 30) { cell.setBackground('#c8e6c9').setFontColor('#1b5e20'); }
          else if (rate >= 20) { cell.setBackground('#fff9c4').setFontColor('#f57f17'); }
          else if (rate >= 10) { cell.setBackground('#ffe0b2').setFontColor('#e65100'); }
          else                 { cell.setBackground('#ffcdd2').setFontColor('#b71c1c'); }
        }
      }

      // M+1기준
      const m1cell = sheet.getRange(dr + i, headerRow.length);
      const m1val  = row[row.length - 1];
      if (m1val === '─' || (typeof m1val === 'string' && m1val.startsWith('🔵'))) {
        if (typeof m1val === 'string' && m1val.startsWith('🔵')) {
          m1cell.setBackground('#e3f2fd').setFontColor('#1565c0').setFontStyle('italic').setFontWeight('bold');
        } else {
          m1cell.setFontColor('#bdbdbd');
        }
      } else {
        m1cell.setNumberFormat('0.0"%"').setFontWeight('bold');
        const r = Number(m1val);
        if      (r >= 30) m1cell.setBackground('#c8e6c9').setFontColor('#1b5e20');
        else if (r >= 20) m1cell.setBackground('#fff9c4').setFontColor('#f57f17');
        else if (r >= 10) m1cell.setBackground('#ffe0b2').setFontColor('#e65100');
        else              m1cell.setBackground('#ffcdd2').setFontColor('#b71c1c');
      }

      if (i % 2 === 0) sheet.getRange(dr + i, 1, 1, 2).setBackground('#f8f9fa');
    });

    sheet.getRange(dr + dataRows.length - 1, 1, 1, headerRow.length).setFontWeight('bold');
  }

  sheet.setColumnWidth(1, 90); sheet.setColumnWidth(2, 80);
  for (let m = 1; m <= MAX_MONTHS; m++) sheet.setColumnWidth(m + 2, 70);
  sheet.setColumnWidth(MAX_MONTHS + 3, 80);
  sheet.setFrozenRows(3);

  Logger.log('✅ ' + HL.OUT.MONTHLY_RET + ' 완료');
}


// ============================================================
// ── 시트 순서 정렬
// ============================================================

function reorderSheets() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  HL.SHEET_ORDER.forEach((name, targetIdx) => {
    const sheet = ss.getSheetByName(name);
    if (!sheet) return;
    try {
      ss.setActiveSheet(sheet);
      ss.moveActiveSheet(targetIdx + 1);
    } catch (e) {
      Logger.log('시트 이동 스킵: ' + name);
    }
  });
  Logger.log('✅ 시트 순서 정렬 완료');
}


// ============================================================
// ── 유틸리티
// ============================================================

/**
 * [v5.1.1] 정규화된 status 문자열에 취소/환불/반품 키워드 포함 시 true.
 * 시트 raw 값이 공백 포함("배송 완료", "취소 완료", "입금전 취소 - 관리자")이라
 * 공백 제거 후 부분일치로 비교.
 */
function isCanceledStatus_(status) {
  const s = String(status || '').replace(/\s+/g, '');
  if (!s) return true; // 빈 상태는 안전하게 제외
  return HL.CANCEL_KEYWORDS.some(kw => s.indexOf(kw) >= 0);
}

function buildHistory(orders) {
  const h = {};
  orders.forEach(o => { if (!h[o.customer]) h[o.customer] = []; h[o.customer].push(o); });
  return h;
}

function buildBuckets(orders, period) {
  const buckets = {};
  orders.forEach(o => {
    let key;
    if      (period === 'D') key = fmt(o.orderDate, 'yyyy-MM-dd');
    else if (period === 'W') key = fmt(weekStart(o.orderDate), 'yyyy-MM-dd') + '(주)';
    else                     key = fmt(o.orderDate, 'yyyy-MM');
    if (!buckets[key]) buckets[key] = [];
    buckets[key].push(o);
  });
  return buckets;
}

function calcGaps(orders) {
  const h = buildHistory(orders); const gaps = [];
  Object.values(h).forEach(list => {
    if (list.length < 2) return;
    list.sort((a, b) => a.orderDate - b.orderDate);
    // [v5.1 #10] 0일 간격 포함 (같은 날 재구매)
    // 단, 동일 orderNo는 이미 loadCafe24Orders/loadSSOrders에서 dedup됨
    for (let i = 1; i < list.length; i++) {
      const d = Math.round((list[i].orderDate - list[i - 1].orderDate) / 86400000);
      if (d >= 0) gaps.push(d);
    }
  });
  return gaps;
}

function pct2(arr, p) {
  if (!arr.length) return 0;
  return arr[Math.max(0, Math.min(Math.ceil((p / 100) * arr.length) - 1, arr.length - 1))];
}

function weekStart(date) {
  const d = new Date(date); const day = d.getDay();
  d.setDate(d.getDate() + (day === 0 ? -6 : 1 - day));
  d.setHours(0, 0, 0, 0); return d;
}

function addMonthsStr(yyyymm, n) {
  const [y, m] = yyyymm.split('-').map(Number);
  const d = new Date(y, m - 1 + n, 1);
  return Utilities.formatDate(d, 'Asia/Seoul', 'yyyy-MM');
}

function fmt(date, format) { return Utilities.formatDate(date, 'Asia/Seoul', format); }

function parseDate(val) {
  if (val instanceof Date && !isNaN(val)) return val;
  const d = new Date(val); return isNaN(d.getTime()) ? null : d;
}

function getSheet(name) {
  const s = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(name);
  if (!s) Logger.log('⚠️ 시트 없음: ' + name);
  return s;
}

function getOrCreateSheet(name) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  return ss.getSheetByName(name) || ss.insertSheet(name);
}
