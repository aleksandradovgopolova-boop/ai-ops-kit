#!/usr/bin/env bash
# Быстрая обратная связь (~1 мин): всё, кроме тестов с маркером slow, параллельно по ядрам.
# Полный контур — scripts/check-full.sh; он же в CI. Разделение существует потому,
# что девятиминутный цикл перестают запускать, и дыры возвращаются.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
cd "$(dirname "$0")/.."
scripts/warn-path-belt.sh
# -n auto: параллель по ядрам (набор параллель-безопасен — проверено на полном прогоне). Без
# pytest-xdist прогон идёт как раньше, последовательно, — быстрый профиль не обязан падать из-за него.
XNUM=""
if python3 -c 'import xdist' >/dev/null 2>&1; then XNUM="-n auto"; fi
# shellcheck disable=SC2086 — XNUM намеренно либо два слова (-n auto), либо пусто
python3 -m pytest tests/ -q -m "not slow" $XNUM "$@"
