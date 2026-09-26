# upsmon

A Raspberry Pi-based UPS monitoring bridge that reads power state from an Arduino over serial and broadcasts it to the network via [Network UPS Tools (NUT)](https://networkupstools.org/).

Since I couldn't figure out the data cable for my UPS, I decided to use an Arduino and a light sensor to detect when on battery power, and feed that into NUT so the whole network can react to power events.

## How it works

The Arduino reads an analog light sensor (aimed at the UPS battery indicator LED) every few seconds
and sends the value over serial. A Python script on the Pi reads these values, applies a rolling
average, and writes a NUT state file. NUT's `dummy-ups` driver reads that file and serves it to
`upsd`, which broadcasts power state to any NUT client on the network. If power isn't restored
within 10 minutes, `upssched` escalates the battery status to trigger a graceful shutdown cascade.

```
Arduino (analog light sensor → serial ADC values)
│
▼
upsmon-bridge.service
(runs upsmon.py via nut-bridge.sh)
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
upssched (10-min battery timer → escalates OB to OB LB)
│
▼
nut-monitor (watches for OB LB → triggers shutdown)
│
▼
NUT secondary clients (other machines on the network)
```

When 3 consecutive readings average >= 10 (battery light on), `upsmon.py` writes `OB` (on battery)
to the NUT state file. When readings drop back to <= 2 (power restored), it writes `OL` (on line).
If power isn't restored within 10 minutes, `upssched` automatically escalates to `OB LB` (low
battery), triggering the shutdown cascade across all NUT clients.

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
| `myups.seq` | NUT dummy-ups state file (auto-generated and git ignored, do not edit manually) |
| `requirements.txt` | Python dependencies (`pyserial`) |
| `upssched-cmd.sh` | Helper script to force a "low battery" signal into NUT for shutdowns |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `UPSMON_TTY` | `ttyACM0` | Device name under `/dev/` |
| `UPSMON_BAUD` | `9600` | Serial baud rate |

## Installation

### 1. Python environment

```bash
sudo apt install nut # meta package
sudo mkdir -p /opt/upsmon
sudo chmod 755 /opt/upsmon
sudo chown nut:nut /opt/upsmon
sudo cp -r . /opt/upsmon
cd /opt/upsmon
sudo su -
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo chown -R nut:nut /opt/upsmon
groupmod -a -U nut dialout # add the nut user to be able to read serial data from the Arduino
```

### 2. NUT configuration

**`/etc/nut/nut.conf`**
```
MODE=netserver
```

**`/etc/nut/ups.conf`**
```ini

maxretry = 3

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
[admin]
	password = adminpass
	actions = SET
	instcmds = ALL

[monuser]
	password  = monuserpass
	upsmon primary
```

**`/etc/nut/upsmon.conf`**
```
RUN_AS_USER root
MONITOR myups@localhost 1 monuser monuserpass primary
MINSUPPLIES 1
SHUTDOWNCMD "/sbin/shutdown -P now"
POLLFREQ 5
POLLFREQALERT 5
HOSTSYNC 15
DEADTIME 15
POWERDOWNFLAG "/run/nut/killpower"
OFFDURATION 30
RBWARNTIME 43200
NOCOMMWARNTIME 300
FINALDELAY 120
NOTIFYFLAG LOWBATT      SYSLOG+WALL
NOTIFYFLAG SHUTDOWN     SYSLOG+WALL
NOTIFYFLAG ONBATT       SYSLOG+WALL+EXEC
NOTIFYFLAG ONLINE       SYSLOG+WALL+EXEC
NOTIFYCMD /usr/sbin/upssched
```

**`/etc/nut/upssched.conf`**
```
CMDSCRIPT /opt/upsmon/upssched-cmd.sh
PIPEFN /run/nut/upssched.pipe
LOCKFN /run/nut/upssched.lock
AT ONBATT * START-TIMER onbatt-shutdown 600
AT ONLINE * EXECUTE online
```


### 3. Systemd service

The `upsmon.py` script runs as its own service, independent of NUT:

```bash
sudo cp upsmon-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now upsmon-bridge.service
```

The nut-monitor systemd service needs a timeout override.  Because upsmon.conf has FINALDELAY set to 180, nut-monitor waits 180 seconds before running SHUTDOWNCMD, but systemd's service timeout is shorter and the monitor gets killed. Fix by adding a long TimeoutStopSec to nut-monitor. Create a systemd drop-in:

```bash
sudo mkdir -p /etc/systemd/system/nut-monitor.service.d
sudo tee /etc/systemd/system/nut-monitor.service.d/timeout.conf << 'EOF'
[Service]
TimeoutStopSec=300
EOF
sudo systemctl daemon-reload
```

Upload `upsmon.processing` to the Arduino Uno via the Arduino IDE, put the light sensor directly next to the UPS light and cover everything with electrical tape to avoid light leakage.  Yes, this is a hack, I know, but it works!

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

If power is restored before shutdown completes, NUT will show `FSD OL` and it *might* not clear automatically. If needed, restart the NUT stack to recover:

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


