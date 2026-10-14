#!/bin/bash
cd "$(dirname "$0")" && exec python3 -m uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}
