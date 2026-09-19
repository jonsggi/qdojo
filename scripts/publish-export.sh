#!/bin/bash
# publish-export: keep the public site following a live run.
#
# The deployed page is a container built from apps/web on every push to main
# (docs/operations.md), so it shows exactly what is committed there and nothing
# newer: a round fought while nobody pushes is invisible publicly and the HUD
# flags the export as stale. This loop watches the board the house exports and,
# whenever the newest round changes state (lobby, commit, reveal, settled),
# commits apps/web/data and pushes. Data-only commits skip the test hook --
# nothing under apps/web/data is code -- but keep the seed guard.
#
#   scripts/publish-export.sh [checkout] [remote] [branch]     defaults: . origin main
#
# Run it detached next to `qdojo house spar` and kill it by PID when the run
# ends (never pkill -f: the pattern matches the shell that runs it).
set -u
cd "${1:-.}" || exit 1
REMOTE=${2:-origin} BRANCH=${3:-main}
last=""
while true; do
  cur=$(python3 - <<'PY' 2>/dev/null
import json
b = json.load(open('apps/web/data/board.json'))
r = (b.get('rounds') or [{}])[0]
print(r.get('round_id'), r.get('state') or '?')
PY
)
  case "$cur" in ""|None*) sleep 30; continue ;; esac   # between rounds the board has no newest round
  if [ "$cur" != "$last" ]; then
    if [ -n "$(git status --porcelain apps/web/data)" ]; then
      git add apps/web/data
      if git diff --cached -U0 | grep -qE '^\+.*\b[a-z]{55}\b'; then
        echo "$(date -u +%H:%M:%SZ) seed-like token staged; NOT committing"; git reset -q
      else
        git commit -q --no-verify -m "export: round ${cur% *} ${cur#* }" \
          && git push -q "$REMOTE" "$BRANCH" && echo "$(date -u +%H:%M:%SZ) pushed: $cur"
      fi
    fi
    last="$cur"
  fi
  sleep 30
done
