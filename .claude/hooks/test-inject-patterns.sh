#!/usr/bin/env bash
# inject-patterns.py 자체 테스트
# 5개 시나리오로 키워드 매칭·주입·미주입 동작 검증

set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="$SCRIPT_DIR/inject-patterns.py"

PASS=0
FAIL=0

run_case() {
    local name="$1"
    local payload="$2"
    local expect="$3"  # "inject" or "no-inject" or grep substring

    echo "=== [$name] ==="
    local out
    # PYTHONIOENCODING으로 stdout/stderr UTF-8 강제 (Windows cp949 회피)
    out=$(printf '%s' "$payload" | PYTHONIOENCODING=utf-8 python "$HOOK" 2>&1)

    case "$expect" in
        no-inject)
            if [ -z "$out" ]; then
                echo "PASS — 출력 없음(매칭 0건)"
                PASS=$((PASS+1))
            else
                echo "FAIL — 출력이 발생함:"
                echo "$out" | head -3
                FAIL=$((FAIL+1))
            fi
            ;;
        *)
            if echo "$out" | grep -q "$expect"; then
                echo "PASS — '$expect' 포함"
                PASS=$((PASS+1))
            else
                echo "FAIL — '$expect' 누락"
                echo "$out" | head -5
                FAIL=$((FAIL+1))
            fi
            ;;
    esac
    echo ""
}

run_case "엑셀 작업"      '{"prompt":"발주 엑셀에 freeze panes 추가해줘","cwd":"."}'                "§엑셀편집"
run_case "API 작업"        '{"prompt":"카페24 OAuth 토큰 갱신 코드 짜줘","cwd":"."}'                "§외부API다루기"
run_case "지역 필터"        '{"prompt":"govt-radar 시군 필터링 로직 점검","cwd":"."}'                 "§지역자격필터"
run_case "단순 질의(미주입)" '{"prompt":"오늘 날씨 어때","cwd":"."}'                                  "no-inject"
run_case "복합 키워드"      '{"prompt":"Vultr cron으로 카페24 API 자동 호출 + 엑셀 발주양식","cwd":"."}' "§자동화점검"

echo "==========="
echo "결과: PASS=$PASS / FAIL=$FAIL"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
