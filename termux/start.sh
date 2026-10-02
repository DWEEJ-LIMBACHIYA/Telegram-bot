#!/data/data/com.termux/files/usr/bin/bash
# Start the bot in the background (safe to run twice: it won't start a second copy).
cd "$(dirname "$0")/.." || exit 1
if pgrep -f "termux/run.sh" > /dev/null; then
  echo "Bot is already running."
  exit 0
fi
termux-wake-lock 2>/dev/null || true   # stop Android from putting Termux to sleep
nohup bash termux/run.sh > /dev/null 2>&1 &
echo "Bot started. Logs: tail -f $(pwd)/data/bot.log"
