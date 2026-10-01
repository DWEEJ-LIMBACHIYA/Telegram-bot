# Telegram Planner Bot

A personal Telegram bot for a to-do list and an event calendar, with an evening check-in that asks what you want to plan for tomorrow.

**Phase 1 (this version)**
- ✅ To-do list for each day: add, rename, mark done, postpone, delete
- 📅 Events with a time, plus a reminder before they start (30 minutes by default)
- 🌙 Evening prompt ("anything for tomorrow?") that shows how today went and can move unfinished tasks to tomorrow
- 🌍 A timezone for each user, so friends in other countries see the right times
- 🔒 An optional allow-list, so only you and your friends can use the bot

**Coming next:** Phase 2 adds recurring tasks and a morning summary. Phase 3 adds friends' availability and booking game sessions in a group chat.

## Using it

Type a message and the bot adds it:

| You send | Result |
|---|---|
| `Buy milk` | task for today |
| `tomorrow Call mom` or `Call mom tomorrow` | task for tomorrow |
| `sat 7pm Gaming night` | event on Saturday at 19:00, with a reminder |
| several lines | one item per line |

Commands: `/today`, `/tomorrow`, `/day fri`, `/add`, `/event`, `/events`, `/timezone`, `/nightly 21:30` (or `off`), `/cancel`, `/help`.

Tap any task or event in a list to mark it done, rename it, postpone it or delete it.

Dates the bot understands: `today`, `tomorrow`, `mon`…`sun`, `next fri`, `+3`, `in 3 days`, `5 oct`, `2026-10-05`.
Times: `19:00`, `7pm`, `7:30pm`, `noon`.

---

## Setup

### 1. Create the bot in Telegram
1. Open **@BotFather**, send `/newbot`, and follow the steps.
2. Copy the **token** it gives you, which looks like `123456789:ABC...`. **Keep it secret.** If it ever leaks, send `/revoke` to BotFather.
3. Open **@userinfobot** to get your numeric Telegram ID. Your friends need to get theirs too.

### 2. Deploy on a Hostinger VPS (Docker Manager)
The VPS should run **Ubuntu with Docker**, the Docker option under "Applications".

1. In hPanel, open **VPS → Docker Manager** and create a new project, for example `planner-bot`.
2. Choose **Compose from URL** and paste:
   ```
   https://github.com/DWEEJ-LIMBACHIYA/Telegram-bot/blob/main/docker-compose.yml   (once the code is on main)
   ```
   Or choose the option to paste YAML yourself and copy in the contents of `docker-compose.yml`.
3. Set the **environment variables**:
   - `BOT_TOKEN`: the token from BotFather
   - `ALLOWED_USER_IDS`: your ID, plus your friends' IDs separated by commas
   - `DEFAULT_TIMEZONE`: for example `America/Toronto` or `Asia/Kolkata`
4. Click **Deploy**. Then open the bot in Telegram and send `/start`.

Use Docker Manager to **restart** the bot, read its **logs**, or **redeploy** it after the code changes.

<details>
<summary>Prefer the terminal? (hPanel → VPS → Browser terminal, or SSH)</summary>

```bash
git clone https://github.com/DWEEJ-LIMBACHIYA/Telegram-bot.git
cd Telegram-bot
cp .env.example .env && nano .env      # fill in BOT_TOKEN etc.
docker compose up -d --build
docker compose logs -f                 # watch it run (Ctrl+C to stop watching)
```
To update later: `git pull && docker compose up -d --build`.
</details>

### Important rules
- **Run only one copy of the bot per token.** If it runs on your laptop and on the VPS at the same time, Telegram reports `409 Conflict`. For testing, create a second bot with BotFather.
- **Never commit the token.** `.env` is already in `.gitignore`.
- **Back up the data.** Everything lives in the `bot-data` Docker volume. Turn on Hostinger's VPS backups or snapshots.
- **Friends must press /start once** before the bot can message them.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # use a separate *test* bot token here
set -a && source .env && set +a
python -m bot
```

Run the tests: `python -m unittest discover -s tests -t . -v`. The end-to-end tests use a fake Telegram API, so they need no token or network.

### Layout
```
bot/
  __main__.py   start-up, handler wiring
  handlers.py   commands, buttons, free-text messages
  views.py      message text + inline keyboards
  scheduler.py  evening prompts and event reminders (rebuilt from the DB at start-up)
  parsing.py    "sat 7pm gaming" → date, time, title
  db.py         SQLite storage (events in UTC, tasks by local date)
  config.py     environment variables
```
