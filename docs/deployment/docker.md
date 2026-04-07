# Docker Deployment

SkopaqTrader ships as a multi-service Docker image. A single image supports all services -- API, Telegram bot, chatbot, MCP server, daemon, and more.

## Quick Start

```bash
# Pull the image
docker pull samuelvinay91/skopaq:latest

# Run the API server
docker run -d --env-file .env -p 8000:8000 samuelvinay91/skopaq:latest api

# Run the Telegram bot
docker run -d --env-file .env samuelvinay91/skopaq:latest telegram

# Interactive chatbot
docker run -it --env-file .env samuelvinay91/skopaq:latest chat
```

## Dockerfile

The image is built from `python:3.14-slim` with a multi-stage build:

```dockerfile
FROM python:3.14-slim AS base
WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git curl

# Python dependencies (cached layer)
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

# Application code
COPY . .
RUN pip install --no-cache-dir -e .

# Non-root user
RUN useradd -m -s /bin/bash skopaq
USER skopaq

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["api"]
```

## Available Services

The `docker/entrypoint.sh` script routes to the correct service based on the command argument:

| Service | Command | Description | Port |
|---------|---------|-------------|------|
| `api` | `docker run ... api` | FastAPI backend | 8000 |
| `telegram` | `docker run ... telegram` | Telegram bot | none |
| `chat` | `docker run -it ... chat` | Interactive chatbot | none |
| `mcp` | `docker run -it ... mcp` | MCP server (stdio) | none |
| `daemon` | `docker run ... daemon` | Paper trading daemon | none |
| `daemon-live` | `docker run ... daemon-live` | Live trading daemon | none |
| `monitor` | `docker run ... monitor` | Position monitor | none |
| `scan` | `docker run ... scan` | One-shot market scan | none |
| `status` | `docker run ... status` | System health check | none |
| `shell` | `docker run -it ... shell` | Bash shell | none |

## Docker Compose

The `docker-compose.yml` defines all services:

```yaml
services:
  api:
    build: .
    command: api
    ports:
      - "8000:8000"
    env_file: .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]

  telegram:
    build: .
    command: telegram
    env_file: .env
    restart: unless-stopped
    depends_on:
      api:
        condition: service_healthy

  chat:
    build: .
    command: chat
    env_file: .env
    stdin_open: true
    tty: true
    profiles:
      - interactive

  daemon:
    build: .
    command: daemon
    env_file: .env
    profiles:
      - trading

  scan:
    build: .
    command: scan
    env_file: .env
    profiles:
      - tools

  mcp:
    build: .
    command: mcp
    env_file: .env
    stdin_open: true
    profiles:
      - mcp
```

### Running Services

```bash
# Start API + Telegram (default profile)
docker compose up -d

# Interactive chatbot
docker compose run --rm chat

# One-shot market scan
docker compose run --rm scan

# Autonomous daemon
docker compose --profile trading up -d daemon

# All services including MCP
docker compose --profile mcp up -d
```

!!! tip "Profiles"
    Services like `chat`, `daemon`, `scan`, and `mcp` are behind Docker Compose profiles. Use `--profile <name>` to include them, or they will not start with `docker compose up`.

## Environment Variables

Create a `.env` file from the template:

```bash
cp .env.example .env
# Edit .env with your API keys
```

Essential variables:

```bash
# Broker
SKOPAQ_KITE_API_KEY=...
SKOPAQ_KITE_API_SECRET=...

# LLM Providers
SKOPAQ_GOOGLE_API_KEY=...
SKOPAQ_ANTHROPIC_API_KEY=...

# Telegram
SKOPAQ_TELEGRAM_BOT_TOKEN=...

# Trading Mode
SKOPAQ_TRADING_MODE=paper
```

!!! warning "Never commit .env"
    The `.env` file contains secrets and is gitignored. Never add it to version control.

## Building from Source

```bash
# Build the image
docker build -t skopaqtrader .

# Build with a specific tag
docker build -t samuelvinay91/skopaq:v0.4.0 .

# Push to Docker Hub
docker push samuelvinay91/skopaq:latest
```

## Health Check

The API service has a built-in health check:

```bash
curl http://localhost:8000/health
```

Docker checks this every 30 seconds. If 3 consecutive checks fail, the container is marked unhealthy.

## Volume Mounts

For persistent data (Kite tokens, logs):

```bash
docker run -d \
  --env-file .env \
  -v skopaq_data:/data \
  -p 8000:8000 \
  samuelvinay91/skopaq:latest api
```

The Kite access token is persisted to `/data/skopaq_kite_token.json` inside the container.

## File Reference

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-service Docker image |
| `docker-compose.yml` | All services with profiles |
| `docker/entrypoint.sh` | Service routing entrypoint |
| `.env.example` | Environment variable template |
