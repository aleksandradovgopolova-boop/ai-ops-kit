#!/usr/bin/env bash
# Быстрая обратная связь (~1 мин): всё, кроме тестов с маркером slow.
# Полный контур — scripts/check-full.sh; он же в CI. Разделение существует потому,
# что девятиминутный цикл перестают запускать, и дыры возвращаются.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pytest tests/ -q --no-cov -m "not slow" "$@"
