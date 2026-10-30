# Forbidden до hybrid retrieval — остаток #1403

**Результат.** При непустом `context.forbidden` разрешённый hybrid-контекст может дополнять v1: запрещённые источники отсекаются до чтения, а не отключают все v2-additions.

**Затрагиваемые пути.** `.ai-ops.yaml` → существующий path pre-filter `context_engine` → full-text, graph, semantic-lite и финальное чтение mandatory → promotion → `ai_ops_run_reporting` → payload/артефакты/реальный локальный pipeline. Нового сборщика и новых production-модулей нет; `repo_graph` и `semantic_lite` уже принимают path_filter и не меняются.

**Инварианты.** Context forbidden сужает AFP/DCP, не расширяет доступ. Symlink и выход за root проверяются существующим `context_cost.forbidden`. Запрещённый mandatory не читается и не теряется молча: view не допускается к promotion. Политика источников входит в fingerprint view. Неизмеренная релевантность остаётся unknown; бюджет полного payload и exact snapshot обязательны.

Уже включённый в v1 файл не подаётся второй раз как addition: manifest и оценочный бюджет описывают фактически переданный текст.

**Failure modes.** Один из retrieval-этапов читает forbidden; mandatory обходит фильтр; symlink скрывает запрещённый/внешний файл; fingerprint не меняется вместе с политикой; runtime добавляет контекст сверх бюджета или заявляет измеренные доли для неразмеченных additions.

**Найденный факт до реализации.** На текущем Mac alias `alias.py → SECRET.PY` существует при реальном файле `secret.py`, но `context_cost.forbidden(..., [secret.py])` вернул false: `Path.resolve()` сохранил чужой регистр. Поэтому scope включает native spelling для case-alias через метаданные каталогов в существующем `context_cost`; glob остаётся case-sensitive по реальным именам, Linux-файлы разного регистра не смешиваются.

**Доказательство.** Positive: настоящий разрешённый v2-файл доходит до writer при включённом forbidden. Fail-closed: запрет mandatory/выход за root/некорректная декларация не становятся готовым view. Side-effect proof: запрещённые файлы существуют, AFP разрешает их класс и без forbidden они читаются; с forbidden spy фиксирует ноль чтений во всех реальных retrieval-этапах. Контролируемый локальный pipeline сохраняет запись и manifest без платной модели; targeted/context/core, ruff/layering/func-size, независимое review и точный CI.

**Не входит.** Фильтрация самостоятельных чтений native runtime, семантическая разметка живого проекта, Storybook-агрегат, релизный план/автоматизация #1439, strict-контракты #1412, AST-пилот #1408. Issue #1403 остаётся открытой по этим границам.

**Review-итерация.** Закрываются найденные P1 Unicode-normalization+case alias и P2 повторной подачи native-case имени v1 через проверку native spelling/идентичности файла. Forbidden `.gitignore` останавливает v2 до чтения, не расширяя сканирование без его исключений. Управляющие `.ai-ops.yaml`/AFP/DCP/Budget не являются источниками payload.
