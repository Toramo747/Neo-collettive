#!/usr/bin/env bash
# Replace the old Render origin with the new domain everywhere in the repo.
#   ops/hetzner/rename_origin.sh osixbay.it            # dry run: lists files and counts
#   ops/hetzner/rename_origin.sh osixbay.it --apply    # rewrites the files
# Jarvis: jarvis-23lu.onrender.com -> jarvis.<domain>. Review the diff, then commit.
set -euo pipefail
NEW="${1:?usage: rename_origin.sh <new-domain> [--apply]}"
MODE="${2:-}"
cd "$(git rev-parse --show-toplevel)"
OLD_NEO="neo-collettive.onrender.com"
OLD_JARVIS="jarvis-23lu.onrender.com"
FILES=$(git grep -l -e "$OLD_NEO" -e "$OLD_JARVIS" -- . ':!ops/hetzner/rename_origin.sh' ':!*.lock' || true)
if [ -z "$FILES" ]; then echo "nothing to rename"; exit 0; fi
echo "$FILES" | while read -r f; do
  printf '%4d  %s\n' "$(grep -c -e "$OLD_NEO" -e "$OLD_JARVIS" "$f")" "$f"
done
echo "total files: $(echo "$FILES" | wc -l)"
if [ "$MODE" != "--apply" ]; then echo "(dry run; add --apply to rewrite)"; exit 0; fi
echo "$FILES" | xargs sed -i -e "s#$OLD_NEO#$NEW#g" -e "s#$OLD_JARVIS#jarvis.$NEW#g"
echo "rewritten. Remaining references to onrender.com (should be only comments/history):"
git grep -n "onrender.com" -- . ':!ops/hetzner/rename_origin.sh' | head -20 || true
