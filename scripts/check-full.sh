#!/usr/bin/env bash
# Полный контур перед коммитом (~9 мин): все тесты + пре-коммит-чеклист.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pytest tests/ -q --no-cov "$@"
echo "--- пре-коммит-чеклист ---"
grep -E '^python3 ' docs/agent-guides/pre-commit-checklist.md | while IFS= read -r cmd; do
  sh -c "$cmd" >/dev/null 2>&1 || { echo "FAIL: $cmd"; exit 1; }
done
echo "чеклист: все команды прошли"
