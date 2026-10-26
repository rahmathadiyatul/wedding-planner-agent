FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir "httpx>=0.27,<0.29"
COPY bot.py /app/bot.py

# Config comes from the environment (see docker-compose.yml / .env).
CMD ["python", "-u", "bot.py"]
