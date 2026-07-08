---
id: example-managed-scope-control
type: rule
title: Example Managed Rule (Scope Control)
domain: core
status: active
version: 0.3.0
vendor_neutral: true
---

# Example Managed Rule — Scope Control

Пример managed-файла, поставляемого parent-пакетом в дочерний репозиторий.
Он **обновляется только parent**; правка вручную запрещена и обнаруживается по
контрольной сумме (`.checksums.json`).

## Правило (пример)

- Работать только в утверждённом scope; выход за scope запрещён.
- Изменения вне scope требуют отдельного согласования.

## Как это работает в child

Если этот файл изменить локально, `ai_managed_checksums.py verify` покажет drift,
и обновление parent->child остановится, предложив перенести правку в `custom/`-overlay.
Локальные дополнения к правилам следует класть в `.ai/project/` или `.ai/custom/`,
не редактируя managed-файлы напрямую.
