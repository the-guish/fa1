# The sample local MCP server. Pin what the build fetches: the base image by its digest, and the
# packages by their versions.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

RUN pip install --no-cache-dir mcp==1.30.0 uvicorn==0.54.0 tzdata==2025.2

COPY server.py /app/server.py

USER nobody
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python", "/app/server.py"]
