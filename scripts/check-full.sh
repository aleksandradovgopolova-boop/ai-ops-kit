#!/usr/bin/env bash
# Полный контур перед коммитом (~4.5 мин). Единственная точка входа: всё, что раньше
# перечислялось в пре-коммит-чеклисте построчно (201 команда на пике), — это тесты.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
cd "$(dirname "$0")/.."
python3 -m pytest tests/ -q --no-cov "$@"
