"""Описание выпуска — сообщение человеку, а не инженерный журнал (#1210).

ПОВОД. Раздел CHANGELOG выпуска — журнал для инженеров: `release.yml` копировал его в GitHub Release
целиком, вместе со «Служебным» (план, история), а PR обновления дочки прятал «что нового» в свёрнутый
JSON, и то одними заголовками. «Честно: что ещё не сделано» в 4.8.0 вставили руками — механизма не
было. Теперь `release_bump` собирает СЛОЙ ВЛАДЕЛЬЦА (слой A) между маркерами в начале раздела,
ограничения берёт из фрагментов типа `limit`, проверяет слой той же функцией, что
`validate_release_notes --layer-a --strict`, а Release и PR обновления показывают именно его.

Тесты держат и положительные, и отказные ветки: без `--owner-notes` выпуск не собирается; замечание
проверки или отсутствие правил — отказ до записи файлов; маркеров нет — извлечение не выдумывает слой,
а отдаёт прежнее; сбой описания — «НЕ УДАЛОСЬ», а не «ничего».
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KIT))

from ai_ops_kit.devtools import release_bump as rb  # noqa: E402
from ai_ops_kit.validation import validate_release_notes as vr  # noqa: E402

pytestmark = pytest.mark.unit

HEADLINE = "Кит теперь сам пишет, что меняется для вас, и честно называет, чего ещё нет."

# Правила слоя A по договору #1210 (форма `registry/communication-policy.yaml -> release_notes`) —
# поверх НАСТОЯЩЕЙ политики кита, с её настоящим глоссарием.
TITLES = {"headline": "Что меняется для вас", "whats_in": "Что вошло",
          "behaviour_changes": "Что изменилось в привычном поведении", "who_is_affected": "Кого касается",
          "known_limits": "Известные ограничения", "after_release": "Что сделать после выпуска",
          "details": "Подробнее"}
RELEASE_NOTES = {
    "layer_a": {"max_words": 250, "max_item_chars": 200, "no_version_number": True,
                "required_blocks": ["headline", "whats_in", "known_limits", "after_release", "details"],
                "block_order": list(TITLES), "block_titles": dict(TITLES),
                "citation_exempt_blocks": ["headline", "details"]},
    "banned_phrases": ["исправлены ошибки и улучшена стабильность"],
    "jargon_source": "product_glossary",
    "every_item_cites_source": True,
}


def notes(headline=HEADLINE, whats_in="- Описание выпуска начинается с того, что важно вам (#1210)",
          limits="нет", after="- Через неделю прочитайте описание следующего выпуска (#1210)",
          wrap=True) -> str:
    """Документ слоя А по шаблону `templates/release/ReleaseNotes.md` (с обёрткой «Слой А/Б»)."""
    body = (f"### Что меняется для вас\n\n{headline}\n\n### Что вошло\n\n{whats_in}\n\n"
            f"### Известные ограничения\n\n{limits}\n\n### Что сделать после выпуска\n\n{after}\n\n"
            "### Подробнее\n\nПолный список изменений — раздел этой версии в CHANGELOG.\n")
    if not wrap:
        return body
    return ("# Описание выпуска\n\n<!-- подсказки шаблона -->\n\n## Слой А — для владельца и "
            f"пользователей\n\n{body}\n## Слой Б — полный журнал изменений\n\n- технический пункт\n\n"
            "## Самопроверка перед публикацией\n\n- [ ] пункт\n")


def _policy_text(release_notes) -> str:
    base = yaml.safe_load((KIT / "registry" / "communication-policy.yaml").read_text(encoding="utf-8"))
    base.pop("release_notes", None)
    if release_notes is not None:
        base["release_notes"] = release_notes
    return yaml.safe_dump(base, allow_unicode=True, sort_keys=False)


def _repo(root: Path, ver="1.2.3", towncrier=False, release_notes=RELEASE_NOTES) -> Path:
    """Репозиторий со всеми версионными поверхностями и правилами описания выпуска в реестре;
    `towncrier=True` — с конфигом и маркером; `release_notes=None` — правил в реестре нет."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "VERSION").write_text(f"{ver}\n", encoding="utf-8")
    (root / "manifest").mkdir()
    (root / "manifest" / "ai-ops-manifest.yaml").write_text(
        f"ai_ops:\n  package_version: {ver}\n", encoding="utf-8")
    (root / "registry").mkdir()
    (root / "registry" / "release-claims.yaml").write_text(
        f"version: {ver}\nchannel: qualification\n", encoding="utf-8")
    (root / "registry" / "release-notes.yaml").write_text(f"version: {ver}\n", encoding="utf-8")
    (root / "registry" / "communication-policy.yaml").write_text(_policy_text(release_notes),
                                                                 encoding="utf-8")
    (root / "README.md").write_text(f"**v{ver} qualification**\n", encoding="utf-8")
    (root / "ROADMAP.md").write_text(f"**v{ver} qualification**\n", encoding="utf-8")
    marker = f"\n{rb._TOWNCRIER_MARKER}\n" if towncrier else ""
    (root / "CHANGELOG.md").write_text(
        f"# CHANGELOG\n\n## [Unreleased]\n{marker}\n## [{ver}] — 2026-01-01 · старое\n\nбыло\n",
        encoding="utf-8")
    (root / "newsfragments").mkdir()
    (root / "newsfragments" / "README.md").write_text("как называть\n", encoding="utf-8")
    if towncrier:
        types = "".join(f'[[tool.towncrier.type]]\ndirectory = "{d}"\nname = "{n}"\nshowcontent = true\n'
                        for d, n in (("feat", "Новое"), ("limit", "Известные ограничения"),
                                     ("chore", "Служебное")))
        (root / "pyproject.toml").write_text(
            '[tool.towncrier]\ndirectory = "newsfragments"\nfilename = "CHANGELOG.md"\n'
            'title_format = "## [{version}] — {project_date}"\nissue_format = "{issue}"\n' + types,
            encoding="utf-8")
    return root


def _frag(root: Path, name: str, text: str) -> None:
    (root / "newsfragments" / name).write_text(text + "\n", encoding="utf-8")


def _section(root: Path, ver: str) -> str:
    return rb.version_section((root / "CHANGELOG.md").read_text(encoding="utf-8"), ver)


def _layer(root: Path, ver: str = "1.2.4") -> str:
    return rb.owner_layer((root / "CHANGELOG.md").read_text(encoding="utf-8"), ver) or ""


def _block(layer: str, title: str) -> str:
    """Тело раздела `#### <title>` слоя A — до следующего заголовка."""
    return layer.split(f"#### {title}", 1)[1].split("\n####", 1)[0].strip()


def _bump(root: Path, text: str | None = None, **kw):
    return rb.bump(root, "1.2.4", title="t", date="2026-09-29",
                   owner_notes=notes() if text is None else text, **kw)


def _cli(root: Path, tmp_path: Path, text: str | None):
    args = ["x", "1.2.4", "--title", "t", "--date", "2026-09-29", "--root", str(root)]
    if text is not None:
        f = tmp_path / "notes.md"
        f.write_text(text, encoding="utf-8")
        args += ["--owner-notes", str(f)]
    return rb.main(args)


# ── CLI: без описания выпуска для владельца выпуск не собирается ────────────────────────────────

def test_cli_bump_without_owner_notes_fails_and_changes_nothing(tmp_path, capsys):
    root = _repo(tmp_path / "r")
    before = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert _cli(root, tmp_path, None) == 1
    assert "--owner-notes" in capsys.readouterr().out
    assert rb.current_version(root) == "1.2.3", "без описания выпуска версия всё равно поднялась"
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == before


def test_cli_bump_with_owner_notes_writes_the_owner_layer(tmp_path):
    root = _repo(tmp_path / "r")
    assert _cli(root, tmp_path, notes()) == 0
    assert HEADLINE in _layer(root)


def test_cli_check_still_works_without_owner_notes(tmp_path):
    root = _repo(tmp_path / "r")
    assert rb.main(["x", "--check", "--root", str(root)]) == 0


def test_only_layer_a_of_the_template_goes_into_the_changelog(tmp_path):
    root = _repo(tmp_path / "r")
    _bump(root)
    layer = _layer(root)
    assert "технический пункт" not in layer and "Самопроверка" not in layer, "в слой A попал слой Б"
    assert "подсказки шаблона" not in layer and "Слой А" not in layer
    unwrapped = _repo(tmp_path / "u")
    _bump(unwrapped, notes(wrap=False))
    assert _layer(unwrapped) == layer, "документ без обёртки «Слой А» разобран иначе"


@pytest.mark.parametrize("headline, why", [
    ("Первый абзац.\n\nВторой абзац.", "ОДНИМ абзацем"),
    ("В версии 4.9.0 кит стал лучше.", "номера версии"),
])
def test_bad_headline_is_refused_before_any_write(tmp_path, headline, why):
    root = _repo(tmp_path / "r")
    with pytest.raises(ValueError, match=why):
        _bump(root, notes(headline=headline))
    assert rb.current_version(root) == "1.2.3", "отказ после записи — версия уже поднята"


def test_unfilled_template_is_refused(tmp_path):
    root = _repo(tmp_path / "r")
    with pytest.raises(ValueError, match="незаполненный шаблон"):
        _bump(root, notes(headline="<Главное изменение выпуска и что оно даёт владельцу.>"))
    with pytest.raises(ValueError, match="незаполненный шаблон"):
        _bump(root, notes() + "\n> Пример: Клиенты сами переносят запись.\n")


# ── строгая проверка слоя A на бампе: те же правила, что validate_release_notes ──────────────────

def test_clean_owner_layer_passes_the_release_notes_check(tmp_path):
    root = _repo(tmp_path / "r")
    _frag(root, "hook-lint.limit.md", "Проверка стиля при правке пока работает только для Python.")
    _bump(root)
    rules = vr.rules_from(yaml.safe_load(
        (root / "registry" / "communication-policy.yaml").read_text(encoding="utf-8")))
    assert vr.check_layer_a(_layer(root), rules) == [], "собранный слой не проходит свою же проверку"


def test_jargon_in_headline_refuses_the_bump(tmp_path, capsys):
    root = _repo(tmp_path / "r")
    rc = _cli(root, tmp_path, notes(headline="Каждый gate теперь сверяет tested_revision."))
    out = capsys.readouterr().out
    assert rc == 1 and "внутренний язык" in out and "gate" in out, out
    assert rb.current_version(root) == "1.2.3", "отказ проверки после записи — версия уже поднята"


def test_overlong_limit_item_refuses_the_bump(tmp_path):
    root = _repo(tmp_path / "r")
    _frag(root, "long-limit.limit.md", "ограничение " * 30)
    with pytest.raises(ValueError, match="пункт длиннее предела"):
        _bump(root)
    assert rb.current_version(root) == "1.2.3"


def test_owner_layer_over_word_limit_is_refused(tmp_path):
    root = _repo(tmp_path / "r")
    with pytest.raises(ValueError, match="длиннее предела"):
        _bump(root, notes(headline="слово " * 260))
    assert rb.current_version(root) == "1.2.3"


def test_missing_required_block_refuses_the_bump(tmp_path):
    root = _repo(tmp_path / "r")
    text = notes().replace("### Что вошло", "### Посторонний раздел")
    with pytest.raises(ValueError, match="Что вошло"):
        _bump(root, text)


def test_item_without_source_refuses_the_bump(tmp_path):
    root = _repo(tmp_path / "r")
    with pytest.raises(ValueError, match="источник"):
        _bump(root, notes(whats_in="- Описание выпуска начинается с главного"))


def test_missing_rules_refuse_the_bump(tmp_path):
    """«Не проверено» не равно «прошло»: без правил в реестре выпуск кита не собирается."""
    root = _repo(tmp_path / "r", release_notes=None)
    with pytest.raises(ValueError, match="проверить не по чему"):
        _bump(root)
    assert rb.current_version(root) == "1.2.3"


# ── слой A в разделе: маркеры, порядок, ограничения ─────────────────────────────────────────────

def test_owner_layer_sits_between_markers_right_under_the_header(tmp_path):
    root = _repo(tmp_path / "r")
    rb.bump(root, "1.2.4", title="Заголовок", date="2026-09-29", body="- инженерный пункт",
            owner_notes=notes())
    sec = _section(root, "1.2.4")
    lines = sec.splitlines()
    assert lines[0] == "## [1.2.4] — 2026-09-29 · Заголовок"
    assert lines[2] == rb.OWNER_START, "слой A не стоит сразу под шапкой раздела"
    assert sec.index(rb.OWNER_END) < sec.index("- инженерный пункт"), "слой B оказался внутри слоя A"
    layer = _layer(root)
    got = [ln[5:] for ln in layer.splitlines() if ln.startswith("#### ")]
    assert got == ["Что меняется для вас", "Что вошло", "Известные ограничения",
                   "Что сделать после выпуска", "Подробнее"], "блоки не в порядке реестра"
    assert rb.owner_layer((root / "CHANGELOG.md").read_text(encoding="utf-8"), "1.2.3") is None


def test_block_titles_and_order_come_from_the_policy(tmp_path):
    rn = copy.deepcopy(RELEASE_NOTES)
    rn["layer_a"]["block_titles"]["whats_in"] = "Что нового"
    rn["layer_a"]["block_order"] = ["headline", "known_limits", "whats_in", "after_release", "details"]
    root = _repo(tmp_path / "r", release_notes=rn)
    _bump(root, notes().replace("### Что вошло", "### Что нового"))
    got = [ln[5:] for ln in _layer(root).splitlines() if ln.startswith("#### ")]
    assert got[1:3] == ["Известные ограничения", "Что нового"], got


def test_explicit_no_limits_stays_no(tmp_path):
    root = _repo(tmp_path / "r")
    _bump(root)
    assert _block(_layer(root), "Известные ограничения") == "нет"


def test_limit_fragments_replace_no_and_carry_their_source(tmp_path):
    root = _repo(tmp_path / "r")
    _frag(root, "hook-lint.limit.md", "Хук при правке пока\nне гоняет профиль линтера.")
    _frag(root, "other.feat.md", "Новая возможность, не ограничение.")
    _bump(root)
    body = _block(_layer(root), "Известные ограничения")
    assert body == "- Хук при правке пока не гоняет профиль линтера. (hook-lint.limit)", body


def test_limit_already_listed_by_the_author_is_not_duplicated(tmp_path):
    root = _repo(tmp_path / "r")
    _frag(root, "hook-lint.limit.md", "Хук пока не гоняет профиль.")
    _frag(root, "ci-only.limit.md", "Проверка в CI дочки пока только для Python.")
    _bump(root, notes(limits="- Хук при правке пока только для Python. (hook-lint.limit)"))
    body = _block(_layer(root), "Известные ограничения")
    assert body.count("(hook-lint.limit)") == 1, body
    assert "- Проверка в CI дочки пока только для Python. (ci-only.limit)" in body


def test_towncrier_drain_keeps_layer_a_on_top_and_limits_in_layer_b(tmp_path):
    """Настоящая сборка towncrier: слой A сверху, фрагменты — в полный журнал, тип `limit` известен."""
    pytest.importorskip("towncrier", reason="towncrier не установлен — сборка проверяется в CI")
    root = _repo(tmp_path / "r", towncrier=True)
    _frag(root, "x.feat.md", "Новая штука.")
    _frag(root, "python-only.limit.md", "Штука пока только для Python.")
    _bump(root)
    sec = _section(root, "1.2.4")
    assert sec.splitlines()[2] == rb.OWNER_START
    layer_b = sec.split(rb.OWNER_END, 1)[1]
    assert "### Известные ограничения" in layer_b and "Штука пока только для Python." in layer_b
    assert "- Штука пока только для Python. (python-only.limit)" in _layer(root)
    assert [p.name for p in (root / "newsfragments").iterdir()] == ["README.md"]


def test_kit_towncrier_config_declares_the_limit_type():
    text = (KIT / "pyproject.toml").read_text(encoding="utf-8")
    types = re.findall(r'\[\[tool\.towncrier\.type\]\]\s*\ndirectory = "([^"]+)"\nname = "([^"]+)"', text)
    assert ("limit", "Известные ограничения") in types, types
    order = [d for d, _ in types]
    assert order.index("limit") < order.index("chore"), "ограничения стоят после «Служебного»"


# ── тело GitHub Release: слой A + ссылка; без маркеров — как раньше ─────────────────────────────

_WITH = (f"# C\n\n## [2.0.0] — 2026-09-29 · новое\n\n{rb.OWNER_START}\n**Что меняется для вас.** Смысл."
         f"\n{rb.OWNER_END}\n\n### Служебное\n\n- план и история\n\n## [1.0.0] — 2026-01-01 · старое\n\n"
         "### Новое\n\n- старый пункт\n")


def test_release_body_is_owner_layer_plus_link_not_the_journal():
    body = rb.release_body(_WITH, "2.0.0", "https://example.test/CHANGELOG.md")
    assert body.startswith("**Что меняется для вас.** Смысл.")
    assert "(https://example.test/CHANGELOG.md)" in body
    assert "Служебное" not in body and "план и история" not in body
    assert rb.OWNER_START not in body


def test_release_body_without_markers_falls_back_to_the_whole_section():
    body = rb.release_body(_WITH, "1.0.0", "https://example.test/CHANGELOG.md")
    assert body == "## [1.0.0] — 2026-01-01 · старое\n\n### Новое\n\n- старый пункт"


def test_release_body_for_missing_version_is_empty():
    assert rb.release_body(_WITH, "3.0.0") == ""


def test_cli_release_notes_prints_body_and_empty_for_missing_version(tmp_path, capsys):
    """Раздела нет — пустой вывод с причиной в stderr: отказывает ОДНА строка release.yml."""
    (tmp_path / "CHANGELOG.md").write_text(_WITH, encoding="utf-8")
    assert rb.main(["x", "--release-notes", "2.0.0", "--root", str(tmp_path)]) == 0
    assert "Смысл." in capsys.readouterr().out
    assert rb.main(["x", "--release-notes", "3.0.0", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr()
    assert out.out == "" and "[3.0.0]" in out.err


def test_release_step_refusal_line_is_unique_for_the_mutation_probe():
    """Проба `release-refuses-without-changelog-section` мутирует строку `exit 1` шага выпуска:
    вторая такая строка сделала бы мутацию неоднозначной, а отказ — недоказанным."""
    text = (KIT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert text.count("            exit 1") == 1


def _release_step():
    wf = yaml.safe_load((KIT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))
    return next(s for s in wf["jobs"]["release"]["steps"] if "gh release create" in str(s.get("run")))


def test_release_workflow_builds_the_body_through_release_notes():
    run = _release_step()["run"]
    assert "ai_ops_kit.devtools.release_bump --release-notes" in run
    assert "--notes-file /tmp/notes.md" in run
    assert "awk" not in run, "раздел по-прежнему копируется целиком awk-ом"


def test_release_workflow_interpolates_nothing_into_shell():
    run = _release_step()["run"]
    assert "${{" not in run, "значение подставляется выражением прямо в shell"
    assert {"VERSION", "TAG", "HEAD_SHA"} <= set(_release_step()["env"])


# ── PR обновления дочки: слой A каждой версии текстом ───────────────────────────────────────────

def test_whats_new_shows_layer_a_and_names_versions_without_it():
    data = rb.whats_new("0.9.0", "2.0.0", text=_WITH)
    assert data["status"] == "ok"
    assert [(v["version"], v["owner_layer"]) for v in data["versions"]] == [("2.0.0", True),
                                                                           ("1.0.0", False)]
    assert "**Что меняется для вас.** Смысл." in data["text"]
    assert "### 1.0.0 — старое" in data["text"] and "Описания для владельца у этой версии нет" in data["text"]
    assert "план и история" not in data["text"] and "старый пункт" not in data["text"]


def test_whats_new_caps_versions_and_length():
    sections = "".join(f"## [1.0.{i}] — 2026-01-01 · v{i}\n\n{rb.OWNER_START}\n{'длинно ' * 400}\n"
                       f"{rb.OWNER_END}\n\n" for i in range(9, 0, -1))
    data = rb.whats_new("1.0.0", "1.0.9", text="# C\n\n" + sections, max_versions=3, max_chars=100)
    assert len(data["versions"]) == 3
    assert "ещё версий: 6" in data["text"]
    assert data["text"].count("обрезано") == 3


def test_whats_new_between_nothing_is_said_not_silent():
    data = rb.whats_new("2.0.0", "2.0.0", text=_WITH)
    assert data["status"] == "empty" and "назвать изменения не могу" in data["text"]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, KIT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def update_ops():
    _load("_inst_1210_hub", "installer/ai_ops.py")
    return _load("_update_ops_1210", "installer/update_ops.py")


def test_update_report_whats_new_reads_the_kit_changelog(update_ops):
    data = update_ops._whats_new("0.0.1", rb.current_version(KIT))
    assert data["status"] == "ok" and data["text"].startswith("Что нового для вас")
    json.dumps(data, ensure_ascii=False)


def test_update_report_whats_new_failure_is_not_nothing(update_ops, monkeypatch):
    def boom(*_a, **_k):
        raise OSError("нет CHANGELOG")
    monkeypatch.setattr(rb, "whats_new", boom)
    data = update_ops._whats_new("1.0.0", "2.0.0")
    assert data["status"] == "failed" and "НЕ УДАЛОСЬ" in data["text"]


def _pr_step():
    doc = yaml.safe_load((KIT / "templates" / "ci" / "ai-ops-update.yml").read_text(encoding="utf-8"))
    return next(s for s in doc["jobs"]["update"]["steps"] if s.get("name") == "Открыть PR с обновлением")


def _run_pr_step(tmp_path, report):
    """Настоящий прогон шага: `git`/`gh` — заглушки, тело PR перехватывается при `gh pr create`."""
    work, stubs = tmp_path / "work", tmp_path / "bin"
    stubs.mkdir()
    (work / ".ai" / "runtime").mkdir(parents=True)
    (work / ".ai" / "runtime" / "last-update-report.json").write_text(
        json.dumps(report, ensure_ascii=False), encoding="utf-8")
    (stubs / "git").write_text('#!/bin/sh\n[ "$1" = diff ] && exit 1\n'
                               '[ "$1" = status ] && echo " M x"\nexit 0\n', encoding="utf-8")
    (stubs / "gh").write_text('#!/bin/sh\n[ "$2" = list ] && { echo 0; exit 0; }\n'
                              'while [ $# -gt 0 ]; do [ "$1" = --body-file ] && cp "$2" "$BODY_OUT"; '
                              'shift; done\n', encoding="utf-8")
    for s in stubs.iterdir():
        s.chmod(0o755)
    body_out = tmp_path / "body.md"
    script = _pr_step()["run"].replace("/tmp/pr-body.md", str(tmp_path / "pr-body.md"))
    env = {**os.environ, "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}", "BODY_OUT": str(body_out),
           "HAS_PAT": "false", "TO": "2.0.0", "FROM": "0.9.0", "GH_TOKEN": "x"}
    r = subprocess.run(["bash", "-e", "-c", script], cwd=work, env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    return body_out.read_text(encoding="utf-8"), work


@pytest.mark.skipif(not shutil.which("bash"), reason="нужен bash")
def test_update_pr_body_shows_layer_a_as_text_before_the_json(tmp_path):
    evil = "Смысл $(touch PWNED1) `touch PWNED2`"
    data = rb.whats_new("0.9.0", "2.0.0", text=_WITH.replace("Смысл.", evil))
    body, work = _run_pr_step(tmp_path, {"whats_new": data})
    assert "**Что меняется для вас.** " + evil in body, "слой A не дошёл до тела PR буквально"
    assert "Описания для владельца у этой версии нет" in body
    assert body.index("Что нового для вас") < body.index("```json"), "слой A спрятан внутри JSON"
    assert not [f for f in work.iterdir() if f.name.startswith("PWNED")], "текст отчёта исполнился"


@pytest.mark.skipif(not shutil.which("bash"), reason="нужен bash")
def test_update_pr_body_without_whats_new_says_it_failed(tmp_path):
    body, _ = _run_pr_step(tmp_path, {"status": "ok"})          # отчёт прежнего кита
    assert "прочитать описание выпусков НЕ УДАЛОСЬ" in body


def test_update_pr_step_reads_whats_new_from_the_report_file_only():
    step = _pr_step()
    assert "whats_new" not in json.dumps(step.get("env") or {})
    lines = [ln for ln in step["run"].splitlines() if "whats_new" in ln]
    assert lines, "шаг PR не читает слой A из отчёта вовсе"
    for line in lines:
        assert "${{" not in line and "$(" not in line, line


@pytest.mark.skipif(not shutil.which("bash"), reason="нужен bash")
def test_release_step_really_publishes_only_the_owner_layer(tmp_path):
    """Настоящий прогон шага release.yml до `gh release create`: в записки идёт слой A и ссылка."""
    run = _release_step()["run"]
    script = run[:run.index("PRERELEASE=")].replace("/tmp/notes.md", str(tmp_path / "notes.md"))
    (tmp_path / "CHANGELOG.md").write_text(_WITH, encoding="utf-8")
    env = {**os.environ, "VERSION": "2.0.0", "TAG": "v2.0.0", "PYTHONPATH": str(KIT),
           "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r"}
    r = subprocess.run(["bash", "-e", "-c", script], cwd=tmp_path, env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    notes = (tmp_path / "notes.md").read_text(encoding="utf-8")
    assert notes.startswith("**Что меняется для вас.** Смысл.")
    assert "(https://github.com/o/r/blob/v2.0.0/CHANGELOG.md)" in notes
    assert "план и история" not in notes and "старый пункт" not in notes


# ── гейт на самом выпуске: слой A выпускаемой версии в CHANGELOG кита строго проверен ────────────

def owner_layer_release_findings(root: Path) -> list:
    """Замечания к слою A версии из VERSION в CHANGELOG `root`: ручная правка CHANGELOG после бампа
    мимо проверки не проходит. Нет слоя, нет правил — тоже замечание (строгий режим кита)."""
    ver = rb.current_version(root)
    layer = rb.owner_layer((root / "CHANGELOG.md").read_text(encoding="utf-8"), ver)
    if layer is None:
        return [f"у выпуска {ver} нет слоя владельца между маркерами — соберите его "
                f"`release_bump {ver} --owner-notes <файл>`"]
    try:
        rules = rb.release_rules(root)
    except ValueError as e:
        return [str(e)]
    return rb.check_owner_layer(layer, rules)


def test_release_gate_helper_flags_hand_edited_jargon(tmp_path):
    root = _repo(tmp_path / "r")
    _bump(root)
    assert owner_layer_release_findings(root) == []
    ch = root / "CHANGELOG.md"
    ch.write_text(ch.read_text(encoding="utf-8").replace(HEADLINE, "Каждый gate стал строже."),
                  encoding="utf-8")
    found = owner_layer_release_findings(root)
    assert found and "gate" in found[0], found


def test_release_gate_helper_flags_missing_layer_and_missing_rules(tmp_path):
    root = _repo(tmp_path / "r")
    assert "нет слоя владельца" in owner_layer_release_findings(root)[0]
    _bump(root)
    (root / "registry" / "communication-policy.yaml").write_text(_policy_text(None), encoding="utf-8")
    assert "проверить не по чему" in owner_layer_release_findings(root)[0]


@pytest.mark.release_gate
@pytest.mark.slow
def test_released_version_owner_layer_passes_the_strict_check():
    """Гонится ТОЛЬКО на выпуске (release.yml, `-m release_gate`): слой A версии из VERSION в
    CHANGELOG кита проходит `validate_release_notes` строго — иначе тег не создаётся."""
    found = owner_layer_release_findings(KIT)
    assert not found, "описание выпуска для владельца не прошло проверку:\n  " + "\n  ".join(found)


def test_release_workflow_runs_the_owner_layer_gate_before_the_tag():
    wf = yaml.safe_load((KIT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["release"]["steps"]
    gate = next(i for i, s in enumerate(steps)
                if "test_release_owner_layer.py" in str(s.get("run")) and "-m release_gate" in str(s.get("run")))
    tag = next(i for i, s in enumerate(steps) if "gh release create" in str(s.get("run")))
    assert gate < tag, "проверка слоя владельца стоит после создания тега"
    assert str(steps[gate].get("if")) == "steps.check_release.outputs.needed == 'true'"


def test_kit_own_policy_and_template_titles_build_a_clean_layer(tmp_path):
    """Правила и шаблон кита (#1219) как есть: документ с заголовками шаблона проходит строго."""
    root = _repo(tmp_path / "r")
    shutil.copy(KIT / "registry" / "communication-policy.yaml",
                root / "registry" / "communication-policy.yaml")
    template = (KIT / "templates" / "release" / "ReleaseNotes.md").read_text(encoding="utf-8")
    for title in TITLES.values():
        assert f"### {title}" in template, f"шаблон и названия блоков разошлись: «{title}»"
    _bump(root)
    assert HEADLINE in _layer(root)
