# Preview без побочных действий (#1477)

- **Результат:** `preview <intent>` только показывает план, даже с флагами исполнения и записи.
- **Пути:** общий CLI dispatch → чтение сохранённой спецификации/сигналов → preview; отдельно process gate, specify, resume, direct intents, run/do и вывод JSON/product/technical.
- **Инварианты:** ранний возврат до mutating dispatch; executor, delivery и model недостижимы; дерево проекта и домашний каталог не меняются; обычное исполнение сохраняется.
- **Failure modes:** specify пишет/переписывает spec; resume передаёт execute/open-pr; run/do запускает движок; direct intent пишет артефакт; preview теряет сохранённую задачу/сигналы или сообщает о немедленном запуске.
- **Доказательство:** реальные временные Git-проекты со снимком дерева; все зарегистрированные intents; force/answers/execute/open-pr/apply/reach; запрещающие sentinels на границах исполнения; обычный specify действительно создаёт spec, обычный resume сохраняет передачу флагов; preview существующей spec сохраняет задачу/сигналы.
- **Не входит:** изменение модели доступа, runtime sandbox, live model/API, реальные child-проекты, release; локальные проверки не заменяют independent review и required exact-head CI.
