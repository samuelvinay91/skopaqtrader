# SkopaqTrader — Multi-service Docker image
#
# Services (select via SKOPAQ_SERVICE env var):
#   api       — FastAPI backend (default)
#   chat      — Interactive AI chatbot REPL
#   telegram  — Telegram bot (@Skopaq_bot)
#   mcp       — MCP server (stdio transport)
#   daemon    — Autonomous trading session
#   monitor   — Position monitor
#
# Quick start:
#   docker run -it --env-file .env skopaqtrader/skopaqtrader chat
#   docker run -d --env-file .env skopaqtrader/skopaqtrader telegram
#   docker run -d --env-file .env -p 8000:8000 skopaqtrader/skopaqtrader api
#
# Or use docker-compose.yml for all services at once.

FROM python:3.14-slim AS base

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (cached layer)
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . 2>/dev/null || pip install --no-cache-dir . \
    && pip install --no-cache-dir python-telegram-bot>=21.0 langchain-ollama>=1.0.0

# Copy application code
COPY . .

# Install the project in editable mode
RUN pip install --no-cache-dir -e .

# Create non-root user
RUN useradd -m -s /bin/bash skopaq
USER skopaq

EXPOSE 8000

# Health check for API mode
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Entry point script
COPY docker/entrypoint.sh /entrypoint.sh
USER root
RUN chmod +x /entrypoint.sh
USER skopaq

ENTRYPOINT ["/entrypoint.sh"]
CMD ["api"]
