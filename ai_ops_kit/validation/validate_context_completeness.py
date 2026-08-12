#!/usr/bin/env python3
"""validate_context_completeness.py (v3.12.0 Startup Context Budget) — проверка ПОЛНОТЫ контекста
репозитория: объявленные обязательными документы (session_orchestration.living_status.required_context_docs)
должны присутствовать в project/custom-оверлее репозитория, а не только в managed-наборе кита.

Причина: новые обязательные документы контекста (ProductStatus.md, now.md) доезжают в
.ai/managed/context/**, но в .ai/project/context/** их может не быть — и «читать первым» тогда исполняет
случайный тяжёлый документ. Здесь мы проверяем, что обязательный набор РЕАЛЬНО заполнен в оверлее.

Список обязательного берётся из манифеста (session_orchestration.living_status.required_context_docs),
НЕ хардкодом. При отсутствии манифеста — консервативный дефолт.

Advisory: rc 0 (пробел — сигнал, не блок), 1 — при --strict и наличии пробелов, либо ошибка чтения.

Использование:  validate_context_completeness.py <child_root> [--strict] [--json]
                validate_context_completeness.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
            Path(__file__).resolve().parents[1])
_DEFAULT_REQUIRED = ["product/ProductStatus.md", "now.md"]


def required_docs(manifest_path: Path = None):
    """Обязательные документы контекста из манифеста (living_status.required_context_docs)."""
    mp = manifest_path or (PKG / "manifest" / "ai-ops-manifest.yaml")
    try:
        mani = yaml.safe_load(mp.read_text(encoding="utf-8")) or {}
        r = (((mani.get("session_orchestration") or {}).get("living_status") or {})
             .get("required_context_docs"))
        if r:
            return list(r)
    except (OSError, yaml.YAMLError):
        pass
    return list(_DEFAULT_REQUIRED)


# Признаки НЕЗАПОЛНЕННОГО документа. Не «слова из шаблона» вообще (тогда любой честный текст,
# цитирующий шаблон, считался бы заготовкой), а прямые указания, что писать здесь ещё не начали:
# фраза-инструкция «заполняется в child-репозитории» и круглые скобки-заглушки в местах, где ждут
# факт. Порог по числу заглушек, а не наличие одной: заполненный документ вправе иметь скобки в
# прозе. Замер на реальных файлах кита до/после заполнения: шаблон давал 8 и 6 заглушек,
# заполненные — 0 и 0.
_TEMPLATE_MARKERS = (
    "заполняется в child-репозитории",
    "заполняется в child-репозитории.",
    "(заполняется",
)
_PLACEHOLDER_RE = r"^\s*[-|>*\d.]*\s*\((?:готово / частично / нет|…|[а-яё][^)]{2,60})\)\s*$"
_PLACEHOLDER_LIMIT = 3


def is_template(text: str) -> bool:
    """Документ контекста — ещё заготовка кита, а не факты репозитория? -> bool.

    ЗАЧЕМ (F-027, внешнее ревью 12.08.2026). `check_completeness` спрашивал только `is_file()`, то
    есть СУЩЕСТВОВАНИЕ файла принималось за ЗАПОЛНЕННОСТЬ: собственные `ProductStatus.md` и `now.md`
    кита месяц лежали шаблонами с фразой «Заполняется в child-репозитории», а валидатор печатал
    `[OK]` и `CONTEXT-COMPLETE`. Это тот же класс, что F-018, где то же самое обнаружилось у
    планирования — там детектор заготовки уже есть (`delivery_plan.is_template`), а здесь его не
    было. Один дефект, две подсистемы, исправлена была одна.
    """
    import re

    # НОРМАЛИЗАЦИЯ ОБЯЗАТЕЛЬНА, и это замер, а не осторожность: заполненный ProductStatus кита
    # цитирует фразу-маркер, объясняя свою историю, и НЕ сработал только потому, что перенос строки
    # разбил её пополам. Детектор, чей ответ зависит от переноса строки, — это удача, а не проверка.
    low = re.sub(r"\s*\n[>\s]*", " ", (text or "").lower())
    if any(m in low for m in _TEMPLATE_MARKERS):
        return True
    holes = len(re.findall(_PLACEHOLDER_RE, text or "", re.M))
    return holes >= _PLACEHOLDER_LIMIT


def check_completeness(child_root, required=None, manifest_path: Path = None):
    """-> dict: required / present / template / missing / complete.

    Документ считается present, если есть в project/context ИЛИ custom/context оверлея (managed —
    это шаблон кита, не заполненный репозиторием). ЗАГОТОВКА присутствием НЕ считается: см.
    `is_template` — существование файла это не заполненность.
    """
    root = Path(child_root)
    required = required if required is not None else required_docs(manifest_path)
    present, missing, template = [], [], []
    for doc in required:
        found = next((p for p in ((root / ".ai/project/context" / doc),
                                  (root / ".ai/custom/context" / doc)) if p.is_file()), None)
        if found is None:
            missing.append(doc)
            continue
        try:
            if is_template(found.read_text(encoding="utf-8", errors="replace")):
                template.append(doc)
                continue
        except OSError as e:
            # Нечитаемый файл — не «заполненный»: молча считать его present значило бы сделать
            # самый мягкий вывод из самого подозрительного состояния.
            template.append(f"{doc} (не читается: {type(e).__name__})")
            continue
        present.append(doc)
    return {"kind": "context-completeness", "required": required,
            "present": present, "template": template, "missing": missing,
            "complete": not missing and not template}


def run(child_root, strict=False, as_json=False, manifest_path: Path = None):
    rep = check_completeness(child_root, manifest_path=manifest_path)
    if as_json:
        print(json.dumps({"schema_version": 1, **rep}, ensure_ascii=False, indent=2))
    else:
        print(f"=== полнота контекста репозитория ({child_root}) ===")
        for doc in rep["required"]:
            if doc in rep["present"]:
                mark = "OK"
            elif any(str(d).startswith(doc) for d in rep["template"]):
                mark = "ЗАГОТОВКА"
            else:
                mark = "MISSING"
            print(f"  [{mark}] {doc}")
        if rep["complete"]:
            print("CONTEXT-COMPLETE: обязательные документы контекста заполнены фактами репозитория.")
        else:
            if rep["missing"]:
                print(f"ВНИМАНИЕ: {len(rep['missing'])} обязательных документов НЕТ в project/custom — "
                      f"`ai-ops update` создаст их черновики из шаблонов: {', '.join(rep['missing'])}")
            if rep["template"]:
                # Заготовка — не «есть»: сказать это прямо, иначе доверие к CONTEXT-COMPLETE ложное.
                print(f"ВНИМАНИЕ: {len(rep['template'])} документов остались ЗАГОТОВКОЙ кита, а не "
                      f"фактами репозитория: {', '.join(map(str, rep['template']))}. Это не «есть»: "
                      f"сессия прочитает их первыми и получит шаблон вместо состояния продукта.")
    return 1 if (strict and (rep["missing"] or rep["template"])) else 0


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print("usage: validate_context_completeness.py <child_root> [--strict] [--json]"); return 2
    return run(args[0], strict="--strict" in argv, as_json="--json" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
