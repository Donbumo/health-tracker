#!/bin/sh
set -eu

flask db upgrade
flask seed-admin

exec gunicorn \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-2}" \
  --access-logfile - \
  --error-logfile - \
  "app:create_app()"
