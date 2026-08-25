#!/usr/bin/env bash
# Полный контур перед коммитом (~4.5 мин). Единственная точка входа: всё, что раньше
# перечислялось в пре-коммит-чеклисте построчно (201 команда на пике), — это тесты.
#
# v3.34: скрипт называет СВОЙ охват сам. «Полный» здесь значит «весь pytest», а не «вся
# поддерживаемая матрица»: PR #38 написал «полный контур зелёный», и compatibility-matrix
# опровергла это в том же релизе. Охват объявляется до и после прогона — ровно в тот момент,
# когда возникает искушение сформулировать результат шире, чем он получен.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
cd "$(dirname "$0")/.."

# Порядок не случаен: сперва честность ОКРУЖЕНИЯ (v3.33.3 — пояс в site-packages делает любой
# зелёный результат недоказательным), затем честность ОХВАТА (v3.34). Оба предупреждения — ДО
# прогона: узнавать, что «зелёное» ничего не значит, надо не после успеха.
scripts/warn-path-belt.sh

# ИНТЕРПРЕТАТОР НАЗЫВАЕТСЯ ОДИН РАЗ И ИСПОЛЬЗУЕТСЯ ТОТ ЖЕ (19.08.2026, `local-run-must-mirror-ci`).
# `python3` из PATH и интерпретатор, которым человек на самом деле работает, — разные вещи: на
# машине владельца `python3` это homebrew 3.14 БЕЗ pytest, а работа идёт в venv 3.11. Скрипт при
# этом объявлял охват по первому и падал на `No module named pytest` — то есть документированная
# точка входа «полный контур» не работала вовсе, а тест об этом молчал, потому что сравнивал
# объявленную версию со СВОИМ интерпретатором.
PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import pytest' >/dev/null 2>&1; then
  echo "ОТКАЗ: интерпретатор '${PYTHON}' есть, а pytest в нём нет — прогонять нечем." >&2
  echo "  $("$PYTHON" -c 'import sys; print(sys.executable)' 2>/dev/null || echo "$PYTHON")" >&2
  echo "Запустите из своего окружения или назовите его явно: PYTHON=.venv/bin/python $0" >&2
  exit 2
fi

FLOOR=$(sed -n 's/^requires-python[[:space:]]*=[[:space:]]*"\(.*\)"/\1/p' pyproject.toml | head -1)
CURRENT=$("$PYTHON" -c 'import platform, sys; print(f"{platform.python_implementation()} {platform.python_version()} / {sys.platform}")')

echo "ОХВАТ: full-current-python — ${CURRENT}."
echo "НЕ входит: объявленный пол requires-python ${FLOOR:-?} и установка в чистое окружение —"
echo "это compatibility-matrix, её дают только джобы CI pipeline-e2e / clean-install / upgrade-path."
echo

# Линтер — ДО тестов: F821 (вызов несуществующего имени) находится за секунды, а тремя минутами
# позже уже неинтересен. Ревизия 2026-08-11: ruff не запускался ни здесь, ни в CI, и пять точек
# входа падали с NameError при живом зелёном контуре.
if command -v ruff >/dev/null 2>&1; then
  echo "ЛИНТЕР: ruff, набор из pyproject.toml ([tool.ruff.lint])."
  ruff check .
  # Битая директива `# noqa` не подавляет ничего, а ruff говорит об этом ПРЕДУПРЕЖДЕНИЕМ и
  # выходит с кодом 0: подавление объявлено и не работает. Поднимаем до ошибки.
  if ruff check . --select ALL 2>&1 | grep -F 'Invalid `# noqa`'; then
    echo "ОШИБКА: битая директива # noqa — подавление объявлено, но не работает." >&2
    exit 1
  fi
  echo
else
  # Громко, а не молча: проверка, которая не запустилась, не должна выглядеть как пройденная.
  echo "ЛИНТЕР НЕ ЗАПУЩЕН: ruff не установлен, класс F821/F811/B023 сейчас НЕ проверен."
  echo "Поставить: pip install ruff  (или pip install -e \".[dev]\")"
  echo "В CI он есть — джоба lint в .github/workflows/package-quality.yml."
  echo
fi

# -n auto: параллель по ядрам. Набор параллель-безопасен (проверено: 3343 passed под -n auto).
# 665с -> ~283с на 10 ядрах. Переопределить числом воркеров: PYTEST_XDIST_AUTO_NUM_WORKERS или -n N в "$@".
"$PYTHON" -m pytest tests/ -q -n auto --dist loadfile "$@"

echo
echo "ЗЕЛЁНЫЙ ОХВАТ: full-current-python (${CURRENT}). Формулируя результат, назови охват:"
echo "«полный контур зелёный» без имени охвата — заявление шире полученного."
