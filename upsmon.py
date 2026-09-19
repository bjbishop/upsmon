#!/usr/bin/env python3

"""NUT dummy-ups pipe-mode bridge.

Reads analog values from an Arduino over serial (same logic as the
original upsmon.py) and emits NUT key=value lines to stdout so that
the dummy-ups driver can serve them to upsd and its clients.

Run this as the 'port' value in ups.conf:
    [myups]
        driver = dummy-ups
        port = /opt/upsmon/nut-bridge.py
        mode = pipe        # or prefix port with | depending on NUT version
        desc = "Homebrew serial UPS"
"""

import collections
import logging
import os
import signal
import sys
import time
import pathlib
import serial

# ---------------------------------------------------------------------------
# Configuration  (mirrors your existing upsmon.py env-var pattern)
# ---------------------------------------------------------------------------

TTY = os.environ.get("UPSMON_TTY", "ttyACM0")
BAUD = int(os.environ.get("UPSMON_BAUD", "9600"))
ENCODING = "ascii"

# Same thresholds as original — no need to retune anything
THRESHOLD_SHUTDOWN = 10   # avg >= this → on battery
THRESHOLD_CANCEL   = 2    # avg <= this → on mains
WINDOW_SIZE        = 3

# How often to re-emit NUT variables even when state hasn't changed.
# dummy-ups will mark the UPS stale if it stops hearing from us.
REPUBLISH_INTERVAL = 30   # seconds

# Use test file for simulation
OVERRIDE_FILE = pathlib.Path("/opt/upsmon/test-state")

# Static NUT variables we always advertise.
# dummy-ups requires at least ups.status; the rest keep upsmon happy.
NUT_STATIC = {
    "device.mfr":          "Homebrew",
    "device.model":        "ArduinoUPS",
    "battery.voltage.nominal": "12.0",
    "ups.load":            "50",       # we have no real load data; dummy value
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    stream=sys.stderr,          # IMPORTANT: logs go to stderr, NUT data to stdout
)
log = logging.getLogger("nut-bridge")

# ---------------------------------------------------------------------------
# NUT output helpers
# ---------------------------------------------------------------------------

SEQ_FILE = pathlib.Path("/opt/upsmon/myups.seq")


def write_seq(on_battery: bool) -> None:
    status = "OB" if on_battery else "OL"
    batt_charge = "75" if on_battery else "100"

    if OVERRIDE_FILE.exists():
        override = OVERRIDE_FILE.read_text().strip().upper()
        if override in ("OB", "OL", "OB LB"):
            log.info("Test override active: forcing %s", override)
            status = override
            batt_charge = "10" if override == "OB LB" else "75" if override == "OB" else "100"

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    signal.signal(signal.SIGTERM, lambda _s, _f: sys.exit(0))
    try:
        ser = serial.Serial(f"/dev/{TTY}", BAUD)
    except serial.SerialException as exc:
        log.error("Cannot open serial port /dev/%s: %s", TTY, exc)
        sys.exit(1)

    log.info("Listening on /dev/%s @ %d baud", TTY, BAUD)

    window:     collections.deque[int] = collections.deque(maxlen=WINDOW_SIZE)
    on_battery: bool                   = False   # assume mains on startup
    last_emit:  float                  = 0.0

    # Emit an initial state immediately so dummy-ups isn't starved at startup
    write_seq(on_battery)
    last_emit = time.monotonic()

    while True:
        # --- Read one serial line -------------------------------------------
        try:
            line  = ser.readline().decode(ENCODING).strip()
            if not line:
                continue
            value = int(line)
        except (ValueError, UnicodeDecodeError) as exc:
            log.warning("Bad reading, skipping: %s", exc)
            continue
        except serial.SerialException as exc:
            log.error("Serial error: %s", exc)
            break

        # --- Windowed average (identical to original logic) -----------------
        window.append(value)
        if len(window) < WINDOW_SIZE:
            continue

        avg = sum(window) / WINDOW_SIZE
        log.debug("Raw=%d  Avg=%.1f  Window=%s", value, avg, list(window))

        # --- Determine new state --------------------------------------------
        if avg <= THRESHOLD_CANCEL and on_battery:
            on_battery = False
            log.info("Mains restored — emitting OL to NUT")
            write_seq(on_battery)
            last_emit = time.monotonic()

        elif avg >= THRESHOLD_SHUTDOWN and not on_battery:
            on_battery = True
            log.warning("Power loss detected — emitting OB to NUT")
            write_seq(on_battery)
            last_emit = time.monotonic()

        # --- Periodic republish so dummy-ups doesn't go stale ---------------
        elif time.monotonic() - last_emit >= REPUBLISH_INTERVAL:
            write_seq(on_battery)
            last_emit = time.monotonic()

    ser.close()


if __name__ == "__main__":
    main()
