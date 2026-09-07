#!/usr/bin/env bash
# Группа CI «selftests-m» — часть slow-набора (маркер slow, не nightly).
# v3.30: группы больше не перечисляют команды по одной. Всё живёт в pytest; разбиение — по маркерам
# и именам, чтобы джобы шли параллельно и примерно равно по времени. Добавленная проверка попадает
# в свою группу сама.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1   # байткод в дереве ломает проверку целостности managed
cd "$(dirname "$0")/../.."
# ЗАМЕР ЦЕНЫ (2026-09-07, #465). Подробный разбор — в selftests-a.sh. Здесь остаётся всё, чего нет
# в группе a: кластеры `test_update_*`/`test_upgrade_*` (u) и `test_validate_*`/`test_validator_*` (v,
# кроме припаркованного монолита), хвост i,l,o,p,r,s,t и все будущие буквы f,g,h,j,k,m,n,q,x,y,z.
# Тяжёлый кластер `test_workpackage_*` (w) уехал в группу a, а самый тяжёлый одиночный файл
# `test_validate_release_claims` (~99 c) припаркован в группе `contracts` — оба ИСКЛЮЧЕНЫ отсюда
# (первый — тем, что он в наборе группы a; второй — явным `and not test_validate_release`), чтобы
# selftests-m не пробивал стену (до ретюна доходил до ~196 c). Маршрутизация — подстрокой по имени
# функции И модуля, поэтому файлы u/v РАСПАДАЮТСЯ между шардами по имени функции (см. selftests-a.sh).
# Партиция полная и непересекающаяся по построению: здесь ровно `not (то, что в группе a)` с тем же
# исключением монолита, ни один slow-тест не потерян и не гоняется дважды. Границу уточнять по
# фактическим временам прогона.
python3 -m pytest -n auto --dist loadfile tests/ -q -m "slow and not nightly" \
  -k "not (test_a or test_b or test_c or test_d or test_e or test_f or test_g or test_h or test_w) and not test_validate_release"
