#!/bin/sh
set -e
# Log DB host/name for debugging (strips password from URL)
echo "DATABASE_URL (masked): $(echo "${DATABASE_URL}" | sed 's|://[^:]*:[^@]*@|://***:***@|')"
alembic upgrade head
exec streamlit run app/streamlit_app.py \
  --server.port="${PORT:-8501}" \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --server.enableCORS=false
