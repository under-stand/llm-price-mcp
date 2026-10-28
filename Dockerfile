# llm-price-mcp container image.
# Default: stdio transport    ->  docker run -i --rm llm-price-mcp
# HTTP (Streamable HTTP /mcp) ->  docker run --rm -p 8081:8081 -e MCP_TRANSPORT=streamable-http llm-price-mcp
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install . && useradd --create-home --uid 10001 app

USER app
# Optional: mount fresher GPU data and point LLM_PRICE_GPU_CSV (or LLM_PRICE_TRACKER_DIR) at it;
# otherwise the dated snapshot bundled in the package is used.
ENV MCP_TRANSPORT=stdio \
    PORT=8081
EXPOSE 8081
ENTRYPOINT ["llm-price-mcp"]
