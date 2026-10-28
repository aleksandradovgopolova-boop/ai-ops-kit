"""Проверки реального wheel без pytest: запускаются clean-install в чистом venv через -I.

Сборка и установка — ответственность check-clean-install.sh. Здесь проверяется поставка,
пользовательский результат и отказ при потере реестра; импорты обязаны идти из venv.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import zipfile

import yaml

import ai_ops_kit


DATA_DIRS = (
    "registry", "quality", "workflows", "schemas", "decisions", "packages", "manifest",
    "standards", "knowledge", "planning", "templates", "context", "agents", "rules",
)


def run_cli(root, *args):
    entry = Path(sys.executable).with_name("ai-ops")
    return subprocess.run([sys.executable, "-I", str(entry), *args], cwd=root,
                          capture_output=True, text=True, timeout=60)


def check_distribution(source, wheel):
    installed = Path(ai_ops_kit.__file__).resolve().parent
    assert installed.is_relative_to(Path(sys.prefix).resolve()), installed
    assert not installed.is_relative_to(source.resolve()), installed
    with zipfile.ZipFile(wheel) as archive:
        assert archive.read("ai_ops_kit/VERSION") == (source / "VERSION").read_bytes()
        for directory in DATA_DIRS:
            files = [p for p in (source / directory).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts
                     and p.suffix not in {".pyc", ".pyo"}]
            assert files, directory
            for path in files:
                relative = path.relative_to(source)
                name = "ai_ops_kit/" + relative.as_posix()
                assert archive.read(name) == path.read_bytes(), name
                assert (installed / relative).read_bytes() == path.read_bytes(), name
            assert not any(n.startswith(directory + "/") for n in archive.namelist())
        # planning/context совмещают код и данные. Наложение не вправе повредить модули.
        for path in (source / "ai_ops_kit").rglob("*.py"):
            relative = path.relative_to(source)
            assert archive.read(relative.as_posix()) == path.read_bytes(), str(relative)
    from ai_ops_kit.planning import standard
    assert standard.PKG == installed
    assert standard.current_version() > 0
    assert standard.compute_fingerprint() == standard.load()["requirements_fingerprint"]
    print("OK  wheel: VERSION, все 14 каталогов, код и стандарт доступны из venv")
    return installed


def check_plan(root):
    root.mkdir()
    help_result = run_cli(root, "--help")
    assert help_result.returncode == 0 and help_result.stdout.strip(), help_result.stderr
    for index, args in enumerate((("Добавить выгрузку отчёта", "--json"),
                                  ("--json", "Добавить поиск по отчётам"))):
        feature = f"wheel-plan-{index}"
        result = run_cli(root, "plan", *args, "--feature", feature)
        assert result.returncode == 0, result.stdout + result.stderr
        report = json.loads(result.stdout)
        assert report["workitem_id"] == feature
        assert report["context_error"] is None, report
        plan_path = root / report["plan"]
        plan = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
        assert plan["workitem_id"] == feature and plan["gates"]
        bundle = yaml.safe_load((plan_path.parent / "context-bundle.yaml").read_text(encoding="utf-8"))
        assert bundle["included"]["agents"], bundle
        assert {"core", "engineering"} <= set(bundle["included"]["rules"]), bundle
    print("OK  wheel plan: оба порядка --json, RunPlan и непустой ContextBundle созданы")


def check_next(root):
    (root / "planning").mkdir()
    (root / "ROADMAP.md").write_text(
        "# ROADMAP\n\n## Сейчас\n\n- `wheel-goal` — выгрузка отчёта\n\n"
        "## Следующий результат\n\n- `next-goal` — поиск отчётов\n\n"
        "## Дальше\n\n- Аналитика\n\n## Later\n\n- Идеи\n", encoding="utf-8")
    (root / "planning/plan.yaml").write_text(yaml.safe_dump({
        "schema_version": 1, "kind": "delivery-plan",
        "goals": [{"id": "wheel-goal", "status": "active", "outcome": {"works": False}}],
        "work": [{"id": "wheel-work", "title": "Выгрузка отчёта", "type": "engineering",
                  "goal": "wheel-goal", "status": "todo", "owner_role": "engineer",
                  "depends_on": [], "write_scope": ["src/"]}],
    }), encoding="utf-8")
    result = run_cli(root, "next", "--json")
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["next_best"]["id"] == "wheel-work", report
    assert not report["plan_errors"] and not report["roadmap"]["errors"], report
    assert report["next_best"]["why"], report
    print("OK  wheel next: выбрана работа из плана продукта")


def check_missing_registry(root, installed):
    tracks = installed / "registry/tracks.yaml"
    saved = tracks.read_bytes()
    try:
        tracks.unlink()
        assert not tracks.exists()  # Сначала доказываем порчу поставки.
        result = run_cli(root, "plan", "Новая задача", "--json", "--feature", "missing-registry")
        assert result.returncode != 0, result.stdout
        assert "tracks.yaml" in result.stdout + result.stderr
        assert not (root / "features/missing-registry/run-plan.yaml").exists()
    finally:
        tracks.write_bytes(saved)
    print("OK  wheel: потеря обязательного реестра не выдаёт успешный план")


if __name__ == "__main__":
    source, wheel, root = map(Path, sys.argv[1:])
    installed = check_distribution(source, wheel)
    check_plan(root)
    check_next(root)
    check_missing_registry(root, installed)
