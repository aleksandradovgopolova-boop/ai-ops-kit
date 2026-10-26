#!/usr/bin/env bash
# Проверки итерации: по умолчанию impact полного diff от origin/main и существующие receipts.
# --impact принимает свою базу/intent/plan-only; --all запускает прежний весь набор без slow.
# Старые pytest-аргументы также используют прежний путь. При неизвестном влиянии impact
# расширяет охват до PR-профиля. Успех итерации не заменяет финальный CI/compatibility-matrix.
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

# Честность версии: тот же интерпретатор ведёт цикл, а блокирующий CI считает пол requires-python.
# Расходится minor (машина владельца: local 3.14 vs CI 3.12) — зелёное здесь не предсказывает
# зелёное в CI; предупреждаем ДО пуша. Advisory: `|| true` — разница версий НЕ блокирует итерацию.
"$PYTHON" -m ai_ops_kit.devtools.python_drift || true

# Обычная итерация использует impact и receipts. База обязательна: иначе после коммита
# чистая рабочая папка скрыла бы изменения ветки. Нет origin/main → явный отказ с возможностью
# назвать реальную базу через --impact --base REF. Сеть автоматически не вызывается.
if [[ $# -eq 0 ]]; then
  "$PYTHON" -m ai_ops_kit.devtools.impact_check_cli --base origin/main
  exit $?
fi
# Impact ведёт lint и тесты через тот же журнал; plan-only ничего не исполняет.
if [[ "${1:-}" == "--impact" ]]; then
  shift
  "$PYTHON" -m ai_ops_kit.devtools.impact_check_cli "$@"
  exit $?
fi

# Прежний весь быстрый набор остаётся явным. Старые pytest-аргументы также совместимы.
if [[ "${1:-}" == "--all" ]]; then shift; fi

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
