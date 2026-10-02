#!/data/data/com.termux/files/usr/bin/bash
# One-time setup on an Android tablet/phone running Termux.
# Usage (paste into Termux):
#   curl -fsSL https://raw.githubusercontent.com/DWEEJ-LIMBACHIYA/Telegram-bot/ccr-44d08e53-me2vwx/termux/install.sh | bash
set -e

BRANCH="ccr-44d08e53-me2vwx"
REPO="https://github.com/DWEEJ-LIMBACHIYA/Telegram-bot.git"
DIR="$HOME/Telegram-bot"

echo "==> Installing Python and git (this can take a few minutes)…"
pkg update -y
pkg install -y python git

echo "==> Downloading the bot…"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only
else
  git clone -b "$BRANCH" "$REPO" "$DIR"
fi
cd "$DIR"

echo "==> Installing Python packages…"
pip install -r requirements.txt

if [ ! -f .env ]; then
  echo
  echo "==> A few questions (you can change these later in $DIR/.env)"
  read -r -p "Bot token from @BotFather: " TOKEN < /dev/tty
  read -r -p "Your Telegram user ID (from @userinfobot; add friends later, comma-separated): " IDS < /dev/tty
  read -r -p "Your timezone, e.g. America/Toronto or Asia/Kolkata: " TZNAME < /dev/tty
  cat > .env <<ENV
BOT_TOKEN=$TOKEN
ALLOWED_USER_IDS=$IDS
DEFAULT_TIMEZONE=${TZNAME:-UTC}
NIGHTLY_TIME=21:00
REMINDER_MINUTES=30
DB_PATH=data/bot.db
ENV
  chmod 600 .env
fi

echo "==> Making the bot start automatically when the tablet boots…"
mkdir -p "$HOME/.termux/boot"
cat > "$HOME/.termux/boot/start-planner-bot.sh" <<BOOT
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
bash "$DIR/termux/start.sh"
BOOT
chmod +x "$HOME/.termux/boot/start-planner-bot.sh" termux/*.sh

bash termux/start.sh
echo
echo "✅ Done! Open your bot in Telegram and send /start."
echo "   Logs:    tail -f $DIR/data/bot.log"
echo "   Stop:    bash $DIR/termux/stop.sh"
echo "   Update:  bash $DIR/termux/update.sh"
