#!/usr/bin/env bash
set -euo pipefail

# Railway/Railpack cung cap bien PORT, local fallback ve 8000.
cd backend
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
