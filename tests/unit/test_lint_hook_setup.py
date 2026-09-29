"""Регистрация хука линта в `.claude/settings.json` дочки и CI-шаг линта (`ai-ops-lint.yml`).

Работа `lint-runs-at-edit-and-in-child-ci` (#1183). Файл настроек — ВЛАДЕЛЬЦА, поэтому:
  * positive     — хук прописан в документированной форме Claude Code и зовёт ДОСТАВЛЕННЫЙ файл;
                   CI-шаблон едет всем дочкам и исполняет команды дочки;
  * fail-closed  — JSON с комментариями / не той формы НЕ переписывается, а называется в отчёте;
  * side-effect  — чужие ключи и хуки целы, повторный прогон не меняет ни байта, опт-аут снимает
                   только своё; исполнение шагов установленного workflow на фикстуре даёт 1 на
                   нарушениях и 0 на чистом коде.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
TEMPLATE = KIT / "templates" / "ci" / "ai-ops-lint.yml"

pytestmark = pytest.mark.unit


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    # Без байткода: `templates/**` едет в поставку целиком, `.pyc` рядом с хуком стал бы её частью.
    saved, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = saved
    return mod


@pytest.fixture(scope="module")
def setup_mod():
    return _load("_lint_hook_setup_under_test", KIT / "installer" / "lint_hook_setup.py")


@pytest.fixture(scope="module")
def ai_ops():
    return _load("_ai_ops_lint_hook", KIT / "installer" / "ai_ops.py")


def _settings(root: Path) -> Path:
    return root / ".claude" / "settings.json"


def _ours(doc: dict, marker: str) -> list:
    return [h for g in doc.get("hooks", {}).get("PostToolUse", []) for h in g.get("hooks", [])
            if marker in h.get("command", "")]


# ── positive ──────────────────────────────────────────────────────────────────────────────────────

def test_created_in_documented_shape(setup_mod, tmp_path):
    res = setup_mod.ensure_lint_hook(tmp_path)
    assert res["action"] == "created"
    doc = json.loads(_settings(tmp_path).read_text(encoding="utf-8"))
    (group,) = doc["hooks"]["PostToolUse"]
    assert group["matcher"] == "Write|Edit|MultiEdit"
    (hook,) = group["hooks"]
    assert hook["type"] == "command" and isinstance(hook["timeout"], int)
    assert setup_mod.DELIVERED in hook["command"] and setup_mod.MARKER in hook["command"]
    assert "CLAUDE_PROJECT_DIR" in hook["command"], "путь хука не привязан к корню проекта"


def test_registered_command_actually_runs_the_delivered_hook(setup_mod, tmp_path):
    """Команду из настроек исполняем оболочкой, как Claude Code: доставленный хук отвечает.

    Нет файла хука (пакетный фильтр, старая поставка) -> тихий 0, а не ошибка в сессии агента."""
    setup_mod.ensure_lint_hook(tmp_path)
    cmd = json.loads(_settings(tmp_path).read_text(encoding="utf-8"))["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(tmp_path), "AI_OPS_PYTHON": sys.executable}
    r = subprocess.run(["sh", "-c", cmd], input="{}", capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0 and r.stdout == "", "без доставленного файла хук обязан молчать"
    delivered = tmp_path / setup_mod.DELIVERED
    delivered.parent.mkdir(parents=True)
    delivered.write_text("import sys; print('HOOK-RAN', sys.argv[1:]); sys.exit(2)\n", encoding="utf-8")
    r = subprocess.run(["sh", "-c", cmd], input="{}", capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 2 and "HOOK-RAN ['hook']" in r.stdout, (r.returncode, r.stdout, r.stderr)


def test_delivered_path_is_really_shipped(ai_ops, setup_mod):
    """Настройки зовут `.ai/managed/<rel>` — этот rel обязан быть в поставке managed-слоя."""
    rels = {rel for _, rel in ai_ops.managed_set()}
    assert setup_mod.DELIVERED.removeprefix(".ai/managed/") in rels


def test_bytecode_next_to_the_hook_does_not_ship(ai_ops):
    """`templates/**` едет целиком: без фильтра `.pyc` от импорта хука уезжал бы в managed дочки."""
    assert ai_ops.is_runtime_asset("templates/runtime/lint_hook.py")
    assert not ai_ops.is_runtime_asset("templates/runtime/__pycache__/lint_hook.cpython-314.pyc")
    assert not ai_ops.is_runtime_asset("templates/runtime/lint_hook.pyc")


def test_deliver_assets_registers_the_hook(ai_ops, tmp_path, monkeypatch):
    """ШОВ: запись доезжает до дочки, потому что её зовёт общая доставка init/update."""
    _cs, _ci = ai_ops._child_scaffolding(), ai_ops._ci_setup()
    for mod, name, stub in ((_cs, "_backfill_required_context", lambda *a, **k: []),
                            (_ci, "sync_ci_workflows", lambda *a, **k: []),
                            (_cs, "_seed_planning_contour", lambda *a, **k: []),
                            (_cs, "_seed_product_layer", lambda *a, **k: [])):
        monkeypatch.setattr(mod, name, stub)
    assets = ai_ops.deliver_assets(tmp_path)
    assert assets["lint_hook"]["action"] == "created"
    assert "момент правки" in ai_ops._assets_report_line(assets)


# ── side-effect: чужое цело, повтор идемпотентен, опт-аут снимает только своё ──────────────────

OWNER = {
    "permissions": {"allow": ["Bash(npm test:*)"]},
    "hooks": {
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo pre"}]}],
        "PostToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command": "prettier -w"}]}],
    },
    "env": {"FOO": "1"},
}


def _write(root: Path, doc) -> Path:
    p = _settings(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=4) if not isinstance(doc, str) else doc, encoding="utf-8")
    return p


def test_owner_keys_and_hooks_survive(setup_mod, tmp_path):
    _write(tmp_path, OWNER)
    assert setup_mod.ensure_lint_hook(tmp_path)["action"] == "updated"
    doc = json.loads(_settings(tmp_path).read_text(encoding="utf-8"))
    assert doc["permissions"] == OWNER["permissions"] and doc["env"] == OWNER["env"]
    assert doc["hooks"]["PreToolUse"] == OWNER["hooks"]["PreToolUse"]
    assert doc["hooks"]["PostToolUse"][0] == OWNER["hooks"]["PostToolUse"][0], "чужой хук сдвинут/изменён"
    assert len(_ours(doc, setup_mod.MARKER)) == 1


def test_repeat_is_byte_identical(setup_mod, tmp_path):
    _write(tmp_path, OWNER)
    setup_mod.ensure_lint_hook(tmp_path)
    before = _settings(tmp_path).read_bytes()
    assert setup_mod.ensure_lint_hook(tmp_path)["action"] == "unchanged"
    assert _settings(tmp_path).read_bytes() == before


def test_stale_own_entry_is_updated_in_place_not_duplicated(setup_mod, tmp_path):
    old = {"type": "command", "command": f"python3 old/path.py  # {setup_mod.MARKER}"}
    doc = json.loads(json.dumps(OWNER))
    doc["hooks"]["PostToolUse"].insert(0, {"matcher": "Write", "hooks": [old]})
    _write(tmp_path, doc)
    assert setup_mod.ensure_lint_hook(tmp_path)["action"] == "updated"
    new = json.loads(_settings(tmp_path).read_text(encoding="utf-8"))
    ours = _ours(new, setup_mod.MARKER)
    assert len(ours) == 1 and setup_mod.DELIVERED in ours[0]["command"]
    assert new["hooks"]["PostToolUse"][0] == setup_mod.kit_group(), "своя запись ушла со своего места"
    assert new["hooks"]["PostToolUse"][1] == OWNER["hooks"]["PostToolUse"][0]


def test_own_hook_inside_owner_group_is_moved_out_owner_hook_kept(setup_mod, tmp_path):
    doc = json.loads(json.dumps(OWNER))
    doc["hooks"]["PostToolUse"][0]["hooks"].append(
        {"type": "command", "command": f"x  # {setup_mod.MARKER}"})
    _write(tmp_path, doc)
    setup_mod.ensure_lint_hook(tmp_path)
    new = json.loads(_settings(tmp_path).read_text(encoding="utf-8"))
    owner_hooks = [h["command"] for g in new["hooks"]["PostToolUse"] for h in g["hooks"]]
    assert "prettier -w" in owner_hooks and len(_ours(new, setup_mod.MARKER)) == 1


def test_opt_out_removes_only_own_entry(setup_mod, tmp_path):
    _write(tmp_path, OWNER)
    setup_mod.ensure_lint_hook(tmp_path)
    (tmp_path / ".ai-ops.yaml").write_text("standard:\n  lint_hook: off\n", encoding="utf-8")
    assert setup_mod.ensure_lint_hook(tmp_path)["action"] == "removed"
    doc = json.loads(_settings(tmp_path).read_text(encoding="utf-8"))
    assert doc == OWNER, "опт-аут тронул чужое"


def test_opt_out_without_own_entry_touches_nothing(setup_mod, tmp_path):
    (tmp_path / ".ai-ops.yaml").write_text("standard:\n  lint_hook: false\n", encoding="utf-8")
    assert setup_mod.ensure_lint_hook(tmp_path)["action"] == "not-installed"
    assert not _settings(tmp_path).exists(), "выключенный хук не должен заводить файл"
    p = _write(tmp_path, {"hooks": {"PostToolUse": []}})
    before = p.read_bytes()
    assert setup_mod.ensure_lint_hook(tmp_path)["action"] == "not-installed"
    assert p.read_bytes() == before


# ── fail-closed: нечитаемое не переписывается ────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    '{\n  // мой комментарий\n  "env": {"A": "1"}\n}\n',
    '{"hooks": ',
    '["not", "an", "object"]',
    '{"hooks": {"PostToolUse": {"matcher": "x"}}}',
])
def test_unreadable_settings_are_not_overwritten(setup_mod, tmp_path, text):
    p = _write(tmp_path, text)
    res = setup_mod.ensure_lint_hook(tmp_path)
    assert res["action"] == "skipped-unreadable" and res["detail"]
    assert p.read_text(encoding="utf-8") == text, "чужой файл переписан"
    line = setup_mod.lint_hook_report_line(res)
    assert "НЕ прописан" in line and setup_mod.MARKER in line, "владелец не получил строку для вставки"


# ── CI-шаблон ──────────────────────────────────────────────────────────────────────────────────

def _steps():
    wf = yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))
    (job,) = wf["jobs"].values()
    return wf, job["steps"]


def test_ci_template_is_delivered_to_every_child(ai_ops):
    assert "ai-ops-lint.yml" in ai_ops.CI_TEMPLATES
    assert "ai-ops-lint.yml" not in ai_ops.CONDITIONAL_CI_TEMPLATES


def test_ci_template_runs_child_commands_with_minimal_permissions(ai_ops):
    wf, steps = _steps()
    assert wf["permissions"] == {"contents": "read"}, "права шире чтения"
    triggers = wf.get(True) or wf.get("on") or {}          # YAML 1.1 читает ключ `on` как True
    assert "pull_request" in triggers, "шаг не бежит на PR — обязательной проверкой его не сделать"
    runs = "\n".join(str(s.get("run", "")) for s in steps)
    assert "project_detector.py detect . --json" in runs, "профиль не из детектора кита"
    assert "lint_hook.py ci" in runs and "--profile" in runs
    for s in steps:
        if "uses" in s:
            assert "@" in s["uses"], f"действие без закрепления: {s['uses']}"


def _run_step(step: dict, cwd: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", step["run"]], cwd=str(cwd), env=env,
                          capture_output=True, text=True, timeout=180)


@pytest.mark.parametrize("bad", [False, True])
def test_installed_workflow_steps_really_gate(tmp_path, bad):
    """ГЛАВНОЕ: шаги установленного workflow исполняются на фикстуре-дочке и КРАСНЕЮТ на нарушении.

    Клон кита подменён ссылкой на этот репозиторий (сеть не нужна). Дочка — go-сервис с конфигом
    golangci-lint: у go-стека нет шага установки зависимостей, и фальшивый линтер стоит в PATH."""
    child = tmp_path / "child"
    (child / "api").mkdir(parents=True)
    (child / "go.mod").write_text("module demo\n\ngo 1.22\n", encoding="utf-8")
    (child / ".golangci.yml").write_text("linters: {}\n", encoding="utf-8")
    (child / "api" / "h.go").write_text("package api\n" + ("// BAD\n" if bad else ""), encoding="utf-8")
    runner = tmp_path / "runner"
    runner.mkdir()
    (runner / "ai-ops-kit").symlink_to(KIT)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "golangci-lint"
    fake.write_text('#!/bin/sh\nif grep -rq BAD api; then echo "api/h.go:2: BAD found"; exit 1; fi\n',
                    encoding="utf-8")
    fake.chmod(0o755)
    env = {**os.environ, "RUNNER_TEMP": str(runner),
           "PATH": f"{bindir}:{Path(sys.executable).parent}:{os.environ.get('PATH', '')}"}
    _, steps = _steps()
    by_name = {s.get("name", ""): s for s in steps}
    prof = _run_step(next(s for n, s in by_name.items() if n.startswith("Профиль")), child, env)
    assert prof.returncode == 0, prof.stderr
    lint = _run_step(next(s for n, s in by_name.items() if n.startswith("Линт")), child, env)
    assert lint.returncode == (1 if bad else 0), lint.stdout + lint.stderr
    assert ("НЕ пройдено" in lint.stdout) is bad and "golangci-lint run" in lint.stdout
