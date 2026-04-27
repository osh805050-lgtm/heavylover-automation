/**
 * 헤비로버 정부지원 레이더 (Google Apps Script)
 * 매일 오전 9시 자동 실행 → 신규 공고 스캔 → 적합도 판정 → 다중 채널 알림
 *
 * ⚠️ 사용법:
 * 1. script.google.com → 새 프로젝트 → 이 파일 내용 붙여넣기
 * 2. [설정] 아이콘 → [스크립트 속성] → 아래 속성 추가
 *    - KAKAO_REST_API_KEY (STEP 5에서)
 *    - KAKAO_ACCESS_TOKEN (STEP 5에서)
 *    - KAKAO_REFRESH_TOKEN (STEP 5에서)
 *    - SHEET_ID (로그 저장용 Google Sheet ID)
 * 3. 함수 선택 → runDailyScan 실행 → 권한 승인
 * 4. [트리거] → runDailyScan 매일 오전 9시 추가
 */

// ==================== 설정 ====================
const CONFIG = {
  // 사업 프로필 (매칭 키워드)
  HEAVYLOVER_KEYWORDS: [
    '식품', 'D2C', '이커머스', '냉동', '단백질', '도시락', '시리얼',
    '청년', '창업', '소상공인', 'HACCP', '수출', '아마존', 'K-Food',
    '마케팅', '인증', '브랜드', '벤처', '경기도', '용인', '바우처',
    'R&D', 'AI', '데이터', '스마트공장', '콘텐츠'
  ],
  SAAS_KEYWORDS: [
    'SaaS', 'ICT', 'SW', '소프트웨어', '글로벌', 'TIPS', 'K-Global',
    '클라우드', '플랫폼', '스타트업', '예비창업', '초기창업'
  ],

  // 제외 키워드 (관련 없는 공고 걸러냄)
  EXCLUDE_KEYWORDS: [
    '농업인', '농민', '어민', '어업', '축산', '건축', '토목',
    '의료기기', '제약', '화학', '철강', '조선', '항공'
  ],

  // 지역 가중치 (경기도 또는 전국 공고 가점)
  PREFERRED_REGIONS: ['경기', '용인', '전국'],

  // 알림 임계값 (적합도 이 이상이면 알림/캘린더)
  NOTIFY_THRESHOLD: 3,        // 카톡 알림 (낮은 문턱 - 사용자 요구)
  CALENDAR_THRESHOLD: 7,      // 캘린더 자동 등록

  // 타겟 사이트
  SOURCES: [
    {
      name: '기업마당',
      url: 'https://www.bizinfo.go.kr/web/lay1/bbs/S1T122C128/AS/74/list.do',
      type: 'bizinfo'
    },
    {
      name: 'K-Startup',
      url: 'https://www.k-startup.go.kr/homepage/biz/announcementList.do',
      type: 'kstartup'
    },
    {
      name: 'NIPA',
      url: 'https://www.nipa.kr/home/2-2',
      type: 'nipa'
    },
    {
      name: '창업진흥원',
      url: 'https://www.kised.or.kr/menu.es?mid=a10302000000',
      type: 'kised'
    }
  ],

  // 이메일 (승현님 계정)
  EMAIL: 'osh805050@gmail.com',

  // 캘린더 ID (primary = 기본 캘린더)
  CALENDAR_ID: 'primary'
};

// ==================== 메인 실행 ====================
function runDailyScan() {
  const startTime = new Date();
  Logger.log('===== 정부지원 레이더 시작: ' + startTime + ' =====');

  const allAnnouncements = [];

  // 1. 각 사이트 크롤링
  CONFIG.SOURCES.forEach(source => {
    try {
      const items = fetchSource_(source);
      Logger.log(source.name + ': ' + items.length + '건 수집');
      allAnnouncements.push(...items);
    } catch (e) {
      Logger.log(source.name + ' 에러: ' + e.message);
    }
  });

  // 2. 중복 제거 (title 기준)
  const deduped = dedupe_(allAnnouncements);
  Logger.log('중복 제거 후: ' + deduped.length + '건');

  // 3. 어제~오늘 신규만 필터
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 2);
  const fresh = deduped.filter(a => !a.postedDate || new Date(a.postedDate) > yesterday);

  // 4. 적합도 판정
  const scored = fresh.map(a => ({
    ...a,
    ...evaluateRelevance_(a)
  }));

  // 5. 알림 대상 선별
  const notifyItems = scored
    .filter(s => s.score >= CONFIG.NOTIFY_THRESHOLD)
    .sort((a, b) => b.score - a.score);

  const calendarItems = scored.filter(s => s.score >= CONFIG.CALENDAR_THRESHOLD);

  // 6. 알림 발송
  if (notifyItems.length > 0) {
    sendGmailDigest_(notifyItems);
    sendKakaoMessage_(notifyItems);
  } else {
    Logger.log('오늘 적합 공고 없음');
  }

  // 7. 캘린더 자동 등록
  calendarItems.forEach(item => {
    try {
      createCalendarEvent_(item);
    } catch (e) {
      Logger.log('캘린더 등록 실패: ' + item.title + ' / ' + e.message);
    }
  });

  // 8. Google Sheets 로그
  logToSheet_(scored);

  const elapsed = (new Date() - startTime) / 1000;
  Logger.log('===== 완료 (' + elapsed + '초) =====');
}

// ==================== 크롤링 ====================
function fetchSource_(source) {
  const res = UrlFetchApp.fetch(source.url, {
    muteHttpExceptions: true,
    followRedirects: true,
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
  });
  const html = res.getContentText('UTF-8');
  return parseSource_(html, source);
}

function parseSource_(html, source) {
  const items = [];

  if (source.type === 'bizinfo') {
    // 기업마당 공고 제목 정규식
    const regex = /<a[^>]*href="([^"]+pblancId=[^"]+)"[^>]*>([^<]+)<\/a>/g;
    let m;
    while ((m = regex.exec(html)) !== null) {
      items.push({
        source: '기업마당',
        title: m[2].replace(/\s+/g, ' ').trim(),
        url: 'https://www.bizinfo.go.kr' + m[1].replace(/&amp;/g, '&'),
        postedDate: null
      });
    }
  }
  else if (source.type === 'kstartup') {
    const regex = /<a[^>]*href="[^"]*announcementList\.do[^"]*"[^>]*>\s*([^<]+)\s*<\/a>/g;
    let m;
    while ((m = regex.exec(html)) !== null) {
      items.push({
        source: 'K-Startup',
        title: m[1].trim(),
        url: source.url,
        postedDate: null
      });
    }
  }
  else if (source.type === 'nipa' || source.type === 'kised') {
    const regex = /<(?:h3|h4|strong)[^>]*>([^<]+)<\/(?:h3|h4|strong)>/g;
    let m;
    let count = 0;
    while ((m = regex.exec(html)) !== null && count < 30) {
      items.push({
        source: source.name,
        title: m[1].trim(),
        url: source.url,
        postedDate: null
      });
      count++;
    }
  }

  return items.slice(0, 50);
}

function dedupe_(items) {
  const seen = new Set();
  return items.filter(i => {
    const key = i.title.substring(0, 30);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// ==================== 적합도 판정 ====================
function evaluateRelevance_(item) {
  const text = item.title;

  // 제외 키워드 체크
  for (const ex of CONFIG.EXCLUDE_KEYWORDS) {
    if (text.includes(ex)) return { score: 0, business: '부적합', reason: '제외 키워드: ' + ex };
  }

  let hlHits = 0;
  let saasHits = 0;
  const matched = [];

  CONFIG.HEAVYLOVER_KEYWORDS.forEach(kw => {
    if (text.includes(kw)) { hlHits++; matched.push(kw); }
  });
  CONFIG.SAAS_KEYWORDS.forEach(kw => {
    if (text.includes(kw)) { saasHits++; matched.push(kw); }
  });

  // 지역 가중치
  const hasRegion = CONFIG.PREFERRED_REGIONS.some(r => text.includes(r));

  // 사업 분류
  let business, score;
  if (hlHits > saasHits) {
    business = '사업1 (헤비로버)';
    score = hlHits * 2 + (hasRegion ? 1 : 0);
  } else if (saasHits > 0) {
    business = '사업2 (SaaS)';
    score = saasHits * 2 + (hasRegion ? 1 : 0);
  } else {
    business = '미분류';
    score = 0;
  }

  // 마감임박 보너스
  if (/D-?[123]|내일 마감|금일 마감|당일 마감/.test(text)) score += 2;

  return {
    score: Math.min(10, score),
    business: business,
    reason: matched.slice(0, 4).join(', '),
    winTips: generateTips_(business, text)
  };
}

function generateTips_(business, text) {
  const tips = [];
  if (business === '사업1 (헤비로버)') {
    if (text.includes('R&D')) tips.push('기술 난이도+사업화가능성 양립, KPI 정량화');
    if (text.includes('수출')) tips.push('수출기업화 합격 이력 활용, 현지 파트너 증빙');
    if (text.includes('바우처')) tips.push('공급기업 매칭 잘할수록 유리, 활용처 구체화');
    if (text.includes('인증')) tips.push('스마트HACCP/ISO22000 수출 유리');
    if (text.includes('용인') || text.includes('경기')) tips.push('지역 가점, 경쟁률 낮음');
  } else if (business === '사업2 (SaaS)') {
    if (text.includes('글로벌')) tips.push('해외 유료고객 실적 > 기술 설명');
    if (text.includes('TIPS')) tips.push('VC 추천 선행 필요');
    if (text.includes('AI')) tips.push('AI 적용 비즈니스 가치 수치화');
  }
  tips.push('심사위원 10분 이내 검토 - 시각자료·볼드·데이터 중심');
  return tips;
}

// ==================== 알림 발송 ====================
function sendGmailDigest_(items) {
  const today = Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd (E)');
  const subject = '[정부지원 레이더] ' + today + ' 신규 ' + items.length + '건';

  let body = '<h2>🎯 ' + today + ' 정부지원 신규 공고</h2>';
  body += '<p>총 <b>' + items.length + '건</b> 감지. 적합도 순 정렬.</p><hr>';

  items.slice(0, 20).forEach((item, i) => {
    const stars = '⭐'.repeat(Math.round(item.score / 2));
    body += '<h3>' + (i + 1) + '. ' + item.title + '</h3>';
    body += '<p>' + stars + ' 적합도 <b>' + item.score + '/10</b> | ' + item.business + ' | 출처: ' + item.source + '</p>';
    body += '<p><b>매칭 키워드</b>: ' + (item.reason || '없음') + '</p>';
    if (item.winTips && item.winTips.length) {
      body += '<p><b>💡 합격 노하우</b>:</p><ul>';
      item.winTips.forEach(t => body += '<li>' + t + '</li>');
      body += '</ul>';
    }
    body += '<p><a href="' + item.url + '">공고 원문 보기</a></p><hr>';
  });

  // Gmail 초안 생성
  GmailApp.createDraft(CONFIG.EMAIL, subject, '', { htmlBody: body });
  Logger.log('Gmail 초안 생성 완료');
}

function sendKakaoMessage_(items) {
  const token = PropertiesService.getScriptProperties().getProperty('KAKAO_ACCESS_TOKEN');
  if (!token) {
    Logger.log('⚠️ 카카오 토큰 없음 - STEP 5 완료 필요');
    return;
  }

  const today = Utilities.formatDate(new Date(), 'Asia/Seoul', 'MM/dd');
  let text = '🎯 ' + today + ' 정부지원 신규 ' + items.length + '건\n\n';
  items.slice(0, 5).forEach((item, i) => {
    text += (i + 1) + '. [' + item.score + '/10] ' + item.title.substring(0, 40) + '\n';
    if (item.winTips && item.winTips[0]) {
      text += '   💡 ' + item.winTips[0].substring(0, 50) + '\n';
    }
    text += '\n';
  });
  if (items.length > 5) text += '+ ' + (items.length - 5) + '건 더 (Gmail 확인)';

  const linkUrl = 'https://heavylover.vercel.app'; // 대시보드 URL (가변)
  const payload = {
    object_type: 'text',
    text: text.substring(0, 200),
    link: {
      web_url: linkUrl,
      mobile_web_url: linkUrl
    },
    button_title: '자세히'
  };

  try {
    UrlFetchApp.fetch('https://kapi.kakao.com/v2/api/talk/memo/default/send', {
      method: 'post',
      headers: { Authorization: 'Bearer ' + token },
      payload: { template_object: JSON.stringify(payload) },
      muteHttpExceptions: true
    });
    Logger.log('카톡 발송 완료');
  } catch (e) {
    Logger.log('카톡 발송 실패: ' + e.message);
    refreshKakaoToken_();
  }
}

function refreshKakaoToken_() {
  const props = PropertiesService.getScriptProperties();
  const apiKey = props.getProperty('KAKAO_REST_API_KEY');
  const refreshToken = props.getProperty('KAKAO_REFRESH_TOKEN');
  if (!apiKey || !refreshToken) return;

  const res = UrlFetchApp.fetch('https://kauth.kakao.com/oauth/token', {
    method: 'post',
    payload: {
      grant_type: 'refresh_token',
      client_id: apiKey,
      refresh_token: refreshToken
    },
    muteHttpExceptions: true
  });
  const data = JSON.parse(res.getContentText());
  if (data.access_token) {
    props.setProperty('KAKAO_ACCESS_TOKEN', data.access_token);
    if (data.refresh_token) {
      props.setProperty('KAKAO_REFRESH_TOKEN', data.refresh_token);
    }
    Logger.log('카카오 토큰 갱신 완료');
  }
}

// ==================== 캘린더 등록 ====================
function createCalendarEvent_(item) {
  const cal = CalendarApp.getCalendarById(CONFIG.CALENDAR_ID);
  if (!cal) return;

  // 마감일 파싱 시도 (제목에서 YYYY-MM-DD, MM/DD 등)
  const deadlineMatch = item.title.match(/(\d{4}[-\.\/]\d{1,2}[-\.\/]\d{1,2})|마감[^\d]*(\d{1,2})[\.\/-](\d{1,2})/);
  let deadline = null;
  if (deadlineMatch) {
    try {
      deadline = new Date(deadlineMatch[1] || deadlineMatch[0]);
    } catch (e) {}
  }

  const eventDate = deadline || new Date();
  const title = '🎯 [발견] ' + item.title.substring(0, 50);
  const desc = '적합도: ' + item.score + '/10\n'
    + '분류: ' + item.business + '\n'
    + '출처: ' + item.source + '\n\n'
    + '💡 합격 노하우:\n' + (item.winTips || []).map(t => '- ' + t).join('\n')
    + '\n\n원문: ' + item.url;

  cal.createAllDayEvent(title, eventDate, { description: desc });
}

// ==================== Google Sheets 로깅 ====================
function logToSheet_(items) {
  const sheetId = PropertiesService.getScriptProperties().getProperty('SHEET_ID');
  if (!sheetId) {
    Logger.log('⚠️ SHEET_ID 미설정');
    return;
  }

  const ss = SpreadsheetApp.openById(sheetId);
  let sheet = ss.getSheetByName('로그');
  if (!sheet) {
    sheet = ss.insertSheet('로그');
    sheet.appendRow(['날짜', '출처', '적합도', '사업', '제목', 'URL', '노하우']);
  }

  const now = Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd HH:mm');
  items.forEach(it => {
    sheet.appendRow([
      now, it.source, it.score, it.business,
      it.title, it.url, (it.winTips || []).join(' / ')
    ]);
  });
  Logger.log('Sheet 로그 ' + items.length + '건 저장');
}

// ==================== 트리거 초기 세팅 ====================
function setupDailyTrigger() {
  // 기존 트리거 제거
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'runDailyScan') ScriptApp.deleteTrigger(t);
  });

  // 매일 오전 9시 실행
  ScriptApp.newTrigger('runDailyScan')
    .timeBased()
    .everyDays(1)
    .atHour(9)
    .create();

  Logger.log('트리거 등록 완료: 매일 오전 9시');
}

// ==================== 수동 테스트 ====================
function testRun() {
  runDailyScan();
}
