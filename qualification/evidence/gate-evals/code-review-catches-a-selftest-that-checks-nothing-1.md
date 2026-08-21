# Code Review

## Вердикт

**FAIL.** Модуль объявляет три проверки, из которых одна не реализована вовсе, вторая логически неспособна сработать (тавтология), третья даёт ложные срабатывания и валит сам себя. Плюс `--selftest` печатает `SELFTEST PASSED`, не вызвав ни одной проверяемой функции — прямое нарушение правила «объявленная проверка обязана исполняться», причём именно того правила, которое модуль призван охранять. Тестов в диффе нет.

---

## Blockers

### B1. `--selftest` ничего не исполняет и печатает `PASSED`

`ai_ops_kit/engops/refusal_paths.py` (~строки 97–102):

```python
if args.selftest:
    print("SELFTEST: refusal_paths.py")
    print("  - check_refusal_paths: OK")
    print("  - format_report: OK")
    print("SELFTEST PASSED")
    return 0
```

Ни `check_refusal_paths`, ни `format_report` не вызываются. `OK` и `PASSED` — литералы. Сценарий отказа: удалить тело `check_refusal_paths` целиком и заменить на `raise NotImplementedError` — `refusal_paths.py --selftest` по-прежнему печатает `SELFTEST PASSED` и возвращает 0. Любой CI-гейт, опирающийся на этот код возврата, зелёный на сломанном модуле.

Это ровно тот антипаттерн, который модуль заявлен ловить: утверждение о пройденной проверке, которой не было.

### B2. Selftest живёт в продакшн-модуле (нарушение AGENTS.md)

AGENTS.md: «Selftest не живёт в продакшн-модуле. Модули `ai_ops_kit/` едут в child-репозиторий; тест модуля — в `tests/unit/test_<module>_selftest.py`». Флаг `--selftest` объявлен в самом `ai_ops_kit/engops/refusal_paths.py` и уезжает в child-репозиторий вместе с модулем. Требуемый `tests/unit/test_refusal_paths_selftest.py` в диффе отсутствует — дифф добавляет ровно один файл.

### B3. Проверка флагов неспособна сработать: `defined_flags` строится из того же текста, что и «упоминания»

Строки ~33 и ~42–45:

```python
defined_flags = set(re.findall(r'--([a-z0-9-]+)', content))
...
r'unrecognized arguments: --([a-z0-9-]+)',
r'unknown flag: --([a-z0-9-]+)',
...
if flag not in defined_flags:
```

`defined_flags` — это **все** вхождения `--<что-то>` в файле, а не определения флагов (`add_argument`). Поэтому любой флаг, найденный error-паттерном, по построению уже лежит в `defined_flags`: та же подстрока `--foo` попала в оба множества. Ветка `issues.append({"type": "undefined_flag"})` для обоих `--`-паттернов **недостижима**.

Сценарий отказа: в CLI есть строка `print("подсказка: запустите с --deep-scan")`, а `add_argument("--deep-scan")` отсутствует — ровно баг из шапки модуля («кит печатает советы с флагами, которых нет»). Проверка возвращает `pass`.

Дополнительно все три паттерна ищут в **исходниках** тексты, которые argparse генерирует в **рантайме** (`unrecognized arguments: --x`, `invalid choice: 'x'`). В исходном коде таких литералов нет — `re.finditer` не находит ничего в принципе. А третий паттерн (`invalid choice`) даже при попадании сравнивал бы имя подкоманды со множеством имён флагов — категориальная ошибка, гарантированный false positive.

### B4. Заявленная проверка команд не реализована

Docstring, строка 9: «Все упомянутые команды существуют». В `check_refusal_paths` нет ни одной строки, работающей с командами/подкомандами. Проверка объявлена в контракте модуля и не исполняется — то же нарушение, что B1, но в основной логике.

### B5. Проверка traceback ловит не то и валит собственный репозиторий

Строки ~58–60:

```python
if "Traceback (most recent call last)" in content:
    if re.search(r'["\'].*Traceback.*["\']', content, re.DOTALL):
```

Ложноотрицательное: реальная утечка сырого traceback происходит через `traceback.print_exc()`, `traceback.format_exc()`, `raise` без обработки — литерала `Traceback (most recent call last)` в таком коде нет. Все настоящие утечки проходят.

Ложноположительное, воспроизводимое немедленно: `refusal_paths.py` лежит в `ai_ops_kit/engops/`, попадает под собственный `glob("*.py")`, и содержит этот литерал (строка ~58). Второй `re.search` с `re.DOTALL` и жадными `.*` матчит от первой кавычки файла (docstring, строка 2) до последней (`"__main__"`) — совпадение гарантировано. Итог: `refusal_paths.py <репозиторий кита>` сообщает `raw_traceback` в самом `refusal_paths.py`, `status: "fail"`, exit 1. Модуль не проходит собственную проверку.

Регекс `["\'].*Traceback.*["\']` с DOTALL вообще не проверяет «внутри строкового литерала» — он матчит любой файл, где есть кавычка до и кавычка после слова `Traceback`, включая комментарии и, как здесь, сам паттерн поиска.

---

## Major

### M1. Вакуумный `pass` при отсутствии целей проверки

`if cli_path.exists():` (строка ~30) и `if engops_path.exists():` (строка ~55) — при непопадании путей `issues` пуст, и `format_report` печатает `✅ All refusal paths are valid`, `status: "pass"`, exit 0. Сценарий: запуск из неверного каталога (`root` по умолчанию `"."`, строка ~89) или переезд CLI в другую директорию → «всё валидно», хотя не прочитан ни один файл. Отчёт обязан различать «проверено и чисто» и «нечего было проверять»: нужен счётчик просмотренных файлов и `status: "skipped"`/`error`, когда он нулевой.

### M2. Путь к CLI захардкожен

`root / "ai_ops_kit" / "cli" / "ai_ops_cli.py"` (строка ~29). Переименование или добавление второго entry point молча выводит их из-под проверки — без сигнала, сливаясь с M1.

### M3. Отчёт не даёт исполнимого совета

Модуль существует ради тезиса «совет, который нельзя выполнить, хуже отсутствия», но `format_report` (строки ~77–91) печатает только `type`, имя флага/файла и `context`. Ни номера строки, ни фрагмента, ни указания, что править. Для `raw_traceback` пользователь получает имя файла на 100+ строк и никакой привязки к месту.

---

## Minor

- **N1.** `import argparse` внутри `main()` (строка ~85) при остальных импортах на уровне модуля (строки 18–21) — расхождение со стилем файла.
- **N2.** `re.findall(r'--([a-z0-9-]+)', content)` захватывает `--` в комментариях, URL и строках вида `foo--bar`; флаги с подчёркиванием или заглавными не матчятся вовсе.
- **N3.** Docstring обещает `refusal_paths.py <child_root>`, но `root` необязателен с дефолтом `"."` (строка ~87) и никак не валидируется как корень child-репозитория — усиливает M1.
- **N4.** `format_report` обращается к `issue['type']` и `issue['context']` без `.get`, тогда как для `flag`/`file` используется `.get` — асимметрия, KeyError при добавлении нового типа issue без `context`.

---

## Scope violations

- Флаг `--selftest` и его тело в продакшн-модуле `ai_ops_kit/engops/refusal_paths.py` — код должен быть в `tests/unit/test_refusal_paths_selftest.py` (AGENTS.md). Единственное нарушение scope; посторонних правок в диффе нет.

---

## Missing tests

- `tests/unit/test_refusal_paths_selftest.py` — отсутствует, требуется правилом репозитория.
- Нет позитивного теста: фикстура с CLI, где в сообщении упомянут флаг без `add_argument`, → ожидается `undefined_flag`. Такой тест сразу вскрыл бы B3.
- Нет теста на реальную утечку traceback (`traceback.print_exc()` в фикстуре) → ожидается `raw_traceback`. Вскрыл бы B5 (ложноотрицательное).
- Нет теста на отсутствие целей проверки → ожидается не-`pass`. Вскрыл бы M1.
- Нет теста «модуль проходит проверку на собственном репозитории» — вскрыл бы самоотравление из B5.

---

## Compatibility risks

- Новых зависимостей нет (`json`, `re`, `sys`, `pathlib`, `argparse` — stdlib). Существующий код не изменён, только новый файл — риска обратной совместимости для потребителей кита нет.
- Единственный риск при включении в гейт: из-за B5 модуль возвращает exit 1 на чистом репозитории. Если его подключат к CI как блокирующую проверку, гейт будет красным всегда и его отключат — то есть проверка окажется мёртвой в обе стороны (не находит настоящее, находит несуществующее).
- Формат вывода зафиксирован `schema_version: 1` — при исправлении набора типов issue стоит менять версию сразу, до появления потребителей.

---

## Что сделано хорошо

- Проблема в шапке модуля сформулирована точно и с обоснованием, почему она важна («совет, который нельзя выполнить, хуже отсутствия») — контракт понятен без чтения кода.
- Структурированный JSON-выход с `schema_version`/`kind`/`status` и отдельный человекочитаемый режим — правильное разделение для машинного гейта и для человека.
- Exit-код связан со `status` (0/1), а не всегда 0 — модуль пригоден для автоматизации, как только логика начнёт работать.
- Строгая типизация возврата и `from __future__ import annotations`, изоляция форматирования от проверки (`check_refusal_paths` / `format_report`) — структура даёт тестировать логику без парсинга stdout.

---

```json
{
  "schema_version": 1,
  "kind": "reviewer-result",
  "gate": "code_review",
  "status": "fail",
  "checks": [
    {"id": "selftest_actually_executes", "status": "fail"},
    {"id": "selftest_placement_agents_md", "status": "fail"},
    {"id": "declared_checks_implemented", "status": "fail"},
    {"id": "flag_check_can_detect", "status": "fail"},
    {"id": "traceback_check_soundness", "status": "fail"},
    {"id": "no_self_false_positive", "status": "fail"},
    {"id": "no_vacuous_pass", "status": "fail"},
    {"id": "unit_tests_present", "status": "fail"},
    {"id": "actionable_report_output", "status": "warn"},
    {"id": "hardcoded_paths", "status": "warn"},
    {"id": "code_style_consistency", "status": "warn"},
    {"id": "scope_creep", "status": "fail"},
    {"id": "new_dependencies", "status": "pass"},
    {"id": "backward_compatibility", "status": "pass"},
    {"id": "structured_output_contract", "status": "pass"}
  ],
  "blockers": [
    "--selftest печатает 'check_refusal_paths: OK', 'format_report: OK' и 'SELFTEST PASSED' без вызова этих функций; при замене тела check_refusal_paths на raise селфтест всё равно возвращает 0 — объявленная проверка не исполняется",
    "Selftest реализован в продакшн-модуле ai_ops_kit/engops/refusal_paths.py и уедет в child-репозиторий; AGENTS.md требует tests/unit/test_refusal_paths_selftest.py, которого в диффе нет",
    "defined_flags = re.findall(r'--([a-z0-9-]+)', content) собирает все вхождения '--flag', а не определения через add_argument, поэтому любой флаг, найденный error-паттерном, уже в defined_flags — ветка undefined_flag недостижима; флаг, упомянутый в подсказке но не объявленный в CLI, даёт pass",
    "Все три error_patterns ищут в исходниках тексты, генерируемые argparse в рантайме ('unrecognized arguments: --x', \"invalid choice: 'x'\") — в коде таких литералов нет, finditer не находит ничего никогда",
    "Заявленная в docstring проверка 'Все упомянутые команды существуют' не реализована ни одной строкой кода",
    "Проверка traceback ищет литерал 'Traceback (most recent call last)', тогда как реальные утечки идут через traceback.print_exc()/format_exc() — все настоящие утечки проходят",
    "refusal_paths.py сам лежит в ai_ops_kit/engops/, попадает под свой glob('*.py') и содержит искомый литерал; regex ['\\\"].*Traceback.*['\\\"] с re.DOTALL и жадными .* матчит от docstring до \"__main__\" — модуль сообщает raw_traceback о самом себе, status=fail, exit 1 на чистом репозитории",
    "При несуществующих cli_path/engops_path (root по умолчанию '.') issues пуст и отчёт печатает '✅ All refusal paths are valid' с exit 0 — модуль утверждает пройденной проверку, для которой не прочитал ни одного файла"
  ]
}
```