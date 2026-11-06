# Очистка тестов сохраняет исходное дерево — #1480

- **Результат:** root-pollution guard восстанавливает фактические bytes/mode перед прогоном, а не содержимое Git index.
- **Пути:** снимок охраняемых файлов и артефактов при загрузке conftest → обнаружение contamination → проверка безопасного восстановления → точечная очистка → отказ загрязнившего теста.
- **Инварианты:** Git index/staged state не читается для восстановления и не изменяется; прежние файлы/артефакты сохраняются; integration writes только в temporary roots.
- **Failure modes:** unstaged поверх staged; изменение только mode/удаление; смешение прежних и новых workflows/managed-файлов; symlink/type substitution; ошибка чтения/восстановления или fixture finalizer.
- **Доказательство positive:** bytes/mode восстанавливаются после доказанной записи contamination; удаляются лишь новые записи.
- **Доказательство fail-closed:** небезопасный тип/родитель или ошибка очистки оставляют явный отказ без разрушительного auto-restore.
- **Доказательство side effects:** реальная доставка CI в temporary root, настоящий Git index с staged/unstaged различием и точное сравнение bytes index до/после.
- **Проверки:** целевые regression/negative tests, core smoke, lint, широкий PR-профиль по риску test harness, независимое review итоговой delta и штатный exact-head CI.
- **Не входит:** cleanup пользовательских/параллельно изменяемых деревьев, live models, release, изменение access/trust/settings или ослабление gates; сторож не является транзакцией против конкурентных writers.
