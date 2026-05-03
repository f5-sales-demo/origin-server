#!/usr/bin/env bash
set -euo pipefail

# Origin Server Post-Boot Smoke Test Suite
# Deterministic validation of all components after deployment or reboot.
# Usage: ./smoke-test.sh <origin-ip-or-hostname> [--ssh]
#   Default:  HTTP-only tests (application endpoints via curl)
#   --ssh:    additionally runs SSH infrastructure tests (requires SSH key)
# Exit codes: 0 = all pass, 1 = failures detected

ORIGIN="${1:?Usage: $0 <origin-ip-or-hostname> [--ssh]}"
SSH_MODE=false
shift || true
while [ $# -gt 0 ]; do
  case "$1" in
    --ssh) SSH_MODE=true ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
  shift
done

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

check_gte() {
  local name="$1" minimum="$2" actual="$3"
  if [ "$actual" -ge "$minimum" ] 2>/dev/null; then
    RESULTS+=("PASS  $name (value=$actual)")
    PASS=$((PASS + 1))
  else
    RESULTS+=("FAIL  $name (expected>=$minimum got=$actual)")
    FAIL=$((FAIL + 1))
  fi
}

ssh_cmd() {
  ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 "azureuser@${ORIGIN}" "$@" 2>/dev/null
}

echo "============================================"
echo "  Origin Server Smoke Test Suite"
echo "  Target: ${BASE}"
echo "  Mode:   $(if $SSH_MODE; then echo 'Full (HTTP + SSH)'; else echo 'HTTP-only'; fi)"
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
# Register on all load-balanced instances (round-robin sends each to a different backend)
for _ in 1 2 3 4; do
  curl -sf --max-time 5 -X POST "${BASE}/vampi/users/v1/register" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"${SMOKE_USER}\",\"password\":\"test123\",\"email\":\"${SMOKE_USER}@test.com\"}" -o /dev/null 2>/dev/null
done
VAMPI_REG=$(curl -sf --max-time 5 -X POST "${BASE}/vampi/users/v1/register" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"${SMOKE_USER}x\",\"password\":\"test123\",\"email\":\"${SMOKE_USER}x@test.com\"}" 2>/dev/null || echo "{}")
check_contains "vampi-register-success" '"success"' "$VAMPI_REG"

# Login will hit one of the instances that has the user
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

# ── 8. DVGA (GraphQL) ─────────────────────────────

echo "── DVGA (GraphQL) ──"

DVGA_HOME=$(curl -sf --max-time 15 -o /dev/null -w "%{http_code}" "${BASE}/dvga/" 2>/dev/null || echo "000")
check "dvga-home-200" "200" "$DVGA_HOME"

DVGA_GQL=$(curl -sf --max-time 10 -X POST "${BASE}/dvga/graphql" \
  -H "Content-Type: application/json" \
  -d '{"query":"{__schema{queryType{name}}}"}' 2>/dev/null || echo "{}")
check_contains "dvga-graphql-introspection" '"Query"' "$DVGA_GQL"

DVGA_PASTE=$(curl -sf --max-time 10 -X POST "${BASE}/dvga/graphql" \
  -H "Content-Type: application/json" \
  -d '{"query":"mutation { createPaste(title: \"smoke-test\", content: \"smoke-test-content\", public: true) { paste { title content } } }"}' 2>/dev/null || echo "{}")
check_contains "dvga-graphql-create-paste" '"smoke-test"' "$DVGA_PASTE"

# ── 9. RESTaurant API ────────────────────────────────

echo "── RESTaurant API ──"

REST_DOCS=$(curl -sf --max-time 10 -o /dev/null -w "%{http_code}" "${BASE}/restaurant/docs" 2>/dev/null || echo "000")
check "restaurant-docs-200" "200" "$REST_DOCS"

REST_OPENAPI=$(curl -sf --max-time 10 "${BASE}/restaurant/openapi.json" 2>/dev/null || echo "{}")
check_contains "restaurant-openapi-title" '"Damn Vulnerable RESTaurant"' "$REST_OPENAPI"

# ── 10. crAPI (port 8888) ─────────────────────────────

echo "── crAPI (port 8888) ──"

CRAPI_BASE="http://${ORIGIN}:8888"

CRAPI_HOME=$(curl -sf --max-time 10 -o /dev/null -w "%{http_code}" "${CRAPI_BASE}/" 2>/dev/null || echo "000")
check "crapi-home-200" "200" "$CRAPI_HOME"

CRAPI_HEALTH=$(curl -sf --max-time 10 "${CRAPI_BASE}/health" 2>/dev/null || echo "")
check_contains "crapi-health-ok" "OK" "$CRAPI_HEALTH"

CRAPI_SIGNUP=$(curl -sf --max-time 15 -X POST "${CRAPI_BASE}/identity/api/auth/signup" \
  -H "Content-Type: application/json" \
  -d '{"name":"Smoke Test","email":"smoke@example.com","number":"5551234567","password":"SmokeTest123"}' 2>/dev/null || echo "{}")
check_contains "crapi-signup-responds" '"message"' "$CRAPI_SIGNUP"

# ── 11. Cross-cutting ───────────────────────────────

echo "── Cross-cutting ──"

NGINX_HEADER=$(curl -sf --max-time 5 -I "${BASE}/health" 2>/dev/null | grep -i "^server:" || echo "")
check_contains "nginx-hides-version" "nginx" "$NGINX_HEADER"
check "nginx-no-version-leak" "true" "$(echo "$NGINX_HEADER" | grep -qP 'nginx/\d' && echo false || echo true)"

GZIP=$(curl -sf --max-time 5 -H "Accept-Encoding: gzip" -o /dev/null -w "%{size_download}" "${BASE}/juice-shop/" 2>/dev/null || echo "0")
NOGZIP=$(curl -sf --max-time 5 -o /dev/null -w "%{size_download}" "${BASE}/juice-shop/" 2>/dev/null || echo "0")
check "gzip-compression-active" "true" "$([ "$GZIP" -lt "$NOGZIP" ] && echo true || echo false)"

# ── 12. Infrastructure (SSH) ─────────────────────────

if $SSH_MODE; then
  echo ""
  echo "── Infrastructure (SSH) ──"

  NGINX_ACTIVE=$(ssh_cmd "systemctl is-active nginx" || echo "unknown")
  check "ssh-nginx-active" "active" "$NGINX_ACTIVE"

  NGINX_TEST=$(ssh_cmd "sudo nginx -t 2>&1 && echo VALID || echo INVALID")
  check_contains "ssh-nginx-config-valid" "VALID" "$NGINX_TEST"

  DOCKER_COUNT=$(ssh_cmd "docker ps -q 2>/dev/null | wc -l" || echo "0")
  check_gte "ssh-docker-container-count" 38 "$DOCKER_COUNT"

  PROGRESS_EXISTS=$(ssh_cmd "test -f /var/log/cloud-init-progress.log && echo yes || echo no")
  check "ssh-progress-log-exists" "yes" "$PROGRESS_EXISTS"

  PROGRESS_LOG=$(ssh_cmd "cat /var/log/cloud-init-progress.log 2>/dev/null" || echo "")
  check_contains "ssh-progress-log-health-check" '\[health-check\]' "$PROGRESS_LOG"
  check_contains "ssh-progress-log-complete" '\[complete\]' "$PROGRESS_LOG"

  SOMAXCONN=$(ssh_cmd "sysctl -n net.core.somaxconn" || echo "0")
  check_gte "ssh-sysctl-somaxconn" 65535 "$SOMAXCONN"

  CRAPI_PG_HEALTH=$(ssh_cmd "docker inspect --format='{{.State.Health.Status}}' crapi-postgres 2>/dev/null" || echo "unknown")
  check "ssh-docker-crapi-postgres-healthy" "healthy" "$CRAPI_PG_HEALTH"

  CRAPI_WEB_HEALTH=$(ssh_cmd "docker inspect --format='{{.State.Health.Status}}' crapi-web 2>/dev/null" || echo "unknown")
  check "ssh-docker-crapi-web-healthy" "healthy" "$CRAPI_WEB_HEALTH"

  NGINX_ERRORS=$(ssh_cmd "sudo journalctl -u nginx --since '5 minutes ago' --priority=err --no-pager -q 2>/dev/null | wc -l" || echo "0")
  check "ssh-no-nginx-errors-last-5min" "0" "$NGINX_ERRORS"
fi

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
