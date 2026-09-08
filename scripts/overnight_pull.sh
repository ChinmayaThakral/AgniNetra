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

START="${1:-2024-11-01}"
DAYS="${2:-3}"
EXPECTED=$((47 * DAYS))
LOG="data/insat_pull.log"
RUNLOG="data/overnight.log"

count_done() { ls data/derived/insat/*.npz 2>/dev/null | wc -l | tr -d ' '; }
stamp() { date "+%Y-%m-%d %H:%M:%S"; }

echo "$(stamp)  starting, target ${EXPECTED} granules from ${START} over ${DAYS} day(s)" | tee -a "$RUNLOG"
echo "$(stamp)  already reduced: $(count_done)" | tee -a "$RUNLOG"

attempt=0
while true; do
  done_now=$(count_done)
  if [ "$done_now" -ge "$EXPECTED" ]; then
    echo "$(stamp)  COMPLETE, ${done_now} of ${EXPECTED} granules reduced" | tee -a "$RUNLOG"
    break
  fi

  attempt=$((attempt + 1))
  echo "$(stamp)  pass ${attempt}, ${done_now} of ${EXPECTED} done, starting pull" | tee -a "$RUNLOG"

  # -i prevents idle sleep, -s prevents system sleep while on mains, -m keeps the
  # disk awake. The assertion lives exactly as long as the command it wraps.
  caffeinate -ims uv run python -u scripts/mosdac_pull.py --start "$START" --days "$DAYS" >> "$LOG" 2>&1

  after=$(count_done)
  echo "$(stamp)  pass ${attempt} ended, ${after} of ${EXPECTED} reduced" | tee -a "$RUNLOG"

  if [ "$after" -le "$done_now" ]; then
    # No progress at all. Back off rather than hammering a link that is down.
    echo "$(stamp)  no progress this pass, sleeping 300s before retrying" | tee -a "$RUNLOG"
    sleep 300
  fi
done

echo "$(stamp)  finished. Run: uv run python scripts/diurnal_profile.py" | tee -a "$RUNLOG"
