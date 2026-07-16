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
3. **Protected paths** (`config/protected-paths.yaml`) — запись только при `privileged` +
   явном approval; иначе отказ.
4. **Необратимое/опасное** (`rm -rf`, `git push --force`, `reset --hard`, `drop table`,
   `curl | sh`, …) — только `destructive` + approval. По умолчанию — отказ.
5. **Evidence обязателен.** Каждое исполненное действие даёт запись с ревизией и exit_code
   — это и есть доказательство стадии (не «модель написала pass»).

## Граница (честно)

Broker/Policy/Evidence — готовы и протестированы как компонент. Полная петля «живая
модель предлагает действия в цикле» интегрируется в оркестратор отдельным шагом (нужен
tool-calling-провайдер); сейчас оркестратор sequential/mock. Для рантаймов со своим tool
loop (claude-code) enforcement всё равно держится на Evidence, не на брокере кита.
