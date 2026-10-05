# Change Brief — #1247 / #1253

Результат: воспроизводимое сравнение ограниченных решений на одном корпусе; отсутствие живого прогона не выдаётся за успех.

Затрагиваемые пути: devtools CLI → фиксированный dataset → текущий роутер / heuristic / импорт ответов внешних providers → per-case evidence → JSON и Markdown отчёты.

Инварианты: stdlib + pyyaml; без нового пакета и production-проводки; expected и policy floor не передаются provider; held-out отделён; safety отдельно от accuracy; неизвестная стоимость не равна нулю.

Failure modes: утечка эталона; отсутствующие/дублированные ответы; NaN и неверные решения; понижение policy floor; ложный ship при неполном сравнении.

Доказательство: positive — один корпус для двух providers; fail-closed — некорректный ответ не даёт успех; side-effect — сохранённые файлы содержат реально полученные решения; проверка CLI на macOS и full-current-python.

Не входит: production DecisionProvider contract (#1248), обязательная зависимость Jev, автоматическое изменение production routing, заявление о доказанной безопасности по малой синтетической выборке.

## Уточнение: бесплатный classifier.dev

По указанию владельца добавляется отдельный экспериментальный service `classifier-free`:
тот же TypeSafe wire contract, только публичный синтетический корпус. Инвариант: реальный
TypeSafe key никогда не передаётся прокси, используются исключительно anonymous запросы.
Доказательство: фиксированный endpoint и placeholder auth в тесте HTTP-запроса; живой capture
с фактическими ответами/usage; проверка safety без изменения floor или production routing.

## Следующий эксперимент: deterministic floor и независимая выборка

Результат: предложение Jev не может опустить ceremony ниже classify(signals); сырое решение
и его ошибки остаются в evidence отдельно от итогового. Policy не читает expected/floor из dataset.
Пути: request → реальный provider → raw evaluate → экспериментальный floor → отдельный provider
в сравнении. Для abstain/ошибки есть deterministic fallback с confidence=null; override не наследует
уверенность модели. Лишь ceremony имеет реализованный policy; остальные точки не объявляются защищёнными.
Корпус размечает отдельная свежая AI-сессия без старых данных/промптов/ответов; это независимость
автора, не независимая человеческая квалификация и не доказательство production safety.
Доказательство: positive max-floor, fail-closed неверные options/сигналы, side-effect raw lower
сначала действительно получен и сохранён; live Jev + LLM одинаковые stripped inputs.
Ограничение владельца: Jev только бесплатный classifier.dev; прямой платный TypeSafe не исследуем.

## #1250: модель/effort и качество результата

До кода: отдельный эксперимент с vendor-neutral choices fast/low, balanced/medium,
deep/high, strongest/high, human-required. Current baseline = настоящий writer_tier + ЯВНО
заданное экспериментальное соответствие class/effort, не новая объявленная production-логика.
Пути: task/context → free Jev или current tier → deterministic model floor/confidence fallback →
конкретный доступный worker из экспериментального config → JSON результат → независимый oracle.
Провайдер не видит expected routing или execution.expected_answer. Expected route — гипотеза;
полезность решает downstream correctness/latency/token usage с включением router overhead.
High risk не может оказаться fast/balanced; human-required не исполняется автоматически;
неизвестный/недоступный worker приводит к abstain или human stop, не к дешёвому подменному worker.
Сильнейший класс не квалифицируем по наличию alias; отсутствующий strongest остаётся unavailable.
Низкая confidence (<0.9) → baseline/floor. Mandatory review остаётся явно обязательным.
Доказательство: real raw downgrade до проверки policy, обработка неполного результата,
проверка реально вызванного worker и сохранившегося JSON результата; сторонний oracle без старых примеров.
Не входит: выполнение произвольного сгенерированного кода, production wiring, платный Jev,
вывод об экономии денег при неизвестной стоимости подписки, full code-change/merge qualification.
