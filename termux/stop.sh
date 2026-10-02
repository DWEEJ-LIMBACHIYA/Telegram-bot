#!/data/data/com.termux/files/usr/bin/bash
pkill -f "termux/run.sh"
pkill -f "python -m bot"
termux-wake-unlock 2>/dev/null || true
echo "Bot stopped."
