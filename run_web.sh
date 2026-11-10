#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ -x .venv-web/bin/python ]]; then
    web_python=.venv-web/bin/python
elif [[ -x work/web-venv/bin/python ]]; then
    web_python=work/web-venv/bin/python
else
    printf '%s\n' 'Install once: python3 -m venv .venv-web' '.venv-web/bin/pip install -r requirements-web.txt'
    exit 1
fi
export OSINTNATOR_ORIGIN=http://127.0.0.1:8766
printf '%s\n' 'Open http://127.0.0.1:8766 in your browser. Press Ctrl-C to stop.'
exec "$web_python" -m uvicorn web_app:create_app --factory --host 127.0.0.1 --port 8766 --workers 1 --no-access-log
