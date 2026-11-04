# Container Isolation — контракт и квалификация рантайма (P0.2)

Изоляция движка — **два слоя**, и это честно разделено:

| Слой | Где | Заявленная граница | Чего НЕ может |
|---|---|---|---|
| **Брокер** (`tool_broker`) | в процессе | allowlist shell, `block_push`, денай сети (best-effort), скраб секретов, write_scope, traversal-guard | это не песочница исполнения: `python3`/`node`/`make` исполняют код репо; лимитов ФС/ресурсов нет |
| **Контейнер** (`containers/`) | рантайм ОС | read-only root, writable только worktree, лимиты CPU/RAM/pids, `cap-drop ALL`, non-root, no-new-privileges | не air-gap: движку нужен egress к API модели и реестрам |

Брокер сужает поверхность **внутри** процесса; ограничения ФС/ресурсов/привилегий должны
обеспечиваться **контейнером**. Само наличие этих двух слоёв не закрывает P0.2: реальные
негативные проверки изоляции остаются открытыми в #1407.

## Декларируемые ограничения контейнера

`containers/run-sandboxed.sh` задаёт перечисленные ниже флаги. Статическая проверка их наличия
и успешный запуск `--help` не заменяют реальные негативные sandbox-пробы:

- `--read-only` — root-fs только для чтения; писать некуда, кроме явных точек;
- bind `<disposable-clone> → /work` — **единственная** writable точка. Это НЕ основной child, а его
  одноразовый клон (v2.93 worktree-only): wrapper делает `git clone --no-hardlinks` перед запуском,
  монтирует ТОЛЬКО клон, и модель физически не может тронуть основной checkout — он не смонтирован.
  После прогона доверенный host-слой забирает ветки `ai-ops/*` из клона обратно в основной репо
  (`git fetch`) — доставка вне контейнера. Клон удаляется (кроме ошибки доставки — путь печатается);
- `--tmpfs /tmp,/home/runner` — writable временные каталоги (кэш npm/pip) без записи на root-fs;
- `--memory`, `--cpus`, `--pids-limit` — лимиты ресурсов (модель/сборка не съедят машину);
- `--cap-drop ALL`, `--security-opt no-new-privileges` — без Linux-привилегий и эскалации;
- non-root пользователь `runner` (uid 10001, зашит в образ).

## Как запустить

```bash
# 1. Собрать образ (на вашем Docker-хосте; контекст — корень кита):
docker build -f containers/Dockerfile -t ai-ops-engine:latest .
# Default: официальный node:22-trixie-slim (Debian 13), не floating node:22-slim/bookworm.
# BASE_IMAGE override допустим только после проверки происхождения образа;
# сборка всё равно проверит фактические Python/Node, а npm — engines зависимостей.
# Требуется сеть с доступом хотя бы к ОДНОМУ контейнерному реестру (base image + npm/pip на сборке).

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

## Поза изоляции — видна, а не молчит (P1)

Дефолт библиотечных входов — `sandbox=False`: модельный shell идёт **без jail**, сеть по умолчанию
доступна. Это осознанный дефолт (иначе прогоны без Docker и легитимные сборки ломались бы), и кит
его **не флипает**. Про саму границу честно: контейнер и `sandbox` кита — это **policy enforcement**
(write-scope, block-push, credential-less git, ресурс-лимиты), а **не security isolation**: агент
управляем, но не заперт наглухо, полагаться на него как на защиту от недоверенного кода нельзя. Но
молчать даже о такой пониженной изоляции нельзя: когда прогон реально работал (были
правки/коммит, не dry-run/preview) без песочницы, вывод прогона называет это прямо — одной честной
строкой рядом с `изоляция:`:

> ⚠ прогон без песочницы (sandbox off), сеть доступна модельному shell; изоляция условна —
> управляемость брокером, не защита от недоверенного кода. Для чувствительных прогонов включите
> её: --sandbox / контейнер run-sandboxed.sh

Поза едет и в отчёт машиночитаемо (`isolation.sandboxed`, `isolation.network`), так что видна и
постфактум. Ноты нет на `--sandbox` и на прогонах без записей (preview/reevaluate).

**Для доставки и чувствительных прогонов** рекомендуется, помимо `--sandbox`/контейнера,
**read-only GitHub-токен** (или полностью credential-less-прогон): доставку PR делает доверенный
host-слой вне контейнера, а модели токен с правом записи в репозиторий не нужен. Так пониженная
изоляция shell не даёт модели пути к записи в GitHub.

## Статус проверки (честно)

Квалификация точки запуска и поддерживаемого runtime — разные проверки. Локальный срез
`74ccc0638122592760520fe11b39710285a52629` (#1478) собран и запустил штатный `--help` без модели,
с отключённой сетью и без host mounts. В том образе фактически Python **3.11.2**, ниже объявленного
пола `pyproject.toml` (**>=3.12**): entrypoint smoke — PASS, supported-runtime qualification — FAIL.
Он не доказывает работоспособность задач на поддерживаемом Python или свойства изоляции.

### Матрица предлагаемого reference runtime

| Конфигурация | Python | Node | Статус доказательства |
|---|---|---|---|
| Старый `node:22-slim` / bookworm, entrypoint head `74ccc063` | Фактически 3.11.2, ниже пола | 22.x | Только build/CLI `--help` PASS; supported-runtime FAIL |
| Новый `node:22-trixie-slim` / Debian 13 | Ожидается 3.13 из Debian; фактическая версия обязана удовлетворять `pyproject.toml` | Сохраняется 22.x | Код и fixtures подготовлены; image pull/build/start **NOT_RUN**, требуется отдельное разрешение |
| Существующий CI `pipeline-e2e` | 3.12 и 3.13 | Не квалифицирует образ | Матрица CI не меняется; её успешность на новом head требуется отдельно |

Новый Dockerfile сначала ставит Python из штатного Debian-репозитория, копирует кит и выполняет
`validate_container_assets.py --runtime-floor` отдельной exec-form `RUN`. Проверка читает
`requires-python` из манифеста и фактический `node --version`; отсутствующий/неразбираемый вход,
старый Python или Node вне 22.x останавливают сборку. Только затем устанавливаются прежние
PyYAML/OpenSpec; `npm_config_engine_strict=true` запрещает проигнорировать несовместимые engines.
Произвольный другой Node major не считается автоматически поддержанным.

Источник выбора: [официальный manifest Node images](https://raw.githubusercontent.com/docker-library/official-images/master/library/node)
содержит `22-trixie-slim` для amd64/arm64v8; [Dockerfile Node 22](https://raw.githubusercontent.com/nodejs/docker-node/main/22/trixie-slim/Dockerfile)
основан на Debian trixie; [пакет Python в Debian trixie](https://packages.debian.org/trixie/python3)
имеет версию 3.13. [OpenSpec 1.6.0](https://raw.githubusercontent.com/Fission-AI/OpenSpec/v1.6.0/package.json)
объявляет Node >=20.19; выбранная ветка 22 удовлетворяет этому ограничению. Это данные upstream,
а не локальная квалификация нового образа; фактические версии нужно записать после разрешённой сборки.

Статический `CONTAINER-ASSETS-OK` подтверждает наличие launch/runtime-check контракта и маркеров
jail-флагов. `CONTAINER-RUNTIME-VERSIONS-OK` подтверждает только версии в исполнившей проверку
среде. Проверки версий и справки не доказывают изоляцию агента: policy enforcement, не security isolation.
Ни один из них не заменяет no-model image build/start на точном новом head. Реальные
model/MCP injection, redaction/exfil и sandbox negatives (network/FS/mount/UID/timeouts/Docker
отказ) остаются открытыми в [#1407](https://github.com/aleksandradovgopolova-boop/ai-ops-kit/issues/1407).
