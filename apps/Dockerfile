# syntax=docker/dockerfile:1
# FA1's control plane (docs/specs/apps.md): Robinauts and neorc as parts, FA1's applications
# beside them, and FA1's own two lists, backend.py and main.tsx. The build context is this
# folder. compose.yaml names Robinauts at the pinned commit as the build context "robinauts".

# Robinauts' interface and its two peers, as node packages, packed from the pinned commit.
FROM node:24-slim AS packages
# git, which Robinauts' script fetches neorc and oneberth with.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /opt/robinauts/src
COPY --from=robinauts LICENSE ./
COPY --from=robinauts backend/openapi.json backend/pyproject.toml backend/
COPY --from=robinauts scripts/ui-packages-from-source.sh scripts/robinauts-ui-pack.sh scripts/
COPY --from=robinauts frontend frontend
COPY vendor.sh /opt/fa1/apps/vendor.sh
RUN sh /opt/fa1/apps/vendor.sh /opt/robinauts/src

# The interface: main.tsx gives the shell Robinauts' applications and FA1's.
FROM node:24-slim AS interface
WORKDIR /opt/fa1/apps
COPY package.json package-lock.json .npmrc ./
COPY --from=packages /opt/fa1/apps/vendor vendor
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# The backend: Robinauts, installed from its lock as its own image installs it, then FA1's
# applications and backend.py.
FROM python:3.12-slim

# git, which uv builds neorc and oneberth from.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_PREFERENCE=only-system \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/robinauts/venv

WORKDIR /opt/robinauts/src
COPY --from=robinauts LICENSE NOTICE ./
COPY --from=robinauts backend/pyproject.toml backend/uv.lock backend/hatch_build.py backend/
COPY --from=robinauts backend/src backend/src
# The handlers Robinauts ships, beside backend/: a flows folder that names none runs these.
COPY --from=robinauts orchestration orchestration
RUN cd backend && uv sync --locked --no-dev

WORKDIR /opt/fa1/apps
COPY . .
COPY --from=interface /opt/fa1/apps/dist dist

# Nothing runs as root. The user and its home are those of Robinauts' own image: the volume
# of the control plane's records is mounted on that home.
RUN useradd --system --create-home --home-dir /var/lib/robinauts --shell /usr/sbin/nologin \
    robinauts
USER robinauts
ENV PATH=/opt/robinauts/venv/bin:$PATH

# compose.yaml gives the ports, and the launch secret on the standard input.
CMD ["python", "/opt/fa1/apps/backend.py", "--port", "8420", "--worker-port", "8421"]
