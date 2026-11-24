#!/bin/sh
set -eu
# Both services may start together; migrations serialize via the database lock.
python -m pilot.migrate
case "${1:-web}" in
  web) exec uvicorn pilot.api:app --host 0.0.0.0 --port "${PORT:-10000}" --no-access-log --limit-concurrency 16 ;;
  worker) exec python -m pilot.worker ;;
  *) echo 'Expected web or worker' >&2; exit 2 ;;
esac
