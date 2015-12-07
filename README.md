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


Image
-----

Here's a picture of my first attempt, pretty hacked together

[Arduino UPS monitor](https://flic.kr/p/BT4Y35)

