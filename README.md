A simple light sensor to detect when the UPS goes on battery power.

When the battery is detected to be engaged, send the signal to shutdown the OS.

If the power is reconnected, the battery light goes off sending the signal to cancel the running shutdown.

* upsmon.processing
The processing code uploaded to the arduino.  I'm using an UNO

* upsmon.py
A python script to monitor of incoming signals from the Arduino

[Arduino UPS monitor](https://flic.kr/p/BT4Y35)

