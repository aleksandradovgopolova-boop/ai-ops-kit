"""Advisory CRAP-пилот #1387, без CI-проводки и исполнения исследуемого кода.

CRAP = CC² * (1 - line_coverage)³ + CC. Line coverage — приближение, не
исходное basis-path coverage. Неизвестное покрытие → null, никогда 0%/100%.
Python AST policy v1: if/for/async-for/while/except/ifexp, boolean operators,
comprehension generators/filters, match cases кроме безусловного wildcard.
Вложенные функции измеряются отдельно; lambdas отдельно не измеряются.

python3 -m ai_ops_kit.devtools.crap_score --help
Обычный запуск read-only; 0 — измерено без нового долга, 1 — долг/неполнота,
2 — ошибка входов. Даже код 1 не подключён как обязательный гейт (dp-002).
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import tokenize

import yaml

KIT = Path(__file__).resolve().parents[2]
ALGORITHM = "python-ast-line-v1"
THRESHOLD = 10
FUNCTION = (ast.FunctionDef, ast.AsyncFunctionDef)
SCOPE = (*FUNCTION, ast.ClassDef, ast.Lambda)
DECISION = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp)


def crap(complexity: int, coverage: float) -> float:
    """Формула Savoia/Evans; coverage — доля [0, 1]."""
    if type(complexity) is not int or complexity < 1:
        raise ValueError("complexity должна быть положительным целым")
    if not math.isfinite(coverage) or not 0 <= coverage <= 1:
        raise ValueError("coverage должна быть конечной долей [0, 1]")
    return complexity ** 2 * (1 - coverage) ** 3 + complexity


def _owned_nodes(fn):
    """Итеративный обход тела; решения nested scopes не заряжают родителя."""
    stack = list(reversed(fn.body))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, SCOPE):
            stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _decision_count(node):
    if isinstance(node, DECISION):
        return 1
    if isinstance(node, ast.BoolOp):
        return len(node.values) - 1
    if isinstance(node, ast.comprehension):
        return 1 + len(node.ifs)
    if isinstance(node, ast.match_case):
        wildcard = isinstance(node.pattern, ast.MatchAs) and node.pattern.pattern is None
        return int(not wildcard or node.guard is not None)
    return 0


def _body_lines(fn):
    lines = set(range(fn.body[0].lineno, fn.end_lineno + 1))
    for node in ast.walk(fn):
        if isinstance(node, FUNCTION):
            if node is not fn:
                lines.difference_update(range(node.body[0].lineno, node.end_lineno + 1))
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                lines.difference_update(range(first.lineno, first.end_lineno + 1))
    return lines


def _definitions(tree, parents=()):
    for child in ast.iter_child_nodes(tree):
        named = isinstance(child, (*FUNCTION, ast.ClassDef))
        names = (*parents, child.name) if named else parents
        if isinstance(child, FUNCTION):
            yield ".".join(names), child
        yield from _definitions(child, names)


def functions(root: Path) -> list[dict]:
    """Устойчивый ключ = relative path + qualified name + SHA256 имён типов узлов.

    Нет ast.dump, lineno и optional empty AST-полей в ключе. Повторения одного
    qualified name и структуры различаются порядковым суффиксом, не теряются.
    """
    paths = sorted((root / "ai_ops_kit").rglob("*.py"))
    if not paths:
        raise ValueError("нет Python-файлов в ai_ops_kit")
    rows, seen = [], Counter()
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"исходник вне дерева или symlink: {path}")
        with tokenize.open(path) as stream:
            source = stream.read()
        tree = ast.parse(source, filename=str(path))
        source_lines = source.splitlines()
        rel = path.relative_to(root).as_posix()
        for name, fn in _definitions(tree):
            nodes = list(_owned_nodes(fn))
            signature = "\n".join([type(fn).__name__, *(type(n).__name__ for n in nodes)])
            digest = hashlib.sha256(signature.encode()).hexdigest()
            key = f"{rel}::{name}@{digest}"
            seen[key] += 1
            key += f"#{seen[key]}" if seen[key] > 1 else ""
            body_lines = _body_lines(fn)
            first = fn.body[0]
            if source_lines[first.lineno - 1].encode("utf-8")[:first.col_offset].strip():
                # Inline suite разделяет line event определения и вызова: неоднозначно.
                body_lines.discard(first.lineno)
            rows.append({"key": key, "path": rel, "name": name, "line": fn.lineno,
                         "complexity": 1 + sum(_decision_count(n) for n in nodes),
                         "body_lines": body_lines})
    if not rows:
        raise ValueError("нет именованных функций для измерения")
    return rows


def measurement_inputs(root: Path) -> dict[str, str]:
    """Снимок исходников, тестов и настроек ДО/ПОСЛЕ доверенного coverage-run.

    Сравнивается весь inventory, включая добавления/удаления. Привязка —
    integrity evidence, не удостоверение подлинности результата тестов.
    """
    paths = set()
    for directory in ("ai_ops_kit", "tests"):
        paths.update((root / directory).rglob("*.py"))
    paths.update(root / name for name in ("pyproject.toml", "pytest.ini", "setup.cfg",
                                          "setup.py", ".coveragerc", "conftest.py"))
    result = {}
    for path in sorted(paths):
        if path.is_file():
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError(f"measurement input вне дерева или symlink: {path}")
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def _digest(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _line_set(value):
    if not isinstance(value, list) or any(type(n) is not int or n < 1 for n in value):
        raise ValueError("coverage lines должны быть списком положительных целых")
    if len(set(value)) != len(value):
        raise ValueError("coverage lines содержат дубли")
    return set(value)


def _coverage_file(data):
    if not isinstance(data, dict):
        raise ValueError("coverage file должен быть mapping")
    hit, miss = _line_set(data.get("executed_lines")), _line_set(data.get("missing_lines"))
    excluded = _line_set(data.get("excluded_lines", []))
    if hit & miss or miss & excluded:
        raise ValueError("coverage line sets противоречат друг другу")
    return hit, miss, excluded


@dataclass
class CoverageEvidence:
    files: dict
    binding: dict
    stale: bool


def load_coverage(root: Path, report: Path, binding: Path) -> CoverageEvidence:
    raw = report.read_bytes()
    data = json.loads(raw)
    bound = json.loads(binding.read_text(encoding="utf-8"))
    if not isinstance(bound, dict) or type(bound.get("schema_version")) is not int or bound["schema_version"] != 1:
        raise ValueError("неподдерживаемый coverage binding")
    if bound.get("outcome") != "passed" or not all(isinstance(bound.get(k), str) and bound[k].strip() for k in ("scope", "python")):
        raise ValueError("coverage binding требует passed, scope и python")
    command = bound.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(v, str) and v for v in command):
        raise ValueError("coverage binding требует command argv")
    if bound.get("report_sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("coverage report hash не совпадает с binding")
    inputs = bound.get("inputs_sha256")
    if not isinstance(inputs, dict) or not inputs or not all(isinstance(k, str) and _digest(v) for k, v in inputs.items()):
        raise ValueError("coverage binding требует inputs_sha256")
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise ValueError("неподдерживаемый coverage JSON")
    meta = data.get("meta", {})
    if not isinstance(meta, dict) or type(meta.get("format")) is not int or meta["format"] not in (2, 3) or not isinstance(meta.get("version"), str):
        raise ValueError("нужен coverage.py JSON format 2/3 с версией")
    files = {}
    for path, stats in data["files"].items():
        rel = Path(path)
        if rel.is_absolute() or rel.as_posix() != path or ".." in rel.parts:
            raise ValueError("coverage paths должны быть каноническими относительно root")
        files[path] = _coverage_file(stats)
    bound = {**bound, "coverage_version": meta["version"]}
    return CoverageEvidence(files, bound, inputs != measurement_inputs(root))


def _function_coverage(row, evidence, line_count):
    if evidence is None:
        return "missing", None
    if evidence.stale:
        return "stale", None
    stats = evidence.files.get(row["path"])
    if stats is None:
        return "missing", None
    hit, miss, excluded = stats
    # coverage.py может включать виртуальную EOF+1 в excluded_lines (Protocol/...);
    # эта строка не является исполненной и не попадает в знаменатель.
    if any(n > line_count for n in hit | miss) or any(n > line_count + 1 for n in excluded):
        raise ValueError(f"coverage line вне исходника: {row['path']}")
    hit = hit - excluded
    lines = row["body_lines"]
    statements = (hit | miss) & lines
    if not statements:
        return "unknown", None
    return "measured", len(hit & lines) / len(statements)


def analyze(root: Path, evidence: CoverageEvidence | None, frozen: dict) -> dict:
    """Read-only отчёт; raw scores сравниваются до округления."""
    rows = functions(root)
    counts = {}
    for row in rows:
        path = row["path"]
        if path not in counts:
            counts[path] = len((root / path).read_bytes().splitlines())
        state, cov = _function_coverage(row, evidence, counts[path])
        score = crap(row["complexity"], cov) if cov is not None else None
        finding = None
        if score is not None and score >= THRESHOLD:
            limit = frozen.get(row["key"])
            if limit is None:
                finding = "new_debt"
            elif score > limit + 1e-9:
                finding = "regression"
        row.update(coverage_status=state, coverage=cov, crap=score, finding=finding)
        row.pop("body_lines")
    # Не выдаём coverage исходников ДО изменения за coverage считанного ПОСЛЕ.
    if evidence is not None and not evidence.stale and evidence.binding["inputs_sha256"] != measurement_inputs(root):
        for row in rows:
            row.update(coverage_status="stale", coverage=None, crap=None, finding=None)
    unknown = sum(r["crap"] is None for r in rows)
    findings = sum(r["finding"] is not None for r in rows)
    return {"schema_version": 1, "mode": "advisory", "algorithm": ALGORITHM,
            "coverage_mode": "line-approximation", "threshold": THRESHOLD,
            "status": "incomplete" if unknown else ("findings" if findings else "measured"),
            "unknown_functions": unknown, "new_or_regressed": findings,
            "stale_baseline_keys": sorted(set(frozen) - {r["key"] for r in rows}),
            "measurement": evidence.binding if evidence else None, "functions": rows}


def baseline_document(rows, evidence):
    return {"schema_version": 1, "kind": "crap-score-advisory", "algorithm": ALGORITHM,
            "threshold": THRESHOLD, "coverage_mode": "line-approximation",
            "measurement": evidence.binding if evidence else None,
            "functions": {r["key"]: r["crap"] for r in rows if r["crap"] is not None and r["crap"] >= THRESHOLD}}


def load_baseline(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    expected = baseline_document([], None)
    if not isinstance(doc, dict) or type(doc.get("schema_version")) is not int:
        raise ValueError("baseline должен быть mapping schema_version=1")
    for key in ("schema_version", "kind", "algorithm", "threshold", "coverage_mode"):
        if doc.get(key) != expected[key]:
            raise ValueError(f"неподдерживаемый baseline {key}")
    entries = doc.get("functions")
    if not isinstance(entries, dict):
        raise ValueError("baseline functions должен быть mapping")
    for key, value in entries.items():
        if not isinstance(key, str) or "::" not in key or "@" not in key:
            raise ValueError("невалидный ключ baseline")
        if type(value) not in (float, int) or not math.isfinite(value) or value < THRESHOLD:
            raise ValueError("baseline принимает только конечный измеренный CRAP >= 10")
    if entries and not isinstance(doc.get("measurement"), dict):
        raise ValueError("непустой baseline требует measurement provenance")
    history = doc.get("raises", [])
    if not isinstance(history, list) or any(not isinstance(r, dict) or not isinstance(r.get("reason"), str)
                                           or not r["reason"].strip() or not isinstance(r.get("functions"), dict)
                                           for r in history):
        raise ValueError("baseline raises должен быть списком обоснованных изменений")
    return doc


def _atomic_write(path, text):
    if path.is_symlink():
        raise ValueError("baseline symlink не перезаписывается")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _write_baseline(path, result, evidence, previous, reason):
    if result["unknown_functions"] or evidence is None:
        raise ValueError("baseline не записан: нужно измеренное покрытие ВСЕХ функций")
    doc = baseline_document(result["functions"], evidence)
    old = previous.get("functions", {}) if previous else {}
    raised = {k: v for k, v in doc["functions"].items() if previous is not None and (k not in old or v > old[k] + 1e-9)}
    if raised and not (reason and reason.strip()):
        raise ValueError("baseline не записан: новый/выросший долг требует --allow-raise REASON")
    history = list(previous.get("raises", [])) if previous else []
    if raised:
        history.append({"reason": reason.strip(), "functions": raised})
    if history:
        doc["raises"] = history
    # Все проверки до записи; при ошибке сериализации старый файл сохраняется.
    text = "# Advisory-пилот #1387. Изменение заморозки требует review.\n" + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    _atomic_write(path, text)


def _render(result):
    print(f"advisory CRAP: {result['status']}; функций {len(result['functions'])}; "
          f"новый/выросший долг {result['new_or_regressed']}; неизвестно {result['unknown_functions']}")
    for row in result["functions"]:
        if row["finding"] or row["crap"] is None:
            score = "unknown" if row["crap"] is None else f"{row['crap']:.3f}"
            print(f"  {row['path']}:{row['line']} {row['name']}: CC={row['complexity']} "
                  f"CRAP={score} coverage={row['coverage_status']} {row['finding'] or ''}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=KIT, help="корень репозитория, сканируется ai_ops_kit/**")
    parser.add_argument("--baseline", type=Path, help="по умолчанию ROOT/packages/crap-score-baseline.yaml")
    parser.add_argument("--coverage", type=Path, help="coverage.py JSON format 2/3, относительные пути")
    parser.add_argument("--coverage-binding", type=Path, help="JSON provenance + hashes до/после measurement")
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--allow-raise", help="обоснование пересматриваемого роста существующей заморозки")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if bool(args.coverage) != bool(args.coverage_binding):
            raise ValueError("нужны одновременно --coverage и --coverage-binding")
        if args.allow_raise and not args.write_baseline:
            raise ValueError("--allow-raise требует --write-baseline")
        root = args.root.resolve()
        path = args.baseline or root / "packages/crap-score-baseline.yaml"
        previous = load_baseline(path) if path.exists() or not args.write_baseline else None
        evidence = load_coverage(root, args.coverage, args.coverage_binding) if args.coverage else None
        result = analyze(root, evidence, previous["functions"] if previous else {})
        if args.write_baseline:
            _write_baseline(path, result, evidence, previous, args.allow_raise)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            _render(result)
        return 0 if args.write_baseline else int(bool(result["unknown_functions"] or result["new_or_regressed"]))
    except (OSError, ValueError, SyntaxError, UnicodeError, yaml.YAMLError) as exc:
        print(f"ERROR crap-score: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
