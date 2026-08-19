FROM python:3.13-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /app/wheels -r requirements.txt
COPY . .
RUN python -m compileall -b . && find . -name "*.py" -delete


FROM python:3.13-slim

WORKDIR /app
COPY --from=builder /app /app
RUN pip install --no-cache /app/wheels/* && chmod +x /app/entrypoint.sh && rm -rf /wheels /app/wheels

EXPOSE 8000
VOLUME ["/app/data", "/app/logs"]
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "-c", "conf/gunicorn.conf.py", "main:app"]
