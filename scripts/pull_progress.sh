#!/usr/bin/env bash
# Live progress for the INSAT-3DS pull. Read only, safe to run any time.
#
# Refreshes in place until every granule is reduced. Ctrl C stops the display and
# leaves the pull alone, because this watches the work rather than doing it.
#
# Usage:  bash scripts/pull_progress.sh [days]

set -u
cd "$(dirname "$0")/.."

DAYS="${1:-3}"

# 47 a day was a guess at the nominal schedule and it is wrong: MOSDAC published 47,
# 45 and 38 granules for 1 to 3 November 2024, so a bar drawn against 141 could never
# reach its end. The pull prints the real count for each day it searches, so read the
# target from there and fall back to the guess only when the log has nothing to say.
TARGET=$(grep -Eo '^[0-9]{4}-[0-9]{2}-[0-9]{2}: [0-9]+ granules' data/insat_pull.log 2>/dev/null |
  tail -n "$DAYS" | awk '{sum += $2} END {print sum + 0}')
[ "${TARGET:-0}" -gt 0 ] || TARGET=$((47 * DAYS))
WIDTH=34
START_COUNT=$(ls data/derived/insat/*.npz 2>/dev/null | wc -l | tr -d " ")
START_TIME=$(date +%s)

bar() {
  local done=$1 total=$2 filled i out=""
  filled=$(( done * WIDTH / total ))
  for ((i = 0; i < WIDTH; i++)); do
    if [ "$i" -lt "$filled" ]; then out="${out}#"; else out="${out}."; fi
  done
  printf "%s" "$out"
}

human() {
  local s=$1
  if [ "$s" -lt 60 ]; then printf "%ds" "$s"
  elif [ "$s" -lt 3600 ]; then printf "%dm" $((s / 60))
  else printf "%dh%02dm" $((s / 3600)) $(((s % 3600) / 60)); fi
}

printf "\n"
while true; do
  done=$(ls data/derived/insat/*.npz 2>/dev/null | wc -l | tr -d " ")
  [ "$done" -gt "$TARGET" ] && done=$TARGET
  pct=$(( done * 100 / TARGET ))
  day1=$(ls data/derived/insat/*01NOV2024*.npz 2>/dev/null | wc -l | tr -d " ")

  elapsed=$(( $(date +%s) - START_TIME ))
  gained=$(( done - START_COUNT ))
  if [ "$gained" -gt 0 ] && [ "$elapsed" -gt 0 ]; then
    eta=$(( (TARGET - done) * elapsed / gained ))
    eta_text=$(human "$eta")
  else
    eta_text="measuring"
  fi

  if pgrep -f mosdac_pull >/dev/null 2>&1; then state="running"
  elif pgrep -f overnight_pull.sh >/dev/null 2>&1; then state="restarting"
  else state="STOPPED"; fi

  printf "\r  [%s] %3d%%  %3d/%-3d  day1 %2d/47  %-10s eta %-8s" \
    "$(bar "$done" "$TARGET")" "$pct" "$done" "$TARGET" "$day1" "$state" "$eta_text"

  if [ "$done" -ge "$TARGET" ]; then
    printf "\n\n  complete. Next: uv run python scripts/diurnal_profile.py\n\n"
    break
  fi
  sleep 20
done
