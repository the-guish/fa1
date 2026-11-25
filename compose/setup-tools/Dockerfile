# The designer's two tool servers, over its working copy of the setup folder
# (docs/specs/review-app.md, "The working copy"): the reference MCP filesystem server and the
# reference MCP git server with one tool of FA1's own, each behind supergateway, which serves it over Streamable HTTP.
# Every request carries the key SUPERGATEWAY_API_KEY holds. The command names the server:
# `files` or `git`. compose.yaml runs both as the setup folder's owner, and its service `owner`
# gives that user the volume at /work.
FROM node:24-slim

# git and Python, for the git server. It runs git itself, and pins what a repository's own
# settings could run: hooks, the file monitor, filters and drivers.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN npm install --global --no-fund --no-audit \
        supergateway@4.2.2 @modelcontextprotocol/server-filesystem@2026.8.31 \
    && python3 -m venv /opt/git-server \
    && /opt/git-server/bin/pip install --no-cache-dir mcp-server-git==2026.11.18 \
    && mkdir /work \
    && chown node:node /work

COPY start.sh /usr/local/lib/fa1-start.sh
# The git server with FA1's tool git_rm: neither reference server removes a file.
COPY git_server.py /usr/local/lib/fa1-git-server.py

USER node
ENV PYTHONDONTWRITEBYTECODE=1
EXPOSE 8938 8939
ENTRYPOINT ["sh", "/usr/local/lib/fa1-start.sh"]
