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

fail() {
  echo "CLEAN-INSTALL FAIL: $*" >&2
  exit 1
}

# ------------------------------------------------------------------ 1. копия кита и child-репозиторий
copy_kit() {
  mkdir -p "$1"
  tar -c --exclude=.git --exclude=__pycache__ --exclude='*.pyc' --exclude=.pytest_cache \
    --exclude=.hypothesis --exclude=htmlcov --exclude='*.egg-info' --exclude='.venv*' \
    --exclude=build --exclude=dist --exclude=.ruff_cache --exclude=.mypy_cache \
    -C "$KIT" . | tar -x -C "$1"
}
copy_kit "$WORK/kit"

mkdir -p "$WORK/child/src"
printf 'def add(a, b):\n    return a + b\n' >"$WORK/child/src/calc.py"
printf '[project]\nname = "demo"\nversion = "0.1"\n' >"$WORK/child/pyproject.toml"
git -C "$WORK/child" init -q .
git -C "$WORK/child" config user.email ci@example.com
git -C "$WORK/child" config user.name ci
git -C "$WORK/child" add -A
git -C "$WORK/child" commit -qm init

# ------------------------------------------------------------------ 2. установка как у пользователя
cd "$WORK/child"
python3 "$WORK/kit/installer/ai_ops.py" init . >"$WORK/init.log" 2>&1 \
  || {
    tail -30 "$WORK/init.log" >&2
    fail "init вернул ненулевой код"
  }
echo "OK  init прошёл"

# ------------------------------------------------------------------ 3. кит исчезает
rm -rf "$WORK/kit"
[ -d "$WORK/kit" ] && fail "parent-кит не удалён"
echo "OK  parent-кит удалён — дальше только child"

# ------------------------------------------------------------------ 4. точки входа ДЕЛАЮТ работу
check_produces_output() {
  local label="$1"
  shift
  local out rc
  # Код возврата — ПОКАЗАТЕЛЬ (#1397): раньше `|| true` его глотал, и команда с Traceback и rc=2
  # проходила как OK. Теперь падение команды — падение проверки.
  out="$("$@" 2>&1)" && rc=0 || rc=$?
  if [ "$rc" -ne 0 ]; then
    printf '%s\n' "$out" | tail -20 >&2
    fail "$label: команда завершилась с кодом $rc (сломанная команда — не «OK»)"
  fi
  case "$out" in
    *Traceback*)
      printf '%s\n' "$out" | tail -20 >&2
      fail "$label: в выводе Traceback — исключение, несмотря на код 0"
      ;;
  esac
  [ -n "${out//[[:space:]]/}" ] || fail "$label: пустой вывод — команда ничего не сделала"
  echo "OK  $label: $(printf '%s' "$out" | head -1 | cut -c1-70)"
}

check_produces_output "ai-ops status" \
  python3 .ai/managed/ai_ops_kit/cli/ai_ops_cli.py status
check_produces_output "run_plan --help" \
  python3 .ai/managed/ai_ops_kit/engine/run_plan.py --help
check_produces_output "workitem --help" \
  python3 .ai/managed/ai_ops_kit/lifecycle/workitem.py --help

# ------------------------------------------------------------------ 5. валидатор child'а зелёный
python3 .ai/managed/ai_ops_kit/validation/validate_ai_ops_child.py >"$WORK/child-validate.log" 2>&1 \
  || {
    tail -20 "$WORK/child-validate.log" >&2
    fail "validate_ai_ops_child упал в свежей установке"
  }
echo "OK  validate_ai_ops_child зелёный"

# ------------------------------------------------------------------ 6. дистрибутив: настоящий pip install
# Инсталлятор кладёт кит в .ai/managed — это ОДИН путь поставки. Второй, объявленный pyproject.toml,
# — обычный пакет. v3.33.0 объявил «пакет стал пакетом», проверив это имитацией sys.path; настоящая
# установка тут же показала модуль, который так не импортируется. Имитация — не установка.
cd "$WORK"
copy_kit "$WORK/wheel-source"
python3 -m venv "$WORK/build-venv" >/dev/null 2>&1 || fail "не удалось создать build venv"
# Сборочные зависимости уже объявлены в pyproject.toml; в runtime-venv они не попадают.
"$WORK/build-venv/bin/python" - "$WORK/wheel-source/pyproject.toml" >"$WORK/build-deps.log" 2>&1 <<'BUILD_DEPS' || {
import pathlib, subprocess, sys, tomllib
requires = tomllib.loads(pathlib.Path(sys.argv[1]).read_text())["build-system"]["requires"]
subprocess.run([sys.executable, "-m", "pip", "install", "-q", *requires], check=True)
BUILD_DEPS
  tail -20 "$WORK/build-deps.log" >&2
  fail "сборочные зависимости недоступны"
}

# Путь sdist -> wheel держит и установку из исходного архива: один прямой wheel этого не доказывает.
mkdir -p "$WORK/dist" "$WORK/wheels"
(cd "$WORK/wheel-source" && "$WORK/build-venv/bin/python" -c \
  'from setuptools.build_meta import build_sdist; import sys; build_sdist(sys.argv[1])' "$WORK/dist") \
  >"$WORK/sdist.log" 2>&1 \
  || {
    tail -20 "$WORK/sdist.log" >&2
    fail "sdist не собрался"
  }
"$WORK/build-venv/bin/pip" wheel --no-deps --no-build-isolation -q \
  --wheel-dir "$WORK/wheels" "$WORK/dist/"*.tar.gz >"$WORK/wheel.log" 2>&1 \
  || {
    tail -20 "$WORK/wheel.log" >&2
    fail "wheel из sdist не собрался"
  }
[ ! -e "$WORK/wheel-source/ai_ops_kit/VERSION" ] || fail "сборка записала VERSION в исходный пакет"

# Fail-closed самой сборки: потеря data-каталога не должна выпускать неполный wheel.
rm -rf "$WORK/wheel-source/registry"
if (cd "$WORK/wheel-source" && "$WORK/build-venv/bin/python" -c \
  'from setuptools.build_meta import build_wheel; import sys; build_wheel(sys.argv[1])' "$WORK/broken") \
  >"$WORK/broken-build.log" 2>&1; then
  fail "сборка wheel без registry ошибочно прошла"
fi
grep -q 'missing runtime data directory: registry' "$WORK/broken-build.log" \
  || {
    tail -20 "$WORK/broken-build.log" >&2
    fail "сборка отказала не по причине отсутствия registry"
  }
rm -rf "$WORK/wheel-source" "$WORK/dist" "$WORK/build-venv"
echo "OK  wheel собран через sdist; неполная сборка отклонена; исходники сборки удалены"

python3 -m venv "$WORK/venv" >/dev/null 2>&1 || fail "не удалось создать venv"

# Снимок .pth-поясов ДО установки. Сравнение до/после, а не «после пусто»: у разработчика,
# ставившего кит до v3.33.1, пояс уже лежит в пользовательском site (его находит `ai-ops doctor`).
# Проверять здесь надо не чистоту машины, а то, что УСТАНОВКА не добавила ни одного пояса —
# именно это делал setup.py на каждом pip install.
belts_of() { PYTHONPATH="$KIT" "$1" -c 'from ai_ops_kit.shared import path_hygiene as ph
print("\n".join(sorted(f["path"] for f in ph.assess()["findings"] if f["rule"] == "path_belt")))'; }
belts_of "$WORK/venv/bin/python" >"$WORK/belts-before.txt" || fail "снимок поясов не снялся"

"$WORK/venv/bin/pip" install -q "$WORK/wheels/"*.whl >"$WORK/pip.log" 2>&1 \
  || {
    tail -20 "$WORK/pip.log" >&2
    fail "pip install пакета не прошёл"
  }
echo "OK  pip install прошёл"

belts_of "$WORK/venv/bin/python" >"$WORK/belts-after.txt" || fail "снимок поясов не снялся"
if ! new_belts="$(comm -13 "$WORK/belts-before.txt" "$WORK/belts-after.txt")" || [ -n "${new_belts//[[:space:]]/}" ]; then
  echo "$new_belts" >&2
  fail "установка написала .pth-пояс в site-packages — пакет правит sys.path чужих процессов"
fi
echo "OK  установка не написала ни одного .pth-пояса"

# Каждый модуль — ПЕРВЫМ в своём процессе: порядок импортов не контракт, и модуль, работающий лишь
# после соседа, в чужом коде сломается на первом же прямом импорте.
"$WORK/venv/bin/python" - <<'PROBE' || fail "модули пакета не импортируются после pip install"
import importlib, subprocess, sys, pathlib
pkg = pathlib.Path(importlib.import_module("ai_ops_kit").__file__).parent
mods = [f"ai_ops_kit.{d.name}.{f.stem}"
        for d in sorted(pkg.iterdir()) if d.is_dir() and d.name != "__pycache__"
        for f in sorted(d.glob("*.py")) if f.name != "__init__.py"]
bad = []
for m in mods:
    r = subprocess.run([sys.executable, "-c", f"import {m}"], capture_output=True, text=True)
    if r.returncode != 0:
        bad.append(f"{m}: {r.stderr.strip().splitlines()[-1] if r.stderr else '?'}")
print(f"    проверено модулей: {len(mods)}, сломанных: {len(bad)}")
for b in bad[:5]:
    print(f"    FAIL {b}")
sys.exit(1 if bad else 0)
PROBE
echo "OK  все модули пакета импортируются из site-packages"

# Изолированный интерпретатор исключает cwd/PYTHONPATH/user site. Проверяем смысл JSON и файлы,
# включая fail-closed после реального удаления реестра, а не только --help и успешный импорт.
"$WORK/venv/bin/python" -I "$KIT/tests/integration/wheel_runtime_probe.py" \
  "$KIT" "$WORK/wheels/"*.whl "$WORK/wheel-product" || fail "wheel не исполняет plan/next вне клона"

echo "CLEAN-INSTALL OK: кит работает там, где нет ни кита, ни pytest, ни PYTHONPATH"
