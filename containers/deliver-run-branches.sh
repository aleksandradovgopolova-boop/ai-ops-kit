#!/usr/bin/env bash
# v2.113 Container delivery scope: доставить из одноразового клона в основной репо ТОЛЬКО ветки
# ai-ops/*, которые СОЗДАЛ или ИЗМЕНИЛ этот прогон (диф снимка ai-ops/* до/после). Не-затронутые
# ai-ops/* НЕ трогаются -> параллельная работа в другой ветке не перезаписывается устаревшей
# версией из клона. Доверенный host-слой (модель в это не вовлечена — она была заперта в клоне).
#
# Использование: deliver-run-branches.sh <clone> <child_repo> <snapshot-before>
#   <snapshot-before> — вывод `git for-each-ref --format='%(objectname) %(refname:short)'
#                        'refs/heads/ai-ops/*'` из КЛОНА, снятый ДО прогона (может отсутствовать/пуст).
# Печатает "DELIVER: <ветки>" (или "DELIVER: nothing"); код 0 — ок, !=0 — доставка не удалась.
set -euo pipefail

CLONE="${1:?нужен путь клона}"
CHILD="${2:?нужен путь основного репо}"
SNAP="${3:?нужен файл-снимок до прогона}"
[ -f "$SNAP" ] || SNAP=/dev/null

REFSPECS=()
NAMES=()
# Ошибка git внутри process substitution не передаётся циклу while. Сначала читаем refs
# обычным присваиванием: set -e остановит доставку при ошибке, а не объявит «nothing».
CURRENT_REFS="$(git -C "$CLONE" for-each-ref --format='%(objectname) %(refname:short)' 'refs/heads/ai-ops/*')"
while read -r sha ref; do
  [ -n "$ref" ] || continue
  before="$(awk -v r="$ref" '$2==r{print $1}' "$SNAP")"
  if [ "$before" != "$sha" ]; then # новая ветка ИЛИ SHA изменился этим прогоном
    REFSPECS+=("+refs/heads/${ref}:refs/heads/${ref}")
    NAMES+=("$ref")
  fi
done <<<"$CURRENT_REFS"

if [ "${#REFSPECS[@]}" -eq 0 ]; then
  echo "DELIVER: nothing (прогон не создал/не изменил ai-ops/*)"
  exit 0
fi

git -C "$CHILD" fetch --quiet "$CLONE" "${REFSPECS[@]}"
echo "DELIVER: ${NAMES[*]}"
