# Build from the repo root:
#   docker build -t persian-writing-mcp .
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements.txt ./
COPY src/ ./src/
RUN pip install --no-cache-dir .
COPY vault/ /app/vault/
EXPOSE 8060
ENV OP_MCP_TRANSPORT=streamable-http \
    OP_MCP_HOST=0.0.0.0 \
    OP_MCP_PORT=8060 \
    OP_VAULT_PATH=/app/vault
# API key via OP_MCP_API_KEY (required for HTTP). /health stays open.
CMD ["obper-mcp"]
