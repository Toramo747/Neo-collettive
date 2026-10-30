#!/usr/bin/env bash
# Load the persisted NEO keys exported from Render (NEO_STATE_JSON, NEO_SETI_PRIVATE_JSON,
# NEO_EVIDENCE_*, NEO_COMMERCIAL_EVIDENCE_*, NEO_CHALLENGE_TRACK_*, BACKUP_*) into the envstore
# volume. Run once, BEFORE the first `systemctl start neo`. Values are never printed.
set -euo pipefail
FILE="${1:?usage: import_state.sh /path/to/render-state.env}"
cd "$(dirname "$0")"
docker compose build --quiet envstore
docker compose run --rm -T -v "$(realpath "$FILE")":/import.env:ro envstore \
  python app.py import /import.env "NEO_STATE_JSON,NEO_SETI_PRIVATE_JSON,NEO_EVIDENCE_,NEO_COMMERCIAL_EVIDENCE_,NEO_CHALLENGE_TRACK_,BACKUP_"
echo "state imported into /srv/neo/state/vars:"
ls /srv/neo/state/vars | sed 's/^/  /' | head -40
