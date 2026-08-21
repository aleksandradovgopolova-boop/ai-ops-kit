# Freshness sweep log

Еженедельный freshness-свип research-модуля. Append-only.

## 2026-07-30

- Горизонт: 14 дней. `freshness_sweep.py --days 14` → exit 0.
- expired: 0 | expiring (≤14д): 0 | superseded: 0 | продлено: 0
- Затронутые DP: нет.
- Валидатор `validate_research_artifacts.py`: OK (errors=0, warnings=7 — предсуществующие quote-grounding WARN по EV-415/416/419/421/422/535/708, не связаны с этим прогоном).
- Итог: всё свежо, правок нет.

## 2026-08-14

- Горизонт: 14 дней. `freshness_sweep.py --days 14` → exit 0 (`today: 2026-08-14`).
- expired: 0 | expiring (≤14д): 0 | superseded: 0 | продлено: 0
- Покрытие: 178 EV, у всех задан `freshness.expires_at`, все в статусе `active`; ближайшее
  истечение — 2026-09-22 (≈39 дней), за пределами окна. Следующая волна попадёт в окно
  свипа примерно 2026-09-08.
- Затронутые DP: нет.
- Валидатор: OK (errors=0). Warnings 7 → 1 после ревизии quote-grounding (ниже).
- Грабли прогона (важно для будущих Watch): системный `python3` — homebrew 3.14 без `pyyaml`,
  на нём и `freshness_sweep.py`, и `verify_quotes.py` падают на `import yaml`. Запускать
  строго через venv кита: `/Users/sasad/.venvs/ai-ops-kit/bin/python3`. Путь валидатора —
  `ai_ops_kit/validation/validate_research_artifacts.py` (не `validation/…`), и ему нужен
  `PYTHONPATH=/Users/sasad/ai-ops-kit`. Проверять статус без пайпа: `cmd | tail` возвращает
  статус `tail`, из-за чего несуществующая команда выглядит как `EXIT=0`.
- Ревизия quote-grounding (по запросу владельца, вне штатных шагов свипа): в EV-415, EV-416,
  EV-419, EV-421, EV-422, EV-535 добавлены verbatim `citation.quote`, снятые живым re-fetch
  источников; уточнены `locator`. `verify_quotes.py` по этим шести: `quote_match`, score=1.00.
  - EV-535: источник перевязан с блога Fabric (403 + бот-защита Cloudflare, цитированию
    недоступен) на Microsoft Learn `fabric/fundamentals/copilot-enable-fabric`, где порог F2
    цитируется дословно. Дата 30.04.2026 и прежний порог F64/~$5,250 остаются НЕподтверждёнными.
  - EV-422: источник не подтверждает часть statement — флагман GigaChat3.1-702B-A36B и
    MMLU RU 0.8267 на странице отсутствуют (там MMLU RU 5-shot у 20B-A3B = 0,598), «обучен
    с нуля» не заявлено. Зафиксировано в `reliability.rationale`; statement не правился.
  - EV-708 — единственный оставшийся WARN, осознанно: statement — агрегат grep-подсчёта по
    ~279 файлам SKILL.md, дословной цитатой такие числа не заземляются. Требует либо
    воспроизведения подсчёта на пиннутом коммите, либо явного исключения в конвенции.

## 2026-08-03 (запись отозвана)

Запись за эту дату была ошибочной и удалена. Она сообщала «валидатор OK» и результат свипа,
но обе команды в реальности не исполнялись: `freshness_sweep.py` падал на `import yaml`,
а путь `validation/validate_research_artifacts.py` не существует; дата в записи (2026-08-03)
не совпадала с датой прогона. Фактическое состояние на 2026-08-14 — в записи выше.
