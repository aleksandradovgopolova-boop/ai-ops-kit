#!/usr/bin/env python3
"""Nightly Product Health Review (v0, read-only).

Собирает delta по изменениям с последнего подтверждённого обзора и формирует утренний бриф.

Граница v0: НИЧЕГО НЕ ПРАВИТ. Только читает и синтезирует.

Структура брифа:
1. Главное одним предложением — что изменилось со вчера
2. Что требует решения (максимум 3 вопроса)
3. Чего система НЕ СТАЛА ДЕЛАТЬ и почему (обязательный раздел — строит доверие)
4. Одна рекомендация дня

Использование:
    nightly_review.py <child_root> [--since COMMIT] [--json]
    nightly_review.py --selftest

Возврат 0 — успех (бриф — данные, решение за людьми).
"""
from __future__ import annotations

import json
import subprocess
import sys

import yaml
from datetime import datetime, timedelta
from pathlib import Path


def _git(root: Path, *args) -> tuple[int, str, str]:
    """Git command wrapper."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, result.stdout, result.stderr
    # Узкий тип (фаза 0, 19.08.2026): запуск может не состояться (нет бинаря, права, битый
    # симлинк) или не уложиться в timeout. Любое ДРУГОЕ исключение здесь — дефект вызова, и он
    # обязан всплыть, а не превратиться в «rc=1» и молча стать «команда не сработала».
    # Тип ошибки НАЗЫВАЕТСЯ в тексте: «не смогли запустить» и «команда вернула ошибку» —
    # разные ответы, и по голому str(e) их не различить.
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", f"{type(e).__name__}: {e}"


def _get_recent_commits(root: Path, since: str | None = None) -> list[dict]:
    """Get commits since last review (or last 24h)."""
    if since:
        range_spec = f"{since}..HEAD"
    else:
        # Last 24 hours
        since_time = (datetime.now() - timedelta(hours=24)).isoformat()
        range_spec = f"--since={since_time}"

    rc, out, _ = _git(root, "log", range_spec, "--pretty=format:%H|%s|%an|%ai", "--no-merges")
    if rc != 0 or not out.strip():
        return []

    commits = []
    for line in out.strip().split("\n"):
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({
                "sha": parts[0][:8],
                "message": parts[1],
                "author": parts[2],
                "date": parts[3],
            })
    return commits


def _get_changed_files(root: Path, since: str | None = None) -> list[str]:
    """Get list of changed files since last review."""
    if since:
        range_spec = f"{since}..HEAD"
    else:
        since_time = (datetime.now() - timedelta(hours=24)).isoformat()
        # Get files from commits in last 24h
        rc, out, _ = _git(root, "log", f"--since={since_time}", "--name-only", "--pretty=format:")
        if rc != 0:
            return []
        files = set()
        for line in out.strip().split("\n"):
            line = line.strip()
            if line and not line.startswith("|"):
                files.add(line)
        return sorted(files)

    rc, out, _ = _git(root, "diff", range_spec, "--name-only")
    if rc != 0:
        return []
    return [f for f in out.strip().split("\n") if f]


def _check_plan_status(root: Path) -> dict:
    """Check plan.yaml for status changes."""
    plan_path = root / "planning" / "plan.yaml"
    if not plan_path.exists():
        return {"exists": False}

    try:
        with open(plan_path, encoding="utf-8") as f:
            plan = yaml.safe_load(f)
        work = plan.get("work", [])
        by_status = {}
        for w in work:
            s = w.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1
        return {"exists": True, "total": len(work), "by_status": by_status}
    # Узкий тип: файл может не читаться, YAML — не разбираться, а пустой документ даёт None и
    # падает на `.get`. Причина НАЗЫВАЕТСЯ: «план не прочитали» и «работ нет» — разные ответы,
    # и обзор, который их путает, отчитается о тишине там, где была поломка.
    except (OSError, yaml.YAMLError, AttributeError) as e:
        return {"exists": True, "error": f"план не разобран ({type(e).__name__}: {e})"}


def _check_ci_status(root: Path) -> dict:
    """Check if CI workflows exist (actual status requires GitHub API)."""
    workflows_dir = root / ".github" / "workflows"
    if not workflows_dir.exists():
        return {"workflows": 0}
    workflows = list(workflows_dir.glob("*.yml")) + list(workflows_dir.glob("*.yaml"))
    return {"workflows": len(workflows)}


def _check_open_prs(root: Path) -> dict:
    """Check for open PRs (requires gh CLI)."""
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--json", "number,title"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            prs = json.loads(result.stdout)
            return {"open_prs": len(prs), "prs": prs[:5]}  # First 5
        return {"open_prs": None, "unavailable": f"gh вернул код {result.returncode}"}
    # Узкий тип: gh может отсутствовать, не уложиться в timeout или отдать не-JSON.
    # Здесь стоял `pass`, и причина исчезала совсем; отсутствие данных выглядело так же, как
    # «открытых PR нет». `None` вместо `-1` — тот же инвариант, что и у usage: unavailable не
    # число и не ноль, а отдельное состояние, и оно названо в `unavailable`.
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return {"open_prs": None, "unavailable": f"{type(e).__name__}: {e}"}


def collect_delta(root: Path, since: str | None = None) -> dict:
    """Collect all delta information."""
    return {
        "commits": _get_recent_commits(root, since),
        "changed_files": _get_changed_files(root, since),
        "plan": _check_plan_status(root),
        "ci": _check_ci_status(root),
        "prs": _check_open_prs(root),
        "timestamp": datetime.now().isoformat(),
    }


def format_brief(delta: dict, root: Path) -> str:
    """Format delta into morning brief."""
    lines = []

    # 1. Главное одним предложением
    commits = delta.get("commits", [])
    if commits:
        lines.append(f"## Главное\n")
        lines.append(f"За последние 24 часа: {len(commits)} коммит(ов), "
                     f"{len(delta.get('changed_files', []))} файл(ов) изменено.\n")
    else:
        lines.append("## Главное\n")
        lines.append("Изменений за последние 24 часа не зафиксировано.\n")

    # 2. Что требует решения
    lines.append("\n## Требует решения\n")
    prs = delta.get("prs", {})
    open_prs = prs.get("open_prs")
    # ТРИ СОСТОЯНИЯ, И ТРЕТЬЕ НЕ РАВНО ВТОРОМУ (инвариант кита, фаза 0). Прежде «не смогли
    # спросить gh» давало -1, сравнение `-1 > 0` было ложным, и обзор печатал «нет открытых
    # вопросов» — то есть отсутствие данных выдавалось за отсутствие работы.
    if open_prs is None:
        lines.append(f"- Открытые PR: не знаю ({prs.get('unavailable', 'причина не названа')}).")
    elif open_prs > 0:
        lines.append(f"- Открытых PR: {open_prs}")
        for pr in prs.get("prs", [])[:3]:
            lines.append(f"  - #{pr['number']}: {pr['title']}")
    else:
        lines.append("- Нет открытых вопросов, требующих немедленного решения.")

    # 3. Чего система НЕ СТАЛА ДЕЛАТЬ
    lines.append("\n## Чего система не стала делать\n")
    lines.append("- v0 read-only: автоматические правки не выполняются (граница релиза).")
    lines.append("- CI-статус не проверяется автоматически (требует GitHub API token).")
    lines.append("- Deep analysis файлов не выполняется (только список изменённых).")

    # 4. Рекомендация дня
    lines.append("\n## Рекомендация дня\n")
    if open_prs is not None and open_prs > 3:
        lines.append("Разобрать очередь PR — накопилось больше 3 открытых.")
    elif commits:
        lines.append("Проверить последние коммиты и убедиться, что все изменения запланированы.")
    else:
        lines.append("Спокойный день. Можно взять новую задачу из плана.")

    return "\n".join(lines)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Nightly Product Health Review (v0, read-only)")
    ap.add_argument("root", nargs="?", default=".", help="Repository root")
    ap.add_argument("--since", help="Commit SHA or ref to diff from")
    ap.add_argument("--json", action="store_true", help="Output delta as JSON")
    ap.add_argument("--selftest", action="store_true", help="Run self-test")
    args = ap.parse_args()

    if args.selftest:
        # ЧЕСТНЫЙ --selftest (фаза 0, 19.08.2026). Здесь печаталась строка о пройденном
        # селфтесте и три строки «... : OK» — без единого вызова проверяемых функций. То есть
        # модуль УТВЕРЖДАЛ проверку, которой не было: ровно класс «объявлено, но не
        # исполняется», против которого стоит весь кит (ср. R-31/R-32 — две фиктивные проверки
        # в валидаторах). Образец честной формы — devtools/mutation_probe.py: модуль объясняет
        # себя и называет, где лежат его настоящие проверки. Правило репозитория (AGENTS.md):
        # тест модуля живёт в tests/, а не в продакшн-модуле, который едет в child-репозиторий.
        print(__doc__)
        print("Проверки модуля — в tests/unit/ (AGENTS.md: selftest не живёт в продакшн-модуле).")
        return 0

    root = Path(args.root).resolve()
    if not (root / ".git").exists():
        print(f"ERROR: {root} is not a git repository", file=sys.stderr)
        return 1

    delta = collect_delta(root, args.since)

    if args.json:
        print(json.dumps(delta, indent=2, ensure_ascii=False))
    else:
        print(format_brief(delta, root))

    return 0


if __name__ == "__main__":
    sys.exit(main())
