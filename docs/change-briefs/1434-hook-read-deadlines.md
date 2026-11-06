# Ограниченное чтение проектных hooks (#1434)

- **Результат:** Python-вход SessionStart/UserPromptSubmit/Stop ограничивает свои read-only фазы 10 с внутри прежнего внешнего лимита 15 с; остаток нужен для cleanup и ответа.
- **Пути:** stdin → project/config/Git binding → session/migration journal → continuation/artifacts → Stop reconciliation/verification → существующая durable запись.
- **Инварианты:** один monotonic бюджет чтения, только read-only фазы прерываемы; state/claim не меняются при timeout до commit; неизвестный исход записи не повторяется.
- **Инварианты:** прежние binding/receipt/security checks, CLI resume worker, native host_actions и отказ Stop сохранены. Nested native provider не меняется.
- **Failure modes:** FIFO/зависший syscall; суммарное истечение бюджета; cancellation/Git cleanup; timeout после предварительной проверки, до записи; некорректные/изменённые binding или artifacts.
- **Доказательство:** positive hook/Stop; реальные FIFO reads с маркером входа; fail-closed timeout/cancel; сравнение state/claim bytes и повторное получение locks; targeted regressions/core smoke.
- **Поставка:** stock init/update в disposable копиях, delivery footprint/budget, независимое entire-delta review и все применимые CI точного head/base до merge.
- **Граница записи:** durable fsync/readback не прерываются таймером чтения; их ошибка остаётся неизвестным исходом, без очистки свидетельств и автоматического повтора.
- **Граница времени:** бюджет начинается после Python bootstrap. Предшествующий shell Git, загрузка интерпретатора и непрерываемые ожидания ядра не получают новой real-time гарантии; внешний timeout сам по себе не доказывает атомарность или завершение записи.
- **Не входит:** модели, Toast replay, production checkout/install, release, изменение gates, закрытие #1434 или утверждение о живой автономности. Нужна отдельная установленная приёмка под двумя аккаунтами.
