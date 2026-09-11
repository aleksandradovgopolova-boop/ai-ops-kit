Архитектурный потолок: число top-level пакетов в `ai_ops_kit/` теперь ратчет (`package_ceiling` в
`packages/layering.yaml`, сейчас 19) — новая capability живёт в существующем домене, а рост числа
пакетов требует архитектурного решения, не привычки «каждая capability — свой пакет». Правило
записано в `AGENTS.md`. Поверх пяти dependency-слоёв названы четыре концептуальных РОЛЬ-слоя
(`conceptual_layers`: DOMAIN / APPLICATION / POLICY / ADAPTERS) с маппингом каждого из 19 пакетов —
документарно, без переезда файлов, и в `ARCHITECTURE.md`. Оба ратчета проверяет
`validate_layering.py` (`tests/contracts/test_package_ceiling.py`): новый пакет краснеет, каждый
пакет отнесён ровно к одному роль-слою, ходят только вниз. (#638)
