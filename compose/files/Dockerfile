# The reference MCP filesystem server behind supergateway, which serves it over Streamable HTTP.
# The server sees /agents-fs alone. Every request carries the key SUPERGATEWAY_API_KEY holds.
FROM node:24-slim

RUN npm install --global --no-fund --no-audit \
        supergateway@4.2.2 @modelcontextprotocol/server-filesystem@2026.8.31 \
    && mkdir /agents-fs \
    && chown node:node /agents-fs

USER node
EXPOSE 8935
CMD ["supergateway", "--stdio", "mcp-server-filesystem /agents-fs", \
     "--outputTransport", "streamableHttp", "--host", "0.0.0.0", "--port", "8935", \
     "--stateful"]
