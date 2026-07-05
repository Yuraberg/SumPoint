FROM python:3.11-slim AS builder

WORKDIR /app

# System deps — retry 3x (transient network issues with VPS repos)
RUN for i in 1 2 3; do \
      apt-get update && \
      apt-get install -y --no-install-recommends gcc libpq-dev && \
      rm -rf /var/lib/apt/lists/* && break || \
      (echo "Attempt $i failed, retrying..." && sleep 5); \
    done && [ -f /usr/bin/gcc ] || exit 1

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.11-slim

WORKDIR /app

# procps — provides pgrep, used by the bot/worker/beat healthchecks in
# docker-compose.yml (image has no process-monitoring tools by default).
RUN apt-get update && apt-get install -y --no-install-recommends procps \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local
COPY . .

# Writable directory for encrypted session files
RUN mkdir -p /app/sessions && chmod 700 /app/sessions \
    && useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
