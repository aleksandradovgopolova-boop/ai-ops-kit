# Example child install (`.ai/`) — иллюстрация Фазы 4

Показывает, как выглядит дочерний репозиторий после установки пакета: зоны
`managed / project / custom / generated / runtime` (см. `../../security/boundary-model.md`).

Это **пример-фикстура**, не рабочая установка. На нём CI непрерывно проверяет
механизм обнаружения ручной правки managed-файлов:

```
python3 02_tools/ci/ai_managed_checksums.py verify \
  02_tools/ai-first-system/examples/child-install/.ai/managed
```

- `.ai/managed/` — обновляется parent; правка вручную запрещена. Содержит
  `.provenance.json` (откуда/какая версия) и `.checksums.json` (sha256 файлов).
- `.ai/project/`, `.ai/custom/` — локальные, защищены от перезаписи.
- `.ai/generated/` — генерируется adapters (Ф6), перегенерируемо.
- `.ai/runtime/` — временное состояние выполнения.

Изменение любого файла в `managed/` без перегенерации `.checksums.json`
поймает валидатор (drift) — обновление в таком случае останавливается (Ф9, Section 28).
