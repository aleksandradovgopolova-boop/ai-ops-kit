# Container Isolation — полный jail рантайма (P0.2)

Изоляция движка — **два слоя**, и это честно разделено:

| Слой | Где | Что гарантирует | Чего НЕ может |
|---|---|---|---|
| **Брокер** (`tool_broker`) | в процессе | allowlist shell, `block_push`, денай сети (best-effort), скраб секретов, write_scope, traversal-guard | это не песочница исполнения: `python3`/`node`/`make` исполняют код репо; лимитов ФС/ресурсов нет |
| **Контейнер** (`containers/`) | рантайм ОС | read-only root, writable только worktree, лимиты CPU/RAM/pids, `cap-drop ALL`, non-root, no-new-privileges | не air-gap: движку нужен egress к API модели и реестрам |

Брокер сужает поверхность **внутри** процесса; настоящую изоляцию ФС/ресурсов/привилегий даёт
**контейнер**. Вместе они закрывают P0.2.

## Что enforce'ит контейнер

`containers/run-sandboxed.sh` запускает образ с флагами (docker их принимает — проверено):

- `--read-only` — root-fs только для чтения; писать некуда, кроме явных точек;
- bind `<child> → /work` — **единственная** writable точка (worktree ребёнка); хост не тронут;
- `--tmpfs /tmp,/home/runner` — writable временные каталоги (кэш npm/pip) без записи на root-fs;
- `--memory`, `--cpus`, `--pids-limit` — лимиты ресурсов (модель/сборка не съедят машину);
- `--cap-drop ALL`, `--security-opt no-new-privileges` — без Linux-привилегий и эскалации;
- non-root пользователь `runner` (uid 10001, зашит в образ).

## Как запустить

```bash
# 1. Собрать образ (на вашем Docker-хосте; контекст — корень кита):
docker build -f containers/Dockerfile -t ai-ops-engine:latest .

# 2. Запустить движок в jail'е против child-репозитория (ключи — из env, не в образ):
OPENAI_COMPATIBLE_BASE_URL=... OPENAI_COMPATIBLE_API_KEY=... \
  containers/run-sandboxed.sh ~/mychild "почини падающий тест" \
    --engine pipeline --provider openai-compatible --model deepseek-chat \
    --execute --sandbox --baseline-diff
```

Тюнинг через env: `AI_OPS_IMAGE`, `AI_OPS_MEM` (2g), `AI_OPS_CPUS` (2), `AI_OPS_NETWORK`
(`bridge` по умолчанию | `none`, если модель и зависимости уже локальны).

## Сеть — честная граница

Контейнер **не air-gapped**: движок должен достучаться до API модели и пакетных реестров
(`npm ci`/`pip install`). Полностью `--network none` работает только если модель и зависимости
локальны (`AI_OPS_NETWORK=none`). Для боевого контроля egress ставьте перед контейнером
**allowlist-прокси** (разрешить только хосты API модели + реестров) — это вне флагов docker, на
уровне сетевой политики хоста/оркестратора.

## Статус проверки (честно)

- Ассеты (`Dockerfile`, `run-sandboxed.sh`) написаны; jail-флаги приняты docker (flag-parse) и
  их присутствие стережёт `validation/validate_container_assets.py` (регресс любого флага — ошибка CI).
- Команда движка, которую оборачивает wrapper (`ai-ops run … --sandbox`), подтверждена живыми
  прогонами.
- **Сборка образа** (pull базового образа) в CI-песочнице кита закрыта egress-прокси — её
  выполняет Docker-хост пользователя. Флаги стандартные; сюрпризов при сборке не ожидается.
