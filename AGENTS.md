# AGENTS.md — upsmon project context

This file provides context for AI-assisted development sessions on this project.

## What this project does

Bridges a homebrew Arduino-based UPS monitor to NUT (Network UPS Tools) so that power loss events are broadcast to NUT clients on the network. The Arduino reads an analog value from the UPS circuit and sends it over serial. A Python script on a Raspberry Pi reads these values and writes NUT state files that the `dummy-ups` driver serves to `upsd`.

## Hardware

- Raspberry Pi running Raspberry Pi OS
- Arduino on `/dev/ttyACM0` at 9600 baud
- Arduino sends raw integer ADC values, one per line
- Low value (~0) = mains power OK
- High value (≥10) = power loss

## Key files and their roles

| File | Role |
|---|---|
| `/opt/upsmon/upsmon.py` | Main Python script. Reads serial, applies windowed average, writes `myups.seq`. Runs as a systemd service via `nut-bridge.sh`. |
| `/opt/upsmon/nut-bridge.sh` | Shell wrapper. Activates `.venv` and execs `upsmon.py`. This is what systemd and (previously) NUT's `dummy-ups` called. |
| `/opt/upsmon/myups.seq` | NUT dummy-ups state file. Written by `upsmon.py`, read by `dummy-ups`. Must be owned by `nut:nut`. Do not edit manually. |
| `/opt/upsmon/test-state` | Optional test override file. If present, overrides real serial state. Values: `OB`, `OL`, `OB LB`. Delete to restore normal operation. |
| `/opt/upsmon/.venv/` | Python virtualenv containing `pyserial`. |
| `/etc/nut/ups.conf` | NUT driver config. Points `dummy-ups` at `myups.seq`. |
| `/etc/nut/upsmon.conf` | NUT monitor config. `FINALDELAY 180`, `HOSTSYNC 15`, `DEADTIME 15`. |
| `/etc/systemd/system/upsmon-bridge.service` | Systemd unit for `upsmon.py`. Runs as root, restarts on failure. |

## Architecture decisions and history

### Why dummy-ups instead of a real driver?
The UPS is a no-name unit with no NUT driver. The Arduino reads the UPS state over analog and sends it as a serial integer. Rather than write a full NUT driver, we use `dummy-ups` in `dummy-loop` mode to serve a state file.

### Why a .seq file instead of pipe mode?
NUT 2.8.1's `dummy-ups` does not support pipe mode — it only supports dummy (file) mode and repeater mode. Earlier attempts to use `mode = pipe` or `port = |script.sh` failed. The solution is `upsmon.py` writing `/opt/upsmon/myups.seq` directly, with `dummy-ups` reading it in `dummy-loop` mode.

### Why a separate systemd service for upsmon.py?
Originally `nut-bridge.sh` was called directly by `dummy-ups` as a pipe-mode script. When pipe mode was found to be unsupported, `dummy-ups` was reconfigured to read a file. `upsmon.py` needed its own independent systemd service (`upsmon-bridge.service`) to keep running and writing the seq file.

### Why does upsmon.py run as root?
The `nut` user does not have access to `/dev/ttyACM0` (owned by `root:dialout`). Running as root is the simplest solution. Alternative: add `nut` to the `dialout` group.

## NUT service names on this system

```
nut-driver@myups.service   — dummy-ups driver instance
nut-server                 — upsd, serves port 3493
nut-monitor                — upsmon, watches state and triggers shutdown
upsmon-bridge.service      — our custom Python bridge script
```

## Restart order after config changes

Always restart in this order:
```bash
sudo systemctl restart nut-driver@myups.service
sudo systemctl restart nut-server
sudo systemctl restart nut-monitor
```

After changes to `upsmon.py` or `nut-bridge.sh`:
```bash
sudo systemctl restart upsmon-bridge.service
```

## FSD (Forced Shutdown) recovery

If power is restored before shutdown completes, NUT shows `FSD OL`. It does not clear automatically. Fix:
```bash
sudo systemctl restart nut-driver@myups.service
sudo systemctl restart nut-server
sudo systemctl restart nut-monitor
```

A `NOTIFYCMD` script on `ONLINE` events can automate this — not yet implemented.

## Key thresholds in upsmon.py

```python
THRESHOLD_SHUTDOWN = 10    # windowed avg >= this → OB (on battery)
THRESHOLD_CANCEL   = 2     # windowed avg <= this → OL (mains restored)
WINDOW_SIZE        = 3     # number of readings in the rolling average
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

# Restore
sudo rm /opt/upsmon/test-state
# Then restart NUT stack to clear FSD
```

## Known issues / future work

- FSD recovery requires manual service restart (NOTIFYCMD automation not yet implemented)
- No NUT secondary clients configured yet — Pi is standalone primary
- `battery.charge` is a dummy value (75 on battery, 100 on mains) — Arduino does not report real battery level
- `ups.load` is a dummy value (50) — no real load monitoring
- Port 3493 firewall rule not yet configured (`ufw allow 3493/tcp`)