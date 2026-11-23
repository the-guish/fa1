# syntax=docker/dockerfile:1
# FA1's Cursor worker (docs/specs/cursor-worker.md): Robinauts' worker module and what its extra
# workers share, installed as Robinauts' base worker installs them, then FA1's engine `cursor`
# and Cursor's CLI. The build context is this folder. compose.yaml names Robinauts at the pinned
# commit as the build context "robinauts".

FROM python:3.12-slim

# git for the agent and the worktrees, ripgrep for the agent's searches, bash, which the CLI's
# launcher is written in, and curl, which fetches the CLI.
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl git ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Cursor's CLI, at one version, checked against the sum of its package. Cursor publishes one
# package per platform, at the address its install script reads (https://cursor.com/install).
ARG CURSOR_CLI_VERSION=2026.11.22-e9042b2
ARG CURSOR_CLI_SHA256_AMD64=7663b1c5d1b56e095ef8e23bef38d66df6cfd665c4873470214e0e411f0f97b3
ARG CURSOR_CLI_SHA256_ARM64=7b7dd0020fb9a2a9e1e7e3f39e2f9f512d1dd9577174ecda8aa82ac31dbc9565
ARG TARGETARCH
RUN --mount=type=tmpfs,target=/tmp/cursor <<'EOF'
set -eu
case "$TARGETARCH" in
    amd64) platform=x64 wanted=$CURSOR_CLI_SHA256_AMD64 ;;
    arm64) platform=arm64 wanted=$CURSOR_CLI_SHA256_ARM64 ;;
    *) echo "Cursor publishes no CLI for $TARGETARCH" >&2; exit 1 ;;
esac
url=https://downloads.cursor.com/lab/$CURSOR_CLI_VERSION/linux/$platform/agent-cli-package.tar.gz
curl -fsSL --retry 3 -o /tmp/cursor/package.tar.gz "$url"
echo "$wanted  /tmp/cursor/package.tar.gz" | sha256sum --check --quiet
mkdir /opt/cursor
tar -xzf /tmp/cursor/package.tar.gz -C /opt/cursor --no-same-owner
ln -s /opt/cursor/dist-package/cursor-agent /usr/local/bin/cursor-agent
EOF

COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_PREFERENCE=only-system \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/robinauts/venv

# Robinauts' worker module and worker-common, from the base worker's lock.
WORKDIR /opt/robinauts/src
COPY --from=robinauts LICENSE NOTICE ./
COPY --from=robinauts backend/pyproject.toml backend/uv.lock backend/hatch_build.py backend/
COPY --from=robinauts backend/src backend/src
COPY --from=robinauts extra-workers/base-worker/pyproject.toml extra-workers/base-worker/uv.lock \
    extra-workers/base-worker/
COPY --from=robinauts extra-workers/worker-common/pyproject.toml extra-workers/worker-common/
COPY --from=robinauts extra-workers/worker-common/src extra-workers/worker-common/src
# The worker imports neither neorc nor oneberth, which uv would build from git.
RUN cd extra-workers/base-worker && uv sync --locked --no-dev \
    --no-install-package neorc --no-install-package neorc-core --no-install-package oneberth

# FA1's engine, beside them. It needs nothing more.
WORKDIR /opt/fa1/workers/cursor
COPY pyproject.toml ./
COPY src src
RUN uv pip install --python /opt/robinauts/venv/bin/python --no-deps .

# Nothing runs as root. The CLI keeps its chats under its home, and each conversation gets a
# directory under the workspaces: the two volumes it writes.
RUN useradd --system --home-dir /var/lib/cursor --shell /usr/sbin/nologin robinauts \
    && mkdir -p /var/lib/cursor /workspace \
    && chown robinauts:robinauts /var/lib/cursor /workspace
USER robinauts
ENV HOME=/var/lib/cursor \
    FA1_CURSOR_WORKSPACES=/workspace \
    PATH=/opt/robinauts/venv/bin:$PATH
WORKDIR /var/lib/cursor
VOLUME ["/var/lib/cursor", "/workspace"]

# It checks its environment and the configuration, reads its token from the file
# ONEBERTH_TOKEN_FILE names, and stops at SIGTERM.
CMD ["python", "-m", "fa1_cursor_worker"]
