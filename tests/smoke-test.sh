#!/usr/bin/env bash
set -euo pipefail

# Origin Server Post-Boot Smoke Test Suite
# Deterministic validation of all components after deployment or reboot.
# Usage: ./smoke-test.sh <origin-ip-or-hostname>
# Exit codes: 0 = all pass, 1 = failures detected

ORIGIN="${1:?Usage: $0 <origin-ip-or-hostname>}"
BASE="http://${ORIGIN}"
PASS=0
FAIL=0
RESULTS=()

check() {
  local name="$1" expected="$2" actual="$3"
  if [ "$actual" = "$expected" ]; then
    RESULTS+=("PASS  $name")
    PASS=$((PASS + 1))
  else
    RESULTS+=("FAIL  $name (expected=$expected got=$actual)")
    FAIL=$((FAIL + 1))
  fi
}

check_contains() {
  local name="$1" needle="$2" haystack="$3"
  if echo "$haystack" | grep -q "$needle"; then
    RESULTS+=("PASS  $name")
    PASS=$((PASS + 1))
  else
    RESULTS+=("FAIL  $name (missing: $needle)")
    FAIL=$((FAIL + 1))
  fi
}

echo "============================================"
echo "  Origin Server Smoke Test Suite"
echo "  Target: ${BASE}"
echo "  Time:   $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "============================================"
echo ""

# ── 1. Infrastructure ──────────────────────────────

echo "── Infrastructure ──"

HEALTH=$(curl -sf --max-time 5 "${BASE}/health" 2>/dev/null || echo "UNREACHABLE")
check "health-endpoint-reachable" "true" "$([ "$HEALTH" != "UNREACHABLE" ] && echo true || echo false)"
check_contains "health-status-healthy" '"status":"healthy"' "$HEALTH"
check_contains "health-lists-juice-shop" '"juice-shop"' "$HEALTH"
check_contains "health-lists-dvwa" '"dvwa"' "$HEALTH"
check_contains "health-lists-vampi" '"vampi"' "$HEALTH"
check_contains "health-lists-httpbin" '"httpbin"' "$HEALTH"
check_contains "health-lists-whoami" '"whoami"' "$HEALTH"
check_contains "health-lists-csd-demo" '"csd-demo"' "$HEALTH"

LANDING=$(curl -sf --max-time 5 -o /dev/null -w "%{http_code}" "${BASE}/" 2>/dev/null || echo "000")
check "landing-page-200" "200" "$LANDING"

# ── 2. Juice Shop ──────────────────────────────────

echo "── Juice Shop ──"

JS_HOME=$(curl -sf --max-time 10 -o /dev/null -w "%{http_code}" "${BASE}/juice-shop/" 2>/dev/null || echo "000")
check "juice-shop-home-200" "200" "$JS_HOME"

JS_API=$(curl -sf --max-time 10 "${BASE}/juice-shop/rest/products/search?q=" 2>/dev/null || echo "{}")
JS_STATUS=$(echo "$JS_API" | grep -oP '"status"\s*:\s*"\K[^"]+' || echo "none")
check "juice-shop-api-status-success" "success" "$JS_STATUS"

JS_COUNT=$(echo "$JS_API" | grep -oP '"id"' | wc -l)
check "juice-shop-products-exist" "true" "$([ "$JS_COUNT" -gt 0 ] && echo true || echo false)"

# ── 3. DVWA ────────────────────────────────────────

echo "── DVWA ──"

DVWA_LOGIN=$(curl -sf --max-time 5 -o /dev/null -w "%{http_code}" -L "${BASE}/dvwa/login.php" 2>/dev/null || echo "000")
check "dvwa-login-page-200" "200" "$DVWA_LOGIN"

DVWA_SETUP=$(curl -sf --max-time 5 -o /dev/null -w "%{http_code}" "${BASE}/dvwa/setup.php" 2>/dev/null || echo "000")
check "dvwa-setup-page-200" "200" "$DVWA_SETUP"

DVWA_SETUP_BODY=$(curl -sf --max-time 5 "${BASE}/dvwa/setup.php" 2>/dev/null || echo "")
check_contains "dvwa-database-connected" "Database" "$DVWA_SETUP_BODY"

DVWA_LOGIN_BODY=$(curl -sf --max-time 5 -L "${BASE}/dvwa/login.php" 2>/dev/null || echo "")
DVWA_TOKEN=$(echo "$DVWA_LOGIN_BODY" | grep -oP "user_token.*?value='\K[a-f0-9]+" | head -1 || echo "")
if [ -n "$DVWA_TOKEN" ]; then
  DVWA_AUTH=$(curl -sf --max-time 5 -c /tmp/smoke-dvwa \
    -L -X POST "${BASE}/dvwa/login.php" \
    -d "username=admin&password=password&Login=Login&user_token=${DVWA_TOKEN}" \
    -o /dev/null -w "%{http_code}" 2>/dev/null || echo "000")
  check "dvwa-login-admin-200" "200" "$DVWA_AUTH"
else
  RESULTS+=("FAIL  dvwa-login-admin-200 (no CSRF token found)")
  FAIL=$((FAIL + 1))
fi

# ── 4. VAmPI ───────────────────────────────────────

echo "── VAmPI ──"

VAMPI_HOME=$(curl -sf --max-time 5 -o /dev/null -w "%{http_code}" "${BASE}/vampi/" 2>/dev/null || echo "000")
check "vampi-home-200" "200" "$VAMPI_HOME"

VAMPI_USERS=$(curl -sf --max-time 5 "${BASE}/vampi/users/v1" 2>/dev/null || echo "{}")
check_contains "vampi-users-endpoint" "users" "$VAMPI_USERS"

SMOKE_USER="smoke$(date +%s)"
VAMPI_REG=$(curl -sf --max-time 5 -X POST "${BASE}/vampi/users/v1/register" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"${SMOKE_USER}\",\"password\":\"test123\",\"email\":\"${SMOKE_USER}@test.com\"}" 2>/dev/null || echo "{}")
check_contains "vampi-register-success" '"success"' "$VAMPI_REG"

VAMPI_LOGIN=$(curl -sf --max-time 5 -X POST "${BASE}/vampi/users/v1/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"${SMOKE_USER}\",\"password\":\"test123\"}" 2>/dev/null || echo "{}")
check_contains "vampi-login-returns-token" "auth_token" "$VAMPI_LOGIN"

# ── 5. httpbin ─────────────────────────────────────

echo "── httpbin ──"

HTTPBIN_GET=$(curl -sf --max-time 5 -o /dev/null -w "%{http_code}" "${BASE}/httpbin/get" 2>/dev/null || echo "000")
check "httpbin-get-200" "200" "$HTTPBIN_GET"

HTTPBIN_POST=$(curl -sf --max-time 5 -X POST "${BASE}/httpbin/post" \
  -H "Content-Type: application/json" -d '{"test":true}' 2>/dev/null || echo "{}")
check_contains "httpbin-post-echoes-body" '"test"' "$HTTPBIN_POST"

HTTPBIN_HEADERS=$(curl -sf --max-time 5 "${BASE}/httpbin/headers" 2>/dev/null || echo "{}")
check_contains "httpbin-headers-has-host" '"Host"' "$HTTPBIN_HEADERS"

HTTPBIN_403=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" "${BASE}/httpbin/status/403" 2>/dev/null || echo "000")
check "httpbin-status-403" "403" "$HTTPBIN_403"

HTTPBIN_500=$(curl -s --max-time 5 -o /dev/null -w "%{http_code}" "${BASE}/httpbin/status/500" 2>/dev/null || echo "000")
check "httpbin-status-500" "500" "$HTTPBIN_500"

# ── 6. whoami ──────────────────────────────────────

echo "── whoami ──"

WHOAMI=$(curl -sf --max-time 5 "${BASE}/whoami/" 2>/dev/null || echo "UNREACHABLE")
check "whoami-reachable" "true" "$([ "$WHOAMI" != "UNREACHABLE" ] && echo true || echo false)"
check_contains "whoami-shows-hostname" "Hostname:" "$WHOAMI"
check_contains "whoami-shows-ip" "IP:" "$WHOAMI"
check_contains "whoami-shows-method" "GET / HTTP" "$WHOAMI"

WHOAMI_HEADER=$(curl -sf --max-time 5 -H "X-Test-Header: smoke-test" "${BASE}/whoami/" 2>/dev/null || echo "")
check_contains "whoami-reflects-custom-header" "X-Test-Header: smoke-test" "$WHOAMI_HEADER"

# ── 7. CSD Demo ────────────────────────────────────

echo "── CSD Demo ──"

CSD_HOME=$(curl -sf --max-time 5 -o /dev/null -w "%{http_code}" "${BASE}/csd-demo/" 2>/dev/null || echo "000")
check "csd-demo-checkout-200" "200" "$CSD_HOME"

CSD_HEALTH=$(curl -sf --max-time 5 "${BASE}/csd-demo/health" 2>/dev/null || echo "{}")
check_contains "csd-demo-health-healthy" '"healthy"' "$CSD_HEALTH"
check_contains "csd-demo-lists-skimmer" '"skimmer"' "$CSD_HEALTH"

CSD_DASH=$(curl -sf --max-time 5 -o /dev/null -w "%{http_code}" "${BASE}/csd-demo/dashboard" 2>/dev/null || echo "000")
check "csd-demo-dashboard-200" "200" "$CSD_DASH"

CSD_EXFIL=$(curl -sf --max-time 5 -X POST "${BASE}/csd-demo/exfil?type=smoke-test" \
  -H "Content-Type: application/json" -d '{"test":"smoke"}' 2>/dev/null || echo "{}")
check_contains "csd-demo-exfil-receives" '"received"' "$CSD_EXFIL"

CSD_LOG=$(curl -sf --max-time 5 "${BASE}/csd-demo/exfil/log" 2>/dev/null || echo "[]")
check_contains "csd-demo-exfil-log-has-entry" "smoke-test" "$CSD_LOG"

# ── 8. Cross-cutting ───────────────────────────────

echo "── Cross-cutting ──"

NGINX_HEADER=$(curl -sf --max-time 5 -I "${BASE}/health" 2>/dev/null | grep -i "^server:" || echo "")
check_contains "nginx-hides-version" "nginx" "$NGINX_HEADER"
check "nginx-no-version-leak" "true" "$(echo "$NGINX_HEADER" | grep -qP 'nginx/\d' && echo false || echo true)"

GZIP=$(curl -sf --max-time 5 -H "Accept-Encoding: gzip" -o /dev/null -w "%{size_download}" "${BASE}/juice-shop/" 2>/dev/null || echo "0")
NOGZIP=$(curl -sf --max-time 5 -o /dev/null -w "%{size_download}" "${BASE}/juice-shop/" 2>/dev/null || echo "0")
check "gzip-compression-active" "true" "$([ "$GZIP" -lt "$NOGZIP" ] && echo true || echo false)"

# ── Results ────────────────────────────────────────

echo ""
echo "============================================"
echo "  RESULTS: ${PASS} passed, ${FAIL} failed"
echo "============================================"
for r in "${RESULTS[@]}"; do
  echo "  $r"
done
echo ""

if [ "$FAIL" -gt 0 ]; then
  echo "SMOKE TEST: FAILED"
  exit 1
else
  echo "SMOKE TEST: PASSED"
  exit 0
fi
