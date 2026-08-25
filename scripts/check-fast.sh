#!/usr/bin/env bash
# Быстрая обратная связь (~1–2 мин): те же БЫСТРЫЕ БЛОКИРУЮЩИЕ ворота, что и CI — линтер (джоба
# `lint`) и весь pytest без маркера `slow` (джобы `fast`/`contracts`), — чтобы красное ловилось
# ДО пуша, а не раундом CI после (работа `local-check-mirrors-ci`, находка
# docs/parallel-execution-retro.md: регистрация валидатора/пакета, layering, public-surface,
# footprint всплывали в CI после пуша, тратя раунд).
#
# НЕ входит и НЕ обязано: медленные selftests (группы `selftests-a`/`selftests-m`, ~8 мин) и
# compatibility-matrix (другой интерпретатор, чистая установка, upgrade-path). Их даёт
# scripts/check-full.sh и CI. Поэтому «быстро зелёное» НЕ значит «CI зелёный»: полный охват — только
# check-full. Разделение существует потому, что девятиминутный цикл перестают запускать, и дыры
# возвращаются.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
cd "$(dirname "$0")/.."

# Порядок как в check-full: сперва честность окружения (пояс в site-packages делает зелёное
# недоказательным), затем — тот же интерпретатор, которым реально работает запускающий.
scripts/warn-path-belt.sh

# ИНТЕРПРЕТАТОР НАЗЫВАЕТСЯ ОДИН РАЗ И ИСПОЛЬЗУЕТСЯ ТОТ ЖЕ (19.08.2026, `local-run-must-mirror-ci`).
# `python3` из PATH и интерпретатор, которым человек на самом деле работает, — разные вещи: на
# машине владельца `python3` это homebrew БЕЗ pytest, и быстрая проверка падала `No module named
# pytest` вместо названного отказа. check-full это уже чинил; check-fast обязан вести себя так же.
PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import pytest' >/dev/null 2>&1; then
  echo "ОТКАЗ: интерпретатор '${PYTHON}' есть, а pytest в нём нет — прогонять нечем." >&2
  echo "  $("$PYTHON" -c 'import sys; print(sys.executable)' 2>/dev/null || echo "$PYTHON")" >&2
  echo "Запустите из своего окружения или назовите его явно: PYTHON=.venv/bin/python $0" >&2
  exit 2
fi

# Линтер — часть блокирующего CI (джоба `lint`) и находится за секунды: F821 (вызов несуществующего
# имени) не должен ждать раунда CI. Тот же набор, что в check-full и CI ([tool.ruff.lint]).
if command -v ruff >/dev/null 2>&1; then
  ruff check .
else
  # Громко, а не молча: проверка, которая не запустилась, не должна выглядеть как пройденная.
  echo "ЛИНТЕР НЕ ЗАПУЩЕН: ruff не установлен, класс F821/F811/B023 сейчас НЕ проверен (в CI он есть)."
fi

# -n auto: параллель по ядрам (набор параллель-безопасен — проверено на полном прогоне). Без
# pytest-xdist прогон идёт последовательно — быстрый профиль не обязан падать из-за его отсутствия.
XNUM=""
if "$PYTHON" -c 'import xdist' >/dev/null 2>&1; then XNUM="-n auto --dist loadfile"; fi
# shellcheck disable=SC2086 — XNUM намеренно либо два слова (-n auto), либо пусто
"$PYTHON" -m pytest tests/ -q -m "not slow" $XNUM "$@"
