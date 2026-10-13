#!/usr/bin/env bash
set -euo pipefail
echo "Arena smoke request: /arena"
curl --fail --silent --show-error -H "X-MYCELIX-Self-Traffic: github-actions-deploy" -H "X-MYCELIX-Self-Traffic-Proof: $(NEO_HEARTBEAT_TOKEN="${HEARTBEAT_TOKEN}" python self_traffic_auth.py sign-url 'https://neo-collettive.onrender.com/arena' --marker github-actions-deploy)" --max-time 30 "https://neo-collettive.onrender.com/arena" > /tmp/arena.html
grep -q "NEO Arena" /tmp/arena.html
grep -q "mycelix-arena" /tmp/arena.html
echo "Arena smoke request: /arena/neo-dialect"
curl --fail --silent --show-error -H "X-MYCELIX-Self-Traffic: github-actions-deploy" -H "X-MYCELIX-Self-Traffic-Proof: $(NEO_HEARTBEAT_TOKEN="${HEARTBEAT_TOKEN}" python self_traffic_auth.py sign-url 'https://neo-collettive.onrender.com/arena/neo-dialect' --marker github-actions-deploy)" --max-time 30 "https://neo-collettive.onrender.com/arena/neo-dialect" > /tmp/arena-neo-dialect.html
grep -q "neo-dialect evolution study" /tmp/arena-neo-dialect.html
grep -q "neo-dialect 1.0 is sufficient for now" /tmp/arena-neo-dialect.html
grep -q "arena-dialect-study-" /tmp/arena-neo-dialect.html
echo "Arena smoke request: /arena/micelio"
curl --fail --silent --show-error -H "X-MYCELIX-Self-Traffic: github-actions-deploy" -H "X-MYCELIX-Self-Traffic-Proof: $(NEO_HEARTBEAT_TOKEN="${HEARTBEAT_TOKEN}" python self_traffic_auth.py sign-url 'https://neo-collettive.onrender.com/arena/micelio' --marker github-actions-deploy)" --max-time 30 "https://neo-collettive.onrender.com/arena/micelio" > /tmp/micelio.html
grep -q "Micelio" /tmp/micelio.html
grep -q "Memoria verificata" /tmp/micelio.html
echo "Arena smoke request: /arena/evoluzione"
curl --fail --silent --show-error -H "X-MYCELIX-Self-Traffic: github-actions-deploy" -H "X-MYCELIX-Self-Traffic-Proof: $(NEO_HEARTBEAT_TOKEN="${HEARTBEAT_TOKEN}" python self_traffic_auth.py sign-url 'https://neo-collettive.onrender.com/arena/evoluzione' --marker github-actions-deploy)" --max-time 30 "https://neo-collettive.onrender.com/arena/evoluzione" > /tmp/evoluzione.html
grep -q "Evoluzione" /tmp/evoluzione.html
grep -q "promozione automatica" /tmp/evoluzione.html
echo "Arena, Micelio and Evoluzione read-only surfaces healthy"
