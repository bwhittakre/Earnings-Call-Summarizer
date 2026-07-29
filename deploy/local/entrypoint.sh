#!/bin/sh
set -eu

role="${1:-monitor}"
shift || true

case "$role" in
  monitor)
    exec python -m services.earnings_monitor run \
      --interval="${EARNINGS_MONITOR_POLL_SECONDS:-300}" "$@"
    ;;
  worker)
    exec python /app/deploy/local/role_runner.py worker "$@"
    ;;
  history-import)
    exec python -m services.earnings_monitor.history_import \
      --source-root=/app \
      --destination="${EARNINGS_MONITOR_DATASET:-/data/company_quarters.parquet}" "$@"
    ;;
  dashboard)
    exec streamlit run /app/services/earnings_monitor/dashboard/app.py \
      --server.address=0.0.0.0 \
      --server.port="${DASHBOARD_PORT:-8501}" \
      --server.headless=true "$@"
    ;;
  *)
    exec "$role" "$@"
    ;;
esac
