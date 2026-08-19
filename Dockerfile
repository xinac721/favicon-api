FROM python:3.14-slim AS builder

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /app
COPY . .
RUN sed '/^[[:space:]]*--index-url[[:space:]]/d' requirements.txt > requirements-build.txt \
    && pip wheel --no-cache-dir --index-url "$PIP_INDEX_URL" --wheel-dir /wheels -r requirements-build.txt \
    && rm requirements-build.txt requirements.txt \
    && find . -type f \( -name '*.py[cod]' -o -name '.DS_Store' \) -delete \
    && find . -depth -type d -name '__pycache__' -empty -delete \
    && python -m compileall -q -b --invalidation-mode=checked-hash . \
    && find . -type f -name '*.py' -delete


FROM python:3.14-slim

ARG DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG DEBIAN_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security

ENV TZ=Asia/Shanghai

WORKDIR /app
RUN --mount=type=bind,from=builder,source=/wheels,target=/wheels,readonly \
    sed -i \
        -e "s|http://deb.debian.org/debian-security|$DEBIAN_SECURITY_MIRROR|g" \
        -e "s|http://deb.debian.org/debian|$DEBIAN_MIRROR|g" \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends --yes cron gosu tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime \
    && printf '%s\n' "$TZ" > /etc/timezone \
    && pip install --no-cache-dir /wheels/* \
    && addgroup --system --gid 10001 app \
    && adduser --system --uid 10001 --ingroup app app \
    && mkdir -p /app/data /app/logs \
    && chown -R app:app /app/data /app/logs
COPY --from=builder /app /app
COPY --from=builder --chmod=0644 /app/conf/blacklist-update.cron /etc/cron.d/blacklist-update

EXPOSE 8000
VOLUME ["/app/data", "/app/logs"]
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["gosu", "app", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "-c", "conf/gunicorn.conf.pyc", "main:app"]
