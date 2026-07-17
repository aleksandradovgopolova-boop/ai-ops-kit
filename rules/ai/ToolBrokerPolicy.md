# ToolBrokerPolicy — модель предлагает действие, политика решает

## Принцип

В контролируемом исполнении (generic-orchestrator) **не модель решает, что ей можно**.
Модель ПРЕДЛАГАЕТ действие (`{op, path, command, content}`); разрешено ли оно — решает
Policy Engine (`tools/tool_broker.py`) по уровням `security/permission-levels.yaml`,
объявленному `write_scope` и `config/protected-paths.yaml`. Broker исполняет только
разрешённое и собирает Evidence (команда, exit_code, ревизия, что тронуто).

**Инвариант:** `execute()` всегда вызывает `decide()` первым. Прямого пути «исполнить в
обход политики» нет.

## Правила

1. **Уровень операции.** read → `read-only`; write → `controlled-write`; shell/git →
   `execution`. Нехватка уровня — отказ, а не «на свой страх».
2. **Write только в write_scope.** Запись вне объявленного scope — отказ (не «случайно
   поправил соседний модуль»).
3. **Protected paths** — запись только при `privileged` + явном approval; иначе отказ.
   Источник = **MERGE**: дефолт пакета (`config/protected-paths.yaml`) + карта child'а
   (`<child>/.ai-ops.yaml → protected_paths`). Child добавляет свои пути (напр.
   `.github/workflows/`), не отменяя универсально-опасные дефолты. Policy знает реальную
   карту репозитория (передать `child_root` в `Policy(...)`).
4. **Необратимое/опасное** (`rm -rf`, `git push --force`, `reset --hard`, `drop table`,
   `curl | sh`, …) — только `destructive` + approval. По умолчанию — отказ.
5. **Evidence обязателен.** Каждое исполненное действие даёт запись с ревизией и exit_code
   — это и есть доказательство стадии (не «модель написала pass»).
6. **Доставку модель не делает (`block_push`).** `git push` из tool-loop запрещён всегда,
   когда `block_push=True` (по умолчанию у движка). Ветку/PR доставляет только доверенный
   delivery-слой движка (`pr_open`), не модель. Иначе модель могла бы отправить незачтённую
   работу мимо гейтов.
7. **Containment shell (`shell_mode`).** `unrestricted` (обратная совместимость) |
   `allowlist` (только бинарь из `shell_allowlist` — типовые build/test/pkg-инструменты) |
   `off` (shell запрещён совсем). Первый токен команды берётся с учётом `VAR=val`-префиксов
   (`CI=1 npm test` → бинарь `npm`).
8. **Сетевой денай (`allow_network=False`).** Частые сетевые бинарники (`curl`, `wget`,
   `nc`, `ssh`, `scp`, `rsync`, …) отклоняются. Это НЕ полный сетевой jail — это
   enforceable-денай частых векторов на уровне брокера.

## Ревьюер под read-only (v2.83, writer ≠ judge)

Независимый ревьюер RunPlan-гейтов (`tool_loop.run_review`) гоняется под `Policy(level="read-only")`:
он МОЖЕТ читать изменение, но `write`/`shell` брокер отклоняет. Это делает разделение «писатель ≠
судья» не только ролевым (отдельный вызов/промпт), но и **capability-enforced**: судья физически
не может править код, который оценивает. Его вердикт — структурный `reviewer-result`, а не слово.

## Sandbox-профиль (v2.81)

`tool_broker.sandbox_policy(child_root, write_scope)` собирает усиленную политику для
прогонов с **недоверенной живой моделью**: `shell_mode="allowlist"` (dev-инструменты из
`SANDBOX_SHELL_ALLOWLIST`) + `block_push=True`. Включается флагом `--sandbox` в
`ai_ops_run.py run` и `qual_run.py`; в отчёте прогона это честно объявлено в блоке
`containment` (`sandbox`, `shell_mode`, `block_push`, `allow_network`).

## Граница (честно)

Broker/Policy/Evidence — готовы, протестированы и **включены в живую петлю** движка
(`execution_pipeline.run_pipeline` гоняет tool-calling-провайдера через `tool_loop`).
`--sandbox` сужает поверхность (shell по allowlist, push/сеть — денай), но это
**enforceable-подмножество на уровне брокера, а не полный jail**: модель всё ещё может
навредить внутри своего worktree, а полная изоляция ФС/сети/ресурсов (лимиты CPU/RAM,
namespaces, read-only mounts) — задача **контейнерного runtime**, вне брокера кита. Для
рантаймов со своим tool loop (claude-code) enforcement держится на Evidence, не на брокере.
