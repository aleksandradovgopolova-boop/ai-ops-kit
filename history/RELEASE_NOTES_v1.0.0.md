# AI Ops Kit v1.0.0 — первый стабильный релиз 🎉

AI-first operating system для продуктово-технологических команд: агенты, workflow-контракты,
quality gates, provider/runtime маршрутизация и управляемые обновления child-репозиториев.

## Что означает 1.0
- Контракты стабильны: patch/minor обновления не ломают подключённые репозитории (SemVer).
- Проверено в бою: два продуктовых репозитория подключены и обновляются штатным `ai-ops update`
  (цепочка 0.6 → 0.7 → 0.8 → 1.0 пройдена без потери локальных файлов).

## Ключевые возможности
- **Задача словами** → классификация → один из 4 workflow (QUICK/ENGINEERING/PRODUCT/RESEARCH) с объяснением маршрута
- **Quality gates** с machine-readable результатами и revision-binding (+ детектор устаревших проверок)
- **Writer ≠ judge**, судья read-only и видит только опубликованные артефакты
- **Маршрутизация** провайдер/модель/среда: декларативные правила, explainable решения, fallback-цепочки (GigaChat — готовая опция)
- **Sequential-оркестратор** — работает даже без native-агентов/MCP (минимальный общий знаменатель)
- **Генерация runtime-команд** для Claude Code / Codex из единого источника
- **OpenSpec** как опция с детерминированными validate/archive/sync и guard'ом от parallel-merge потерь
- **Управляемые обновления**: diff → PR, ручные правки managed-слоя ловятся, локальное никогда не перезаписывается молча

## Установка
```bash
git clone https://github.com/aleksandradovgopolova-boop/ai-ops-kit.git
cd <ваш-репозиторий>
python3 <путь>/ai-ops-kit/installer/ai_ops.py init .
python3 <путь>/ai-ops-kit/installer/ai_ops.py doctor
```
