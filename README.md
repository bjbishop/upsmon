UPSMON
======

Since I couldn't figure out the data cable for my UPS, I decided to us my Arduino and a light sensor as a fun project to detect when on battery power.


Goals
-----

When the battery is detected to be engaged, send the signal to shutdown the OS.

If the power is reconnected, the battery light goes off sending the signal to cancel the running shutdown.


Code
----

* upsmon.processing

The processing code uploaded to the arduino.  I'm using an UNO

* upsmon.py

A python script to monitor of incoming signals from the Arduino


Environment Variables
---------------------

| Variable | Default | Description |
|---|---|---|
| `UPSMON_TTY` | `ttyACM0` | Device name under `/dev/` |
| `UPSMON_BAUD` | `9600` | Serial baud rate |
| `UPSMON_DRYRUN` | `0` | Set to `1` to suppress real shutdown/cancel commands |


Installation
------------

```bash
# Copy project to /opt/upsmon
sudo cp -r . /opt/upsmon
cd /opt/upsmon

# Create venv and install deps
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Install and enable the systemd service
sudo cp upsmon.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now upsmon
```

Upload `upsmon.processing` to the Arduino Uno via the Arduino IDE.


Usage
-----

The service starts automatically on boot and watches `/dev/ttyACM0`.

```bash
# View live logs
journalctl -u upsmon -f

# Stop / start / restart
sudo systemctl stop upsmon
sudo systemctl start upsmon
sudo systemctl restart upsmon

# Check service health (used by cron / healthcheck)
./upsmon_checker.sh
```

**How it works:** The Arduino reads an analog light sensor every 5 seconds and sends the value over serial. When 3 consecutive readings average >= 10 (battery light on), `schedule_shutdown()` queues a 1-minute delayed poweroff. When readings drop back to <= 2 (power restored), `cancel_pending_shutdown()` cancels it.

A flag file at `/run/upsmon/flag` prevents duplicate shutdown calls and is managed automatically by the service via `RuntimeDirectory=upsmon`.


Health Check (upsmon_checker.sh)
--------------------------------

An external watchdog script that reports service status to [Healthchecks.io](https://healthchecks.io) via `hc-ping.com`. Run it from cron or a systemd timer to get alerts when the UPS monitor is unhealthy.

It checks three things in order:
1. Is `upsmon.service` active? If not → ping **fail** and exit.
2. Does the serial port (`/dev/ttyACM0`) exist?
3. Is the shutdown flag file (`/run/upsmon/flag`) present?

| Port exists | Flag file exists | Result |
|---|---|---|
| yes | no | **OK** — normal operation |
| yes | yes | **OK** — power returned, awaiting service cancel |
| no | yes | **Fail** — shutdown already in progress |
| no | no | **Fail** — port disappeared, waiting for service to react |

All output is tagged `upsmon_checker` and sent to the systemd journal via `logger`.

### Run manually

```bash
./upsmon_checker.sh
```

### Cron

```bash
# Add to root's crontab (sudo crontab -e)
*/5 * * * * /opt/upsmon/upsmon_checker.sh
```

### Systemd timer

Create two files:

**/etc/systemd/system/upsmon_checker.service**
```ini
[Unit]
Description=UPS monitor health check

[Service]
Type=oneshot
ExecStart=/opt/upsmon/upsmon_checker.sh
```

**/etc/systemd/system/upsmon_checker.timer**
```ini
[Unit]
Description=Run UPS monitor health check every 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=30s

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now upsmon_checker.timer

# Verify
systemctl list-timers upsmon_checker.timer
```

The systemd timer approach is preferred over cron — it integrates with the journal, respects dependencies, and its status is visible via `systemctl`.


Testing (dry-run mode)
----------------------

Dry-run mode logs what *would* happen without executing shutdown commands.

```bash
# Option A: env var
UPSMON_DRYRUN=1 .venv/bin/python upsmon.py

# Option B: marker file (can toggle at runtime without restart)
sudo touch /opt/upsmon/.dryrun     # enable
sudo rm -f /opt/upsmon/.dryrun     # disable
```

Note: the systemd unit's `ExecStartPre` removes `.dryrun` on every start so the service always runs live in production.
 
