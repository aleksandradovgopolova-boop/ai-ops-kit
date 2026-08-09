#!/usr/bin/env bash
# Прогон установки в ЧИСТОМ окружении — то, что видит пользователь, а не разработчик (v3.31.1).
#
# Зачем отдельно от pytest: этот прогон должен идти там, где НЕТ pytest, hypothesis, editable-
# установки кита и PYTHONPATH. Ровно в таких условиях за один день всплыли три дефекта, которых
# зелёный CI не видел: голый `import _bootstrap` в валидаторах, пояс PYTHONPATH в workflow и
# молчаливый no-op всех 94 точек входа. Каждый раз кит «работал» у себя и не работал у пользователя.
#
# Критерий — РАБОТА (непустой вывод), а не код возврата: скрипт, который ничего не делает,
# возвращает 0 и выглядит успехом. Именно так дефект точек входа пережил проверку «прямой запуск rc=0».
#
# Поток повторяет пользовательский буквально:
#   копия кита -> чистый git-репозиторий -> ai_ops.py init -> УДАЛИТЬ кит -> запускать из child.
# Удаление parent'а — не педантизм: у пользователя клона кита нет вовсе.
set -euo pipefail

KIT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

export PYTHONDONTWRITEBYTECODE=1
unset PYTHONPATH || true

fail() { echo "CLEAN-INSTALL FAIL: $*" >&2; exit 1; }

# ------------------------------------------------------------------ 1. копия кита и child-репозиторий
mkdir -p "$WORK/kit"
tar -c --exclude=.git --exclude=__pycache__ --exclude='*.pyc' --exclude=.pytest_cache \
    --exclude=.hypothesis --exclude=htmlcov --exclude='*.egg-info' -C "$KIT" . | tar -x -C "$WORK/kit"

mkdir -p "$WORK/child/src"
printf 'def add(a, b):\n    return a + b\n' > "$WORK/child/src/calc.py"
printf '[project]\nname = "demo"\nversion = "0.1"\n' > "$WORK/child/pyproject.toml"
git -C "$WORK/child" init -q .
git -C "$WORK/child" config user.email ci@example.com
git -C "$WORK/child" config user.name ci
git -C "$WORK/child" add -A
git -C "$WORK/child" commit -qm init

# ------------------------------------------------------------------ 2. установка как у пользователя
cd "$WORK/child"
python3 "$WORK/kit/installer/ai_ops.py" init . > "$WORK/init.log" 2>&1 \
  || { tail -30 "$WORK/init.log" >&2; fail "init вернул ненулевой код"; }
echo "OK  init прошёл"

# ------------------------------------------------------------------ 3. кит исчезает
rm -rf "$WORK/kit"
[ -d "$WORK/kit" ] && fail "parent-кит не удалён"
echo "OK  parent-кит удалён — дальше только child"

# ------------------------------------------------------------------ 4. точки входа ДЕЛАЮТ работу
check_produces_output() {
  local label="$1"; shift
  local out
  out="$("$@" 2>&1 || true)"
  [ -n "${out//[[:space:]]/}" ] || fail "$label: пустой вывод — команда ничего не сделала (rc не показатель)"
  echo "OK  $label: $(printf '%s' "$out" | head -1 | cut -c1-70)"
}

check_produces_output "ai-ops status" \
  python3 .ai/managed/tools/ai_ops_cli.py status
check_produces_output "run_plan --help" \
  python3 .ai/managed/tools/run_plan.py --help
check_produces_output "workitem --help" \
  python3 .ai/managed/tools/workitem.py --help

# ------------------------------------------------------------------ 5. валидатор child'а зелёный
python3 .ai/managed/validation/validate_ai_ops_child.py > "$WORK/child-validate.log" 2>&1 \
  || { tail -20 "$WORK/child-validate.log" >&2; fail "validate_ai_ops_child упал в свежей установке"; }
echo "OK  validate_ai_ops_child зелёный"

echo "CLEAN-INSTALL OK: кит работает там, где нет ни кита, ни pytest, ни PYTHONPATH"
