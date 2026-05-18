# Pipecat Cloud agent image for the pipecat × Avaturn Live demo.
#
# Pipecat Cloud's base image already runs the FastAPI server that routes
# /bot and /ws to the agent — we just install dependencies from the
# project's uv lockfile and drop in our code.

# Pin a versioned base for reproducible deploys. Check
# https://hub.docker.com/r/dailyco/pipecat-base/tags for the current
# release and bump deliberately.
FROM dailyco/pipecat-base:0.1.20

# Install uv (alpha-quality copy from the official image; pin if you want
# reproducible CI).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Cache deps separately from source for faster rebuilds.
COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-install-project --no-dev

COPY pipecat_avaturn /app/pipecat_avaturn
COPY bot.py /app/bot.py
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}"
