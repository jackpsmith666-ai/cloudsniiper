FROM python:3.11-slim

WORKDIR /app

COPY headless_sniper.py .
COPY bearer.txt .
COPY webhook.txt .
COPY proxies.txt .

ENV PYTHONUNBUFFERED=1
ENV SNIPER_TARGET=lineage
ENV SNIPER_INTERVAL_MS=20

CMD ["python", "headless_sniper.py"]
