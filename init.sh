#!/usr/bin/env bash
set -euo pipefail

echo "Repository: $(pwd)"
echo "Harness status: pre-bootstrap"
echo "Application stack is not initialized yet."
echo "Next step: implement feature 'bootstrap-app-skeleton' from feature_list.json."
echo "Expected future commands (Python + FastAPI, see docs/technical-discovery.md):"
echo "  install: pip install -e '.[dev]'"
echo "  verify:  pytest"
echo "  start:   uvicorn <app module>:app --reload"
