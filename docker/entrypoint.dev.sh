#!/usr/bin/env bash
set -euo pipefail

pip install --no-cache-dir --break-system-packages $(python -c "import tomllib; print(' '.join(tomllib.load(open('/app/pyproject.toml','rb'))['project']['dependencies']))") > /dev/null

exec "$@"
