FROM node:26-bookworm-slim AS web-build
WORKDIR /app
RUN npm install --global pnpm@11.9.0
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY web/package.json web/package.json
RUN pnpm install --frozen-lockfile
COPY web web
RUN pnpm --filter @webaccessible/web build

FROM python:3.12-slim AS runtime
ARG BUILD_COMMIT=uncommitted
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright BUILD_COMMIT=$BUILD_COMMIT
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11.24 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend backend
COPY contracts contracts
COPY --from=web-build /app/web/dist web/dist
RUN mkdir -p /data
ENV OPERATIONAL_DATABASE_PATH=/data/webaccessible.sqlite3 PORT=8080
EXPOSE 8080
CMD ["/app/.venv/bin/uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
