"""Описание выпуска — сообщение человеку, а не инженерный журнал (#1210).

ПОВОД. Раздел CHANGELOG выпуска — журнал для инженеров: `release.yml` копировал его в GitHub Release
целиком, вместе со «Служебным» (план, история), а PR обновления дочки прятал «что нового» в свёрнутый
JSON, и то одними заголовками. «Честно: что ещё не сделано» в 4.8.0 вставили руками — механизма не
было. Теперь `release_bump` собирает СЛОЙ ВЛАДЕЛЬЦА (слой A) между маркерами в начале раздела,
ограничения берёт из фрагментов типа `limit`, а Release и PR обновления показывают именно его.

Тесты держат и положительные, и отказные ветки: без `--headline` выпуск не собирается; маркеров нет —
извлечение не выдумывает слой, а отдаёт прежнее; сбой описания — «НЕ УДАЛОСЬ», а не «ничего».
"""
from __future__ import annotations

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

pytestmark = pytest.mark.unit

HEADLINE = "Кит теперь сам пишет, что меняется для вас, и честно называет, чего ещё нет."


def _repo(root: Path, ver="1.2.3", towncrier=False) -> Path:
    """Репозиторий со всеми версионными поверхностями; `towncrier=True` — с конфигом и маркером."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "VERSION").write_text(f"{ver}\n", encoding="utf-8")
    (root / "manifest").mkdir()
    (root / "manifest" / "ai-ops-manifest.yaml").write_text(
        f"ai_ops:\n  package_version: {ver}\n", encoding="utf-8")
    (root / "registry").mkdir()
    (root / "registry" / "release-claims.yaml").write_text(
        f"version: {ver}\nchannel: qualification\n", encoding="utf-8")
    (root / "registry" / "release-notes.yaml").write_text(f"version: {ver}\n", encoding="utf-8")
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


# ── CLI: без абзаца «что меняется для вас» выпуск не собирается ─────────────────────────────────

def test_cli_bump_without_headline_fails_and_changes_nothing(tmp_path, capsys):
    root = _repo(tmp_path / "r")
    before = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    rc = rb.main(["x", "1.2.4", "--title", "t", "--date", "2026-09-29", "--root", str(root)])
    assert rc == 1
    assert "--headline" in capsys.readouterr().out
    assert rb.current_version(root) == "1.2.3", "без --headline версия всё равно поднялась"
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == before


def test_cli_bump_with_headline_writes_the_owner_layer(tmp_path):
    root = _repo(tmp_path / "r")
    rc = rb.main(["x", "1.2.4", "--title", "t", "--date", "2026-09-29", "--headline", HEADLINE,
                  "--root", str(root)])
    assert rc == 0
    assert HEADLINE in (rb.owner_layer((root / "CHANGELOG.md").read_text(encoding="utf-8"), "1.2.4") or "")


def test_cli_check_still_works_without_headline(tmp_path):
    root = _repo(tmp_path / "r")
    assert rb.main(["x", "--check", "--root", str(root)]) == 0


@pytest.mark.parametrize("bad, why", [
    ("", "пустой"),
    ("Первый абзац.\n\nВторой абзац.", "ОДНИМ абзацем"),
    ("В версии 4.9.0 кит стал лучше.", "без номера версии"),
])
def test_bad_headline_is_refused_before_any_write(tmp_path, bad, why):
    root = _repo(tmp_path / "r")
    with pytest.raises(ValueError) as e:
        rb.bump(root, "1.2.4", title="t", date="2026-09-29", headline=bad)
    if why != "пустой":
        assert why in str(e.value)
    assert rb.current_version(root) == "1.2.3", "отказ после записи — версия уже поднята"


def test_owner_layer_over_word_limit_is_refused(tmp_path):
    root = _repo(tmp_path / "r")
    with pytest.raises(ValueError, match="слов при пределе"):
        rb.bump(root, "1.2.4", title="t", date="2026-09-29", headline="слово " * 260)
    assert rb.current_version(root) == "1.2.3"


def test_too_long_limit_item_is_refused(tmp_path):
    root = _repo(tmp_path / "r")
    _frag(root, "long.limit.md", "ограничение " * 30)
    with pytest.raises(ValueError, match="limit.md"):
        rb.bump(root, "1.2.4", title="t", date="2026-09-29", headline=HEADLINE)


# ── слой A в разделе: маркеры, порядок, ограничения ─────────────────────────────────────────────

def test_owner_layer_sits_between_markers_right_under_the_header(tmp_path):
    root = _repo(tmp_path / "r")
    rb.bump(root, "1.2.4", title="Заголовок", date="2026-09-29", body="- инженерный пункт",
            headline=HEADLINE)
    sec = _section(root, "1.2.4")
    lines = sec.splitlines()
    assert lines[0] == "## [1.2.4] — 2026-09-29 · Заголовок"
    assert lines[2] == rb.OWNER_START, "слой A не стоит сразу под шапкой раздела"
    assert sec.index(rb.OWNER_END) < sec.index("- инженерный пункт"), "слой B оказался внутри слоя A"
    layer = rb.owner_layer((root / "CHANGELOG.md").read_text(encoding="utf-8"), "1.2.4")
    for title in ("Что меняется для вас", "Известные ограничения", "Что дальше", "Подробности"):
        assert f"**{title}" in layer, f"в слое A нет блока «{title}»"
    assert "инженерный пункт" not in layer
    assert rb.owner_layer((root / "CHANGELOG.md").read_text(encoding="utf-8"), "1.2.3") is None


def test_no_limit_fragments_means_explicit_no(tmp_path):
    root = _repo(tmp_path / "r")
    rb.bump(root, "1.2.4", title="t", date="2026-09-29", headline=HEADLINE)
    layer = rb.owner_layer((root / "CHANGELOG.md").read_text(encoding="utf-8"), "1.2.4")
    after = layer.split("**Известные ограничения**", 1)[1].split("**Что дальше", 1)[0]
    assert after.strip().startswith("Нет"), f"пустые ограничения не названы явным «Нет»: {after!r}"


def test_limit_fragments_land_in_known_limits(tmp_path):
    root = _repo(tmp_path / "r")
    _frag(root, "hook.limit.md", "Хук при правке пока\nне гоняет профиль линтера.")
    _frag(root, "other.feat.md", "Новая возможность, не ограничение.")
    rb.bump(root, "1.2.4", title="t", date="2026-09-29", headline=HEADLINE)
    layer = rb.owner_layer((root / "CHANGELOG.md").read_text(encoding="utf-8"), "1.2.4")
    limits = layer.split("**Известные ограничения**", 1)[1].split("**Что дальше", 1)[0]
    assert "- Хук при правке пока не гоняет профиль линтера." in limits
    assert "Новая возможность" not in limits and "Нет" not in limits


def test_after_release_text_is_used_when_given(tmp_path):
    root = _repo(tmp_path / "r")
    rb.bump(root, "1.2.4", title="t", date="2026-09-29", headline=HEADLINE,
            after_release="Перезапустите `ai-ops doctor`.")
    layer = rb.owner_layer((root / "CHANGELOG.md").read_text(encoding="utf-8"), "1.2.4")
    assert "**Что дальше.** Перезапустите `ai-ops doctor`." in layer


def test_towncrier_drain_keeps_layer_a_on_top_and_limits_in_layer_b(tmp_path):
    """Настоящая сборка towncrier: слой A сверху, фрагменты — в полный журнал, тип `limit` известен."""
    pytest.importorskip("towncrier", reason="towncrier не установлен — сборка проверяется в CI")
    root = _repo(tmp_path / "r", towncrier=True)
    _frag(root, "x.feat.md", "Новая штука.")
    _frag(root, "y.limit.md", "Штука пока только для Python.")
    rb.bump(root, "1.2.4", title="t", date="2026-09-29", headline=HEADLINE)
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    sec = rb.version_section(text, "1.2.4")
    assert sec.splitlines()[2] == rb.OWNER_START
    layer_b = sec.split(rb.OWNER_END, 1)[1]
    assert "### Известные ограничения" in layer_b and "Штука пока только для Python." in layer_b
    assert "- Штука пока только для Python." in rb.owner_layer(text, "1.2.4")
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


def test_cli_release_notes_prints_body_and_refuses_missing_version(tmp_path, capsys):
    (tmp_path / "CHANGELOG.md").write_text(_WITH, encoding="utf-8")
    assert rb.main(["x", "--release-notes", "2.0.0", "--root", str(tmp_path)]) == 0
    assert "Смысл." in capsys.readouterr().out
    assert rb.main(["x", "--release-notes", "3.0.0", "--root", str(tmp_path)]) == 1
    assert "[3.0.0]" in capsys.readouterr().err


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
