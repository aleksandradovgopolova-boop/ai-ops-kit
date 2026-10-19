# Durable учёт пакетов до очистки

- Результат: отдельные реальные вызовы сохраняются в product/task ledger; повтор сведения одной source stream не удваивает их; cleanup допускается только после durable проверки объявленных артефактов.
- Пути: существующий `usage_ledger.merge_ledgers` → JSONL-адаптер existing LifecycleStore → координатор isolated package runs (delivery #1307 merged `c2e4155de033d442636e8ef9607307ee5f246663`).
- Инварианты: source/run/stream/offset identity, SHA/digest для целостности; два одинаковых calls не сливаются; unknown USD остаётся unknown; исходные ledger/config не переписываются.
- Безопасность: только UsageRecord whitelist и объявленные безопасные evidence-поля; не копировать config/env/credentials/raw prompts; запретить source symlink escape и невалидные package paths.
- Отказы: malformed source/changed stream, durable write/readback fault, fan-in fail/retry, collision provenance, concurrent destination append. Последняя owned копия не удаляется при незавершённом сохранении.
- Доказательство до кода: source2 → product2 → task1 у старого helper; новые тесты сохраняют оба вызова, повтор импортирует 0, новая source запись добавляется один раз; actual source files проверяются до cleanup.
- Запись: общий existing journal lock для append и merge; atomic JSONL через единый LifecycleStore, без второй реализации durable-контракта.
- Не входит: provider context/finalize (другой writer), новый Budget, native paid fanout, новый subsystem/module/package, копирование всего дерева и бессрочное выключение cleanup.
- Процесс: targeted до реализации, одна независимая review/коррекция; целевой/core smoke, затем все обязательные exact-head CI; local full лишь по конкретному непокрытому риску по #1306; PR не смешивается с delivery.

- Унаследованные ledger при клонировании: до package call фиксируется byte-offset+prefix SHA; копируются только новые строки. Переписанная baseline блокирует cleanup.

## Контролируемое evidence

151 целевая/core проверка после review прошла: UsageRecord fan-in, LifecycleStore, существующие Git package/delivery швы. Новые реальные Git случаи покрывают package pass/fail/exception, cleanup после durable receipt, corrupt/receipt refusal с сохранением source, inherited tracked history и повтор сохранения без двойного учёта. Исполнитель AI, модельный runner инъектирован; это не живой продуктовый запуск. USD/активное время человека/owner acceptance неизвестны.

Один независимый AI review: три P1 и два P2. Четыре новые регрессии падали до коррекции; missing/corrupt Git, обязательная durable baseline, числовая latency и отчёт об IO-сбое cleanup исправлены одной итерацией. P2 конкурентной подмены файлового пути между проверкой symbolic link и IO остаётся отдельной задачей anchored/dirfd IO существующего LifecycleStore; статическая проверка ссылок не объявляется полной защитой от конкурентного локального процесса.

Сохранённый controlled Git fixture без global Git identity: 3.194 с, четыре отдельных одинаковых вызова, package sources удалены только после receipt, integration `8976de4e328341d65295a434d73615c9a4c36f65` физически доступна. Source base `53308eba78a561027dea812214895c527660c56d` с явно dirty реализацией; JSON receipt/ledger и точные source SHA сохранены в `outputs/kit-product-performance-20261016/parallel-artifacts/controlled-proof.json`. Это injected runner/aggregate, не живой продуктовый замер.
