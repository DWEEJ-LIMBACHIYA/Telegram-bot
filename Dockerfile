FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/app/data/bot.db

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot ./bot

# Run as a normal user; the database lives in /app/data (a Docker volume).
RUN useradd --create-home bot && mkdir -p /app/data && chown bot /app/data
USER bot

CMD ["python", "-m", "bot"]
