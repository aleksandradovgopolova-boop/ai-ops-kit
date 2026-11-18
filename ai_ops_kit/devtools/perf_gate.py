"""Гейт скорости и памяти кита (#1409): схема, принятая владельцем 18.11.2026.

Почему не «текущий прогон против сохранённой базы» для всего. Замер 13.11.2026 на трёх ручных
прогонах GitHub Actions: внутри одной машины база и повтор расходятся не больше чем на 10%, а между
машинами одно и то же время различается до 1,73× — даже у машин с одинаковым именем. Сохранённая
база времени поэтому даёт ложную тревогу либо (при строгой сверке окружения) не сравнивает вообще.

- **Время — парой.** База (последний выпуск) и кандидат прогоняются по очереди на ОДНОЙ машине в
  ОДНОМ прогоне. Сравнение квитанций разных машин или прогонов — `INCOMPARABLE`, никогда не зелёное.
- **Память — против принятой базы.** Пик RSS между машинами расходится не больше чем на 2%, поэтому
  сверка окружения идёт по устойчивым полям (ОС, архитектура, мажор.минор Python, реализация, CPU), а
  не по имени машины, ядру и точным версиям пакетов. Принятая база —
  `qualification/evidence/performance-baseline-1409/accepted-memory-baseline.json`.

Порог по умолчанию 1,2 для обеих частей. Итог — худшая из частей; любое «не смогли сравнить»
важнее регрессии и даёт код 2: зелёным может быть только реально выполненное сравнение.

Запуск: `python3 -m ai_ops_kit.devtools.perf_gate compare|pair --help`.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from ai_ops_kit.devtools import bench_performance as bench

DEFAULT_THRESHOLD = 1.2
PAIRED_METADATA = ("environment", "suite_sha256", "iterations", "warmup", "execution_context",
                   "ci_run_id", "ci_run_attempt", "memory_semantics")
MEMORY_METADATA = ("suite_sha256", "iterations", "warmup", "execution_context", "memory_semantics")
NOT_COMPARED = ("INVALID", "ERROR", "INCOMPARABLE", "REJECTED_WINDOW")
EXIT_CODES = {"OK": 0, "REGRESSION": 1}


def stable_environment(environment: dict) -> dict:
    """Поля, которые не меняются от машины к машине одного образа runner."""
    python = str(environment.get("python", ""))
    return {"os": str(environment.get("platform", "")).split("-", 1)[0],
            "machine": environment.get("machine"),
            "python": ".".join(python.split(".")[:2]),
            "implementation": environment.get("implementation"),
            "cpu_count": environment.get("cpu_count")}


def _check_threshold(threshold) -> None:
    if not bench._positive_number(threshold) or threshold <= 1:
        raise ValueError("regression threshold must exceed 1")


def _validated(*receipts) -> dict | None:
    """Вернуть отказ, если хоть одна квитанция не годится; None — обе пригодны."""
    try:
        errors = [bench.validate_receipt(receipt) for receipt in receipts]
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return {"status": "INVALID", "reason": str(exc)}
    failed = next((error for error in errors if error), None)
    return {"status": "ERROR", "reason": failed} if failed else None


def _ratios(current: dict, reference: dict, metric: str, threshold: float) -> dict:
    cases = {}
    for name, result in current["results"].items():
        if not reference["results"][name][metric] > 0:
            return {"status": "INVALID", "reason": f"nonpositive reference {name}.{metric}"}
        ratio = result[metric] / reference["results"][name][metric]
        cases[name] = {"status": "REGRESSION" if ratio > threshold else "OK", "ratio": ratio,
                       "reference": reference["results"][name][metric], "current": result[metric]}
    status = "REGRESSION" if any(c["status"] == "REGRESSION" for c in cases.values()) else "OK"
    return {"status": status, "metric": metric, "threshold": threshold, "cases": cases}


def compare_paired_time(base: dict, candidate: dict, threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Время кандидата против базы, снятой на той же машине в том же прогоне."""
    _check_threshold(threshold)
    refusal = _validated(base, candidate)
    if refusal:
        return refusal
    for key in PAIRED_METADATA:
        if base["metadata"].get(key) != candidate["metadata"].get(key):
            return {"status": "INCOMPARABLE", "reason": f"not one machine and run: {key} differs"}
    if base["metadata"]["execution_context"] == "github_actions" and not base["metadata"].get("ci_run_id"):
        return {"status": "INCOMPARABLE", "reason": "Actions receipt without run id"}
    return _ratios(candidate, base, "median_ms", threshold)


def compare_memory(current: dict, accepted: dict, threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Пик RSS против принятой базы; окружение сверяется только по устойчивым полям."""
    _check_threshold(threshold)
    refusal = _validated(current, accepted)
    if refusal:
        return refusal
    for key in MEMORY_METADATA:
        if current["metadata"].get(key) != accepted["metadata"].get(key):
            return {"status": "INCOMPARABLE", "reason": f"accepted baseline differs: {key}"}
    now = stable_environment(current["metadata"]["environment"])
    then = stable_environment(accepted["metadata"]["environment"])
    if now != then:
        changed = sorted(k for k in now if now[k] != then[k])
        return {"status": "INCOMPARABLE", "reason": f"stable environment differs: {', '.join(changed)}"}
    return _ratios(current, accepted, "median_peak_rss_bytes", threshold)


def combine(time_verdict: dict, memory_verdict: dict) -> dict:
    statuses = (time_verdict["status"], memory_verdict["status"])
    overall = next((s for s in statuses if s in NOT_COMPARED), None)
    if overall is None:
        overall = "REGRESSION" if "REGRESSION" in statuses else "OK"
    return {"status": overall, "time": time_verdict, "memory": memory_verdict}


def exit_code(verdict: dict) -> int:
    """0 — сравнение выполнено и чисто; 1 — выполнено, есть регрессия; 2 — сравнения не было."""
    return EXIT_CODES.get(verdict["status"], 2)


def read_window() -> dict | None:
    """Снимок машины для чистоты окна; вне Linux недоступен — и тогда пара не запускается."""
    try:
        vmstat = dict(line.split()[:2] for line in Path("/proc/vmstat").read_text().splitlines())
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        return {"boot_id": boot_id, "pswpin": int(vmstat["pswpin"]), "pswpout": int(vmstat["pswpout"])}
    except (OSError, KeyError, ValueError):
        return None


def _source(root: Path) -> tuple[str, bool]:
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True, timeout=15).strip()
    return git("rev-parse", "HEAD"), bool(git("status", "--porcelain"))


def _preflight(sides: dict, window) -> str | None:
    if window is None:
        return "window guard unavailable: /proc swap and boot id are required"
    for side, (root, sha) in sides.items():
        actual, dirty = _source(root)
        if actual != sha or dirty:
            return f"{side} checkout is not the reviewed clean source {sha}"
    return None


def run_pair(suite, base_root, base_sha, candidate_root, candidate_sha, out_dir,
             iterations=bench.DEFAULT_ITERATIONS, warmup=1, threshold=DEFAULT_THRESHOLD,
             memory_baseline: dict | None = None, window_reader=read_window) -> dict:
    """Прогнать базу и кандидата по очереди на этой машине и вынести вердикт.

    Без чистого исходника и без доступного снимка окна не исполняется ни одна команда. Квитанции,
    снимок окна и вердикт пишутся в `out_dir`, который должен быть новым.
    """
    bench._validate_suite(suite)
    _check_threshold(threshold)
    sides = {"base": (Path(base_root), base_sha), "candidate": (Path(candidate_root), candidate_sha)}
    before = window_reader()
    refusal = _preflight(sides, before)
    if refusal:
        return {"status": "INVALID", "reason": refusal}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=False)
    receipts = {}
    for side, (root, _sha) in sides.items():
        receipts[side] = bench.run_suite(suite, root, out / f"{side}.logs", iterations, warmup)
        (out / f"{side}.json").write_text(json.dumps(receipts[side], indent=2, ensure_ascii=False) + "\n",
                                          encoding="utf-8")
    after = window_reader()
    unchanged = _preflight(sides, after) is None
    stable = after is not None and before == after
    (out / "window.json").write_text(json.dumps({
        "before": before, "after": after, "source_unchanged": unchanged, "swap_and_boot_stable": stable,
        "qualification": "CANDIDATE" if unchanged and stable else "REJECTED"}, indent=2) + "\n", encoding="utf-8")
    time_verdict = compare_paired_time(receipts["base"], receipts["candidate"], threshold)
    memory_verdict = (compare_memory(receipts["candidate"], memory_baseline, threshold)
                      if memory_baseline is not None else {"status": "INVALID", "reason": "no accepted memory baseline"})
    verdict = combine(time_verdict, memory_verdict)
    if not (unchanged and stable):
        verdict = {**verdict, "status": "REJECTED_WINDOW", "reason": "swap, reboot or source change during the pair"}
    return verdict


STATUS_WORDS = {"OK": "в норме", "REGRESSION": "ухудшение выше порога", "INCOMPARABLE": "сравнить нельзя",
                "INVALID": "квитанция не годится", "ERROR": "замер не удался",
                "REJECTED_WINDOW": "окно замера не чистое"}


def format_summary(verdict: dict) -> str:
    """Короткая сводка для страницы прогона: итог, затем по частям и этапам."""
    lines = [f"## Скорость и память: {STATUS_WORDS.get(verdict['status'], verdict['status'])}", ""]
    if verdict.get("reason"):
        lines += [f"Причина: {verdict['reason']}", ""]
    for title, key in (("Время (база и кандидат на одной машине)", "time"),
                       ("Память (против принятой базы)", "memory")):
        part = verdict.get(key) or {}
        lines.append(f"### {title}: {STATUS_WORDS.get(part.get('status'), part.get('status'))}")
        if part.get("reason"):
            lines.append(f"Причина: {part['reason']}")
        for name, case in (part.get("cases") or {}).items():
            lines.append(f"- {name}: ×{case['ratio']:.2f} (порог {part['threshold']})")
        lines.append("")
    return "\n".join(lines)


def _load(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _emit(verdict: dict, output) -> int:
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps(verdict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = format_summary(verdict)
    print(summary)
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(summary + "\n")
    return exit_code(verdict)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="perf_gate", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    compare = sub.add_parser("compare", help="Сравнить готовые квитанции, без запуска команд")
    compare.add_argument("--base", type=Path, required=True)
    compare.add_argument("--candidate", type=Path, required=True)
    pair = sub.add_parser("pair", help="Прогнать базу и кандидата на этой машине (нужен host-slot)")
    pair.add_argument("--suite", type=Path, required=True)
    pair.add_argument("--base-root", type=Path, required=True)
    pair.add_argument("--base-sha", required=True)
    pair.add_argument("--candidate-root", type=Path, required=True)
    pair.add_argument("--candidate-sha", required=True)
    pair.add_argument("--out", type=Path, required=True, help="Новый каталог для квитанций и вердикта")
    pair.add_argument("--iterations", type=int, default=bench.DEFAULT_ITERATIONS)
    pair.add_argument("--warmup", type=int, default=1)
    for command in (compare, pair):
        command.add_argument("--memory-baseline", type=Path, required=True)
        command.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
        command.add_argument("--output", type=Path, help="Куда записать вердикт JSON")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        memory = _load(args.memory_baseline)
        if args.command == "compare":
            verdict = combine(compare_paired_time(_load(args.base), _load(args.candidate), args.threshold),
                              compare_memory(_load(args.candidate), memory, args.threshold))
        else:
            verdict = run_pair(bench.load_suite(args.suite), args.base_root, args.base_sha,
                               args.candidate_root, args.candidate_sha, args.out, args.iterations,
                               args.warmup, args.threshold, memory)
    except Exception as exc:  # noqa: BLE001 — любая внутренняя ошибка = «сравнения не было» (2), не регрессия (1)
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return _emit(verdict, args.output or (args.out / "verdict.json" if args.command == "pair" else None))


if __name__ == "__main__":
    sys.exit(main())
