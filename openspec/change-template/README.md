# change-template — расширенный OpenSpec change-пакет

Шаблон папки одного изменения. OpenSpec-часть проверяется `openspec validate`;
расширения (`execution/`, `gates/`, `decisions/`, `learning/`, `verification.md`) —
наш слой (Section 9 целевой архитектуры).

```
change/
├── change.yaml            # метаданные (schemas/change-metadata) [ext]
├── proposal.md            # OpenSpec: зачем + что
├── requirements.md        # требования [ext/OpenSpec]
├── specs/<capability>/spec.md  # OpenSpec: дельта ADDED/MODIFIED/REMOVED/RENAMED
├── design.md              # OpenSpec: как (опц.)
├── tasks.md               # OpenSpec: чек-лист реализации
├── decisions/ADR-*.md     # [ext] ADR
├── gates/<gate>.gate.json # [ext] machine-readable результаты ворот
├── execution/             # [ext] наш task-lifecycle (см. ../../templates/task)
├── learning/LearningPatch.md  # [ext]
├── evidence/              # [ext]
└── verification.md        # [ext]
```
