#!/usr/bin/env bash
# Полный контур перед коммитом (~4.5 мин). Единственная точка входа: всё, что раньше
# перечислялось в пре-коммит-чеклисте построчно (201 команда на пике), — это тесты.
#
# v3.34: скрипт называет СВОЙ охват сам. «Полный» здесь значит «весь pytest», а не «вся
# поддерживаемая матрица»: PR #38 написал «полный контур зелёный», и джоба python39-compat
# опровергла это в том же релизе. Охват объявляется до и после прогона — ровно в тот момент,
# когда возникает искушение сформулировать результат шире, чем он получен.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
cd "$(dirname "$0")/.."

FLOOR=$(sed -n 's/^requires-python[[:space:]]*=[[:space:]]*"\(.*\)"/\1/p' pyproject.toml | head -1)
CURRENT=$(python3 -c 'import platform, sys; print(f"{platform.python_implementation()} {platform.python_version()} / {sys.platform}")')

echo "ОХВАТ: full-current-python — ${CURRENT}."
echo "НЕ входит: объявленный пол requires-python ${FLOOR:-?} и установка в чистое окружение —"
echo "это compatibility-matrix, её дают только джобы CI python39-compat / pipeline-e2e / clean-install."
echo

python3 -m pytest tests/ -q --no-cov "$@"

echo
echo "ЗЕЛЁНЫЙ ОХВАТ: full-current-python (${CURRENT}). Формулируя результат, назови охват:"
echo "«полный контур зелёный» без имени охвата — заявление шире полученного."
