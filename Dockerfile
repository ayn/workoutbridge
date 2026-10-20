FROM node:22-bookworm-slim AS frontend
ENV NODE_OPTIONS=--max-old-space-size=512
WORKDIR /web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.13-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.12.21 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY workoutbridge/ ./workoutbridge/
RUN uv sync --locked --no-dev --extra garmin --extra web
COPY --from=frontend /web/dist /app/web/dist
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
CMD ["uvicorn", "workoutbridge.web:application", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
