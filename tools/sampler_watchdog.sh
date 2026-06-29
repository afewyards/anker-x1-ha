#!/bin/sh
# Anker X1 sampler watchdog — relaunches the sampler forever (auto-restart on
# crash). Stop with: pkill -f sampler_watchdog ; pkill -f anker_sampler.py
LOG=/share/sampler.log
while true; do
  echo "$(date "+%Y-%m-%d %H:%M:%S") watchdog: starting sampler" >> "$LOG"
  python3 /share/anker_sampler.py 5 99999999 >> "$LOG" 2>&1
  rc=$?
  echo "$(date "+%Y-%m-%d %H:%M:%S") watchdog: sampler exited rc=$rc, restart in 10s" >> "$LOG"
  sleep 10
done
