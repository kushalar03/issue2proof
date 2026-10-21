# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock pyproject.toml README.md LICENSE ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --disable-pip-version-check --no-cache-dir -r requirements.lock
COPY --chown=10001:10001 issue2proof ./issue2proof
COPY --chown=10001:10001 artifacts ./artifacts
COPY --chown=10001:10001 examples ./examples
RUN pip install --disable-pip-version-check --no-deps --no-build-isolation . \
    && useradd --uid 10001 --create-home app \
    && mkdir -p /data && chown app:app /data
USER 10001
ENV ISSUE2PROOF_DB=/data/runs.sqlite3 ISSUE2PROOF_PUBLIC=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3)"
CMD ["uvicorn", "issue2proof.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
