"""Обязательное поле конфига дочки ЧИТАЕТСЯ кодом, а не только требуется схемой.

ПОВОД — ЗАМЕР, И ДВАЖДЫ ОДИН И ТОТ ЖЕ КЛАСС.

  * **F-022** (поле, 12.08.2026): `parent.update_policy` обязателен по схеме, манифест объявляет
    `silent_update: forbidden`, а `init` обещает владельцу вслух «обновления — только через ваш
    PR» — и значение НЕ читала ни одна строка кода. Дочка с `policy: pr` получила обновление
    НА МЕСТЕ посреди продуктовой задачи.
  * **Аудит 19.08.2026**: ровно то же с `parent.update_channel`. Поле обязательно, `init` писал
    его в КАЖДУЮ установку со значением `stable`, `grep` по всему репозиторию давал только схему
    и пример — а ежедневный workflow приносил ветку по умолчанию, то есть `edge`.

Дважды один класс — значит нужен не разбор, а механизм. Мы просим у владельца обязательное
решение; если код его не читает, мы просим впустую и при этом создаём у человека ложную
уверенность, что решение действует.

ЧТО ИМЕННО ТРЕБУЕТСЯ. Поле должно читаться там, где ЧИТАЮТ САМ КОНФИГ ДОЧКИ, — а не встречаться
где-нибудь в репозитории по совпадению имени. Совпадение имени и есть та слабая проверка, которая
пропустила бы оба случая: слово `providers` встречается всюду.

ИСКЛЮЧЕНИЯ ОБЪЯВЛЕНЫ И НЕСУТ ПРИЧИНУ. Структурные поля (`schema_version`, `kind`) поведением не
управляют — их проверяет схема и `validate_ai_ops_child`. Молчаливого исключения нет: запись без
причины краснеет здесь же.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = PKG_ROOT / "schemas" / "child-config.schema.json"

# Признак «файл работает с конфигом дочки»: он его открывает или знает путь.
CONFIG_MARKERS = (".ai-ops.yaml", "CHILD_CONFIG", "_read_child_cfg", "_child_cfg_data",
                  "child_config", "_child_config")

# Поля, которые поведением НЕ управляют. Причина обязательна — проверяется тестом ниже.
STRUCTURAL = {
    "schema_version": "версия формата: её смысл — совместимость, и проверяет её схема, "
                      "а не поведение кита",
    "kind": "тип документа: отличает конфиг дочки от любого другого yaml; проверяется "
            "`validate_ai_ops_child`, поведением не управляет",
}


def _required_fields() -> list[str]:
    """Плоские имена обязательных полей схемы (включая вложенные в `parent`)."""
    doc = json.loads(SCHEMA.read_text(encoding="utf-8"))
    out = []

    def walk(node, prefix=""):
        if not isinstance(node, dict):
            return
        for name in node.get("required", []) or []:
            out.append(f"{prefix}{name}")
        for key, sub in (node.get("properties") or {}).items():
            walk(sub, f"{prefix}{key}.")

    walk(doc)
    return out


def _config_readers() -> list[Path]:
    """Файлы, которые действительно работают с `.ai-ops.yaml`."""
    files = []
    for base in ("ai_ops_kit", "installer"):
        for p in (PKG_ROOT / base).rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if any(m in text for m in CONFIG_MARKERS):
                files.append(p)
    return files


@pytest.mark.contract
def test_every_required_field_is_read_by_code():
    readers = _config_readers()
    assert readers, "не найдено ни одного файла, читающего конфиг дочки — проверка потеряла предмет"
    blob = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in readers)

    dead = []
    for field in _required_fields():
        leaf = field.rsplit(".", 1)[-1]
        if leaf in STRUCTURAL:
            continue
        # Читается ли лист: `get("leaf")`, `["leaf"]`, `.leaf` в пути доступа.
        if not re.search(rf'''["']{re.escape(leaf)}["']''', blob):
            dead.append(field)

    assert not dead, (
        "обязательные поля конфига дочки НЕ читает ни одна строка кода: " + ", ".join(dead) +
        ".\nМы просим у владельца обязательное решение и не исполняем его — это класс F-022 "
        "(`update_policy`) и находки аудита 19.08 (`update_channel`), оба стоили поля. "
        "Либо начните читать поле, либо уберите его из `required` в схеме.")


@pytest.mark.contract
def test_a_structural_exemption_carries_its_reason():
    """Исключение без причины — тихий обход, а не решение."""
    empty = [k for k, v in STRUCTURAL.items() if not str(v).strip()]
    assert not empty, f"исключения без записанной причины: {empty}"
    unknown = [k for k in STRUCTURAL if k not in {f.rsplit(".", 1)[-1] for f in _required_fields()}]
    assert not unknown, (
        f"объявлено исключение для поля, которого нет среди обязательных: {unknown} — "
        f"список стал кладбищем")


@pytest.mark.contract
def test_the_guard_would_catch_a_dead_field():
    """Охрана обязана краснеть на образце дефекта — иначе она сама «объявлена и не исполняется».

    Образец — ровно тот, что был реальностью до 19.08.2026: поле есть в `required`, и ни одного
    его вхождения в коде, читающем конфиг.
    """
    blob = "providers\nupdate_policy\ninstalled_version\nsource"
    leaf = "update_channel"
    assert not re.search(rf'''["']{re.escape(leaf)}["']''', blob), \
        "разбор ослеп: мёртвое поле не распознаётся как мёртвое"
    alive = '.get("update_channel")'
    assert re.search(rf'''["']{re.escape(leaf)}["']''', alive), \
        "разбор ослеп в обратную сторону: живое поле считается мёртвым"
