#!/usr/bin/env python3
"""Гейт eval-кейсов: изменённый агент обязан иметь eval-кейсы (evaluations/README.md).

Правило: если в диапазоне изменений (diff base..HEAD) добавлен или изменён файл
agents/**/*.md (кроме README), то должен существовать файл eval-кейсов
evaluations/agents/<agent-id>.md, где <agent-id> — имя файла агента без расширения.

Существующих агентов без eval-кейсов гейт НЕ трогает: требование распространяется
только на то, что меняется, — иначе гейт был бы красным всегда и его бы выключили.

База диффа (первое подходящее):
  1. аргумент --base <ref>;
  2. переменная окружения AI_OPS_DIFF_BASE;
  3. HEAD~1 (обычный push/merge);
  4. если базу определить нельзя (первый коммит, нет git) — OK с предупреждением.

Использование:  python3 validation/validate_agent_evals.py [--base <ref>] [--selftest]
Возврат 0 — чисто, 1 — есть ошибки.
"""

import os
import subprocess
import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = "agents/"
EVALS_DIR = "evaluations/agents"


def changed_files(base):
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=AM", f"{base}", "HEAD"],
            capture_output=True, text=True, cwd=PKG_ROOT, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def check(changed, evals_present):
    """Чистая проверка: список изменённых путей -> список ошибок."""
    errors = []
    for path in changed:
        if not path.startswith(AGENTS_DIR) or not path.endswith(".md"):
            continue
        stem = Path(path).stem
        if stem.lower() == "readme":
            continue
        if stem not in evals_present:
            errors.append(
                f"агент '{path}' изменён, но нет eval-кейсов {EVALS_DIR}/{stem}.md "
                "(минимум 3 кейса, см. evaluations/README.md)")
    return errors


def resolve_base(argv):
    if "--base" in argv:
        return argv[argv.index("--base") + 1]
    if os.environ.get("AI_OPS_DIFF_BASE"):
        return os.environ["AI_OPS_DIFF_BASE"]
    probe = subprocess.run(["git", "rev-parse", "--verify", "HEAD~1"],
                           capture_output=True, text=True, cwd=PKG_ROOT)
    if probe.returncode == 0:
        return "HEAD~1"
    return None


def evals_present_on_disk():
    d = PKG_ROOT / EVALS_DIR
    return {p.stem for p in d.glob("*.md")} if d.is_dir() else set()


def selftest():
    ok = True

    def expect(name, got, want):
        nonlocal ok
        status = "PASS" if got == want else "FAIL"
        ok = ok and (got == want)
        print(f"{status} {name}")

    # 1. изменённый агент без eval-кейсов -> ошибка
    errs = check(["agents/core/task-planner.md"], evals_present=set())
    expect("изменённый агент без eval -> fail", len(errs), 1)
    # 2. изменённый агент с eval-кейсами -> чисто
    errs = check(["agents/core/task-planner.md"], evals_present={"task-planner"})
    expect("изменённый агент с eval -> pass", len(errs), 0)
    # 3. изменения вне agents/ и README не требуют eval
    errs = check(["registry/agents.yaml", "agents/README.md", "workflows/release.md"],
                 evals_present=set())
    expect("не-агентные изменения -> pass", len(errs), 0)
    print("agent-evals selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    base = resolve_base(argv)
    if base is None:
        print("OK (с предупреждением): база диффа недоступна — проверка изменённых "
              "агентов пропущена.")
        return 0
    changed = changed_files(base)
    if changed is None:
        print(f"OK (с предупреждением): git diff {base}..HEAD недоступен — "
              "проверка пропущена.")
        return 0
    errors = check(changed, evals_present_on_disk())
    if errors:
        print("ОШИБКИ (eval-гейт агентов):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK: eval-гейт агентов чист (diff {base}..HEAD, "
          f"{len(changed)} изменённых файлов).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
