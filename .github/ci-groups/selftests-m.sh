#!/usr/bin/env bash
# Группа CI «selftests-m» — перенесённые селфтесты M–Z.
# v3.30: группы больше не перечисляют команды по одной. Всё, что раньше стояло здесь
# построчно, живёт в pytest; разбиение — по маркерам и именам, чтобы джобы шли параллельно
# и примерно равно по времени. Добавленная проверка попадает в свою группу сама.
set -euo pipefail
cd "$(dirname "$0")/../.."
python3 -m pytest tests/ -q --no-cov -m slow -k "not (test_a or test_b or test_c or test_d or test_e or test_f or test_g or test_h or test_i or test_j or test_k or test_l)"
