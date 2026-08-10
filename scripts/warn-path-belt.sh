#!/usr/bin/env bash
# Предупредить об остаточном .pth-поясе кита ПЕРЕД прогоном проверок.
#
# Зачем перед, а не после: пояс подкладывает корень репозитория, tools/ и validation/ в каждый
# процесс Python и делает зелёными проверки, которые обязаны краснеть. Замерено на
# test_validator_bootstrap.py::test_missing_bootstrap_is_caught — он копирует репозиторий, удаляет
# там validation/_bootstrap.py и ждёт ModuleNotFoundError; с поясом импорт находит _bootstrap
# в НАСТОЯЩЕМ репозитории. То есть «локально всё зелёное» на такой машине ничего не значит,
# и узнать об этом надо ДО того, как прогон закончится успехом.
#
# Только предупреждение, без падения: чинить машину — не работа этого скрипта, а `ai-ops doctor`
# (там проверка блокирующая) и `ai-ops doctor --remove-path-belt`.
set -uo pipefail
cd "$(dirname "$0")/.."
python3 -c 'import sys
sys.path.insert(0, ".")
from ai_ops_kit.shared import path_hygiene as ph
rep = ph.assess()
if rep["findings"]:
    sys.stderr.write("ВНИМАНИЕ, гигиена путей — локальный прогон может быть зелёным на сломанном "
                     "коде:\n" + ph.summary_line(rep) + "\n\n")' || true
