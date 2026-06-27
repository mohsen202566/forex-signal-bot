#!/usr/bin/env bash
set -e
cd /root/forex-bot
if [ -d venv ]; then
  source venv/bin/activate
fi
python3 bot.py
