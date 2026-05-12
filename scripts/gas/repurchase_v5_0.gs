function myFunction() {

}
// ============================================================
// 헤비로버 재구매 분석 모듈 v5.0
// ============================================================
// [v5.0 변경]
// 1. 구매횟수_퍼널 시트 추가
//    → 1회/2회/3회/4회+ 고객수 및 비율
//    → 1→2 / 2→3 / 3→4 전환율 + 평균 소요일
//    → 플랫폼별 (카페24 / SS / 통합)
// 2. 코호트_누적매출, 코호트_누적재구매현황 제거
// 3. 나머지 시트 구조 유지
// ============================================================
// [시트 구조]
// raw데이터 → 재구매(카페24/SS/통합 × 일/주/월)
// → 코호트 전환율(카페24/SS/통합)
// → 구매횟수_퍼널_카페24/SS/통합
// → 재구매_간격분석 → 코호트_월별잔존율
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

  CANCEL: ['취소', '환불', '반품'],

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


// ============================================================
// ── 실행 함수
// ============================================================

/**
 * [매주 실행] 전체 업데이트
 */
function runAll() {
  Logger.log('▶ 전체 분석 시작: ' + new Date());
  const cafe24 = loadCafe24Orders();
  const ss     = loadSSOrders();
  const all    = [...cafe24, ...ss];

  if (all.length === 0) { Logger.log('❌ 데이터 없음'); return; }
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

  // 2. 코호트 전환율 (30/60/90일)
  writeCohortSheet(cafe24, HL.OUT.COHORT_CAFE24, '카페24');
  writeCohortSheet(ss,     HL.OUT.COHORT_SS,     '스마트스토어');
  writeCohortSheet(all,    HL.OUT.COHORT_ALL,    '통합');

  // 3. 구매횟수 퍼널 + 단계별 전환율/소요일
  writePurchaseFunnelSheet(cafe24, HL.OUT.FUNNEL_CAFE24, '카페24');
  writePurchaseFunnelSheet(ss,     HL.OUT.FUNNEL_SS,     '스마트스토어');
  writePurchaseFunnelSheet(all,    HL.OUT.FUNNEL_ALL,    '통합');

  // 4. 코호트 월별 잔존율
  writeMonthlyRetentionSheet(all);

  // 5. 재구매 간격 분석
  writeIntervalSheet(all);

  reorderSheets();
  Logger.log('✅ 전체 완료: ' + new Date());
}


// ============================================================
// ── 데이터 로드
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
    if (isCanceled(status)) continue;
    const orderDate = parseDate(rawDate);
    if (!orderDate) continue;

    if (!orderMap[orderNo]) {
      const amt = isNaN(amount) ? 0 : amount;
      // 0원 주문도 구매 이력으로 인정 (쿠폰/적립금 전액 사용 케이스)
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
    if (isCanceled(status)) continue;
    const orderDate = parseDate(rawDate);
    if (!orderDate) continue;

    if (!orderMap[orderNo]) {
      orderMap[orderNo] = { customer, orderDate, amount: 0, platform: 'ss', orderNo };
    }
    orderMap[orderNo].amount += isNaN(amount) ? 0 : amount;
  }

  return Object.values(orderMap).filter(o => o.amount > 0)
    .sort((a, b) => a.orderDate - b.orderDate);
}


// ============================================================
// ── 재구매 지표 시트
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
    const totalCust         = repurchaseCustCnt + newCust.size;
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
    sheet.getRange(2, 1, 1, 9).merge()
         .setValue('⚠️ 통합: 카페24(휴대전화)/스마트스토어(구매자ID) 식별 체계 달라 동일 고객 중복 가능')
         .setFontColor('#c0392b').setFontStyle('italic')
         .setFontSize(10).setBackground('#fce4ec');
  }

  sheet.getRange(dataStartRow, 1, 1, 9)
       .setValues([['기간', '재구매자수', '재구매건수', '재구매매출(원)',
                    'AOV(원)', '재구매빈도', '재구매율(%)', '신규구매자수', '신규매출(원)']])
       .setFontWeight('bold').setBackground('#1a73e8')
       .setFontColor('#ffffff').setHorizontalAlignment('center').setFontSize(10);

  const colWidths = [period === 'D' ? 100 : 85, 80, 80, 110, 90, 80, 80, 90, 110];
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
// ── 코호트 전환율 시트 (30/60/90일)
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
  sheet.getRange(2, 1, 1, 11).merge()
       .setValue('⏳ 관찰중 = 아직 해당 기간이 안 지남  |  ✅ = 확정된 수치')
       .setFontColor('#e65100').setBackground('#fff3e0').setFontSize(10).setFontStyle('italic');

  sheet.getRange(3, 1, 1, 11)
       .setValues([['코호트월', '첫구매자수',
                    '30일 전환수', '30일 전환율', '30일',
                    '60일 전환수', '60일 전환율', '60일',
                    '90일 전환수', '90일 전환율', '90일']])
       .setFontWeight('bold').setBackground('#1a73e8')
       .setFontColor('#ffffff').setHorizontalAlignment('center')
       .setFontSize(10).setWrap(false);

  sheet.getRange(3, 3, 1, 3).setBackground('#1565c0');
  sheet.getRange(3, 6, 1, 3).setBackground('#0d47a1');
  sheet.getRange(3, 9, 1, 3).setBackground('#1565c0');

  [90, 80, 85, 85, 45, 85, 85, 45, 85, 85, 45].forEach((w, i) =>
    sheet.setColumnWidth(i + 1, w));

  const rows = sortedMonths.map(month => {
    const d   = cohortMap[month];
    const row = [month, d.total];
    COHORT_WINDOWS.forEach(w => {
      const rate = d.total > 0
        ? Math.round(d['c' + w] / d.total * 1000) / 10 : 0;
      row.push(d['c' + w], rate, d['o' + w] > 0 ? '⏳' : '✅');
    });
    return row;
  });

  if (rows.length > 0) {
    const dr = 4;
    sheet.getRange(dr, 1, rows.length, 11).setValues(rows)
         .setFontSize(10).setHorizontalAlignment('center');
    sheet.getRange(dr, 2, rows.length, 1).setNumberFormat('#,##0');
    [3, 6, 9].forEach(col => {
      sheet.getRange(dr, col,     rows.length, 1).setNumberFormat('#,##0');
      sheet.getRange(dr, col + 1, rows.length, 1).setNumberFormat('0.0"%"');
    });
    for (let i = 0; i < rows.length; i++) {
      const hasObs = [4, 7, 10].some(col => rows[i][col - 1] === '⏳');
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
// ── 구매횟수 퍼널 시트 (핵심 신규 기능)
// ============================================================
//
// [시트 구조]
//
// 섹션1. 전체 요약 (현재 누적 기준)
//   1회만 구매 | 2회 구매 | 3회 구매 | 4회 이상 | 합계
//   → 각 구간 고객수 + 비율
//
// 섹션2. 단계별 전환율 + 평균 소요일
//   단계    | 전환자수 | 전환율 | 평균소요일 | 중앙값소요일
//   1→2     | N명      | XX%   | XX일       | XX일
//   2→3     | N명      | XX%   | XX일       | XX일
//   3→4     | N명      | XX%   | XX일       | XX일
//
// 섹션3. 월별 추이 (코호트별 1→2 전환율)
//   월      | 1→2전환율 | 2→3전환율 | 1→2평균소요일
// ============================================================

function writePurchaseFunnelSheet(orders, sheetName, platformLabel) {
  if (!orders || orders.length === 0) return;

  const history = buildHistory(orders);
  Object.values(history).forEach(list =>
    list.sort((a, b) => a.orderDate - b.orderDate));

  // ── 고객별 구매 횟수 집계
  const custPurchaseCnt = {};
  Object.entries(history).forEach(([custId, list]) => {
    custPurchaseCnt[custId] = list.length;
  });

  const totalCust = Object.keys(custPurchaseCnt).length;
  const cnt1      = Object.values(custPurchaseCnt).filter(n => n === 1).length;
  const cnt2      = Object.values(custPurchaseCnt).filter(n => n === 2).length;
  const cnt3      = Object.values(custPurchaseCnt).filter(n => n === 3).length;
  const cnt4plus  = Object.values(custPurchaseCnt).filter(n => n >= 4).length;

  // ── 단계별 소요일 계산
  // 각 고객의 N→N+1 소요일을 배열로 수집
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

  // 전환자수, 전환율, 평균, 중앙값 계산
  // 분모 정의:
  //   1→2: 1회 이상 구매자 전체 (= totalCust)
  //   2→3: 2회 이상 구매자 (= cnt2 + cnt3 + cnt4plus)
  //   3→4: 3회 이상 구매자 (= cnt3 + cnt4plus)
  const stageData = [
    {
      label:       '1→2',
      converted:   cnt2 + cnt3 + cnt4plus,
      base:        totalCust,
      gaps:        gapsByStage['1→2'],
    },
    {
      label:       '2→3',
      converted:   cnt3 + cnt4plus,
      base:        cnt2 + cnt3 + cnt4plus,
      gaps:        gapsByStage['2→3'],
    },
    {
      label:       '3→4',
      converted:   cnt4plus,
      base:        cnt3 + cnt4plus,
      gaps:        gapsByStage['3→4'],
    },
  ];

  // ── 월별 코호트 추이 계산
  const cohortFunnel = {};
  Object.entries(history).forEach(([custId, list]) => {
    const cohortMonth = fmt(list[0].orderDate, 'yyyy-MM');
    if (!cohortFunnel[cohortMonth]) {
      cohortFunnel[cohortMonth] = {
        total: 0,
        converted12: 0, gaps12: [],
        converted23: 0, gaps23: [],
      };
    }
    const d = cohortFunnel[cohortMonth];
    d.total++;

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

  // ── 시트 출력 시작
  const sheet     = getOrCreateSheet(sheetName);
  const updatedAt = Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd HH:mm');

  sheet.clearContents();
  sheet.clearFormats();

  // 타이틀
  sheet.getRange(1, 1)
       .setValue('🛒 구매횟수 퍼널 | ' + platformLabel)
       .setFontWeight('bold').setFontSize(13);
  sheet.getRange(1, 6)
       .setValue('업데이트: ' + updatedAt)
       .setFontColor('#888888').setFontSize(10);

  // ────────────────────────────────────────────────
  // 섹션1: 전체 요약
  // ────────────────────────────────────────────────
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

  // 1회 이탈 행 강조 (빨강)
  sheet.getRange(SEC1_ROW + 2, 1, 1, 6).setBackground('#ffcdd2').setFontColor('#b71c1c');
  // 4회 이상 행 강조 (초록)
  sheet.getRange(SEC1_ROW + 5, 1, 1, 6).setBackground('#c8e6c9').setFontColor('#1b5e20');
  // 합계행
  sheet.getRange(SEC1_ROW + 6, 1, 1, 6).setFontWeight('bold').setBackground('#f5f5f5');

  // ────────────────────────────────────────────────
  // 섹션2: 단계별 전환율 + 소요일
  // ────────────────────────────────────────────────
  const SEC2_ROW = SEC1_ROW + summaryRows.length + 3;

  sheet.getRange(SEC2_ROW, 1, 1, 6).merge()
       .setValue('■ 단계별 전환율 + 재구매까지 소요일')
       .setFontWeight('bold').setFontSize(11)
       .setBackground('#e8eaf6').setFontColor('#1a237e');

  sheet.getRange(SEC2_ROW, 7, 1, 1)
       .setValue('※ 소요일: 이전 구매일로부터 다음 구매까지 걸린 일수')
       .setFontColor('#888888').setFontSize(9).setFontStyle('italic');

  sheet.getRange(SEC2_ROW + 1, 1, 1, 7)
       .setValues([['단계', '기준고객수', '전환고객수', '전환율', '평균소요일', '중앙값소요일', '해석']])
       .setFontWeight('bold').setBackground('#1a73e8')
       .setFontColor('#ffffff').setHorizontalAlignment('center').setFontSize(10);

  const stageRows = stageData.map(s => {
    const rate    = s.base > 0 ? Math.round(s.converted / s.base * 1000) / 10 : 0;
    const sorted  = s.gaps.slice().sort((a, b) => a - b);
    const avgDay  = sorted.length > 0
                    ? Math.round(sorted.reduce((a, b) => a + b, 0) / sorted.length) : '-';
    const medDay  = sorted.length > 0
                    ? sorted[Math.floor(sorted.length / 2)] : '-';

    let interpretation = '-';
    if (s.base > 0) {
      if (rate >= 40) interpretation = '우수';
      else if (rate >= 25) interpretation = '양호';
      else if (rate >= 15) interpretation = '개선필요';
      else interpretation = '위험';
    }

    return [s.label, s.base, s.converted, rate, avgDay, medDay, interpretation];
  });

  sheet.getRange(SEC2_ROW + 2, 1, stageRows.length, 7).setValues(stageRows).setFontSize(10);
  sheet.getRange(SEC2_ROW + 2, 2, stageRows.length, 2).setNumberFormat('#,##0');
  sheet.getRange(SEC2_ROW + 2, 4, stageRows.length, 1).setNumberFormat('0.0"%"');
  sheet.getRange(SEC2_ROW + 2, 1, stageRows.length, 7).setHorizontalAlignment('center');

  // 해석 컬럼 색상
  stageRows.forEach((row, i) => {
    const cell = sheet.getRange(SEC2_ROW + 2 + i, 7);
    const val  = row[6];
    if      (val === '우수')    cell.setBackground('#c8e6c9').setFontColor('#1b5e20');
    else if (val === '양호')    cell.setBackground('#fff9c4').setFontColor('#f57f17');
    else if (val === '개선필요') cell.setBackground('#ffe0b2').setFontColor('#e65100');
    else if (val === '위험')    cell.setBackground('#ffcdd2').setFontColor('#b71c1c');
    if (i % 2 === 0) {
      sheet.getRange(SEC2_ROW + 2 + i, 1, 1, 6).setBackground(
        sheet.getRange(SEC2_ROW + 2 + i, 1).getBackground() === '#ffffff' ? '#f8f9fa' : undefined
      );
    }
  });

  // ────────────────────────────────────────────────
  // 섹션3: 월별 코호트 추이
  // ────────────────────────────────────────────────
  const SEC3_ROW = SEC2_ROW + stageRows.length + 4;

  sheet.getRange(SEC3_ROW, 1, 1, 7).merge()
       .setValue('■ 월별 코호트 1→2 / 2→3 전환율 추이 (개선되고 있는지 확인)')
       .setFontWeight('bold').setFontSize(11)
       .setBackground('#e8eaf6').setFontColor('#1a237e');

  sheet.getRange(SEC3_ROW + 1, 1, 1, 7)
       .setValues([['코호트월', '첫구매자수',
                    '1→2 전환수', '1→2 전환율', '1→2 평균소요일',
                    '2→3 전환수', '2→3 전환율']])
       .setFontWeight('bold').setBackground('#1a73e8')
       .setFontColor('#ffffff').setHorizontalAlignment('center').setFontSize(10);

  // 1→2 헤더 구분색
  sheet.getRange(SEC3_ROW + 1, 3, 1, 3).setBackground('#1565c0');
  sheet.getRange(SEC3_ROW + 1, 6, 1, 2).setBackground('#0d47a1');

  const trendRows = sortedMonths.map(month => {
    const d        = cohortFunnel[month];
    const rate12   = d.total > 0 ? Math.round(d.converted12 / d.total * 1000) / 10 : 0;
    const rate23   = d.converted12 > 0 ? Math.round(d.converted23 / d.converted12 * 1000) / 10 : 0;
    const sorted12 = d.gaps12.slice().sort((a, b) => a - b);
    const avg12    = sorted12.length > 0
                     ? Math.round(sorted12.reduce((a, b) => a + b, 0) / sorted12.length) : '-';
    return [month, d.total, d.converted12, rate12, avg12, d.converted23, rate23];
  });

  if (trendRows.length > 0) {
    const dr = SEC3_ROW + 2;
    sheet.getRange(dr, 1, trendRows.length, 7).setValues(trendRows).setFontSize(10);
    sheet.getRange(dr, 2, trendRows.length, 2).setNumberFormat('#,##0');
    sheet.getRange(dr, 4, trendRows.length, 1).setNumberFormat('0.0"%"');
    sheet.getRange(dr, 6, trendRows.length, 1).setNumberFormat('#,##0');
    sheet.getRange(dr, 7, trendRows.length, 1).setNumberFormat('0.0"%"');
    sheet.getRange(dr, 1, trendRows.length, 7).setHorizontalAlignment('center');

    for (let i = 0; i < trendRows.length; i++) {
      if (i % 2 === 0) sheet.getRange(dr + i, 1, 1, 7).setBackground('#f8f9fa');
    }
    sheet.getRange(dr + trendRows.length - 1, 1, 1, 7)
         .setBackground('#e8f5e9').setFontWeight('bold');
  }

  // 컬럼 너비
  [90, 80, 85, 85, 85, 85, 85, 150].forEach((w, i) =>
    sheet.setColumnWidth(i + 1, w));

  sheet.setFrozenRows(1);
  Logger.log('✅ ' + sheetName + ' 완료');
}


// ============================================================
// ── 간격 분석 시트
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
  sheet.getRange(1, 1).setValue('📊 재구매 간격 분포 분석').setFontWeight('bold').setFontSize(12);
  sheet.getRange(1, 2).setValue('업데이트: ' + updatedAt).setFontColor('#888888').setFontSize(10);
  sheet.setColumnWidth(1, 160); sheet.setColumnWidth(2, 80); sheet.setColumnWidth(3, 220);

  sheet.getRange(3, 1, 1, 3).setValues([['지표', '값', '의미']])
       .setFontWeight('bold').setBackground('#1a73e8').setFontColor('#ffffff').setFontSize(10);

  const summaryRows = [
    ['샘플 수',           stats.count + '건', '2회 이상 구매한 고객의 구매 간격'],
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

  const bins   = [30, 60, 90, 120, 180, 365, Infinity];
  const labels = ['30일 이내', '31~60일', '61~90일', '91~120일', '121~180일', '181~365일', '365일 초과'];
  let prev = 0;
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
// ── 코호트 월별 잔존율 시트
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
  sheet.getRange(2, 1, 1, totalCols).merge()
       .setValue('🟢 30%↑  🟡 20~29%  🟠 10~19%  🔴 10%↓  ─ = 아직 해당 월 미도래')
       .setFontColor('#1565c0').setBackground('#e3f2fd').setFontSize(10).setFontStyle('italic');

  const headerRow = ['코호트월', '첫구매자수'];
  for (let m = 1; m <= MAX_MONTHS; m++) headerRow.push('M+' + m);
  headerRow.push('M+1기준');  // M+1을 비교 기준으로 변경 (헤비로버 재구매 주기 반영)

  sheet.getRange(3, 1, 1, headerRow.length)
       .setValues([headerRow])
       .setFontWeight('bold').setBackground('#1a73e8')
       .setFontColor('#ffffff').setHorizontalAlignment('center').setFontSize(10);

  // M+1 기준 컬럼 강조
  sheet.getRange(3, headerRow.length, 1, 1).setBackground('#e65100');

  const dataRows = sortedCohorts.map(cohortMonth => {
    const customers = cohortCustomers[cohortMonth];
    const size      = customers.length;
    const row       = [cohortMonth, size];

    for (let m = 1; m <= MAX_MONTHS; m++) {
      const targetMonth = addMonthsStr(cohortMonth, m);
      if (targetMonth > currentMonth) {
        row.push('─');
      } else {
        const retained = customers.filter(id =>
          custMonths[id] && custMonths[id].has(targetMonth)
        ).length;
        row.push(Math.round(retained / size * 1000) / 10);
      }
    }

    // M+1기준 (row[2] = M+1)
    const m1 = row[2];
    row.push((m1 !== undefined && m1 !== '─') ? m1 : '─');
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
        } else {
          const rate = Number(val);
          cell.setNumberFormat('0.0"%"');
          if      (rate >= 30) { cell.setBackground('#c8e6c9').setFontColor('#1b5e20'); }
          else if (rate >= 20) { cell.setBackground('#fff9c4').setFontColor('#f57f17'); }
          else if (rate >= 10) { cell.setBackground('#ffe0b2').setFontColor('#e65100'); }
          else                 { cell.setBackground('#ffcdd2').setFontColor('#b71c1c'); }
        }
      }

      // M+1기준 마지막 열
      const m1cell = sheet.getRange(dr + i, headerRow.length);
      const m1val  = row[row.length - 1];
      if (m1val !== '─') {
        m1cell.setNumberFormat('0.0"%"').setFontWeight('bold');
        const r = Number(m1val);
        if      (r >= 30) m1cell.setBackground('#c8e6c9').setFontColor('#1b5e20');
        else if (r >= 20) m1cell.setBackground('#fff9c4').setFontColor('#f57f17');
        else if (r >= 10) m1cell.setBackground('#ffe0b2').setFontColor('#e65100');
        else              m1cell.setBackground('#ffcdd2').setFontColor('#b71c1c');
      } else {
        m1cell.setFontColor('#bdbdbd');
      }

      if (i % 2 === 0) sheet.getRange(dr + i, 1, 1, 2).setBackground('#f8f9fa');
    });

    sheet.getRange(dr + dataRows.length - 1, 1, 1, headerRow.length).setFontWeight('bold');
  }

  sheet.setColumnWidth(1, 90); sheet.setColumnWidth(2, 80);
  for (let m = 1; m <= MAX_MONTHS; m++) sheet.setColumnWidth(m + 2, 62);
  sheet.setColumnWidth(MAX_MONTHS + 3, 72);
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
    for (let i = 1; i < list.length; i++) {
      const d = Math.round((list[i].orderDate - list[i - 1].orderDate) / 86400000);
      if (d > 0) gaps.push(d);
    }
  });
  return gaps;
}

// pct2: 내부 percentile (pct는 퍼널 내부 로컬변수와 이름 충돌 방지)
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

function isCanceled(status) { return HL.CANCEL.some(kw => status.includes(kw)); }

function getSheet(name) {
  const s = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(name);
  if (!s) Logger.log('⚠️ 시트 없음: ' + name);
  return s;
}

function getOrCreateSheet(name) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  return ss.getSheetByName(name) || ss.insertSheet(name);
}
