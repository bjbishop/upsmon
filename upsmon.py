#!/usr/bin/env python

from subprocess import call
from time import sleep
import serial
import locale
import pathlib
import os

encoding = locale.getdefaultlocale()[1]
tmpfilename = "/tmp/upsmon.txt"
p = pathlib.Path(tmpfilename)

try:
    tty = os.environ['UPSMON_TTY']
except KeyError:
    tty = "ttyACM0"

try:
    baud = int(os.environ['UPSMON_BAUD'])
except KeyError:
    baud = 9600


def shutdown():
    if not p.exists():
        try:
            open(tmpfilename, "a").close()
        except IOError:
            print("File error reading", tmpfilename)

        print("SHUTTING DOWN IN 1 MINUTE")
        call("/bin/bash -c \"/usr/bin/nohup /sbin/shutdown -h -P +1 &\"", shell=True)


def cancel_shutdown():
    if p.exists():
        print("TMP FILE ", tmpfilename, " EXISTS, CANCEL THE SHUTDOWN")
        call(["/sbin/shutdown", "-c", "||", "true"])
        os.remove(tmpfilename)


s = serial.Serial(f"/dev/{tty}", baud)

print("starting up, sleeping")
sleep(2)

while True:
    line = s.readline().decode(encoding)
    parsed = int(line.split("\r", 2)[0].strip())
    if (int(parsed) <= 4):
        cancel_shutdown()
    if (int(parsed) >= 5):
        shutdown()
