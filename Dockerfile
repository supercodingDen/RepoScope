FROM python:3.12.14-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254 AS source-tools
ARG GIT_DEBIAN_VERSION=1:2.39.5-0+deb12u3
ARG CA_CERTIFICATES_DEBIAN_VERSION=20250419~deb12u1
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git=${GIT_DEBIAN_VERSION} ca-certificates=${CA_CERTIFICATES_DEBIAN_VERSION} \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/lib/reposcope/sources \
    && chown 10001:10001 /var/lib/reposcope/sources

FROM source-tools AS dependencies
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.11
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --python /usr/local/bin/python

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
COPY scripts/import_local_source.py ./scripts/import_local_source.py
COPY contracts ./contracts
COPY src ./src
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/src:/app" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
USER 10001:10001
EXPOSE 8000 9000
CMD ["python", "-m", "reposcope", "api"]
