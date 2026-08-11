#!/usr/bin/env bash
# Быстрая обратная связь (~1 мин): всё, кроме тестов с маркером slow.
# Полный контур — scripts/check-full.sh; он же в CI. Разделение существует потому,
# что девятиминутный цикл перестают запускать, и дыры возвращаются.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
cd "$(dirname "$0")/.."
scripts/warn-path-belt.sh
python3 -m pytest tests/ -q -m "not slow" "$@"
