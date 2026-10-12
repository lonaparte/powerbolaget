# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    COASTAL_DATA=/data

WORKDIR /app
COPY requirements.lock pyproject.toml ./
COPY tools/deps.py ./tools/
# The same command installs dependencies outside Docker. The optional CA bundle supports builds behind a trusted HTTPS proxy.
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    PIP_NO_CACHE_DIR=1 python tools/deps.py install

COPY app ./app
RUN python tools/deps.py check
COPY web ./web
COPY tests ./tests
COPY pytest.ini LICENSE THIRD-PARTY-NOTICES.txt ./
COPY licenses ./licenses
RUN groupadd --gid 10001 game \
    && useradd --uid 10001 --gid game --no-create-home game \
    && mkdir /data \
    && chown game:game /data \
    && chmod -R a+rX /app

USER 10001:10001
EXPOSE 8082
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8082/api/health', timeout=4).read()"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8082", "--workers", "1"]
