#!/bin/sh
set -eu

flask db upgrade
flask seed-admin

exec gunicorn \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-2}" \
  --timeout "${GUNICORN_TIMEOUT:-60}" \
  --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-30}" \
  --keep-alive "${GUNICORN_KEEP_ALIVE:-5}" \
  --log-level "${GUNICORN_LOG_LEVEL:-info}" \
  --access-logfile - \
  --error-logfile - \
  --capture-output \
  "app:create_app()"
