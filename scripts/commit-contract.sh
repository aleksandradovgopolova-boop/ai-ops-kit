#!/usr/bin/env bash
# Исполнить CommitContract на том, что реально уходит в коммит.
#
# ЗАЧЕМ (замер 12.08.2026). `commit_policy.check_commit` существует с v3.19.0 и НЕ ЗАПУСКАЛСЯ
# нигде: ни в хуках, ни в CI. На коммите 4a231ae, где `git add -A` унёс в чужой коммит фикс
# CI-шаблона и research-скан, контракт даёт `broad_scope` — «затронуто 5 верхнеуровневых каталогов,
# похоже на несколько задач в одном коммите». Проверка была права и молчала, потому что её не звали.
#
# Стадия `commit-msg`, а не `pre-commit`: контракту нужны И файлы, И текст сообщения (часть правил —
# про сообщение: заглушки, секреты, ссылка на WorkItem и evidence). На стадии `pre-commit` сообщения
# ещё нет, поэтому половина контракта там не исполнилась бы — а половина проверки хуже отсутствующей:
# она создаёт видимость полной.
#
# Сегодня контракт СОВЕТУЕТ (enforce: advise): rc берётся из `allowed`, то есть блокируют только
# настоящие нарушения, а советы печатаются. Ужесточение — решение владельца
# (planning/plan.yaml -> session-coordination), правило репозитория: сначала field evidence.
set -euo pipefail
cd "$(dirname "$0")/.."

MSG_FILE="${1:-}"
if [ -z "$MSG_FILE" ] || [ ! -f "$MSG_FILE" ]; then
  echo "commit-contract: не передан файл сообщения коммита — хук вызван не со стадии commit-msg." >&2
  exit 2
fi

# Shell выбирает интерпретатор; индекс, сообщение и координацию читает Python.
PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import yaml' 2>/dev/null; then
  echo "CommitContract НЕ ВЫПОЛНЕН: у '$PYTHON' нет pyyaml — охват коммита и осмысленность" >&2
  echo "сообщения сейчас НЕ проверены (это не «нарушений нет»)." >&2
  echo "Поставить: $PYTHON -m pip install pyyaml   (или PYTHON=<интерпретатор> с pyyaml)" >&2
  exit 1
fi
exec "$PYTHON" -m ai_ops_kit.devtools.commit_hook "$MSG_FILE"
