"""Пропуск проверок по «только документация» — это ОСВОБОЖДЕНИЕ с причиной, а не пустой pass.

НАХОДКА B2-08 (второй реальный brownfield, 2026-08-14). Ветка `tier == "skip"` в
`evidence_collector` возвращала `status: pass` с единственным флагом `skip_verification`, которого
НЕТ в `required_evidence` гейта, и `not_applicable: []`. Дальше `gate_executor` честно не находил
ни одного из пяти обязательных флагов и превращал такой pass в БЛОКИРУЮЩИЙ отказ «бездоказательный
pass». Ветка, созданная чтобы пропустить проверку, сама её и заваливала.

ВАЖНО ПРО ОХВАТ: сначала это выглядело как «кит бесполезен на репозитории без тестов». Замер
опроверг: воспроизводится на ПОЛНОМ наборе команд, то есть на любом репозитории, включая сам кит.
Отсутствие тестов у продукта было совпадением, а не причиной. Цена: ни одно изменение только
документации не могло дойти до владельца.

ЧЕГО ЗДЕСЬ НЕЛЬЗЯ СЛОМАТЬ: запрет бездоказательного pass. Освобождение отличается от него тем, что
названо и записано в warnings — «проверку не делали, потому что она не применима», а не «проверка
прошла». Поэтому тестов три, и второй сторожит именно запрет.
"""
from __future__ import annotations

from evidence_collector import collect            # noqa: F401  (шов проверяется ниже)
from gate_executor import evaluate

GATE = "implementation_verification"
DOCS_REASON = "изменение только документации — продуктовые проверки не применимы"
DOCS_EXEMPT = {"build_passed", "lint_passed", "typecheck_passed", "tests_passed"}


def _evaluate(evidence, exempt=None, reason=None):
    return [g for g in evaluate(
        "QUICK", evidence=evidence, tested_revision="deadbeef", gate_ids=[GATE],
        signals={"size": "small", "risk": "low"},
        not_applicable={GATE: exempt or set()},
        exempt_reason={GATE: reason})["gate_results"] if g["gate"] == GATE][0]


def test_docs_only_change_is_not_blocked(tmp_path):
    """positive: изменение только документации проходит, и причина освобождения названа."""
    g = _evaluate({GATE: {"status": "pass",
                          "provided": ["skip_verification", "tested_revision"],
                          "evidence": ["skip_reason:docs_only"]}},
                  exempt=DOCS_EXEMPT, reason=DOCS_REASON)

    assert g["status"] == "pass", f"изменение документации заблокировано: {g['blockers']}"
    assert not g["blockers"], f"остались блокеры: {g['blockers']}"
    assert any(DOCS_REASON in w for w in g["warnings"]), (
        f"освобождение молчаливое — в отчёте не сказано, почему проверок не было: {g['warnings']}")


def test_pass_without_evidence_still_blocks():
    """границы: запрет бездоказательного pass НЕ ослаблен.

    Это обратная цена правки и главный риск: «починить» блокировку можно было бы, разрешив pass
    без доказательств вообще — и тогда кит начал бы зеленить непроверенное, ровно то, против чего
    построен. Освобождение законно только когда оно ОБЪЯВЛЕНО; неназванного освобождения нет.
    """
    g = _evaluate({GATE: {"status": "pass", "provided": ["skip_verification"], "evidence": []}})

    assert g["status"] == "fail", "pass без доказательств и без освобождений перестал блокировать"
    assert any("бездоказательный pass" in b for b in g["blockers"]), g["blockers"]


def test_stack_exemption_keeps_its_own_reason():
    """side-effect proof: старое освобождение (нет инструмента в стеке) не получило чужую причину.

    Причина освобождения — основание, по которому человек принимает решение. Написать «нет
    инструмента в стеке» там, где инструмент есть и просто не нужен, значит подсунуть ложное
    основание; обратная подстановка так же вредна. Поэтому проверяется, что без явной причины
    текст остаётся прежним.
    """
    g = _evaluate({GATE: {"status": "pass", "provided": ["build_passed", "tested_revision"],
                          "evidence": []}},
                  exempt={"lint_passed", "typecheck_passed", "tests_passed"})

    assert g["status"] == "pass", g["blockers"]
    assert any("нет инструмента в стеке" in w for w in g["warnings"]), (
        f"причина освобождения по стеку потеряна: {g['warnings']}")
    assert not any(DOCS_REASON in w for w in g["warnings"]), "подставлена чужая причина"


def test_collector_and_gate_agree_on_the_flags(tmp_path):
    """шов: сборщик освобождает РОВНО те флаги, которые гейт считает обязательными.

    Дефект жил не внутри функции, а в шве: сборщик отдавал флаг `skip_verification`, которого гейт
    не знает. Список берётся У ОБЕИХ СТОРОН — из сборщика и из реестра гейтов, — а не переписан
    константой в тесте.

    Первая версия этого теста ПЕРЕЖИЛА мутацию «сборщик снова не освобождает ничего»: она сравнивала
    константу теста с реестром и сборщик не вызывала вовсе. Тест шва, не трогающий шов, — это
    декорация; поймано мутацией, не чтением.
    """
    import gate_executor as gx
    from evidence_collector import collect

    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "readme.md").write_text("текст\n", encoding="utf-8")
    coll = collect({}, tmp_path, None, changed_files=["docs/readme.md"])

    assert coll["gate_evidence"][GATE]["status"] == "pass", coll["gate_evidence"]
    exempt = set(coll["not_applicable"])
    provided = set(coll["gate_evidence"][GATE]["provided"])
    assert coll.get("not_applicable_reason"), "освобождение без причины — это молчаливый пропуск"

    required = set(gx.load_gates()[GATE]["required_evidence"])
    assert required <= (exempt | provided), (
        f"гейт требует то, чего сборщик не покрывает: {sorted(required - (exempt | provided))}")

    # и сквозной проверкой: с этим evidence гейт действительно не блокирует
    g = _evaluate(coll["gate_evidence"], exempt=exempt, reason=coll["not_applicable_reason"])
    assert g["status"] == "pass" and not g["blockers"], g["blockers"]
