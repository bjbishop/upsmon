# upsmon

A Raspberry Pi-based UPS monitoring bridge that reads power state from an Arduino over serial and broadcasts it to the network via [Network UPS Tools (NUT)](https://networkupstools.org/).

Since I couldn't figure out the data cable for my UPS, I decided to use an Arduino and a light sensor to detect when on battery power, and feed that into NUT so the whole network can react to power events.

## How it works

The Arduino reads an analog light sensor (aimed at the UPS battery indicator LED) every few seconds and sends the value over serial. A Python script on the Pi reads these values, applies a rolling average, and writes a NUT state file. NUT's `dummy-ups` driver reads that file and serves it to `upsd`, which broadcasts power state to any NUT client on the network.

```
Arduino (analog light sensor → serial ADC values)
        │
        ▼
upsmon.py (windowed average → writes myups.seq)
        │
        ▼
dummy-ups driver (reads myups.seq in dummy-loop mode)
        │
        ▼
upsd (serves on port 3493)
        │
        ▼
nut-monitor (watches for OB/LB → triggers shutdown)
        │
        ▼
NUT secondary clients (other machines on the network)
```

When 3 consecutive readings average >= 10 (battery light on), `upsmon.py` writes `OB` (on battery) to the NUT state file. When readings drop back to <= 2 (power restored), it writes `OL` (on line). NUT clients react to these state changes and shut down gracefully.

## Hardware

- Raspberry Pi (any model with USB)
- Arduino Uno running `upsmon.processing`, connected via USB (appears as `/dev/ttyACM0`)
- Light sensor aimed at the UPS battery indicator LED
- Arduino sends raw integer ADC values at 9600 baud, one per line

## Files

| File | Purpose |
|---|---|
| `upsmon.processing` | Arduino sketch (upload via Arduino IDE to an Uno) |
| `upsmon.py` | Python bridge — reads serial, writes `myups.seq` |
| `nut-bridge.sh` | Shell wrapper that activates the venv and runs `upsmon.py` |
| `myups.seq` | NUT dummy-ups state file (auto-generated, do not edit manually) |
| `requirements.txt` | Python dependencies (`pyserial`) |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `UPSMON_TTY` | `ttyACM0` | Device name under `/dev/` |
| `UPSMON_BAUD` | `9600` | Serial baud rate |

## Installation

### 1. Python environment

```bash
sudo cp -r . /opt/upsmon
cd /opt/upsmon
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. NUT configuration

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
SHUTDOWNCMD "/sbin/shutdown -h +0"
HOSTSYNC 15
DEADTIME 15
FINALDELAY 180
```

### 3. Systemd service

The `upsmon.py` script runs as its own service, independent of NUT:

```bash
sudo cp upsmon-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now upsmon-bridge.service
```

Upload `upsmon.processing` to the Arduino Uno via the Arduino IDE.

## Usage

```bash
# View live logs from the bridge script
journalctl -fu upsmon-bridge.service

# View NUT monitor logs
journalctl -fu nut-monitor

# Check current UPS status
upsc myups@localhost ups.status

# Stop / start / restart the bridge
sudo systemctl stop upsmon-bridge.service
sudo systemctl start upsmon-bridge.service
sudo systemctl restart upsmon-bridge.service
```

## UPS Status Values

| Status | Meaning |
|---|---|
| `OL` | On line — mains power present |
| `OB` | On battery — power loss detected |
| `OB LB` | On battery, low battery — shutdown cascade triggered |

## Testing

Simulate a power outage without pulling the plug using a test override file:

```bash
# Simulate on battery
echo "OB" | sudo tee /opt/upsmon/test-state

# Simulate low battery (triggers FSD and shutdown cascade)
echo "OB LB" | sudo tee /opt/upsmon/test-state

# Restore to mains
sudo rm /opt/upsmon/test-state
```

The override file is checked on every write cycle (up to 30 seconds) and takes priority over real serial data.

## FSD Recovery

If power is restored before shutdown completes, NUT will show `FSD OL` and will not clear automatically. Restart the NUT stack to recover:

```bash
sudo systemctl restart nut-driver@myups.service
sudo systemctl restart nut-server
sudo systemctl restart nut-monitor
```

## Adding NUT Clients

On each machine to be shut down by this Pi:

1. Install `nut-client`
2. Set `MODE=netclient` in `/etc/nut/nut.conf`
3. Configure `/etc/nut/upsmon.conf`:
```
MONITOR myups@<pi-ip> 1 upsmon <password> secondary
SHUTDOWNCMD "/sbin/shutdown -h +0"
```
4. Open port 3493 on the Pi: `sudo ufw allow 3493/tcp`

## Health Check

The original `upsmon_checker.sh` healthcheck script is no longer applicable in this NUT-based architecture. Use NUT's own status tools instead:

```bash
# Quick status
upsc myups@localhost

# Full variable dump
upsc myups@localhost
```

For external monitoring, consider polling `upsc myups@localhost ups.status` from a cron job or systemd timer and reporting to [Healthchecks.io](https://healthchecks.io).