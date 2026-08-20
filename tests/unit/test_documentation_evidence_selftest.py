"""Гейт `documentation_updated` стал машинным — и машина обязана быть права (C3, v3.37).

Гейт переведён из самозаявления в валидатор: раньше стадия, которая работу и сделала, объявляла её
задокументированной. Перевод осмыслен только если проверка отвечает на вопрос лучше писателя, а не
просто быстрее. Поэтому здесь проверяется не «функция не падает», а четыре утверждения:

1. Оба доказательства читаются из ДИФА, а не со слов: документация тронута, запись истории есть.
2. Третье состояние не сворачивается во второе: базы сравнения нет -> `unverifiable`, каталог
   фрагментов не объявлен -> `unknown` по этому доказательству. Ни то, ни другое не «нарушение».
3. Освобождение громкое: «документация не нужна» закрывает доказательство только явным
   объявлением с причиной, и причина уходит в warnings.
4. Гейт advisory: непройденное даёт warn с причиной, а не блок и не тихий pass.

Прогоны идут на настоящих временных git-репозиториях — проверка читает git, и подменять git
значило бы проверять подмену.
"""
from __future__ import annotations

import subprocess

import pytest

from ai_ops_kit.gates import documentation_evidence as de
from ai_ops_kit.gates.gate_executor import evaluate_gate, load_gates

GATES = load_gates()


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    """Репозиторий с одним коммитом-базой и объявленным каталогом фрагментов."""
    r = tmp_path / "child"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "pyproject.toml").write_text(
        '[tool.ai_ops.release_gates]\nchangelog_fragments_dir = "newsfragments"\n',
        encoding="utf-8")
    (r / "src.py").write_text("x = 1\n", encoding="utf-8")
    (r / "newsfragments").mkdir()
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    return r


def _commit(root, msg="work"):
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)


# ─── 1. оба доказательства читаются из дифа ────────────────────────────────────────────────────

def test_docs_and_a_fragment_close_the_gate(repo):
    (repo / "README.md").write_text("описание\n", encoding="utf-8")
    (repo / "newsfragments" / "work.feat.md").write_text("новость\n", encoding="utf-8")
    _commit(repo)

    a = de.assess(repo, base="HEAD~1")
    assert a["status"] == "documented"
    assert a["docs_changed"] == ["README.md"]
    assert a["fragments"] == ["newsfragments/work.feat.md"]

    ev = de.gate_evidence(a)
    res = evaluate_gate("documentation_updated", GATES["documentation_updated"],
                        {"documentation_updated": ev})
    assert res["status"] == "pass"
    assert sorted(ev["provided"]) == ["docs_updated_or_explicit_none", "release_notes_entry"]


def test_a_fragment_is_not_counted_as_documentation(repo):
    """Иначе один фрагмент закрывал бы ОБА доказательства — проверка проверяла бы себя."""
    (repo / "newsfragments" / "work.fix.md").write_text("новость\n", encoding="utf-8")
    _commit(repo)
    a = de.assess(repo, base="HEAD~1")
    assert a["docs_changed"] == [] and a["fragments"] == ["newsfragments/work.fix.md"]
    assert a["status"] == "not_documented"
    assert "не трогает документацию" in a["reason"]


def test_code_only_change_does_not_close_the_gate(repo):
    (repo / "src.py").write_text("x = 2\n", encoding="utf-8")
    _commit(repo)
    a = de.assess(repo, base="HEAD~1")
    assert a["status"] == "not_documented"
    ev = de.gate_evidence(a)
    res = evaluate_gate("documentation_updated", GATES["documentation_updated"],
                        {"documentation_updated": ev})
    assert res["status"] == "warn" and res["blocking"] is False, "гейт advisory: warn, не блок"
    assert any("не трогает документацию" in w for w in res["warnings"])


def test_docs_without_a_release_note_are_not_enough(repo):
    (repo / "README.md").write_text("описание\n", encoding="utf-8")
    _commit(repo)
    a = de.assess(repo, base="HEAD~1")
    assert a["status"] == "not_documented"
    assert "newsfragments" in a["reason"]


# ─── 2. третье состояние ───────────────────────────────────────────────────────────────────────

def test_without_a_base_the_answer_is_unverifiable_not_no(tmp_path):
    """«Сравнить не с чем» — не «документация не тронута». Это разные ответы."""
    r = tmp_path / "fresh"
    r.mkdir()
    _git(r, "init", "-q")
    a = de.assess(r)
    assert a["status"] == "unverifiable"
    assert "НЕ следует" in a["reason"]
    ev = de.gate_evidence(a)
    assert ev["status"] == "warn" and not ev.get("provided"), "непроверенное не даёт доказательств"


def test_a_repo_that_never_declared_a_fragments_dir_gets_unknown_not_a_violation(repo):
    """Дочка вправе вести историю иначе. Обвинять её в нарушении непринятого правила нельзя."""
    (repo / "pyproject.toml").unlink()
    (repo / "README.md").write_text("описание\n", encoding="utf-8")
    _commit(repo)
    a = de.assess(repo, base="HEAD~1")
    assert a["fragments_dir"] is None
    assert a["status"] == "partly"
    assert any(c["id"] == "release_notes_dir_not_declared" and c["status"] == "warn"
               for c in a["checks"])
    ev = de.gate_evidence(a)
    assert ev["provided"] == ["docs_updated_or_explicit_none"], "закрыто ровно то, что проверено"
    assert ev["status"] == "warn"


# ─── 3. освобождение громкое ───────────────────────────────────────────────────────────────────

def test_docs_not_needed_closes_the_evidence_but_says_so_out_loud(repo):
    (repo / "src.py").write_text("x = 3\n", encoding="utf-8")
    _commit(repo)
    a = de.assess(repo, base="HEAD~1")
    ev = de.gate_evidence(a, docs_not_needed="правка внутренняя, поведение не описано нигде")
    assert ev["provided"] == ["docs_updated_or_explicit_none"]
    assert any("объявлена ненужной" in w and "внутренняя" in w for w in ev["warnings"])
    res = evaluate_gate("documentation_updated", GATES["documentation_updated"],
                        {"documentation_updated": ev})
    assert any("объявлена ненужной" in w for w in res["warnings"]), \
        "освобождение обязано доехать до отчёта, а не остаться в вызове"


def test_without_a_declaration_the_gate_tells_how_to_close_it(repo):
    (repo / "src.py").write_text("x = 4\n", encoding="utf-8")
    _commit(repo)
    ev = de.gate_evidence(de.assess(repo, base="HEAD~1"))
    assert any("docs_not_needed" in w for w in ev["warnings"]), \
        "отказ без выхода — это тупик, а не проверка"


# ─── 4. гейт исполняется боевым путём ──────────────────────────────────────────────────────────

def test_the_gate_runs_through_deterministic_run_not_only_through_this_test():
    """Объявленная проверка обязана ИСПОЛНЯТЬСЯ: `deterministic_run` знает этот валидатор."""
    from ai_ops_kit.gates import gate_executor as ge
    out = ge.deterministic_run("validate-documentation-updated")
    assert out is not None, "валидатор объявлен в реестре, но executor его не запускает"
    status, checks, provided = out
    assert status in ("pass", "warn", "fail")
    assert checks, "проверка без единого check не отчитывается ни о чём"


def test_the_registry_and_the_code_agree_on_who_closes_this_gate():
    from ai_ops_kit.gates import gate_executor as ge
    g = GATES["documentation_updated"]
    assert g["closed_by"] == "validator" == ge.closed_by(g)
    assert g["validator"] == "validate-documentation-updated"
