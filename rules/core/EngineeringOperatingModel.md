# EngineeringOperatingModel — операционная модель инженерной работы (v3.19.0, срез 1)

## Зачем

Гейты кита проверяли **содержание** изменения (спека, план, ревью, security) и не проверяли
**операционную гигиену** вокруг него: каким коммитом изменение ложится в историю и на какой ветке
живёт. Это давало дефекты, которые не ловил ни один судья:

- обновление managed-слоя кита ехало одним коммитом с продуктовыми правками — **откатить обновление
  отдельно стало невозможно**, хотя именно этот откат нужен чаще всего;
- в историю попадали `.env`, приватные ключи, worktree прогонов;
- сообщение «fix» не давало ни причины, ни evidence — через неделю история перестаёт быть источником истины;
- **ветка отставала от базы на 234 коммита, и это не было ничьей ответственностью** (реальный случай
  дочки 2026-08-04): диф ветки гейты смотрели, актуальность базы — нет. Живой прогон на такой ветке
  измеряет продукт месячной давности, то есть не измеряет ничего.

Срез 1 закрывает коммит и ветку. Окружения/деплой — срез 2, экономический preflight — срез 3.

## CommitContract (`tools/commit_policy.py`)

Один коммит = один откатываемый шаг одной задачи.

**Жёсткие инварианты (блокируют всегда):**

```
zone_mixing                 managed-слой кита (.ai/managed/**, .ai-ops.yaml, .ai/generated/**)
                            нельзя мешать с продуктовым кодом в одном коммите
runtime_artifacts           .ai/runtime/**, .ai/worktrees/** в историю не попадают
forbidden_file              .env (кроме .env.example), приватные ключи/сертификаты, id_rsa, .netrc
secret_in_message           литеральный секрет в тексте сообщения (история необратима)
protected_without_approval  затронуты protected_paths без ApprovalRecord
placeholder_message         «wip» / «fix» / «обновление» для отслеживаемых типов задач
empty_commit                нет файлов
```

**Мягкие правила (по умолчанию СОВЕТУЮТ):** `large_commit` (>40 файлов), `broad_scope`
(>4 верхнеуровневых каталогов), `short_message`, `no_workitem`, `no_evidence`.

Мягкие применяются только к отслеживаемым типам задач (ENGINEERING / AI_FEATURE / PRODUCT / CRITICAL);
QUICK ими не обвешивается. Поднять до блока — `engineering_operating_model.commit.enforce: block`.

Модуль **не сканирует содержимое файлов** — это делает `tools/security_scan.py`, дублировать не надо.
Здесь дополняющая проверка: имена файлов и текст сообщения.

## BranchContract (`tools/branch_policy.py`)

**Жёсткие инварианты:**

```
direct_commit_to_protected_ref   движок не коммитит в main/master/release/* — только PR
branch_naming                    ветка доставки начинается с ai-ops/ (иначе прогон не связать с WorkItem)
```

**Мягкие правила:**

```
base_drift        ветка отстаёт от базы ≥ 20 коммитов
base_stale        ≥ 100 коммитов — прогон измерит не текущий продукт, освежить базу ДО работы
base_not_synced   сама база отстаёт от upstream (ветвление от стухшего локального main)
multi_workitem    в ветке коммиты нескольких WorkItem
stale_branch      ветка старше 14 дней
```

## Честность измерений

Неизмеренное отставание отдаётся как `unavailable` (`None`), **никогда как 0**: ноль означал бы
«отставания нет» — это ложь, когда базы просто нет локально или upstream не объявлен. Тот же
инвариант, что в Usage Truth (`usage_status unavailable != 0`) и UI Evidence (`absent` не маскируется).

## Сила: что блокируем, что советуем

Жёстко блокируется только необратимое (необратимый вред истории, потеря возможности откатить,
утечка секрета, обход одобрения человека). Всё, что касается **темпа и вкуса** владельца — размер
коммита, момент рефреша базы, возраст ветки — по умолчанию СОВЕТ. Тот же принцип, что в
`SessionEconomyPolicy.md`: кит не управляет рантаймом и не форсит ритм работы.

## Конфигурация (`.ai-ops.yaml`)

```yaml
engineering_operating_model:
  commit:
    enforce: advise            # advise | block — сила мягких правил
    max_files: 40
    max_top_level_dirs: 4
    min_message_chars: 15
    require_workitem: true
    require_evidence: true
  branch:
    enforce: advise
    branch_prefix: "ai-ops/"
    protected_refs: [main, master, "release/*"]
    base_drift_advisory: 20
    base_drift_stale: 100
    max_branch_age_days: 14
    one_workitem_per_branch: true
```

Ключа нет — работают дефолты из `DEFAULTS` обоих модулей. Согласованность порогов проверяет
`validation/validate_engops_policy.py` (в CI).

## Поверхность

```
ai-ops engops                     политика + актуальность текущей ветки
ai-ops engops branch [--base X]   вердикт по ветке
ai-ops engops commit --files ... --message "..."   вердикт по предполагаемому коммиту
ai-ops doctor                     строки «политика коммитов» и «актуальность ветки»
```

Связка: `rules/core/SessionEconomyPolicy.md` (гигиена сессии), `rules/core/DelegationPolicy.md`
(делегирование), `rules/core/HumanApproval.md` (ApprovalRecord для protected_paths).
