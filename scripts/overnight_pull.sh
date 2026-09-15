#!/usr/bin/env bash
# Pull the INSAT-3DS granules unattended, overnight.
#
# Three things this handles that a bare python invocation does not.
#
# Sleep. This machine is set to sleep after one minute on battery, which stops the
# transfer the moment nobody touches the keyboard. `caffeinate` holds it awake for
# as long as the pull runs and releases it the instant the pull exits, so nothing
# is left holding the machine open afterwards.
#
# Crashes. The link stalls and the process can die. The loop restarts it, and the
# pull is idempotent because it skips any granule whose reduced file already
# exists, so a restart costs nothing already downloaded.
#
# Knowing when it is done. It stops on its own once every granule is reduced,
# rather than looping forever against a finished job.
#
# Usage:  bash scripts/overnight_pull.sh [start-date] [days]

set -u
cd "$(dirname "$0")/.."

LOCK="data/.pull.lock"

# Started twice by accident once, which left two runners and six pull processes
# racing for the same part files. A partial written by one and resumed by the other
# is a corrupt granule that still opens. One runner at a time.
if [ -e "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
  echo "already running as PID $(cat "$LOCK"). Nothing started." >&2
  exit 1
fi
mkdir -p data && echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT INT TERM

# Caffeinate stops idle sleep, not a flat battery. Refuse to begin an overnight run
# on a charge that will not survive it.
if pmset -g batt 2>/dev/null | grep -q "Battery Power"; then
  charge=$(pmset -g batt | grep -oE "[0-9]+%" | head -1 | tr -d "%")
  if [ "${charge:-0}" -lt 30 ]; then
    echo "on battery at ${charge}%. Plug in and rerun: an overnight pull will not finish." >&2
    exit 1
  fi
  echo "warning: running on battery at ${charge}%. Plug in." >&2
fi

START="${1:-2024-11-01}"
DAYS="${2:-3}"
# Anything after the day count goes straight to the pull, so a run can ask for
# --keep without this script growing an opinion about every flag the pull has.
if [ "$#" -gt 2 ]; then shift 2; PASS=("$@"); else PASS=(); fi
EXPECTED=$((47 * DAYS))
LOG="data/insat_pull.log"
RUNLOG="data/overnight.log"

# Set OUT_SUBDIR to pull a second season without the two sharing a directory. The
# count and the pull must agree on it, or the loop watches one place and fills another.
OUT_SUBDIR="${OUT_SUBDIR:-insat}"
count_done() { ls "data/derived/$OUT_SUBDIR"/*.npz 2>/dev/null | wc -l | tr -d ' '; }
stamp() { date "+%Y-%m-%d %H:%M:%S"; }

echo "$(stamp)  starting, target ${EXPECTED} granules from ${START} over ${DAYS} day(s)" | tee -a "$RUNLOG"
echo "$(stamp)  already reduced: $(count_done)" | tee -a "$RUNLOG"

# A pass that adds nothing means either the link is down or the catalogue holds
# fewer granules than the nominal schedule implies. The second is the normal case:
# MOSDAC published 47, 45 and 38 for 1 to 3 November 2024 against a nominal 48 a
# day, so a run targeting 47 a day can never reach its target and the old loop
# retried until it was killed. Stop after this many consecutive empty passes, which
# is long enough to ride out a dropped link and short enough not to spin overnight.
STALL_LIMIT=3
stalls=0

attempt=0
while true; do
  done_now=$(count_done)
  if [ "$done_now" -ge "$EXPECTED" ]; then
    echo "$(stamp)  COMPLETE, ${done_now} of ${EXPECTED} granules reduced" | tee -a "$RUNLOG"
    break
  fi
  if [ "$stalls" -ge "$STALL_LIMIT" ]; then
    echo "$(stamp)  STOPPING, ${stalls} passes in a row added nothing. ${done_now} granules reduced." | tee -a "$RUNLOG"
    echo "$(stamp)  That is everything MOSDAC is serving for this range, or the link is down." | tee -a "$RUNLOG"
    break
  fi

  attempt=$((attempt + 1))
  echo "$(stamp)  pass ${attempt}, ${done_now} of ${EXPECTED} done, starting pull" | tee -a "$RUNLOG"

  # -i prevents idle sleep, -s prevents system sleep while on mains, -m keeps the
  # disk awake. The assertion lives exactly as long as the command it wraps.
  caffeinate -ims uv run python -u scripts/mosdac_pull.py \
    --start "$START" --days "$DAYS" --out "$OUT_SUBDIR" \
    ${PASS[@]+"${PASS[@]}"} >> "$LOG" 2>&1

  after=$(count_done)
  echo "$(stamp)  pass ${attempt} ended, ${after} of ${EXPECTED} reduced" | tee -a "$RUNLOG"

  if [ "$after" -le "$done_now" ]; then
    # No progress at all. Back off rather than hammering a link that is down.
    stalls=$((stalls + 1))
    echo "$(stamp)  no progress this pass (${stalls} of ${STALL_LIMIT}), sleeping 300s" | tee -a "$RUNLOG"
    [ "$stalls" -lt "$STALL_LIMIT" ] && sleep 300
  else
    stalls=0
  fi
done

echo "$(stamp)  finished. Run: uv run python scripts/diurnal_profile.py" | tee -a "$RUNLOG"
