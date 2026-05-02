# 카페24 UTM 캡처 스크립트 설치 가이드

## 목적
Meta 광고세트별 첫구매→재구매 추적을 위해, 광고에서 들어온 손님의 UTM 파라미터를
카페24 주문 메모(buyer_message)에 자동 저장.

## 전제 조건 (Meta 광고관리자 설정 — 이미 완료)
각 광고세트의 URL 파라미터:
```
utm_source=meta&utm_medium=paid&utm_campaign={{campaign.name}}&utm_content={{adset.id}}&utm_term={{ad.name}}
```
- `{{adset.id}}` = 광고세트 ID (분석 기본 단위)
- `{{ad.name}}` = 광고 이름 (광고 단위 분석용)

---

## 설치 위치 (카페24 관리자)

쇼핑몰 관리자 → **디자인** → **PC쇼핑몰 디자인** → **HTML 편집** → **공통 → /layout/basic/main.html**
(또는 사용 중인 스킨의 공통 레이아웃 파일)

`</body>` 태그 **바로 위**에 아래 스크립트 전체를 붙여넣기.

---

## 스크립트 (전체 복사)

```html
<!-- HeavyLover UTM Capture (광고세트별 재구매 추적) -->
<script>
(function() {
  'use strict';
  var UTM_KEYS = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'];
  var STORAGE_PREFIX = 'hl_';
  var STORAGE_TTL_DAYS = 30;

  // 1. 랜딩 시점에 URL의 UTM 파라미터를 localStorage에 저장 (TTL 30일)
  function captureUtmFromUrl() {
    try {
      var params = new URLSearchParams(window.location.search);
      var captured = false;
      UTM_KEYS.forEach(function(k) {
        var v = params.get(k);
        if (v) {
          localStorage.setItem(STORAGE_PREFIX + k, v);
          captured = true;
        }
      });
      if (captured) {
        localStorage.setItem(STORAGE_PREFIX + 'ts', String(Date.now()));
      }
    } catch (e) { /* localStorage 미지원 시 무시 */ }
  }

  // 2. TTL 만료 체크 (30일 지나면 삭제)
  function purgeIfExpired() {
    try {
      var ts = parseInt(localStorage.getItem(STORAGE_PREFIX + 'ts') || '0', 10);
      if (!ts) return;
      var ageMs = Date.now() - ts;
      if (ageMs > STORAGE_TTL_DAYS * 86400 * 1000) {
        UTM_KEYS.forEach(function(k) { localStorage.removeItem(STORAGE_PREFIX + k); });
        localStorage.removeItem(STORAGE_PREFIX + 'ts');
      }
    } catch (e) {}
  }

  // 3. 주문서 페이지에서 buyer_message 필드에 UTM 자동 삽입
  //    (카페24 결제 페이지의 배송 메모 input/textarea에 prepend)
  function injectUtmToOrderForm() {
    try {
      var utm = {};
      var hasUtm = false;
      UTM_KEYS.forEach(function(k) {
        var v = localStorage.getItem(STORAGE_PREFIX + k);
        if (v) { utm[k] = v; hasUtm = true; }
      });
      if (!hasUtm) return;

      // 주문서 페이지 식별: URL에 'order' 또는 'cart' 포함
      var path = window.location.pathname.toLowerCase();
      if (!/order|cart|checkout/.test(path)) return;

      // buyer_message 필드 후보 (카페24 기본 스킨 + 커스텀 대비 다중 셀렉터)
      var selectors = [
        'textarea[name="buyer_message"]',
        'textarea[name="order_memo"]',
        'textarea[name="message"]',
        'input[name="buyer_message"]',
        'textarea[id*="message" i]',
        'textarea[id*="memo" i]',
      ];

      var utmString = UTM_KEYS
        .filter(function(k) { return utm[k]; })
        .map(function(k) { return k + '=' + encodeURIComponent(utm[k]); })
        .join('&');

      function tryInject() {
        var injected = false;
        selectors.forEach(function(sel) {
          var el = document.querySelector(sel);
          if (!el || el.dataset.hlUtmInjected === '1') return;
          // 기존 메시지 보존 + UTM은 [HL_UTM] 접두사로 구분
          var existing = (el.value || '').trim();
          var marker = '[HL_UTM]';
          if (existing.indexOf(marker) !== -1) return; // 이미 있음
          var sep = existing ? '\n' : '';
          el.value = existing + sep + marker + ' ' + utmString;
          el.dataset.hlUtmInjected = '1';
          injected = true;
        });
        return injected;
      }

      // DOM 로드 직후 + 일정 시간 후 재시도 (카페24 폼은 동적 로드 가능)
      tryInject();
      setTimeout(tryInject, 500);
      setTimeout(tryInject, 1500);
      setTimeout(tryInject, 3000);
    } catch (e) {}
  }

  // 실행 순서
  purgeIfExpired();
  captureUtmFromUrl();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectUtmToOrderForm);
  } else {
    injectUtmToOrderForm();
  }
})();
</script>
<!-- /HeavyLover UTM Capture -->
```

---

## 동작 원리

```
1. 사용자가 광고 클릭 (URL: ...?utm_content=23856789012345&...)
        ↓
2. 카페24 사이트 도착 → 스크립트가 localStorage에 UTM 저장 (30일 TTL)
        ↓
3. 사용자가 상품 둘러보고 결제 페이지 진입
        ↓
4. 스크립트가 주문서의 buyer_message 필드에 자동 삽입:
   "[HL_UTM] utm_source=meta&utm_medium=paid&utm_content=23856789012345&..."
        ↓
5. 사용자가 결제 완료 → 카페24 DB에 buyer_message 저장
        ↓
6. cafe24_client.fetch_orders()가 buyer_message를 받아옴
        ↓
7. extract_utm_from_order()가 utm_content(adset_id) 파싱 → 시트에 누적
```

---

## 검증 방법

### 1. 광고 URL 직접 클릭 테스트
1. 본인 Meta 광고 1건 클릭 (또는 직접 URL 입력: `https://heavylover.co.kr/?utm_content=TEST_ADSET&utm_source=meta`)
2. 개발자 도구(F12) → **Application** → **Local Storage** → 도메인 선택
3. `hl_utm_content` 값에 `TEST_ADSET` 들어있는지 확인

### 2. 주문서 페이지 진입 테스트
1. 위 1번 후 상품 → 장바구니 → 주문서 페이지 이동
2. 배송 메모/주문 메모 textarea에 `[HL_UTM] utm_content=TEST_ADSET...` 자동 삽입 확인
3. 사용자가 추가로 메시지 입력해도 UTM은 위에 그대로 유지

### 3. 실제 주문 생성 후 API 검증
1. 위 테스트 주문 1건 실제 결제
2. 다음 명령으로 buyer_message 확인:
   ```bash
   ssh root@vultr "cd /root/heavylover-automation && python3 -c '
   import cafe24_client
   orders = cafe24_client.fetch_orders(days_back=1)
   for o in orders[-3:]:
       msg = o.get(\"buyer_message\", \"\")
       utm = cafe24_client.extract_utm_from_order(o)
       print(o[\"order_id\"], \"->\", utm)
   '"
   ```

---

## 한계 및 주의

| 항목 | 내용 |
|---|---|
| 직접 유입 | URL에 utm_* 없이 들어온 손님은 UTM 비어있음 (organic 분류) |
| iOS Safari | localStorage TTL 7일로 단축됨 (Apple ITP 정책) |
| 사용자 메시지 충돌 | 사용자가 `[HL_UTM]` 직접 입력하면 파싱 실패 — 충분히 드물어 무시 |
| 모바일 앱 | 카페24 모바일 앱은 별도 스킨 — 동일 스크립트를 모바일 메인 레이아웃에도 추가 필요 |
| 4월 이전 소급 | 불가능. 스크립트 설치 시점부터 수집 시작 |

---

## 다음 단계 (스크립트 설치 후)

1. 1~2일 후 실제 주문에 UTM 캡처되는지 확인
2. `sheets_sync.py` 카페24 시트 헤더에 `adset_id`, `ad_name` 컬럼 추가 (별도 작업)
3. `repurchase_report.py` 코호트 분류에 `adset_id` 차원 추가 (별도 작업)
4. 60일 후 (7월 초) 광고세트별 1→2 전환율 분석 가능
