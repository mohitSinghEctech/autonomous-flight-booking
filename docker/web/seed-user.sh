#!/bin/sh
set -e
until wget -qO- "http://web:9099/" >/dev/null 2>&1; do sleep 1; done
wget -qO- --header "Content-Type: application/json" \
  --post-data "{\"email\":\"$TEST_USER_EMAIL\",\"password\":\"$TEST_USER_PASSWORD\",\"returnSecureToken\":false}" \
  "http://web:9099/identitytoolkit.googleapis.com/v1/accounts:signUp?key=local" >/dev/null 2>&1 || true
echo "test user ready: $TEST_USER_EMAIL"
