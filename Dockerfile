FROM python:3.12.14-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS source-tools
ARG GIT_DEBIAN_VERSION=1:2.39.5-0+deb12u3
ARG CA_CERTIFICATES_DEBIAN_VERSION=20250419~deb12u1
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git=${GIT_DEBIAN_VERSION} ca-certificates=${CA_CERTIFICATES_DEBIAN_VERSION} \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/lib/reposcope/sources \
    && chown 10001:10001 /var/lib/reposcope/sources

FROM source-tools AS dependencies
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never TIKTOKEN_CACHE_DIR=/app/tiktoken-cache
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.11
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --python /usr/local/bin/python
RUN mkdir -p /app/tiktoken-cache \
    && /app/.venv/bin/python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

FROM dependencies AS test
RUN uv sync --frozen --all-groups --python /usr/local/bin/python
COPY contracts ./contracts
COPY packages ./packages
COPY src ./src
COPY scripts ./scripts
COPY tests ./tests
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/src:/app" PYTHONDONTWRITEBYTECODE=1
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

FROM source-tools AS runtime
WORKDIR /app
COPY --from=dependencies /app/.venv /app/.venv
COPY --from=dependencies /app/tiktoken-cache /app/tiktoken-cache
COPY scripts/import_local_source.py ./scripts/import_local_source.py
COPY scripts/launch_from_secrets.py ./scripts/launch_from_secrets.py
COPY contracts ./contracts
COPY src ./src
COPY LICENSE NOTICE ./
COPY docs/third-party-notices.md ./docs/third-party-notices.md
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/src:/app" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp TIKTOKEN_CACHE_DIR=/app/tiktoken-cache
USER 10001:10001
EXPOSE 8000 9000
CMD ["python", "-m", "reposcope", "api"]
