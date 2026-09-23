#!/bin/bash
# combat-publish: keep the public site following the live combat devnet.
#
# The deployed page is built from apps/web on every push to main, so live
# fights only reach spectators when their export is committed. This loop
# commits apps/web/data/combat/v1 when it changed, at most every INTERVAL
# seconds, and pushes the current branch to main. Data-only commits skip the
# test hook -- nothing under apps/web/data is code -- but keep the seed guard.
#
#   scripts/combat-publish.sh [checkout] [interval-seconds] [remote] [target-branch]
#       defaults: . 180 origin main
#
# Run it detached next to `qdojo combat live` and stop it by PID (never pkill -f).
set -u
cd "${1:-.}" || exit 1
INTERVAL=${2:-180} REMOTE=${3:-origin} TARGET=${4:-main}
DATA=apps/web/data/combat/v1
while true; do
  if [ -n "$(git status --porcelain -- "$DATA")" ]; then
    git add -A -- "$DATA"
    if git diff --cached -U0 | grep -qE '^\+.*\b[a-z]{55}\b'; then
      echo "$(date -u +%H:%M:%SZ) seed-like token staged; NOT committing"; git reset -q
    else
      tick=$(python3 -c "import json;print(json.load(open('$DATA/index.json'))['generated_tick'])" 2>/dev/null)
      git commit -q --no-verify -m "combat export: devnet tick ${tick:-?}" -- "$DATA"
      if git push -q "$REMOTE" "HEAD:$TARGET"; then
        echo "$(date -u +%H:%M:%SZ) pushed tick ${tick:-?}"
      else
        echo "$(date -u +%H:%M:%SZ) push refused; rebasing onto $REMOTE/$TARGET"
        git pull -q --rebase "$REMOTE" "$TARGET" && git push -q "$REMOTE" "HEAD:$TARGET" \
          && echo "$(date -u +%H:%M:%SZ) pushed after rebase"
      fi
    fi
  fi
  sleep "$INTERVAL"
done
