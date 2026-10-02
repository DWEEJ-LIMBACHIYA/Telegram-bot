#!/data/data/com.termux/files/usr/bin/bash
# Download the latest code and restart the bot.
cd "$(dirname "$0")/.." || exit 1
git pull --ff-only && pip install -r requirements.txt
bash termux/stop.sh
sleep 2
bash termux/start.sh
