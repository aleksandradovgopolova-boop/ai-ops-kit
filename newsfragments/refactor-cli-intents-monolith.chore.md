Монолит проб-свободных intent-хендлеров `ai_ops_kit/cli/ai_ops_cli_intents.py` (1950 строк) разрезан
по когезивным группам на три соседних модуля пакета `ai_ops_kit.cli`: `ai_ops_cli_product.py`
(продукт/поставка/бэклог — `build_preview`, `_run_backlog`, `products`/`delivery`/`model`/`contract`/
`inspect`/`plan`/`session`), `ai_ops_cli_lifecycle.py` (онбординг и governance — `onboard`/`reach`/
`team`/`replan`/`governance`/`bootstrap`/`health`/`roadmap`/`doctor`/`new`/`discuss`) и
`ai_ops_cli_report.py` (read-only отчётность — `explain`/`inbox`). Поведение не менялось — чистый
построчный перенос; `ai_ops_cli_intents.py` теперь импортирует имена из соседей и ре-экспортирует их
(и диспетч в `ai_ops_cli`, и тесты по-прежнему резолвят обработчики по имени `ai_ops_cli_intents`), в
нём остались проекции `work`/`readout`/`graph`. Файл усох до 257 строк, каждый новый модуль ниже
порога 700; потолок module-size снят с усохшего файла записью в ленте `raises`.
