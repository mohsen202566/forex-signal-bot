#!/bin/bash
cd /root/ai-range-5m-bot || exit 1
set -a
source .env
set +a
exec /root/ai-range-5m-bot/venv/bin/python /root/ai-range-5m-bot/main.py
