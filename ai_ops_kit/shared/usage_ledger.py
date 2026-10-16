#!/usr/bin/env python3
"""usage_ledger.py (v3.10.0 Usage Truth) — ЧЕСТНЫЙ учёт ВСЕХ модельных/runtime-вызовов.

Каждый вызов модели (writer/reviewer/fix-loop/fallback/escalation/parallel-пакеты) пишет UsageRecord.
Источник записей — orchestrator._record_call (+ _CALL_CONTEXT, который ставит ai_ops_run per-вызов).
Здесь — персист (append-only JSONL), агрегация по ЗАДАЧЕ и по ПРОДУКТУ, и валидатор ЧЕСТНОСТИ:
неизвестное использование = usage_status:unavailable с input/output=None (НИКОГДА 0), не «бесплатный» вызов.

UsageRecord:
  run_id, workitem_id, package_id, role, provider, model, runtime,
  input_tokens, output_tokens, usage_status (measured|estimated|unavailable),
  cost, cost_status (measured|estimated|unavailable), latency, trigger (initial|retry|review|escalation|fallback)

Ledger:
  features/<wid>/usage-ledger.jsonl   — по задаче (append-only)
  .ai/usage/product-ledger.jsonl      — агрегат по всему child-продукту (append-only)

CLI:  usage_ledger.py <child_root> [--workitem <wid>] [--json]   # показать стоимость задачи/продукта
      usage_ledger.py --selftest
"""
from __future__ import annotations

# v4: самодостаточный вход — файл можно запустить напрямую (без PYTHONPATH). Кладём корень пакета
# (маркер VERSION) в sys.path ДО пакетных импортов — раньше это делал плоский shim tools/ через
# _bootstrap; теперь точка входа сама себя обслуживает.
import sys as _sys
from pathlib import Path as _P_bootstrap
_root = next((_p for _p in _P_bootstrap(__file__).resolve().parents if (_p / "VERSION").is_file()), None)
if _root is not None and str(_root) not in _sys.path:
    _sys.path.insert(0, str(_root))

import json
import hashlib
from collections.abc import Iterable
import math
import sys
from pathlib import Path
from typing import Any, cast

from ai_ops_kit.shared.contracts import UsageRecord  # noqa: E402
from ai_ops_kit.shared import lifecycle_store

FIELDS = ("run_id", "workitem_id", "package_id", "role", "provider", "model", "runtime",
          "input_tokens", "output_tokens", "usage_status", "cost", "cost_status", "latency", "trigger",
          # v3.24.0 Cost & Architecture Accuracy — контекстные поля для economic alternatives и cost-per-decision
          "task_type", "workflow", "risk", "size", "writer_tier", "execution_mode", "stack", "architecture_impact")
USAGE_STATUS = ("measured", "estimated", "unavailable")
TRIGGERS = ("initial", "retry", "review", "escalation", "fallback", "reevaluate")


def cost_value(value: object) -> float | None:
    """Денежное число; bool/строка/переполнение не являются ценой."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    if isinstance(value, int) and number != value:
        return None
    return number if math.isfinite(number) and number >= 0 else None


def check(rec: UsageRecord) -> list[str]:
    """Валидация одной UsageRecord + ЧЕСТНОСТЬ. -> список ошибок."""
    e = []
    if not isinstance(rec, dict):
        return ["record не объект"]
    us = rec.get("usage_status")
    if us not in USAGE_STATUS:
        e.append(f"usage_status ∉ {USAGE_STATUS} (got {us!r})")
    it, ot = rec.get("input_tokens"), rec.get("output_tokens")
    # ЧЕСТНОСТЬ #1: unavailable -> токены НЕ заполнены (None), НЕ 0 (0 = «точно ноль», это ложь для неизвестного).
    if us == "unavailable" and (it is not None or ot is not None):
        e.append("usage_status=unavailable, но input/output_tokens заданы (неизвестное != 0; должно быть None)")
    # ЧЕСТНОСТЬ #2: measured -> хотя бы один счётчик токенов присутствует.
    if us == "measured" and it is None and ot is None:
        e.append("usage_status=measured, но токенов нет (нечего измерять)")
    for k in ("input_tokens", "output_tokens"):
        v = rec.get(k)
        if v is not None and not (isinstance(v, int) and v >= 0):
            e.append(f"{k} должен быть неотрицательным int или None (got {v!r})")
    cs = rec.get("cost_status")
    if cs is not None and cs not in USAGE_STATUS:
        e.append(f"cost_status ∉ {USAGE_STATUS} (got {cs!r})")
    if rec.get("cost") is None and cs == "measured":
        e.append("cost_status=measured, но cost=None")
    if rec.get("cost") is not None and cost_value(rec["cost"]) is None:
        e.append("cost должен быть конечным неотрицательным числом или None")
    tr = rec.get("trigger")
    if tr is not None and tr not in TRIGGERS:
        e.append(f"trigger ∉ {TRIGGERS} (got {tr!r})")
    return e


def normalize(rec: dict, run_id: str | None = None, workitem_id: str | None = None) -> UsageRecord:
    """Привести сырую запись _record_call к UsageRecord (заполнить недостающие ключи None, влить контекст)."""
    out = {k: rec.get(k) for k in FIELDS}
    if out.get("run_id") is None:
        out["run_id"] = run_id
    if out.get("workitem_id") is None:
        out["workitem_id"] = workitem_id
    # cost может прийти как cost_usd_est (назад-совместимость)
    if out.get("cost") is None and rec.get("cost_usd_est") is not None:
        out["cost"] = rec.get("cost_usd_est")
    out["cost"] = cost_value(out.get("cost"))
    if out["cost"] is None:
        out["cost_status"] = "unavailable"
    # out собран по ключам FIELDS (== поля UsageRecord); comprehension теряет TypedDict-тип — cast
    # возвращает его: функция для того и есть, чтобы привести сырую запись к форме UsageRecord.
    return cast(UsageRecord, out)


def _task_path(child_root: str | Path, wid: str | int) -> Path:
    return Path(child_root) / "features" / str(wid) / "usage-ledger.jsonl"


def _product_path(child_root: str | Path) -> Path:
    return Path(child_root) / ".ai" / "usage" / "product-ledger.jsonl"


def append(child_root: str | Path, workitem_id: str, records: list[dict] | None, run_id: str | None = None, extra_context: dict | None = None) -> int:
    """Записать UsageRecords в ledger задачи И продукта (append-only). Возвращает число записанных.
    v3.24.0: extra_context — dict дополнительных полей (task_type, workflow, stack, risk, size, writer_tier,
    execution_mode, architecture_impact), которые штампуется на ВСЕ записи (если в записи поле None)."""
    recs: list[dict] = [dict(normalize(r, run_id=run_id, workitem_id=workitem_id)) for r in (records or [])]
    # v3.24.0: штампуем extra_context на записи, где поля ещё не заполнены
    if extra_context:
        for rec in recs:
            for k, v in extra_context.items():
                if k in FIELDS and rec.get(k) is None and v is not None:
                    rec[k] = v
    if not recs:
        return 0
    with lifecycle_store._journal_lock(_product_path(child_root)):
        for p in (_task_path(child_root, workitem_id), _product_path(child_root)):
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                for r in recs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(recs)


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln:
            try:
                record = json.loads(ln)
                if isinstance(record, dict):
                    clean = normalize(record)
                    record.update(cost=clean["cost"], cost_status=clean["cost_status"])
                out.append(record)
            except json.JSONDecodeError:
                continue
    return out


def load_task(child_root: str | Path, wid: str | int) -> list[dict]:
    return _load(_task_path(child_root, wid))


def load_product(child_root: str | Path) -> list[dict]:
    return _load(_product_path(child_root))


def aggregate(records: list[dict] | None) -> dict:
    """Агрегат ЧЕСТНО: суммы токенов/стоимости ТОЛЬКО по записям с данными; unavailable считается отдельно
    (не как 0). -> {calls, measured/estimated/unavailable counts, input/output_tokens, cost,
    cost_complete (нет ли unavailable-стоимости), by_role/by_trigger/by_provider/by_task_type/by_workflow/by_writer_tier}."""
    agg: dict[str, Any] = {"calls": 0, "usage_measured": 0, "usage_unavailable": 0,
           "input_tokens": 0, "output_tokens": 0, "cost": 0.0,
           "cost_measured": 0, "cost_estimated": 0, "cost_unavailable": 0,
           "cost_overflow": False, "cost_precision_lost": False,
           "by_role": {}, "by_trigger": {}, "by_provider": {},
           # v3.24.0: новые измерения для economic alternatives и cost-per-decision
           "by_task_type": {}, "by_workflow": {}, "by_writer_tier": {}}
    for r in records or []:
        agg["calls"] += 1
        us = r.get("usage_status")
        if us == "unavailable":
            agg["usage_unavailable"] += 1
        else:
            agg["usage_measured"] += 1
            agg["input_tokens"] += int(r.get("input_tokens") or 0)
            agg["output_tokens"] += int(r.get("output_tokens") or 0)
        price = cost_value(r.get("cost"))
        cs = r.get("cost_status") if price is not None else "unavailable"
        if cs == "measured":
            agg["cost_measured"] += 1
        elif cs == "estimated":
            agg["cost_estimated"] += 1
        else:
            agg["cost_unavailable"] += 1
        if price is not None:
            total = agg["cost"] + price
            if math.isfinite(total):
                if price > 0 and agg["cost"] > 0 and total in (price, agg["cost"]):
                    agg["cost_precision_lost"] = True
                agg["cost"] = total
            else:
                # Уже учтённая цена остаётся нижней границей, полная недоступна.
                agg["cost_overflow"] = True
        for dim, key in (("by_role", "role"), ("by_trigger", "trigger"), ("by_provider", "provider"),
                         ("by_task_type", "task_type"), ("by_workflow", "workflow"),
                         ("by_writer_tier", "writer_tier")):
            k = r.get(key) or "unknown"
            agg[dim][k] = agg[dim].get(k, 0) + 1
    agg["cost"] = round(agg["cost"], 6)
    # ЧЕСТНОСТЬ: стоимость ПОЛНАЯ только если ни одного вызова с неизвестной стоимостью.
    agg["cost_complete"] = (agg["cost_unavailable"] == 0 and not agg["cost_overflow"]
                            and not agg["cost_precision_lost"])
    return agg


def complete_cost(values: Iterable[object]) -> float | None:
    """Полная денежная сумма или None, если представима только нижняя граница."""
    values = list(values)
    if not values:
        return None
    result = aggregate([{"cost": value, "cost_status": "measured"} for value in values])
    return cast(float, result["cost"]) if result["cost_complete"] else None


def _strict_rows(path: Path) -> list:
    """Не путать повреждённый JSONL с отсутствующими вызовами."""
    if not path.exists():
        return []
    rows = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("usage ledger содержит не объект")
    return rows


def _no_symlink(root: Path, path: Path) -> None:
    rel = path.relative_to(root)
    if any((root.joinpath(*rel.parts[:i])).is_symlink() for i in range(1, len(rel.parts) + 1)):
        raise ValueError("usage ledger содержит symlink")


def snapshot_ledgers(root: str | Path) -> dict:
    """Граница унаследованной clone history ДО вызовов пакета, без копирования её записей."""
    root = Path(root).resolve()
    snapshot = {}
    for path in [root / ".ai/usage/product-ledger.jsonl", *sorted(root.glob("features/*/usage-ledger.jsonl"))]:
        if path.exists() or path.is_symlink():
            _no_symlink(root, path)
            content = path.read_bytes()
            if content and not content.endswith(b"\n"):
                raise ValueError("source usage baseline не заканчивается полной строкой")
            snapshot[str(path.relative_to(root))] = {"offset": len(content),
                                                    "digest": hashlib.sha256(content).hexdigest()}
    return snapshot


def _source_rows(root: Path, path: Path, identity: str, baseline: dict | None = None) -> tuple:
    _no_symlink(root, path)
    rel = path.relative_to(root)
    content = path.read_bytes()
    if baseline is not None and not isinstance(baseline, dict):
        raise ValueError("source usage baseline невалидна")
    baseline = baseline if baseline is not None else {"offset": 0, "digest": hashlib.sha256(b"").hexdigest()}
    offset = baseline.get("offset")
    if (not isinstance(offset, int) or isinstance(offset, bool) or offset < 0 or offset > len(content)
            or hashlib.sha256(content[:offset]).hexdigest() != baseline.get("digest")):
        raise ValueError("source usage baseline изменён; cleanup запрещён")
    rows = []
    for line in content[offset:].splitlines(keepends=True):
        if line.strip():
            raw = json.loads(line)
            if not isinstance(raw, dict):
                raise ValueError("source usage record не объект")
            row = dict(normalize(raw))  # только UsageRecord, не config/prompts/произвольные поля
            numeric = {"input_tokens", "output_tokens", "cost", "latency"}
            if check(row) or any(v is not None and not isinstance(v, str)
                                 for k, v in row.items() if k not in numeric):
                raise ValueError("source UsageRecord не соответствует объявленному контракту")
            if any(isinstance(row.get(k), bool) for k in numeric):
                raise ValueError("boolean не является числом usage")
            if row.get("latency") is not None and cost_value(row["latency"]) is None:
                raise ValueError("latency должна быть конечным неотрицательным числом или None")
            row["_ai_ops_source"] = {"id": identity, "stream": rel.as_posix(), "offset": offset,
                                      "digest": hashlib.sha256(line).hexdigest()}
            rows.append(row)
        offset += len(line)
    return rows, hashlib.sha256(content).hexdigest()


def _origin_key(origin: dict) -> tuple:
    if (not all(isinstance(origin.get(k), str) and origin[k] for k in ("id", "stream", "digest"))
            or not isinstance(origin.get("offset"), int) or isinstance(origin["offset"], bool)
            or origin["offset"] < 0):
        raise ValueError("usage provenance не соответствует контракту")
    return tuple(origin[k] for k in ("id", "stream", "offset"))


def _merge_rows(existing: list, incoming: list) -> tuple:
    seen = {}
    for row in existing:
        origin = row.get("_ai_ops_source")
        if origin is not None and not isinstance(origin, dict):
            raise ValueError("destination usage provenance повреждён")
        if isinstance(origin, dict):
            key = _origin_key(origin)
            if key in seen:
                raise ValueError("destination usage provenance collision")
            seen[key] = origin.get("digest")
    added = 0
    merged = list(existing)
    for row in incoming:
        origin = row["_ai_ops_source"]
        key = _origin_key(origin)
        if key in seen:
            if seen[key] != origin["digest"]:
                raise ValueError("source usage stream изменён на уже импортированном offset")
            continue
        merged.append(row)
        seen[key], added = origin["digest"], added + 1
    return merged, added


def _merge_ledgers(child_root: str | Path, source_roots: list, source_ids: dict | None, source_baselines: dict | None) -> int:
    """Durable fan-in UsageRecord. Identity = source/run + stream + byte offset, НЕ содержимое.

    source_ids задаёт стабильный coordinator-owned id при перемещении source в архив; по умолчанию
    canonical source path. Возврат — новые product calls. Сбой -> ValueError: source удалять НЕЛЬЗЯ.
    Ledger без provenance сохраняется, его старые импорты ретроспективно не угадываются.
    """
    snapshots, batches = {}, {}
    if source_ids is not None and not isinstance(source_ids, dict):
        raise ValueError("source usage identities должны быть словарём")
    if source_baselines is not None and not isinstance(source_baselines, dict):
        raise ValueError("source usage baselines должны быть словарём")
    child_root = Path(child_root).resolve()
    _no_symlink(child_root, Path(str(_product_path(child_root)) + ".lock"))
    for source in source_roots:
        root = Path(source).resolve()
        if not root.is_dir():
            raise ValueError("source usage root отсутствует")
        identity = (source_ids or {}).get(str(source), (source_ids or {}).get(str(root), str(root)))
        if not isinstance(identity, str) or not identity:
            raise ValueError("source usage identity отсутствует")
        baseline = (source_baselines or {}).get(str(source), (source_baselines or {}).get(str(root), {}))
        if not isinstance(baseline, dict):
            raise ValueError("source usage baseline не словарь")
        paths = [root / ".ai/usage/product-ledger.jsonl", *sorted(root.glob("features/*/usage-ledger.jsonl"))]
        if any(not isinstance(rel, str) or Path(rel).is_absolute() or ".." in Path(rel).parts
               or not isinstance(value, dict) for rel, value in baseline.items()):
            raise ValueError("source usage baseline невалидна")
        if any(not (root / rel).is_file() for rel in baseline):
            raise ValueError("source usage baseline исчез; cleanup запрещён")
        for path in paths:
            if path.is_symlink() or path.exists():
                rows, digest = _source_rows(root, path, identity, baseline.get(str(path.relative_to(root))))
                snapshots[path] = digest
                dst = child_root / path.relative_to(root)
                _no_symlink(child_root, dst)
                batches.setdefault(dst, []).extend(rows)
    if not batches:
        return 0
    added, writes = 0, {}
    with lifecycle_store._journal_lock(_product_path(child_root), required=True):
        # Сначала ВЕСЬ prospective merge: corrupt/collision не приводит к частичной записи.
        for path, rows in batches.items():
            merged, count = _merge_rows(_strict_rows(path), rows)
            if count:
                writes[path] = merged
            if path == _product_path(child_root):
                added += count
        for path, rows in writes.items():
            result = lifecycle_store.durable_write_jsonl(path, rows)
            if not result.get("ok") or _strict_rows(path) != rows:
                raise ValueError("usage ledger durable write/readback не подтверждён")
        if any(hashlib.sha256(path.read_bytes()).hexdigest() != digest for path, digest in snapshots.items()):
            raise ValueError("source usage ledger изменился во время сохранения; cleanup запрещён")
    return added


def merge_ledgers(child_root: str | Path, source_roots: list, *, source_ids: dict | None = None,
                  source_baselines: dict | None = None) -> int:
    """Свести подтверждённые streams один раз; ValueError означает: source копию удалять НЕЛЬЗЯ."""
    try:
        return _merge_ledgers(child_root, source_roots, source_ids, source_baselines)
    except (OSError, TypeError) as exc:
        raise ValueError(f"usage archive недоступен ({type(exc).__name__}); cleanup запрещён") from exc


def _fmt_agg(title: str, a: dict) -> str:
    lines = [f"{title}: вызовов {a['calls']} (measured {a['usage_measured']}, unavailable {a['usage_unavailable']})"]
    lines.append("  токены (measured): in=%d out=%d" % (a["input_tokens"], a["output_tokens"]))
    _c = "$%.4f" % a["cost"]
    lines.append("  стоимость: %s%s" % (_c, "" if a["cost_complete"] else "  ⚠ НЕПОЛНАЯ (есть вызовы с неизвестной стоимостью)"))
    lines.append("  cost-статусы: measured %d / estimated %d / unavailable %d" %
                 (a["cost_measured"], a["cost_estimated"], a["cost_unavailable"]))
    lines.append("  по ролям: " + ", ".join("%s=%d" % kv for kv in sorted(a["by_role"].items())))
    lines.append("  по триггерам: " + ", ".join("%s=%d" % kv for kv in sorted(a["by_trigger"].items())))
    lines.append("  по провайдерам: " + ", ".join("%s=%d" % kv for kv in sorted(a["by_provider"].items())))
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print("usage: usage_ledger.py <child_root> [--workitem <wid>] [--json]"); return 2
    child_root = args[0]
    wid = None
    if "--workitem" in argv:
        wid = argv[argv.index("--workitem") + 1]
    prod = load_product(child_root)
    out = {"product": aggregate(prod)}
    if wid:
        out["task"] = aggregate(load_task(child_root, wid))
    if "--json" in argv:
        print(json.dumps(out, ensure_ascii=False, indent=2)); return 0
    if wid:
        print(_fmt_agg(f"ЗАДАЧА {wid}", out["task"]))
        print()
    print(_fmt_agg("ПРОДУКТ (все задачи)", out["product"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
