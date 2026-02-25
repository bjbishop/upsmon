#!/bin/sh
# -----------------------------------------------------------------------
# upsmon_checker.sh — External watchdog for the upsmon service.
#
# Reports service health to Healthchecks.io so you get alerted if the
# UPS monitor stops working.  Designed to run via a systemd timer or
# cron every few minutes.
#
# Checks (in order):
#   1. Is upsmon.service active?
#   2. Does the serial port exist?
#   3. Is the shutdown flag file present?
#
# See the README "Health Check" section for the decision matrix.
# -----------------------------------------------------------------------

set -o errexit -o nounset

FLAGFILE=${FLAGFILE:-/run/upsmon/flag}
UPSMON_SERVICE=upsmon.service
PORT=${PORT:-/dev/ttyACM0}
HCPING=6cd441db-efd1-47ac-9734-ab04a732b704
TAG="upsmon_checker"

# Send all subsequent output to the systemd journal (and still to
# stderr for interactive debugging).  Uses logger(1) via a file
# descriptor so every echo/command output goes to the journal
# tagged with $TAG.
exec > >(logger -t "$TAG") 2>&1

healthcheck_up() {
    curl -fsS -m 10 --retry 5 -o /dev/null https://hc-ping.com/${HCPING}
}

healthcheck_down() {
    curl -fsS -m 10 --retry 5 -o /dev/null https://hc-ping.com/${HCPING}/fail
}

# -----------------------------------------------------------------------
# Pre-flight: make sure the upsmon service (which owns the flag file and
# the /run/upsmon directory via RuntimeDirectory=) is active.  If it
# isn't running, /run/upsmon won't exist and there's nothing to check.
# -----------------------------------------------------------------------
if ! systemctl is-active --quiet "$UPSMON_SERVICE"; then
    echo "$UPSMON_SERVICE is not running — nothing to check"
    healthcheck_down
    false
fi

# -----------------------------------------------------------------------
# Main logic.  The flag file is managed exclusively by the Python
# service; this script only *reads* it to determine state.
# -----------------------------------------------------------------------
if [ -c "$PORT" ]; then
    if [ -f "$FLAGFILE" ]; then
	# Power is back but the service hasn't cancelled yet.
	# The Python process will see the ADC readings drop and
	# remove the flag + cancel the shutdown on its own.
	echo "Port present but flag file exists — awaiting service cancel"
	healthcheck_up
    else
	echo "ALL GOOD: flag file not present and port exists"
	healthcheck_up
    fi
    true
else
    echo "$PORT does NOT exist"
    if [ -f "$FLAGFILE" ]; then
	echo "$FLAGFILE exists — shutdown already in progress"
	[ -f /run/systemd/shutdown/scheduled ] && cat /run/systemd/shutdown/scheduled
    else
	# Port disappeared but the service hasn't reacted yet.
	echo "Flag file not yet created — waiting for service to detect power loss"
    fi
    healthcheck_down
    false
fi
