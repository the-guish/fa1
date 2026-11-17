# Robinauts' to-do list MCP server (mcp/to-do-list), installed from its lock. compose.yaml names that folder, at
# the pinned commit, as the build context "source". On 0.0.0.0, the MCP SDK checks no Host: the
# server is reached on the project's network alone.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_PREFERENCE=only-system \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/todo/venv

WORKDIR /opt/todo/src
COPY --from=source pyproject.toml uv.lock ./
COPY --from=source src src
RUN uv sync --locked --no-dev --no-editable

RUN useradd --create-home --uid 10001 todo \
    && mkdir /data \
    && chown todo:todo /data

USER todo
EXPOSE 8936
CMD ["/opt/todo/venv/bin/robinauts-to-do-list", "--host", "0.0.0.0", "--port", "8936", "--file", "/data/todos.json"]
