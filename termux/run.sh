#!/data/data/com.termux/files/usr/bin/bash
# Runs the bot forever, restarting it if it crashes or loses the network.
cd "$(dirname "$0")/.." || exit 1
mkdir -p data
set -a; . ./.env; set +a

while true; do
  # keep the log from growing forever
  if [ -f data/bot.log ] && [ "$(wc -c < data/bot.log)" -gt 5000000 ]; then
    mv data/bot.log data/bot.log.old
  fi
  python -m bot >> data/bot.log 2>&1
  echo "$(date) bot stopped (exit $?), restarting in 15s" >> data/bot.log
  sleep 15
done
