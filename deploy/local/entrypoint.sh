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
    exec python -m services.earnings_monitor worker \
      --interval="${WORKER_IDLE_SECONDS:-10}" "$@"
    ;;
  history-import)
    exec python -m services.earnings_monitor.history_import \
      --source-root="${EARNINGS_MONITOR_HISTORY_SOURCE:-/history-source/output}" \
      --destination="${EARNINGS_MONITOR_DATASET:-/data/company_quarters.parquet}" "$@"
    ;;
  dashboard)
    # Streamlit serves <script_dir>/static at /app/static/... when enabled.
    # Compose may already bind-mount reports into dashboard/static/reports.
    mkdir -p /app/static \
      /app/services/earnings_monitor/dashboard/static \
      /home/app/.streamlit
    REPORTS_SRC="${EARNINGS_MONITOR_HISTORY_SOURCE:-/history-source/output}/cross_company/reports"
    REPORTS_DST="/app/services/earnings_monitor/dashboard/static/reports"
    if [ -d "$REPORTS_SRC" ] && [ ! -e "$REPORTS_DST" ]; then
      ln -sfn "$REPORTS_SRC" "$REPORTS_DST"
    fi
    if [ -d "$REPORTS_SRC" ] && [ ! -e /app/static/reports ]; then
      ln -sfn "$REPORTS_SRC" /app/static/reports
    fi
    # Ensure static serving even if CLI flags are overridden by config defaults.
    cat > /home/app/.streamlit/config.toml <<'EOF'
[server]
enableStaticServing = true
headless = true
address = "0.0.0.0"
port = 8501
EOF
    exec streamlit run /app/services/earnings_monitor/dashboard/app.py \
      --server.address=0.0.0.0 \
      --server.port="${DASHBOARD_PORT:-8501}" \
      --server.headless=true \
      --server.enableStaticServing=true "$@"
    ;;
  *)
    exec "$role" "$@"
    ;;
esac
