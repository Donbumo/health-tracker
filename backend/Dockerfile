FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FLASK_APP=app:create_app

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
RUN chmod +x /app/docker-entrypoint.sh \
    && addgroup --system app \
    && adduser --system --ingroup app app \
    && mkdir -p /data/uploads/raw \
    && chown -R app:app /app /data

USER app

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
