"""Описание выпуска проверяет машина, а не внимательность автора (#1210, `release-notes-checked-by-machine`).

Каждое правило — положительный и отрицательный случай; строгость (кит — строго, дочка — совет);
«нет файла» — неизвестно, а не нарушение; «правил нет» — честный код 2; замер фрагментов не падает
никогда. Отдельно — прогон на НАСТОЯЩИХ данных кита: текущая очередь newsfragments и раздел [4.8.0]
CHANGELOG, где жаргон (PLC2401) известен заранее.
"""
from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KIT))

from ai_ops_kit.validation import validate_release_notes as vr  # noqa: E402

pytestmark = pytest.mark.unit

TITLES = {"headline": "Что меняется для вас", "whats_in": "Что вошло",
          "known_limits": "Известные ограничения", "after_release": "Что сделать после выпуска",
          "details": "Подробнее"}
RELEASE_NOTES = {
    "layer_a": {"max_words": 250, "max_item_chars": 200, "required_blocks": list(TITLES),
                "block_titles": dict(TITLES)},
    "banned_phrases": ["исправлены ошибки и улучшена стабильность"],
    "jargon_source": "product_glossary",
    "tone": "шутить можно о сделанном, но не о непроверенном",
    "every_item_cites_source": True,
}


def _policy(**over) -> dict:
    """Настоящая политика кита (с настоящим глоссарием) + раздел release_notes по общему договору."""
    base = yaml.safe_load((KIT / "registry" / "communication-policy.yaml").read_text(encoding="utf-8"))
    rn = copy.deepcopy(RELEASE_NOTES)
    for k, v in over.items():
        (rn["layer_a"] if k in rn["layer_a"] or k.startswith("citation") or k == "jargon_patterns"
         else rn)[k] = v
    base["release_notes"] = rn
    return base


def _rules(**over) -> dict:
    return vr.rules_from(_policy(**over))


GOOD = """# Что нового

## Что меняется для вас

Кит теперь сам проверяет описание выпуска, прежде чем его увидите вы.

## Что вошло

- Описание выпуска проверяется машиной: длина, понятные слова, ссылка на источник (#1210).

## Известные ограничения

- нет

## Что сделать после выпуска

- Ничего делать не нужно: проверка включится сама (release-notes-checked-by-machine).

## Подробнее

Полный журнал — в CHANGELOG.
"""


def _findings(text: str, **over) -> list:
    return vr.check_layer_a(text, _rules(**over))


def _msgs(text: str, **over) -> str:
    return "\n".join(m for _, m in _findings(text, **over))


def _write_policy(tmp_path: Path, policy: dict) -> Path:
    p = tmp_path / "communication-policy.yaml"
    p.write_text(yaml.safe_dump(policy, allow_unicode=True), encoding="utf-8")
    return p


# ── правила: объявлены / не объявлены ───────────────────────────────────────────────────────────

def test_good_document_has_no_findings():
    assert _findings(GOOD) == []


def test_missing_release_notes_key_raises_rules_missing():
    policy = _policy()
    del policy["release_notes"]
    with pytest.raises(vr.RulesMissing, match="не объявлены"):
        vr.rules_from(policy)


def test_missing_rules_exit_2_with_honest_message(tmp_path, capsys):
    policy = _policy()
    del policy["release_notes"]
    doc = tmp_path / "notes.md"
    doc.write_text(GOOD, encoding="utf-8")
    code = vr.main(["--layer-a", str(doc), "--policy", str(_write_policy(tmp_path, policy))])
    assert code == 2
    assert "не объявлены" in capsys.readouterr().out


def test_missing_policy_file_exit_2(tmp_path, capsys):
    doc = tmp_path / "notes.md"
    doc.write_text(GOOD, encoding="utf-8")
    assert vr.main(["--layer-a", str(doc), "--policy", str(tmp_path / "nope.yaml")]) == 2
    assert "не найдена" in capsys.readouterr().out


def test_no_mode_selected_exit_2(capsys):
    assert vr.main([]) == 2
    assert "не выбран режим" in capsys.readouterr().out


def test_undeclared_glossary_is_named_not_silently_skipped(tmp_path, capsys):
    policy = _policy()
    del policy["product_glossary"]
    doc = tmp_path / "notes.md"
    doc.write_text(GOOD, encoding="utf-8")
    assert vr.main(["--layer-a", str(doc), "--policy", str(_write_policy(tmp_path, policy))]) == 0
    assert "Не проверялось" in capsys.readouterr().out


# ── обязательные разделы ────────────────────────────────────────────────────────────────────────

def test_missing_required_block_is_reported_by_title():
    text = GOOD.replace("## Что сделать после выпуска", "## Разное")
    assert "нет обязательного раздела «Что сделать после выпуска»" in _msgs(text)


def test_block_title_matches_case_and_colon_insensitively():
    text = GOOD.replace("## Что вошло", "### что вошло:")
    assert "Что вошло" not in _msgs(text)


def test_empty_known_limits_is_a_finding():
    text = GOOD.replace("## Известные ограничения\n\n- нет\n", "## Известные ограничения\n\n<!-- заполнить -->\n")
    assert "«Известные ограничения» пуст" in _msgs(text)


def test_explicit_none_in_known_limits_is_fine():
    assert "пуст" not in _msgs(GOOD)


# ── длина ───────────────────────────────────────────────────────────────────────────────────────

def test_too_many_words_is_a_finding():
    text = GOOD.replace("Полный журнал — в CHANGELOG.", "слово " * 300)
    assert "слов при пределе 250" in _msgs(text)


def test_words_within_limit_pass():
    assert "слов при пределе" not in _msgs(GOOD, max_words=60)


def test_long_item_is_reported_with_its_line():
    long_item = "- " + "а" * 201 + " (#1)"
    text = GOOD.replace("- нет", long_item)
    found = [(n, m) for n, m in _findings(text) if "пункт длиннее" in m]
    assert found == [(13, "пункт длиннее предела: 201 знаков при пределе 200")]


def test_citation_does_not_count_towards_item_length():
    item = "- " + "а" * 200 + " (#1210, some-long-fragment-name)"
    assert "пункт длиннее" not in _msgs(GOOD.replace("- нет", item))


def test_continuation_line_belongs_to_its_item():
    item = "- " + "а" * 150 + "\n  " + "б" * 100 + " (#1)"
    assert "пункт длиннее предела: 251" in _msgs(GOOD.replace("- нет", item))


# ── пустые фразы ────────────────────────────────────────────────────────────────────────────────

def test_banned_phrase_is_found_case_insensitively():
    text = GOOD.replace("Кит теперь", "Исправлены ошибки и улучшена стабильность. Кит теперь")
    assert "пустая фраза" in _msgs(text)


def test_text_without_banned_phrase_passes():
    assert "пустая фраза" not in _msgs(GOOD)


# ── жаргон ──────────────────────────────────────────────────────────────────────────────────────

def test_glossary_term_is_jargon():
    assert "gate" in _msgs(GOOD.replace("Кит теперь", "Новый gate: кит теперь"))


def test_glossary_term_inside_backticks_is_still_jargon():
    assert "write_scope" in _msgs(GOOD.replace("Кит теперь", "Поле `write_scope` и кит теперь"))


def test_glossary_term_is_case_insensitive():
    assert "coverage" in _msgs(GOOD.replace("Кит теперь", "Coverage вырос, кит теперь"))


def test_glossary_matches_whole_words_only():
    assert "внутренний язык" not in _msgs(GOOD.replace("Кит теперь", "Через gateway кит теперь"))


def test_lint_rule_code_is_jargon():
    assert "PLC2401" in _msgs(GOOD.replace("Кит теперь", "Правило `PLC2401` включено; кит теперь"))


def test_plain_russian_is_not_jargon():
    assert vr.jargon_hits("Кит сам проверяет описание выпуска.", _rules()) == []


def test_jargon_patterns_are_configurable_from_policy():
    text = GOOD.replace("Кит теперь", "Новое правило PLC2401, кит теперь")
    assert "PLC2401" not in _msgs(text, jargon_patterns=[r"\bnever-matches\b"])


# ── ссылка на источник ──────────────────────────────────────────────────────────────────────────

def test_item_without_citation_is_a_finding():
    text = GOOD.replace(" (#1210)", "")
    assert "не ссылается на источник" in _msgs(text)


def test_fragment_name_is_a_valid_citation():
    text = GOOD.replace("(#1210)", "(lint-profile-per-stack.feat)")
    assert "не ссылается" not in _msgs(text)


def test_several_sources_in_one_citation():
    text = GOOD.replace("(#1210)", "(#1183, kit-identifier-baseline)")
    assert "не ссылается" not in _msgs(text)


def test_single_word_in_parentheses_is_not_a_citation():
    text = GOOD.replace("(#1210)", "(prettier)")
    assert "не ссылается" in _msgs(text)


def test_headline_items_are_exempt_from_citation():
    text = GOOD.replace("Кит теперь сам проверяет", "- Кит теперь сам проверяет")
    assert "не ссылается" not in _msgs(text)


def test_citation_not_required_when_policy_says_so():
    text = GOOD.replace(" (#1210)", "")
    assert "не ссылается" not in _msgs(text, every_item_cites_source=False)


def test_citation_pattern_is_configurable_from_policy():
    text = GOOD.replace("(#1210)", "(ISSUE-7)")
    assert "не ссылается" not in _msgs(text, citation_pattern=r"ISSUE-\d+|#\d+|[a-z-]+")


# ── строгость: кит строго, дочка советует ───────────────────────────────────────────────────────

BAD = GOOD.replace(" (#1210)", "")


def _run(tmp_path, text, *extra):
    doc = tmp_path / "notes.md"
    doc.write_text(text, encoding="utf-8")
    return vr.main(["--layer-a", str(doc), "--policy", str(_write_policy(tmp_path, _policy())), *extra])


def _as_child(monkeypatch, tmp_path):
    managed = tmp_path / "child" / ".ai" / "managed"
    managed.mkdir(parents=True)
    monkeypatch.setattr(vr, "PKG", managed)


def test_kit_is_strict_by_default(tmp_path, capsys):
    assert _run(tmp_path, BAD) == 1
    assert "notes.md:9 — пункт не ссылается" in capsys.readouterr().out


def test_clean_document_is_green_in_strict_mode(tmp_path):
    assert _run(tmp_path, GOOD) == 0


def test_child_is_advisory_by_default(monkeypatch, tmp_path, capsys):
    _as_child(monkeypatch, tmp_path)
    assert _run(tmp_path, BAD) == 0
    out = capsys.readouterr().out
    assert "не ссылается" in out and "совет" in out


def test_child_strict_flag_makes_findings_fail(monkeypatch, tmp_path):
    _as_child(monkeypatch, tmp_path)
    assert _run(tmp_path, BAD, "--strict") == 1


def test_missing_file_is_unknown_not_violation_in_child(monkeypatch, tmp_path, capsys):
    _as_child(monkeypatch, tmp_path)
    policy = _write_policy(tmp_path, _policy())
    assert vr.main(["--layer-a", str(tmp_path / "absent.md"), "--policy", str(policy)]) == 0
    assert "неизвестно" in capsys.readouterr().out


def test_missing_file_in_strict_mode_is_not_executed(tmp_path, capsys):
    policy = _write_policy(tmp_path, _policy())
    assert vr.main(["--layer-a", str(tmp_path / "absent.md"), "--policy", str(policy)]) == 2
    assert "неизвестно" in capsys.readouterr().out


# ── замер фрагментов: предупреждает, не падает ──────────────────────────────────────────────────

def _fragments(tmp_path, texts: dict) -> Path:
    d = tmp_path / "newsfragments"
    d.mkdir()
    (d / "README.md").write_text("как писать фрагмент " * 50, encoding="utf-8")
    for name, text in texts.items():
        (d / name).write_text(text, encoding="utf-8")
    return d


def test_fragment_measure_counts_median_max_and_over_limit(tmp_path):
    d = _fragments(tmp_path, {"a.feat.md": "а" * 100, "b.fix.md": "б" * 300, "c.chore.md": "в" * 500})
    m = vr.measure_fragments(d, _rules())
    assert (m["count"], m["median"], m["max"], len(m["over"])) == (3, 300, 500, 2)


def test_fragment_measure_finds_jargon(tmp_path):
    d = _fragments(tmp_path, {"a.quality.md": "Включено правило PLC2401 и gate."})
    assert vr.measure_fragments(d, _rules())["jargon"] == [("a.quality.md", ["gate", "PLC2401"])]


def test_fragments_mode_never_fails_on_long_fragments(tmp_path, capsys):
    d = _fragments(tmp_path, {"a.feat.md": "а" * 2000})
    assert vr.main(["--fragments", str(d), "--policy", str(_write_policy(tmp_path, _policy()))]) == 0
    assert "Длиннее 200 знаков: 1 из 1" in capsys.readouterr().out


def test_fragments_mode_without_rules_still_measures_and_exits_0(tmp_path, capsys):
    policy = _policy()
    del policy["release_notes"]
    d = _fragments(tmp_path, {"a.feat.md": "а" * 50})
    assert vr.main(["--fragments", str(d), "--policy", str(_write_policy(tmp_path, policy))]) == 0
    out = capsys.readouterr().out
    assert "не объявлены" in out and "Записей: 1" in out


def test_fragments_mode_missing_dir_is_unknown(tmp_path, capsys):
    assert vr.main(["--fragments", str(tmp_path / "none")]) == 0
    assert "неизвестно" in capsys.readouterr().out


# ── настоящие данные кита ───────────────────────────────────────────────────────────────────────

def test_real_newsfragments_queue_is_measured_and_never_fails(tmp_path, capsys):
    real = KIT / "newsfragments"
    expected = len([p for p in real.glob("*.md") if p.name != "README.md"])
    policy = _write_policy(tmp_path, _policy())
    assert vr.main(["--fragments", str(real), "--policy", str(policy)]) == 0
    out = capsys.readouterr().out
    assert (f"Записей: {expected};" in out) if expected else ("Записей нет" in out)


def _changelog_section(version: str) -> str:
    text = (KIT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## \[{re.escape(version)}\].*?(?=^## \[)", text, re.S | re.M)
    assert m, f"в CHANGELOG нет раздела [{version}]"
    return m.group(0)


def test_real_changelog_4_8_0_is_flagged_as_engineering_log(tmp_path, capsys):
    """Раздел [4.8.0] — известный журнал: PLC2401 в тексте, пункты по 400–1000 знаков, блоков нет."""
    doc = tmp_path / "4.8.0.md"
    doc.write_text(_changelog_section("4.8.0"), encoding="utf-8")
    code = vr.main(["--layer-a", str(doc), "--policy", str(_write_policy(tmp_path, _policy()))])
    out = capsys.readouterr().out
    assert code == 1
    assert re.search(r"4\.8\.0\.md:\d+ — внутренний язык в тексте для людей: .*PLC2401", out)
    assert "нет обязательного раздела «Известные ограничения»" in out
    assert "пункт длиннее предела" in out
