#!/bin/sh

set -o errexit -o nounset

LOCKFILE=${LOCKFILE:-/tmp/upsmon_checker.lock}
PORT=${PORT:-/dev/ttyU0}
HCPING=6cd441db-efd1-47ac-9734-ab04a732b704

healthcheck_up() {
    curl -fsS -m 10 --retry 5 -o /dev/null https://hc-ping.com/${HCPING}
}

healthcheck_down() {
    curl -fsS -m 10 --retry 5 -o /dev/null https://hc-ping.com/${HCPING}/fail
}

if [ -c $PORT ]; then
    if [ -f $LOCKFILE ]; then
	rm $LOCKFILE
	echo "$LOCKFILE removed"
	if pgrep -fl shutdown; then
	    echo "Cancel the running shutdown"
	    pkill shutdown
	else
	    echo "A shutdown should be running but is not"
	    healthcheck_down
	    false
	fi
    else
	echo "ALL GOOD: lockfile not present and port exists"
    fi
    healthcheck_up
    true
else
    echo "$PORT does NOT exist"
    if [ -f $LOCKFILE ]; then
	echo "$LOCKFILE already exists, shutdown already in progress"
	pgrep shutdown
    else
	touch $LOCKFILE
	echo "Created $LOCKFILE, shutting down"
	nohup shutdown -p +15 2>&1 &
    fi
    healthcheck_down
    false
fi
