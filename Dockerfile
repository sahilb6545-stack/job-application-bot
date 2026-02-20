# ── Build stage ───────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS base

# Playwright system dependencies for Chromium on Debian Bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl gnupg ca-certificates fonts-liberation \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 \
    libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 libnspr4 \
    libnss3 libx11-xcb1 libxcomposite1 libxdamage1 \
    libxrandr2 xdg-utils libxshmfence1 \
    libpango-1.0-0 libpangocairo-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Store Playwright browsers inside /app so botuser can access them after chown
ENV PLAYWRIGHT_BROWSERS_PATH=/app/.playwright-browsers
RUN playwright install --with-deps chromium

# Copy application code
COPY . .

# Ensure data directory exists
RUN mkdir -p /app/data

# Expose health check port
EXPOSE 8080

# Create non-root user and hand over all of /app (including browsers)
RUN useradd -m botuser && chown -R botuser:botuser /app
USER botuser

CMD ["python", "main.py"]
