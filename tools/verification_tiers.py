#!/usr/bin/env python3
"""verification_tiers.py (v3.26.0 Progressive Verification) — определение уровня верификации
и выбор тестов на основе изменённых файлов.

Verification tiers:
- affected: только тесты, затронутые изменениями (быстро, для итерации)
- module: все тесты затронутых модулей/пакетов (средне, для checkpoint)
- full: полный набор тестов (медленно, для merge/release)

Test selection engine:
changed_files → repo_graph.impact() → affected_tests() → targeted test command

CLI: verification_tiers.py --changed file1 file2 [--tier affected|module|full] [--json]
     verification_tiers.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
for _p in (PKG / "tools",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ============================================================================
# Verification Tiers
# ============================================================================

TIERS = ("affected", "module", "full")

# Файлы, которые всегда требуют full verification (критическая инфраструктура)
ALWAYS_FULL_PATTERNS = (
    "registry/", "schemas/", "quality/gates.yaml",
    "tools/orchestrator.py", "tools/execution_pipeline.py",
    "tools/preflight.py", "tools/gate_executor.py",
    "tools/tool_broker.py", "tools/lifecycle_store.py",
)

# Файлы, которые не требуют verification (документация, конфиги)
SKIP_VERIFICATION_PATTERNS = (
    "*.md", "*.txt", "LICENSE", "VERSION",
    ".gitignore", ".dockerignore",
    "docs/", "context/", "decisions/",
)


def _matches_any(path: str, patterns: tuple) -> bool:
    """Проверить, соответствует ли путь любому из паттернов."""
    for p in patterns:
        if p.endswith("/"):
            if path.startswith(p) or f"/{p}" in path:
                return True
        elif "*" in p:
            if Path(path).match(p):
                return True
        elif path == p or path.endswith(f"/{p}"):
            return True
    return False


def decide_tier(changed_files: list, force_tier: str = None) -> str:
    """Определить уровень верификации на основе изменённых файлов.
    force_tier — принудительный уровень (если задан).
    -> 'affected' | 'module' | 'full'"""
    if force_tier and force_tier in TIERS:
        return force_tier
    if not changed_files:
        return "affected"  # нет изменений — минимальная проверка

    # Критическая инфраструктура -> full
    for f in changed_files:
        if _matches_any(f, ALWAYS_FULL_PATTERNS):
            return "full"

    # Только документация/конфиги -> skip (но возвращаем affected для безопасности)
    all_skip = all(_matches_any(f, SKIP_VERIFICATION_PATTERNS) for f in changed_files)
    if all_skip:
        return "affected"  # минимальная проверка даже для docs

    # Много файлов (>20) -> module или full
    if len(changed_files) > 20:
        return "module"

    # По умолчанию — affected
    return "affected"


# ============================================================================
# Test Selection Engine
# ============================================================================

def select_tests(changed_files: list, child_root: str, tier: str = None) -> dict:
    """Выбрать тесты на основе изменённых файлов и уровня верификации.
    -> {tier, changed_files, affected_tests, targeted_command, full_command, note}"""
    import repo_graph

    tier = decide_tier(changed_files, tier)
    child_root = Path(child_root)

    if tier == "full":
        return {
            "tier": "full",
            "changed_files": changed_files,
            "affected_tests": None,  # все тесты
            "targeted_command": None,  # полная команда из project_detector
            "full_command": True,
            "note": "Full verification: критическая инфраструктура или много изменений",
        }

    # Строим граф
    graph = repo_graph.build_graph(child_root, subdirs=None, include_js=True)

    # Находим затронутые тесты
    affected = repo_graph.affected_tests(graph, changed_files)

    if not affected:
        return {
            "tier": tier,
            "changed_files": changed_files,
            "affected_tests": [],
            "targeted_command": None,
            "full_command": False,
            "note": "Нет затронутых тестов — изменения не влияют на тесты",
        }

    # Формируем targeted command (зависит от стека)
    # Для Python: pytest test1.py test2.py
    # Для JS: jest --testPathPattern="test1|test2"
    py_tests = [t for t in affected if t.endswith(".py")]
    js_tests = [t for t in affected if any(t.endswith(ext) for ext in (".test.js", ".test.ts", ".test.jsx", ".test.tsx", ".spec.js", ".spec.ts"))]

    commands = []
    if py_tests:
        commands.append(f"pytest {' '.join(py_tests)}")
    if js_tests:
        # Jest pattern
        patterns = "|".join(Path(t).stem for t in js_tests)
        commands.append(f"jest --testPathPattern=\"{patterns}\"")

    return {
        "tier": tier,
        "changed_files": changed_files,
        "affected_tests": affected,
        "targeted_command": " && ".join(commands) if commands else None,
        "full_command": False,
        "note": f"{tier.capitalize()} verification: {len(affected)} тестов затронуто",
    }


def selftest():
    """Selftest: контракты и логика."""
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # 1. decide_tier: критическая инфраструктура -> full
    tier = decide_tier(["tools/orchestrator.py"])
    expect("decide_tier: orchestrator.py -> full", tier == "full")

    # 2. decide_tier: документация -> affected
    tier = decide_tier(["README.md", "docs/guide.md"])
    expect("decide_tier: docs -> affected", tier == "affected")

    # 3. decide_tier: много файлов -> module
    tier = decide_tier([f"tools/file{i}.py" for i in range(25)])
    expect("decide_tier: 25 files -> module", tier == "module")

    # 4. decide_tier: обычный файл -> affected
    tier = decide_tier(["tools/usage_ledger.py"])
    expect("decide_tier: обычный файл -> affected", tier == "affected")

    # 5. decide_tier: force_tier
    tier = decide_tier(["README.md"], force_tier="full")
    expect("decide_tier: force_tier=full -> full", tier == "full")

    # 6. select_tests: синтетический репо
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "tools").mkdir()
        (root / "tools" / "module.py").write_text("def func(): return 1\n", encoding="utf-8")
        (root / "tools" / "test_module.py").write_text("import module\ndef test_func(): assert module.func() == 1\n", encoding="utf-8")
        result = select_tests(["tools/module.py"], str(root))
        expect("select_tests: affected tier", result["tier"] == "affected")
        expect("select_tests: test_module.py в affected_tests", "tools/test_module.py" in (result["affected_tests"] or []))
        expect("select_tests: targeted_command содержит pytest", "pytest" in (result["targeted_command"] or ""))

    # 7. select_tests: full для критической инфраструктуры
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "tools").mkdir()
        (root / "tools" / "orchestrator.py").write_text("def run(): pass\n", encoding="utf-8")
        result = select_tests(["tools/orchestrator.py"], str(root))
        expect("select_tests: orchestrator -> full tier", result["tier"] == "full")
        expect("select_tests: full_command=True", result["full_command"] is True)

    print("verification_tiers selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())

    # CLI
    changed_files = []
    tier = None
    as_json = "--json" in sys.argv

    if "--changed" in sys.argv:
        idx = sys.argv.index("--changed")
        for i in range(idx + 1, len(sys.argv)):
            if sys.argv[i].startswith("--"):
                break
            changed_files.append(sys.argv[i])

    if "--tier" in sys.argv:
        idx = sys.argv.index("--tier")
        if idx + 1 < len(sys.argv):
            tier = sys.argv[idx + 1]

    if not changed_files:
        print("Usage: verification_tiers.py --changed file1 file2 [--tier affected|module|full] [--json]")
        sys.exit(1)

    # Для CLI нужен child_root — используем текущую директорию
    child_root = str(Path.cwd())
    result = select_tests(changed_files, child_root, tier)

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"VERIFICATION: tier={result['tier']}")
        print(f"  Changed: {len(result['changed_files'])} файлов")
        if result["affected_tests"]:
            print(f"  Affected tests: {len(result['affected_tests'])}")
            for t in result["affected_tests"][:5]:
                print(f"    - {t}")
            if len(result["affected_tests"]) > 5:
                print(f"    ... и ещё {len(result['affected_tests']) - 5}")
        if result["targeted_command"]:
            print(f"  Command: {result['targeted_command']}")
        print(f"  Note: {result['note']}")
