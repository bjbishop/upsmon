#!/usr/bin/env python

"""UPS monitor – reads analog values from an Arduino over serial
and triggers a graceful system shutdown when power is lost."""

import collections
import logging
import os
import pathlib
import signal
import sys
from subprocess import call

import serial

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TTY = os.environ.get("UPSMON_TTY", "ttyACM0")
BAUD = int(os.environ.get("UPSMON_BAUD", "9600"))
ENCODING = "ascii"  # Arduino Serial.println() sends plain ASCII

TMPFILE = pathlib.Path("/run/upsmon/flag")

# Dry-run mode — set the env var OR drop the marker file to enable.
# When active, shutdown/cancel commands are logged but never executed.
# NOTE: the marker file lives in WorkingDirectory (/opt/upsmon), NOT /tmp,
# because the systemd unit uses PrivateTmp=yes which isolates /tmp.
DRYRUN_FILE = pathlib.Path("/opt/upsmon/.dryrun")
DRYRUN = os.environ.get("UPSMON_DRYRUN", "0").strip().lower() in ("1", "true", "yes")

# Hysteresis thresholds – avoids rapid toggling when the ADC value
# hovers near a single cut-off point.  These correspond to the raw
# analogRead() values sent by the Arduino (see upsmon.processing).
THRESHOLD_SHUTDOWN = 10   # avg >= this  → battery light ON  → schedule shutdown
THRESHOLD_CANCEL = 2      # avg <= this  → battery light OFF → cancel shutdown

# Number of consecutive readings that must agree before acting.
WINDOW_SIZE = 3

# How long to wait before powering off once battery is detected.
# Gives time for short blips to self-correct.
SHUTDOWN_DELAY = "+1minute"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
log = logging.getLogger("upsmon")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_dryrun() -> bool:
    """Return True if dry-run mode is active.

    Checked on every decision so you can toggle it at runtime by
    creating or removing /opt/upsmon/.dryrun without restarting the
    service.
    """
    return DRYRUN or DRYRUN_FILE.exists()

# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def schedule_shutdown() -> None:
    """Schedule a delayed poweroff (idempotent via flag-file guard).

    Creates a flag file so subsequent calls are no-ops, then asks
    systemd to power off after SHUTDOWN_DELAY.  If the flag file
    cannot be created, we bail out rather than risk an untracked
    shutdown that cancel_pending_shutdown() can't detect.
    """
    if TMPFILE.exists():
        return
    if is_dryrun():
        log.warning("DRYRUN: would schedule shutdown — skipping")
        return
    try:
        TMPFILE.touch()
    except OSError:
        log.error("Cannot create flag file %s — aborting shutdown", TMPFILE)
        return
    log.warning("SHUTTING DOWN in %s", SHUTDOWN_DELAY)
    call(["/usr/bin/systemctl", "poweroff", f"--when={SHUTDOWN_DELAY}"])


def cancel_pending_shutdown() -> None:
    """Cancel a previously scheduled poweroff and remove the flag file.

    The systemctl cancel runs *before* unlinking the flag so that
    even if the unlink fails, the shutdown is still cancelled.
    """
    if not TMPFILE.exists():
        return
    if is_dryrun():
        log.info("DRYRUN: would cancel shutdown — skipping")
        return
    log.info("Cancelling pending shutdown (removing %s)", TMPFILE)
    call(["/usr/bin/systemctl", "poweroff", "--when=cancel"])
    try:
        TMPFILE.unlink()
    except FileNotFoundError:
        pass

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    # Clean exit on SIGTERM (sent by systemd on stop)
    signal.signal(signal.SIGTERM, lambda _sig, _frame: sys.exit(0))

    ser = serial.Serial(f"/dev/{TTY}", BAUD)
    log.info("Listening on /dev/%s @ %d baud", TTY, BAUD)
    if is_dryrun():
        log.info("*** DRY-RUN MODE ACTIVE — no shutdown commands will be executed ***")

    window: collections.deque[int] = collections.deque(maxlen=WINDOW_SIZE)

    while True:
        try:
            line = ser.readline().decode(ENCODING).strip()
            if not line:
                continue
            value = int(line)
        except (ValueError, UnicodeDecodeError) as exc:
            log.warning("Bad reading, skipping: %s", exc)
            continue
        except serial.SerialException as exc:
            log.error("Serial error: %s", exc)
            break

        window.append(value)
        if len(window) < WINDOW_SIZE:
            continue  # wait until we have enough samples

        avg = sum(window) / WINDOW_SIZE
        log.debug("Raw=%d  Avg=%.1f  Window=%s", value, avg, list(window))

        if avg <= THRESHOLD_CANCEL:
            cancel_pending_shutdown()
        elif avg >= THRESHOLD_SHUTDOWN:
            schedule_shutdown()

    ser.close()


if __name__ == "__main__":
    main()
