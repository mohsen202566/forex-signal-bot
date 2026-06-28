#!/bin/bash
cd /root/forex-signal-bot || exit 1
set -a
source .env
set +a
exec /root/forex-signal-bot/venv/bin/python /root/forex-signal-bot/main.py
