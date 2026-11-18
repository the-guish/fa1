# Robinauts' diagrams MCP server (mcp/diagrams), installed from its lock. compose.yaml names that folder, at
# the pinned commit, as the build context "source". On 0.0.0.0, the MCP SDK checks no Host: the
# server is reached on the project's network alone.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_PREFERENCE=only-system \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/diagrams/venv

WORKDIR /opt/diagrams/src
COPY --from=source pyproject.toml uv.lock ./
COPY --from=source src src
RUN uv sync --locked --no-dev --no-editable

RUN useradd --create-home --uid 10001 diagrams

USER diagrams
EXPOSE 8937
CMD ["/opt/diagrams/venv/bin/robinauts-diagrams", "--host", "0.0.0.0", "--port", "8937"]
