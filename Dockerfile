# Business objective: run the exact validated dependency graph and application consistently across environments.
# Technical description: builds pinned dependency/application wheels in a multi-stage image, installs only from the local wheelhouse, then runs as a non-root user with health checks and immutable application code.
FROM python:3.12-slim AS builder
WORKDIR /build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
COPY requirements-runtime.lock pyproject.toml README.md ./
RUN python -m pip wheel --wheel-dir /wheels -r requirements-runtime.lock
COPY src ./src
RUN python -m pip wheel --wheel-dir /wheels --no-deps .

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/home/app/.local/bin:$PATH" ICA_PROJECT_ROOT=/app
RUN groupadd --system app && useradd --system --gid app --create-home app
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels invoice-canonicalization-agent && rm -rf /wheels
COPY --chown=app:app config ./config
COPY --chown=app:app prompts ./prompts
COPY --chown=app:app data ./data
RUN mkdir -p /var/lib/invoice-canonicalizer && chown -R app:app /var/lib/invoice-canonicalizer
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["uvicorn", "invoice_canonicalizer.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
