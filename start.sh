#!/bin/sh
set -e
alembic upgrade head
exec streamlit run app/streamlit_app.py \
  --server.port="${PORT:-8501}" \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --server.enableCORS=false
