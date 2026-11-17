# mcp-server-fetch behind mcp-proxy, which serves it over Streamable HTTP. The MCP SDK stays on
# 1.x: mcp-proxy 0.12 needs it, and mcp-server-fetch 2026.8.18 is its last release on 1.x.
FROM python:3.12-slim

RUN pip install --no-cache-dir "mcp<2" "mcp-proxy==0.12.0" "mcp-server-fetch==2026.8.18" \
    && useradd --create-home --uid 10001 fetch

USER fetch
EXPOSE 8932
CMD ["mcp-proxy", "--host", "0.0.0.0", "--port", "8932", "--", "mcp-server-fetch"]
