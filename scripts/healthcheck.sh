#!/usr/bin/env bash
# Periodic health probe → Healthchecks.io dead-man's-switch.
#
# Pings $HC_URL on success, $HC_URL/fail on app-unreachable. Supply HC_URL
# via /etc/strava-healthcheck.env (see DEPLOY.md §Monitoring).

set -u
: "${HC_URL:?HC_URL env var required (see /etc/strava-healthcheck.env)}"
APP_URL="${APP_URL:-http://127.0.0.1:8000/api/health}"

if curl -sS --max-time 10 -f "$APP_URL" >/dev/null 2>&1; then
  curl -sS --max-time 10 -fsS "$HC_URL" >/dev/null 2>&1
else
  curl -sS --max-time 10 -fsS "${HC_URL}/fail" >/dev/null 2>&1
fi
