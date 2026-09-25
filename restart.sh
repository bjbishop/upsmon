#!/bin/sh

# Stop and start everything
sudo systemctl stop nut-monitor
sudo systemctl stop nut-server
sudo systemctl stop nut-driver@myups.service
sudo systemctl stop upsmon-bridge.service
sleep 5
sudo systemctl start upsmon-bridge.service
sudo systemctl start nut-driver@myups.service
sudo systemctl start nut-server
sleep 5
sudo systemctl start nut-monitor
