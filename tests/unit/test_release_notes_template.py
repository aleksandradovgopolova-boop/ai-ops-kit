# -*- coding: utf-8 -*-
"""Описание выпуска — сообщение человеку: правила данными и шаблон по ним (#1210).

Работа `release-notes-template-rules-and-agent`. Правила слоя А живут в
`registry/communication-policy.yaml -> release_notes`; шаблон `templates/release/ReleaseNotes.md`
обязан нести КАЖДЫЙ блок из `block_titles` в объявленном порядке, а его примеры — сами соблюдать
правила: шаблон, который нарушает собственные пределы, учит нарушать.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
POLICY = KIT / "registry" / "communication-policy.yaml"
TEMPLATE = KIT / "templates" / "release" / "ReleaseNotes.md"
OLD_TEMPLATE = KIT / "templates" / "documentation" / "ReleaseNotes.md"
AGENT = KIT / "agents" / "delivery" / "release-manager.md"

CONTRACT_BLOCKS = ("headline", "whats_in", "behaviour_changes", "who_is_affected",
                   "known_limits", "after_release", "details")
REQUIRED_BLOCKS = ("headline", "whats_in", "known_limits", "after_release", "details")

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def policy():
    return yaml.safe_load(POLICY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rn(policy):
    section = policy.get("release_notes")
    assert isinstance(section, dict), "в communication-policy нет раздела release_notes"
    return section


@pytest.fixture(scope="module")
def template():
    assert TEMPLATE.is_file(), f"нет шаблона {TEMPLATE.relative_to(KIT)}"
    return TEMPLATE.read_text(encoding="utf-8")


_CITATION = re.compile(r"\s*\((?:#\d+|[a-z0-9.-]+)(?:,\s*(?:#\d+|[a-z0-9.-]+))*\)\s*$")


def _examples(text):
    """Заполненные примеры шаблона без метки источника и разметки."""
    out = []
    for m in re.finditer(r"(?m)^> Пример: (.*)$", text):
        out.append(_CITATION.sub("", m.group(1)).replace("**", "").strip())
    return out


# ─── правила: раздел и поля контракта ──────────────────────────────────────────────────────────

def test_layer_a_limits_are_declared(rn):
    la = rn["layer_a"]
    assert la["max_words"] == 250
    assert la["max_item_chars"] == 200


def test_required_blocks_match_contract(rn):
    assert tuple(rn["layer_a"]["required_blocks"]) == REQUIRED_BLOCKS


def test_block_order_is_the_contract_order(rn):
    assert tuple(rn["layer_a"]["block_order"]) == CONTRACT_BLOCKS


def test_block_titles_follow_block_order(rn):
    la = rn["layer_a"]
    assert tuple(la["block_titles"]) == tuple(la["block_order"])
    assert all(isinstance(t, str) and t.strip() for t in la["block_titles"].values())


def test_required_blocks_are_titled(rn):
    la = rn["layer_a"]
    assert set(la["required_blocks"]) <= set(la["block_titles"])


def test_banned_phrases_are_nonempty_russian(rn):
    phrases = rn["banned_phrases"]
    assert phrases, "banned_phrases пуст"
    assert all(re.search(r"[а-яё]", p) for p in phrases)
    assert "исправлены ошибки и улучшена стабильность" in phrases


def test_jargon_reuses_existing_glossary(rn, policy):
    assert rn["jargon_source"] == "product_glossary"
    assert isinstance(policy.get(rn["jargon_source"]), dict) and policy[rn["jargon_source"]]


def test_tone_is_subordinate_to_never_hide_degradation(rn, policy):
    tone = rn["tone"]
    rule_ids = {r.get("id") for r in policy.get("rules") or []}
    assert tone["subordinate_to"] == "never-hide-degradation"
    assert tone["subordinate_to"] in rule_ids
    assert tone["rules"]


def test_every_item_cites_source(rn):
    assert rn["every_item_cites_source"] is True
    assert "#PR" in rn["source_marker"]
    assert set(rn["layer_a"]["citation_exempt_blocks"]) <= set(rn["layer_a"]["block_titles"])


def test_policy_points_at_the_template(rn):
    assert (KIT / rn["template"]).resolve() == TEMPLATE.resolve()


# ─── шаблон: блоки, слои, самопроверка ─────────────────────────────────────────────────────────

def test_template_has_every_block_title(rn, template):
    headings = re.findall(r"(?m)^###\s+(.+?)\s*$", template)
    missing = [t for t in rn["layer_a"]["block_titles"].values() if t not in headings]
    assert not missing, f"в шаблоне нет блоков: {missing}"


def test_template_blocks_in_declared_order(rn, template):
    la = rn["layer_a"]
    positions = [template.index(f"### {la['block_titles'][k]}") for k in la["block_order"]]
    assert positions == sorted(positions)


def test_template_has_both_layers(rn, template):
    assert "## Слой А" in template
    layer_b = [h for h in re.findall(r"(?m)^## (.+)$", template) if h.startswith("Слой Б")]
    assert layer_b and rn["layer_b"]["title"].lower() in layer_b[0].lower()


def test_template_ends_with_self_check(template):
    tail = template.split("## Самопроверка", 1)
    assert len(tail) == 2, "нет раздела самопроверки"
    assert tail[1].count("- [ ]") >= 5


def test_template_every_block_has_example(rn, template):
    la = rn["layer_a"]
    titles = [la["block_titles"][k] for k in la["block_order"] if k != "details"]
    for title, nxt in zip(titles, titles[1:] + [la["block_titles"]["details"]]):
        body = template.split(f"### {title}", 1)[1].split(f"### {nxt}", 1)[0]
        assert "> Пример:" in body, f"у блока «{title}» нет примера"
        assert "Подсказка:" in body, f"у блока «{title}» нет подсказки"


def test_template_examples_cite_source(template):
    lines = re.findall(r"(?m)^> Пример: .*$", template)
    assert lines and all(_CITATION.search(ln) for ln in lines)


def test_template_examples_fit_item_limit(rn, template):
    limit = rn["layer_a"]["max_item_chars"]
    too_long = [e for e in _examples(template) if len(e) > limit]
    assert not too_long, too_long


def test_template_examples_avoid_banned_phrases(rn, template):
    text = " ".join(_examples(template)).lower()
    assert not [p for p in rn["banned_phrases"] if p.lower() in text]


def test_template_examples_avoid_glossary_terms(policy, template):
    text = " ".join(_examples(template))
    hits = [t for t in policy["product_glossary"]
            if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", text, re.IGNORECASE)]
    assert not hits, hits


# ─── ссылки: прежний путь и агент ──────────────────────────────────────────────────────────────

def test_old_template_points_to_new_one(template):
    assert "templates/release/ReleaseNotes.md" in OLD_TEMPLATE.read_text(encoding="utf-8")


def test_release_manager_uses_template_and_policy():
    text = AGENT.read_text(encoding="utf-8")
    assert "templates/release/ReleaseNotes.md" in text
    assert "release_notes" in text


# ─── русский жаргон кита: ловит строгая проверка, а не только глоссарий ─────────────────────────

VALIDATOR = KIT / "ai_ops_kit" / "validation" / "validate_release_notes.py"

CLEAN_LAYER_A = """### Что меняется для вас

Клиенты сами переносят запись, без звонка администратору.

### Что вошло

- Перенос записи самим клиентом. Сделайте: откройте запись → «Перенести». Увидите: свободные окна. (self-reschedule.feat)

### Известные ограничения

- нет

### Что сделать после выпуска

- Через 2 недели посмотрите долю переносов без звонка: цель — 30%. (self-reschedule.feat)

### Подробнее

Полный список изменений — в журнале ниже.
"""


def _strict(tmp_path, text):
    import subprocess
    import sys

    notes = tmp_path / "notes.md"
    notes.write_text(text, encoding="utf-8")
    return subprocess.run([sys.executable, str(VALIDATOR), "--layer-a", str(notes), "--strict",
                           "--policy", str(POLICY)], capture_output=True, text=True, cwd=KIT)


def test_jargon_patterns_keep_builtin_ones(rn):
    import importlib.util

    spec = importlib.util.spec_from_file_location("_vr_probe", VALIDATOR)
    vr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vr)
    pats = rn["layer_a"]["jargon_patterns"]
    assert set(vr.DEFAULT_JARGON_PATTERNS) <= set(pats), "ключ заменяет встроенные шаблоны"


def test_clean_layer_a_passes_strict(tmp_path):
    r = _strict(tmp_path, CLEAN_LAYER_A)
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("word", ["гейт", "Гейты", "ратчет", "towncrier", "allowlist"])
def test_russian_kit_jargon_fails_strict(tmp_path, word):
    text = CLEAN_LAYER_A.replace("Перенос записи самим клиентом.",
                                 f"Перенос записи самим клиентом, {word} пройден.")
    r = _strict(tmp_path, text)
    assert r.returncode == 1, r.stdout + r.stderr
    assert word in r.stdout + r.stderr
