#!/usr/bin/env bash
# Локальные профили: default — full-current-python; --pr — без nightly/release_gate.
# Единственная точка входа: всё, что раньше
# перечислялось в пре-коммит-чеклисте построчно (201 команда на пике), — это тесты.
#
# v3.34: скрипт называет СВОЙ охват сам. «Полный» здесь значит «весь pytest», а не «вся
# поддерживаемая матрица»: PR #38 написал «полный контур зелёный», и compatibility-matrix
# опровергла это в том же релизе. Охват объявляется до и после прогона — ровно в тот момент,
# когда возникает искушение сформулировать результат шире, чем он получен.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
cd "$(dirname "$0")/.."

# --pr обещает конкретный набор: пользовательский selector не может сузить его молча.
HOST_ARGS=("$@")
PROFILE=full-current-python
if [[ "${1:-}" == "--pr" ]]; then PROFILE=pr-current-python; shift; fi
CUSTOM=0
COLLECTION=0
if [[ -n "${PYTEST_ADDOPTS:-}" ]]; then CUSTOM=1; fi
ARGS=("$@")
for ((i=0; i<${#ARGS[@]}; i++)); do
  case "${ARGS[i]}" in
    -n|--numprocesses|--dist|--durations|--durations-min|--tb|--capture|--color)
      if ((i+1 < ${#ARGS[@]})) && [[ "${ARGS[i+1]}" != -* ]]; then
        i=$((i+1))
      else CUSTOM=1; fi ;;
    --numprocesses=*|--dist=*|--durations=*|--durations-min=*|--tb=*|--capture=*|--color=*|-n[0-9]*|-nauto|-nlogical)
      ;;
    -q|-v|-vv|-s|--disable-warnings|--strict-markers|--strict-config) ;;
    --collect-only|--co) COLLECTION=1; CUSTOM=1 ;;
    *) CUSTOM=1 ;;
  esac
done
if [[ "$PROFILE" == pr-current-python && "$CUSTOM" == 1 ]]; then
  echo "ОТКАЗ: --pr не допускает selectors, collect-only, неизвестные аргументы или PYTEST_ADDOPTS." >&2
  exit 2
fi
if [[ "$CUSTOM" == 1 ]]; then PROFILE=custom-current-python; fi
if [[ "$COLLECTION" == 1 ]]; then PROFILE=collection-only; fi

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

# Collection-only не исполняет тесты; широкие профили требуют настоящего host-slot.
# Исходные argv сохраняются: --pr нельзя потерять при re-exec после shift.
if [[ "$PROFILE" != collection-only ]] && ! "$PYTHON" -m ai_ops_kit.devtools.host_resource_cli --verify-inherited; then
  exec "$PYTHON" -m ai_ops_kit.devtools.host_resource_cli \
    --owner kit-check-full --wait-seconds 3600 -- bash "$0" "${HOST_ARGS[@]}"
fi

FLOOR=$(sed -n 's/^requires-python[[:space:]]*=[[:space:]]*"\(.*\)"/\1/p' pyproject.toml | head -1)
CURRENT=$("$PYTHON" -c 'import platform, sys; print(f"{platform.python_implementation()} {platform.python_version()} / {sys.platform}")')

echo "ОХВАТ: ${PROFILE} — ${CURRENT}."
case "$PROFILE" in
  pr-current-python) echo "Все обычные fast/slow/contracts; НЕ входят nightly и release_gate." ;;
  full-current-python) echo "Весь локальный pytest, включая nightly; НЕ входит release_gate (отдельный CI выпуска)." ;;
  *) echo "Запрошена база full-current-python с пользовательским выбором/сбором: полнота НЕ подтверждается." ;;
esac
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
if [[ "$PROFILE" == pr-current-python ]]; then
  "$PYTHON" -m pytest tests/ -q -n auto --dist loadfile -m "not nightly and not release_gate" "$@"
else
  "$PYTHON" -m pytest tests/ -q -n auto --dist loadfile "$@"
fi

echo
case "$PROFILE" in
  full-current-python|pr-current-python)
    echo "ЗЕЛЁНЫЙ ОХВАТ: ${PROFILE} (${CURRENT}). Совместимость и release gates подтверждает отдельный CI." ;;
  collection-only) echo "СБОР ЗАВЕРШЁН: collection-only; тесты НЕ исполнялись, зелёного evidence нет." ;;
  *) echo "КОД 0: custom-current-python; пользовательский выбор НЕ подтверждает полный охват." ;;
esac
