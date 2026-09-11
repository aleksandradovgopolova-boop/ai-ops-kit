"""CONFLICTING — восьмое состояние знания: источники истины об одном факте противоречат.

  * positive     — README(PostgreSQL) vs ARCHITECTURE(SQLite) => конфликт с ПЕРЕЧИСЛЕНИЕМ голосов;
                   поднимается в reconstruct как status=conflicting и в `model` как needs_input;
  * no-false     — согласные источники и одиночный голос НЕ дают конфликта (ложная тревога дороже
                   молчания); «мигрировали с X на Y» в одном документе — не спор;
  * resolve      — явное подтверждение владельца перебивает conflicting (человек сильнее).
"""
from __future__ import annotations

from ai_ops_kit.planning import repo_audit as A
from ai_ops_kit.planning import source_conflict as SC
from ai_ops_kit.ui import presenter_formatters as PF


def _write(root, **files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


# ── positive ──────────────────────────────────────────────────────────────────────────────────

def test_readme_and_architecture_disagree_is_conflicting(tmp_path):
    _write(tmp_path,
           **{"README.md": "Хранилище: PostgreSQL для всех данных.",
              "ARCHITECTURE.md": "Данные лежат в SQLite, встроенно."})
    conflicts = SC.detect(tmp_path)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c["category"] == "database" and c["state"] == SC.CONFLICTING
    sources = {claim["source"]: claim["values"] for claim in c["claims"]}
    # Обе стороны перечислены — молчаливого выбора нет.
    assert sources["README"] == ["postgres"]
    assert sources["ARCHITECTURE"] == ["sqlite"]


def test_code_deps_contradict_doc(tmp_path):
    _write(tmp_path,
           **{"ARCHITECTURE.md": "СУБД: MongoDB.",
              "requirements.txt": "psycopg2-binary==2.9\nflask\n"})
    conflicts = SC.detect(tmp_path)
    assert len(conflicts) == 1
    labels = {c["source"] for c in conflicts[0]["claims"]}
    assert "код (зависимости)" in labels and "ARCHITECTURE" in labels


def test_reconstruct_flips_persistence_to_conflicting(tmp_path):
    _write(tmp_path,
           **{"README.md": "PostgreSQL.", "ARCHITECTURE.md": "SQLite."})
    ev = A.discover(tmp_path)
    rec = A.reconstruct(tmp_path, ev)
    assert rec["persistence"]["status"] == A.CONFLICTING
    assert rec["persistence"]["conflicts"]


def test_run_surfaces_conflicts_top_level_and_model_asks(tmp_path):
    _write(tmp_path,
           **{"README.md": "Мы используем PostgreSQL.",
              "ARCHITECTURE.md": "Persistence: SQLite."})
    rep = A.run(tmp_path)
    assert rep["conflicts"] and rep["conflicts"][0]["category"] == "database"
    # `model` не выдаёт «ok»: противоречие требует решения владельца, а не сбора недостающего.
    msg = PF.from_repository_understanding(rep)
    assert msg["status"] == "needs_input"
    assert "противореч" in (msg["why_it_matters"] or "").lower()
    assert msg["technical_details"]["payload"]["conflicting_sources"] == "database"


def test_render_lists_diverging_sources(tmp_path):
    _write(tmp_path, **{"README.md": "PostgreSQL.", "ARCHITECTURE.md": "SQLite."})
    rep = A.run(tmp_path)
    text = A.render(rep)
    assert "ПРОТИВОРЕЧИЯ ИСТОЧНИКОВ" in text
    assert "postgres" in text and "sqlite" in text


# ── no false positives ──────────────────────────────────────────────────────────────────────

def test_agreeing_sources_no_conflict(tmp_path):
    _write(tmp_path,
           **{"README.md": "PostgreSQL.", "ARCHITECTURE.md": "PostgreSQL везде."})
    assert SC.detect(tmp_path) == []


def test_single_voice_no_conflict(tmp_path):
    _write(tmp_path, **{"README.md": "PostgreSQL."})
    assert SC.detect(tmp_path) == []


def test_migration_narrative_in_one_doc_no_conflict(tmp_path):
    # Один документ упоминает обе СУБД (история миграции) — множества пересекаются, не спор.
    _write(tmp_path,
           **{"README.md": "Мигрировали с SQLite на PostgreSQL в 2024.",
              "ARCHITECTURE.md": "PostgreSQL."})
    assert SC.detect(tmp_path) == []


def test_no_sources_no_conflict(tmp_path):
    _write(tmp_path, **{"README.md": "Просто приложение без упоминания СУБД."})
    assert SC.detect(tmp_path) == []


# ── resolve ─────────────────────────────────────────────────────────────────────────────────

def test_owner_confirmation_beats_conflicting(tmp_path):
    _write(tmp_path,
           **{"README.md": "PostgreSQL.", "ARCHITECTURE.md": "SQLite.",
              ".ai-ops.yaml": ("product_operating_model:\n  confirmed:\n"
                               "    persistence: PostgreSQL — источник истины\n")})
    rec = A.reconstruct(tmp_path, A.discover(tmp_path))
    # Явный выбор владельца РЕШАЕТ спор: состояние становится user_confirmed, не conflicting.
    assert rec["persistence"]["status"] == A.USER_CONFIRMED
