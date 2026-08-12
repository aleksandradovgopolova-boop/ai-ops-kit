"""F-026: охват проверки чисел в документах не имеет права быть неполным.

НАХОДКА (внешнее ревью 12.08.2026). README говорил «34 гейта», а `docs/index.md` и два документа
`docs/architecture/` — «32» при фактических 34. При этом `CLAIMS-OK` и `RELEASE-CLAIMS-OK` печатались
на каждом прогоне.

Причина оказалась НЕ в отсутствии механизма. `validate_release_claims.derived_number_errors`
существует, работает и даже формулирует нужный инвариант сам («проверка ослепла: текст переписали, а
правило осталось»). Он просто перечислял ОДИН файл — README. Проверка без охвата — половина проверки,
а половина создаёт видимость полной.

Поэтому здесь охраняется не поведение (оно уже покрыто), а ОХВАТ: если документ называет число
гейтов, он обязан быть в списке проверяемых. Иначе следующий документ снова разойдётся молча.

Числа помечены `<!-- claim:gates-total -->`: маркер невидим при рендере и однозначен. Шаблон по прозе
ломается от переформулировки — первая попытка «искать число рядом со словом гейт» сразу дала ложный
красный, потому что в ROADMAP рядом стоят «21 гейт» (блокирующие) и «34» (всего).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
MARKER = "<!-- claim:gates-total -->"
SCANNED = ["README.md", "ROADMAP.md", "AGENTS.md", "docs"]


def _claims():
    return yaml.safe_load((KIT / "registry" / "release-claims.yaml").read_text(encoding="utf-8"))


def _docs_with_marker():
    found = []
    for rel in SCANNED:
        p = KIT / rel
        files = sorted(p.rglob("*.md")) if p.is_dir() else ([p] if p.is_file() else [])
        for f in files:
            if MARKER in f.read_text(encoding="utf-8", errors="replace"):
                found.append(f.relative_to(KIT).as_posix())
    return found


@pytest.mark.unit
def test_every_document_stating_the_number_is_checked():
    """Охват: каждый документ с маркером перечислен в `derived_numbers_in_docs`.

    Это защита от ПРИЧИНЫ, а не от следствия: правило работало, но покрывало один файл из пяти.
    """
    listed = {r["file"] for r in (_claims().get("derived_numbers_in_docs") or [])}
    marked = set(_docs_with_marker())
    assert marked, "маркеры исчезли из документов — проверять стало нечего"
    missing = sorted(marked - listed)
    assert not missing, (
        "документ называет число гейтов, но не проверяется — оно разойдётся молча: "
        f"{missing}. Добавьте его в registry/release-claims.yaml -> derived_numbers_in_docs")


@pytest.mark.unit
def test_listed_documents_exist_and_state_the_number():
    """Обратная сторона: в списке нет файлов, где предмета уже нет.

    Правило, указывающее в никуда, — это не охрана, а строка в реестре.
    """
    stale = []
    for row in (_claims().get("derived_numbers_in_docs") or []):
        p = KIT / row["file"]
        if not p.is_file():
            stale.append(f"{row['file']}: файла нет")
        elif not re.search(row["pattern"], p.read_text(encoding="utf-8", errors="replace")):
            stale.append(f"{row['file']}: образец {row['pattern']!r} не находит число")
    assert not stale, stale


@pytest.mark.unit
def test_the_number_in_docs_equals_the_registry_fact():
    """Тот же вердикт, что в CI, но названный числом: сколько гейтов реально и что написано."""
    import sys

    sys.path.insert(0, str(KIT / "ai_ops_kit" / "validation"))
    import validate_release_claims as vrc

    data = _claims()
    gates = yaml.safe_load((KIT / "quality" / "gates.yaml").read_text(encoding="utf-8"))["gates"]
    assert data["gates_count"] == len(gates), (
        f"claim gates_count={data['gates_count']}, а в quality/gates.yaml {len(gates)}")
    assert vrc.derived_number_errors(data, KIT) == []
