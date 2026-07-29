# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app \
    && mkdir -p /data && chown app:app /data

COPY requirements.txt /tmp/root-requirements.txt
COPY "Structured Narrative/requirements.txt" /tmp/structured-narrative-requirements.txt
COPY services/earnings_monitor/requirements.txt /tmp/service-requirements.txt
RUN pip install --requirement /tmp/root-requirements.txt \
    --requirement /tmp/structured-narrative-requirements.txt \
    --requirement /tmp/service-requirements.txt

COPY . /app
RUN chmod +x /app/deploy/local/entrypoint.sh && chown -R app:app /app /data

USER app
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os; os.kill(1, 0)"

ENTRYPOINT ["/app/deploy/local/entrypoint.sh"]
CMD ["monitor"]
