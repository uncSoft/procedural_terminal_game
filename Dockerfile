# The game in web browsers: one link, a page that asks who's playing, and each name its own saves (ptg serve).
# Render builds this on every push to the deployed branch: see "Play it in a browser" in the README.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.23 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# The dependencies first, so a change to the game alone rebuilds only the last layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra web --extra claude
COPY src ./src
RUN uv sync --frozen --no-dev --extra web --extra claude

# Players' saves go in /data (Render's disk); the server is quiet, since its sound would play on the server.
ENV PATH="/app/.venv/bin:$PATH" PTG_DATA=/data PTG_SOUND=0
EXPOSE 10000
CMD ["ptg", "serve", "--host", "0.0.0.0"]
