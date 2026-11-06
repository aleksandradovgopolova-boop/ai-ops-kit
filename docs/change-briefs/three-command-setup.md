# Подключение из checkout за три команды

Результат: после получения проверенного checkout один stdlib-вход готовит отдельное
Python-окружение и вызывает существующий `installer/ai_ops.py setup`. Полный путь:
clone → bootstrap → activate, без скрытой предварительной установки PyYAML.

Критерии: Git и Python 3.12+ с venv/ensurepip уже доступны; target — существующий
Git-проект с первым коммитом/автором. Это предпосылки, не «чистая ОС без Python».
Зависимость — существующий requirements.txt, только wheel, без нового опубликованного
пакета, curl|sh, source build, смены permissions/security или вызова модели.

Пути: stdlib bootstrap → собственный venv в игнорируемой `.ai/runtime/bootstrap/`
checkout кита → pip requirements → проверка зависимости → существующий setup →
доставленный child CLI. Существующие init/setup/update и entrypoint не меняются.
Для пробы без своего проекта `--demo` после той же подготовки вызывает уже существующий
`examples/first-session/demo.py`: только временный sample, без моделей.
RU/EN одинаковы по шагам, wrapper поддерживает оба языка; CLI setup не считается переведённым.

Инварианты: не ставить в global/user site, не менять credentials и системный PATH;
не перезаписывать чужое окружение; ошибка подготовки не запускает setup и не пишет
в target. Повтор проверяет среду заново, но не ставит dependency без необходимости.
Настройки/продуктовые файлы target сохраняются существующим setup; native readiness
не меняется. Первый commit 8fbb69ca остаётся отдельным.

Failure modes: dependency отсутствует; pip недоступен/нет сети; чужой или повреждённый
venv; конкурентная подготовка; target без Git/первого commit. Каждый — видимый отказ,
а не «готово». Файловая блокировка окружения не даёт двум процессам менять его одновременно.

Доказательство ДО implementation: unit positive/fail-closed/preservation; subprocess
без PyYAML, реальный отдельный venv с существующей проверенной dependency, temp sample
setup и повтор; заранее сохранённые исходники/локальные файлы сравниваются после запуска.
Ошибочная dependency останавливает до target writes. Фиксируется реальное время и охват,
не выдаётся offline wheel cache за проверенный интернет-маршрут на всех ОС.
Целевые тесты installer, core smoke, lint, ссылки и независимый review применимой delta.

Не входит: публикация, внешнее распространение, модель/подписка, реальные проекты,
новые зависимости, credentials, Windows qualification, полная локализация CLI,
автозапуск/безопасность native adapter и CI, которого не было.
