# Change Brief — дубль обязательного набора PR↔merge убран без потери финального гейта (#1376)

## Результат

Полный обязательный набор проверок (`package-quality`: критический путь `selftests-m`) больше НЕ
исполняется дважды на одно влитое изменение. Прежде он шёл и на голове PR (событие `pull_request`),
и снова на merge-коммите (событие `push` в `main`) — по замеру #1372 это ~2× обязательного набора на
каждый merge (по 285…519 с на прогон). Теперь на `push` в `main` полный набор не гоняется вовсе;
финальный полный гейт на ТОЧНОМ итоговом SHA сохранён — он перенесён на релиз и запускается ровно
на релизном коммите.

Решение владельца: **Вариант 1** (GitHub merge queue на его плане недоступен и остаётся форжд-
зависимым механизмом, см. `tests/contracts/test_ci_event_gating.py` — `merge_group` снят осознанно).

## Затрагиваемые пути

- `.github/workflows/package-quality.yml` — убран триггер `push: branches: [main]`; добавлен
  `workflow_call: {}`. Теперь это ещё и reusable workflow: release вызывает ТОТ ЖЕ набор job'ов на
  релизном SHA, поэтому релизный гейт физически не может разойтись с PR-гейтом (одно определение).
  `pull_request` и `workflow_dispatch` сохранены; `permissions: contents: read` не тронуты.
- `.github/workflows/release.yml` — триггер сменён с `workflow_run` (успех `package-quality` на main)
  на `push: branches: [main]` + `workflow_dispatch`. Разбит на три job'а:
  - `check` — дешёвое решение «нужен ли выпуск» (VERSION + отсутствие тега у GitHub), без тестов, на
    каждый push в main (секунды);
  - `full-gate` — `needs: check`, `if: needed == 'true'`, `uses: ./.github/workflows/package-quality.yml`:
    полный обязательный набор на релизном SHA (`github.sha` = merge-коммит), и ТОЛЬКО когда выпуск
    нужен;
  - `release` — `needs: [check, full-gate]`, `if: needed == 'true' && full-gate.result == 'success'`:
    мутационный гейт, дренаж очереди заявлений, слой владельца, создание тега/Release. Все прежние
    релизные гейты СОХРАНЕНЫ дословно, на том же релизном SHA (`checkout ref: github.sha`).
- Тесты-стражи, кодировавшие ПРЕЖНИЙ механизм (триггер `workflow_run`, `workflow_run.head_sha`,
  per-step `if` на гейтах), обновлены под новый — с сохранением того же инварианта, не ослаблением:
  `tests/unit/test_release_gates.py`, `tests/unit/test_release_owner_layer.py`,
  `tests/unit/test_changelog_queue_drained.py`, `tests/unit/test_evidence_scope.py`.

## Инвариант гейта (жёсткий, доказан структурой workflow)

Тег/Release НЕ появляется, если полный обязательный набор не прошёл на точном итоговом SHA:

- `release` зависит от `full-gate` (`needs`) и идёт лишь при `needs.full-gate.result == 'success'`;
- `full-gate` — это `package-quality` целиком (матрица `quality` + `lint` + `clean-install` +
  `upgrade-path` + `pipeline-e2e`), вызванный как reusable: его job'ы чекаутят `github.sha` —
  релизный merge-коммит;
- создание тега (`gh release create`) стоит ПОСЛЕ мутационного гейта в том же job'е `release`.

Релиз НЕ стал менее защищённым: тот же полный набор на том же точном SHA, плюс неизменённые
мутационный/очередь/слой-владельца гейты. Разница лишь в том, что набор запускает сам release, а не
прежний `workflow_run`-сигнал. Это сильнее прежнего: привязка теперь явная (`needs`/`if`), а не
через слепой триггер.

## Другие потребители снятого push-прогона

Снятый `push`-прогон `package-quality` на main имел двух потребителей `workflow_run`:

1. `release.yml` — перепроволочен (выше).
2. `status-dashboard.yml` — слушает `workflow_run` от `[package-quality, docs, nightly-quality,
   nightly-coverage]` на main, плюс имеет свои триггеры: `schedule` (ежедневно), `workflow_dispatch`
   и `push` в main по путям-источникам. Пульт остаётся свежим на каждый merge через `docs`
   (он по-прежнему идёт на `push` в main) и свой `push`-paths-триггер; запись `package-quality` в его
   списке становится холостой на main (reusable-вызов из release отдельного `workflow_run` не
   порождает). Файл НЕ тронут осознанно — потребитель сохранён; холостую запись владелец может убрать
   отдельно (пульт — не гейт).

## Честная граница (компромисс)

Голова `main` между релизами проверена на PR (обязательные контексты + feedback), но НЕ
перепрогоняется на своём post-merge SHA до момента релиза. То есть точный merge-коммит обычного (не
релизного) изменения полным набором не покрывается до ближайшего выпуска. Это сознательный размен
Варианта 1: экономия — снятие ~половины прогонов обязательного набора; цена — окно между merge и
релизом, где итоговый SHA обычного изменения держится проверкой на PR, а не повторным прогоном на
себе. Финальный полный гейт на ТОЧНОМ релизном SHA при этом сохранён полностью. Строгий «один
прогон ровно на итоговом коммите каждого merge» давал бы только merge queue — он владельцу недоступен
и форжд-зависим.

## Доказательство

- YAML валиден; структура: `release` → `push:[main]`+`dispatch`; `full-gate uses package-quality`;
  `release needs [check, full-gate]` с условием на `needed` и `full-gate.result == 'success'`.
- Таргетные стражи (venv): `test_release_gates.py`, `test_release_owner_layer.py`,
  `test_changelog_queue_drained.py`, `test_evidence_scope.py`, `test_ci_event_gating.py`,
  `test_ci_workflows.py`, `test_workflow_least_privilege.py`, `test_iteration_repeated_work.py`,
  `test_kit_security_scan_job.py`, `test_enforcement_inventory.py` — зелёные (166 passed, 28 skipped).
- `test_actual_release_commands_never_tag_after_mutation_failure` (поведенческий, реальные run-блоки):
  при падении мутационного гейта тег не создаётся — зелёный.
