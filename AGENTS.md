# AGENTS.md — upsmon project context

This file provides context for AI-assisted development sessions on this project.

## What this project does

Bridges a homebrew Arduino-based UPS monitor to NUT (Network UPS Tools) so that power loss events are broadcast to NUT clients on the network. The Arduino reads an analog light sensor aimed at the UPS battery indicator LED and sends the value over serial. A Python script on a Raspberry Pi reads these values and writes a NUT state file that the `dummy-ups` driver serves to `upsd` and its clients.

## Repository branches

- `main` — original standalone Python shutdown script (no NUT)
- `nut` — current branch; NUT integration replacing the direct shutdown approach

## Hardware

- Raspberry Pi 3 running Raspberry Pi OS (headless)
- Arduino Uno running `upsmon.processing`, connected via USB at `/dev/ttyACM0`, 9600 baud
- Arduino sends raw integer ADC values, one per line
- Low value (~0) = mains power present (light sensor dark)
- High value (≥10) = power loss detected (battery LED on)
- Pi 3 does not cut its own power on `shutdown -h` — use `-P` for true poweroff

## Key files and their roles

| File | Role |
|---|---|
| `/opt/upsmon/upsmon.py` | Main Python script. Reads serial, applies windowed average, writes `myups.seq`. Runs as a systemd service via `nut-bridge.sh`. |
| `/opt/upsmon/nut-bridge.sh` | Shell wrapper. Activates `.venv` and execs `upsmon.py`. Called by `upsmon-bridge.service`. |
| `/opt/upsmon/myups.seq` | NUT dummy-ups state file. Written by `upsmon.py`, read by `dummy-ups`. Must be owned by `nut:nut`. Do not edit manually. |
| `/opt/upsmon/test-state` | Optional test override file. If present, overrides real serial state. Valid values: `OB`, `OL`, `OB LB`. Automatically deleted at service start via `ExecStartPre`. |
| `/opt/upsmon/upssched-cmd.sh` | Called by upssched when timers fire. Handles `onbatt-shutdown` (writes `OB LB` to test-state) and `online` (cleans up test-state). |
| `/opt/upsmon/.venv/` | Python virtualenv containing `pyserial`. |
| `/etc/nut/ups.conf` | NUT driver config. Points `dummy-ups` at `myups.seq` in `dummy-loop` mode. |
| `/etc/nut/upssched.conf` | upssched timer config. 10-minute ONBATT timer escalates to OB LB. |
| `/etc/nut/upsmon.conf` | NUT monitor config. `FINALDELAY 180`, `HOSTSYNC 15`, `DEADTIME 15`. |
| `/etc/systemd/system/upsmon-bridge.service` | Systemd unit for `upsmon.py`. Runs as root, restarts on failure, clears test-state on start. |
| `/etc/systemd/system/nut-monitor.service.d/timeout.conf` | Drop-in that sets `TimeoutStopSec=300` so systemd doesn't kill nut-monitor during FINALDELAY. |

## NUT configuration files

**`/etc/nut/nut.conf`**
```
MODE=netserver
```

**`/etc/nut/ups.conf`**
```ini
[myups]
    driver = dummy-ups
    port = /opt/upsmon/myups.seq
    mode = dummy-loop
    desc = "Homebrew serial UPS"
```

**`/etc/nut/upsd.conf`**
```
LISTEN 0.0.0.0 3493
```

**`/etc/nut/upsd.users`**
```ini
[upsmon]
    password = yourpassword
    upsmon primary
```

**`/etc/nut/upsmon.conf`**
```
MONITOR myups@localhost 1 upsmon yourpassword primary
SHUTDOWNCMD "/sbin/shutdown -P now"
NOTIFYCMD /usr/sbin/upssched
NOTIFYFLAG ONBATT       SYSLOG+WALL+EXEC
NOTIFYFLAG ONLINE       EXEC
NOTIFYFLAG LOWBATT      SYSLOG+WALL
NOTIFYFLAG SHUTDOWN     SYSLOG+WALL
HOSTSYNC 15
DEADTIME 15
FINALDELAY 180
```

**`/etc/nut/upssched.conf`**
```ini
CMDSCRIPT /opt/upsmon/upssched-cmd.sh
PIPEFN /run/nut/upssched.pipe
LOCKFN /run/nut/upssched.lock

AT ONBATT * START-TIMER onbatt-shutdown 600
AT ONLINE * EXECUTE online
```

**`/opt/upsmon/upssched-cmd.sh`**
```bash
#!/bin/bash
case "$1" in
    onbatt-shutdown)
        logger -t upssched "10 minutes on battery reached — forcing OB LB"
        echo "OB LB" > /opt/upsmon/test-state
        ;;
    online)
        logger -t upssched "Power restored — cleaning up test-state"
        rm -f /opt/upsmon/test-state
        ;;
esac
```

**`/etc/systemd/system/upsmon-bridge.service`**
```ini
[Unit]
Description=Homebrew UPS serial monitor bridge
After=network.target
Before=nut-driver@myups.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/upsmon
ExecStartPre=/bin/rm -f /opt/upsmon/test-state
ExecStart=/opt/upsmon/nut-bridge.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/nut-monitor.service.d/timeout.conf`**
```ini
[Service]
TimeoutStopSec=300
```

## Architecture decisions and history

### Why dummy-ups instead of a real NUT driver?
The UPS has no data port and no NUT driver. The Arduino reads the UPS state via a light sensor and sends it as a serial integer. Rather than write a full NUT driver, we use `dummy-ups` in `dummy-loop` mode to serve a state file that `upsmon.py` writes.

### Why a .seq file instead of pipe mode?
NUT 2.8.1's `dummy-ups` does NOT support pipe mode. Only dummy (file) mode and repeater mode exist. Attempts to use `mode = pipe` or `port = |script.sh` both failed — the driver either ignored the mode key or tried to open the pipe prefix as a literal filename. The solution is `upsmon.py` writing `/opt/upsmon/myups.seq` directly, with `dummy-ups` reading it in `dummy-loop` mode.

### Why a separate systemd service for upsmon.py?
Originally `nut-bridge.sh` was intended to be called by `dummy-ups` as a pipe-mode script. When pipe mode was found unsupported, `dummy-ups` was reconfigured to read a file. `upsmon.py` needed its own independent systemd service (`upsmon-bridge.service`) to keep running and updating the seq file.

### Why does upsmon.py run as root?
`/dev/ttyACM0` is owned by `root:dialout`. Running the service as root is the simplest solution. Alternative: add the `nut` user to the `dialout` group and run as `nut`.

### Why -P instead of -h in SHUTDOWNCMD?
`shutdown -h` halts the OS but the Pi 3 does not cut its own power — it sits halted with power applied. `shutdown -P now` signals the PMIC to actually cut power so the Pi turns off and restarts cleanly when power is reapplied.

### Why ExecStartPre clears test-state?
After a real outage, `upssched-cmd.sh` writes `OB LB` to `test-state`. If the Pi shuts down before the `online` cleanup runs, `test-state` persists on disk. On next boot, `upsmon-bridge` reads it, writes `OB LB` to the seq file, NUT triggers FSD again, and the Pi shuts down in a boot loop. `ExecStartPre=/bin/rm -f /opt/upsmon/test-state` breaks this loop unconditionally on every start.

### Why TimeoutStopSec=300 on nut-monitor?
`FINALDELAY 180` means nut-monitor waits 180 seconds after FSD before running `SHUTDOWNCMD`. Systemd's default `TimeoutStopSec` is shorter and was killing nut-monitor mid-countdown before the shutdown command could execute. Setting `TimeoutStopSec=300` gives nut-monitor enough time to complete the full FINALDELAY sequence.

### Why upssched for OB LB escalation?
The Arduino only detects presence/absence of the battery LED — it has no way to report actual battery level. Without a real low-battery signal, NUT would sit at `OB` indefinitely. `upssched` starts a 600-second (10 minute) timer on `ONBATT` and escalates to `OB LB` by writing to `test-state` if power isn't restored in time.

### Multiple NOTIFYFLAG entries for the same event
Only one `NOTIFYFLAG` entry per event is respected. Use `+` to combine flags:
```
NOTIFYFLAG ONBATT SYSLOG+WALL+EXEC   # correct
```
Not two separate lines — the second overwrites the first.

### FSD state does not survive a reboot
A clean boot always starts fresh — FSD is not persisted to disk. The boot loop issue was caused by the stale `test-state` file, not persisted FSD state.

## NUT service names on this system

```
nut-driver@myups.service   — dummy-ups driver instance (reads myups.seq)
nut-server                 — upsd, serves port 3493
nut-monitor                — upsmon daemon, watches state, triggers shutdown
upsmon-bridge.service      — our custom Python bridge (writes myups.seq)
```

## Restart order after config changes

After changes to `upsmon.py` or `nut-bridge.sh`:
```bash
sudo systemctl restart upsmon-bridge.service
```

After changes to `upsmon-bridge.service` unit file:
```bash
sudo systemctl daemon-reload
sudo systemctl restart upsmon-bridge.service
```

After changes to `/etc/nut/*.conf` or NUT services (no FSD active):
```bash
sudo systemctl restart nut-driver@myups.service
sudo systemctl restart nut-server
sudo systemctl restart nut-monitor
```

## FSD recovery (manual)

**WARNING: Never restart `nut-monitor` while FSD is still set in upsd.** When nut-monitor stops with FSD active it interprets the stop as a shutdown situation and runs `SHUTDOWNCMD`, causing an immediate shutdown. Always restart the driver and server first to clear FSD from upsd's memory, then wait for them to fully settle before restarting nut-monitor.

This Pi 3 runs at 700MHz and is slow — use a 15 second sleep between steps:

```bash
sudo systemctl restart nut-driver@myups.service
sudo systemctl restart nut-server
sleep 15
sudo systemctl restart nut-monitor
```

Then confirm:
```bash
upsc myups@localhost ups.status   # should show OL with no FSD
```

Note: a clean reboot also clears FSD since it is not persisted to disk. After reboot the safe restart sequence above is still required to clear the `FSD OL` state that appears on first boot after a shutdown.

## Key thresholds in upsmon.py

```python
THRESHOLD_SHUTDOWN = 10    # windowed avg >= this → write OB (on battery)
THRESHOLD_CANCEL   = 2     # windowed avg <= this → write OL (mains restored)
WINDOW_SIZE        = 3     # number of serial readings in the rolling average
REPUBLISH_INTERVAL = 30    # seconds between seq file rewrites when state unchanged
```

## Testing procedure

```bash
# Simulate outage
echo "OB" | sudo tee /opt/upsmon/test-state
upsc myups@localhost ups.status   # should show OB within 30s

# Simulate low battery / shutdown trigger
echo "OB LB" | sudo tee /opt/upsmon/test-state
upsc myups@localhost ups.status   # should show FSD OB LB

# Restore (also done automatically by upssched-cmd.sh on ONLINE event)
sudo rm /opt/upsmon/test-state
# Then restart NUT stack to clear FSD if needed
```

## Known issues / future work

- `battery.charge` is a dummy value (75 on battery, 100 on mains) — Arduino does not report real battery level
- `ups.load` is a dummy value (50) — no real load monitoring
