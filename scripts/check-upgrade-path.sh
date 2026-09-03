#!/usr/bin/env bash
# Обновление версия -> версия: САМЫЙ ЧАСТЫЙ сценарий дочки, не проверенный ничем (аудит 19.08.2026).
#
# ЗАЧЕМ. `check-clean-install.sh` проверяет установку С НУЛЯ. Но с нуля дочка ставится один раз, а
# обновляется каждый день: `ai-ops-update.yml` включён по умолчанию. Именно на этом пути и жили
# самые дорогие находки поля:
#   F-030 — правило «закрытая работа живёт в history» приехало к дочкам БЕЗ миграции, и после
#           обновления `./ai-ops next` отказывался отвечать, печатая по ошибке на каждую работу;
#   F-032 — точка входа обновлялась на релиз позже кита;
#   гейт отставания — репозиторий с 15.08 лгал о своей версии: объявлена 3.36.10, установлена
#           3.36.12, содержимое разошлось на 49 файлов.
# Каждая из них ломала не установку, а ОБНОВЛЕНИЕ — и ни одна проверка кита туда не смотрела.
#
# ЧТО ИМЕННО ПРОВЕРЯЕТСЯ: ставим ПРЕДЫДУЩИЙ выпуск, обновляем до текущего дерева и требуем, чтобы
# после обновления дочка отвечала на вопросы владельца, версия и содержимое сходились, а файлы
# ВЛАДЕЛЬЦА остались нетронутыми.
#
# КРИТЕРИЙ — РАБОТА, А НЕ КОД ВОЗВРАТА (тот же урок, что в check-clean-install): команда, которая
# ничего не делает, возвращает 0 и выглядит успехом.
# ПРОВЕРКА УМЕЕТ КРАСНЕТЬ — ЗАМЕРЕНО, А НЕ ОБЪЯВЛЕНО (19.08.2026). Зелёная проверка ничего не
# значит, пока не показано, что она ловит то, ради чего написана. Два мутанта, оба убиты:
#   1. `bump_child_config` перестаёт обновлять версию (класс F-032, «копия лжёт о себе»)
#      -> FAIL на шаге 3/4;
#   2. `deliver_assets` правит файл владельца
#      -> «UPGRADE-PATH FAIL: обновление изменило файл владельца src/app.ts».
# Реестр `quality/mutation-probes.yaml` сюда не подходит: он целится в pytest-тесты, а это
# отдельный прогон в чистом окружении — тот же образец, что `check-clean-install.sh`.
set -euo pipefail

KIT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

export PYTHONDONTWRITEBYTECODE=1
unset PYTHONPATH || true

fail() { echo "UPGRADE-PATH FAIL: $*" >&2; exit 1; }
note() { echo "OK  $*"; }

# ------------------------------------------------------------------ 1. с какой версии обновляемся
# Предыдущий выпуск берём из тегов САМОГО репозитория, а не вписываем числом: вписанное устаревает
# на следующем релизе и проверка начинает мерить не то.
CURRENT="$(tr -d '[:space:]' < "$KIT/VERSION")"
PREV_TAG="$(git -C "$KIT" tag --sort=-v:refname | grep -v "^v${CURRENT}$" | head -1 || true)"
[ -n "$PREV_TAG" ] || fail "не нашёл предыдущий тег — не от чего обновляться"
note "обновляем ${PREV_TAG} -> ${CURRENT} (рабочее дерево)"

# Копия кита на предыдущем теге. `git archive` вместо клона: нужен слепок файлов, а не история.
mkdir -p "$WORK/kit-prev"
git -C "$KIT" archive "$PREV_TAG" | tar -x -C "$WORK/kit-prev"
[ -f "$WORK/kit-prev/installer/ai_ops.py" ] || fail "в теге $PREV_TAG нет установщика"

# ------------------------------------------------------------------ 2. дочка с файлами ВЛАДЕЛЬЦА
mkdir -p "$WORK/child/src"
printf 'export const answer = 42\n' > "$WORK/child/src/app.ts"
printf '{"name":"demo","version":"0.1.0"}\n' > "$WORK/child/package.json"
git -C "$WORK/child" init -q .
git -C "$WORK/child" config user.email ci@example.com
git -C "$WORK/child" config user.name ci
git -C "$WORK/child" add -A
git -C "$WORK/child" commit -qm init
OWNER_SHA_BEFORE="$(shasum "$WORK/child/src/app.ts" | cut -d' ' -f1)"

cd "$WORK/child"
python3 "$WORK/kit-prev/installer/ai_ops.py" init . > "$WORK/init.log" 2>&1 \
  || { tail -30 "$WORK/init.log" >&2; fail "установка предыдущего выпуска не прошла"; }
git add -A && git commit -qm "ai-ops init $PREV_TAG"
note "установлен $PREV_TAG"

INSTALLED_BEFORE="$(python3 -c "import yaml;print(yaml.safe_load(open('.ai-ops.yaml'))['parent']['installed_version'])")"
[ -n "$INSTALLED_BEFORE" ] || fail "конфиг дочки без installed_version"

# ------------------------------------------------------------------ 3. ОБНОВЛЕНИЕ
# `--in-place`: путь CI. Политика `pr` уводит обновление в ветку, и это правильно для владельца, но
# здесь нам нужно проверить САМО обновление, а не механизм его доставки (его проверяет отдельно
# `test_installer`).
python3 "$KIT/installer/ai_ops.py" update --in-place > "$WORK/update.log" 2>&1 \
  || { tail -40 "$WORK/update.log" >&2; fail "обновление вернуло ненулевой код"; }
grep -q . "$WORK/update.log" || fail "обновление ничего не напечатало — код возврата не показатель"
note "обновление прошло: $(head -1 "$WORK/update.log" | cut -c1-70)"

# ------------------------------------------------------------------ 4. версия и содержимое сошлись
INSTALLED_AFTER="$(python3 -c "import yaml;print(yaml.safe_load(open('.ai-ops.yaml'))['parent']['installed_version'])")"
[ "$INSTALLED_AFTER" = "$CURRENT" ] \
  || fail "после обновления конфиг объявляет $INSTALLED_AFTER, а пакет $CURRENT — копия лжёт о себе (класс F-032)"
note "объявленная версия сошлась с пакетом: $INSTALLED_AFTER"

python3 .ai/managed/ai_ops_kit/validation/ai_managed_checksums.py verify > "$WORK/drift.log" 2>&1 \
  || { tail -20 "$WORK/drift.log" >&2; fail "целостность managed-слоя после обновления нарушена"; }
note "целостность managed-слоя: сошлась"

# ------------------------------------------------------------------ 5. дочка ОТВЕЧАЕТ владельцу
# Ровно то, что сломала F-030: после обновления `next` отказывался отвечать. Требуем непустой
# вывод, а не код возврата.
answers() {
  local label="$1"; shift
  local out
  out="$("$@" 2>&1 || true)"
  [ -n "${out//[[:space:]]/}" ] || fail "$label: пустой вывод после обновления"
  case "$out" in
    *"Traceback"*) echo "$out" | tail -20 >&2; fail "$label: трейсбек после обновления" ;;
  esac
  note "$label: $(printf '%s' "$out" | head -1 | cut -c1-64)"
}

answers "ai-ops next"   python3 .ai/managed/ai_ops_kit/cli/ai_ops_cli.py next .
answers "ai-ops status" python3 .ai/managed/ai_ops_kit/cli/ai_ops_cli.py status .
answers "ai-ops model"  python3 .ai/managed/ai_ops_kit/cli/ai_ops_cli.py model .
answers "doctor"        python3 "$KIT/installer/ai_ops.py" doctor

# ------------------------------------------------------------------ 6. файлы ВЛАДЕЛЬЦА не тронуты
OWNER_SHA_AFTER="$(shasum "$WORK/child/src/app.ts" | cut -d' ' -f1)"
[ "$OWNER_SHA_BEFORE" = "$OWNER_SHA_AFTER" ] \
  || fail "обновление изменило файл владельца src/app.ts"
[ -f "$WORK/child/package.json" ] || fail "обновление удалило файл владельца package.json"
note "файлы владельца не тронуты"

echo "UPGRADE-PATH OK: $PREV_TAG -> $CURRENT — дочка отвечает, версия сошлась, владелец не задет"
