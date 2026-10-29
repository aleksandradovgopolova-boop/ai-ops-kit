"""Политика источников и наблюдения compiled payload, без семантических догадок."""
from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

import yaml


def _relative(value, *, pattern=False):
    if (not isinstance(value, str) or not value or "\\" in value
            or value.startswith("/") or any(p in (".", "..", "") for p in value.rstrip("/").split("/"))
            or (not pattern and any(c in value for c in "*?[]"))):
        raise ValueError(f"context: нужен относительный путь без обхода: {value!r}")
    return value


def load_policy(root):
    """Отсутствие ключа совместимо; ошибочная декларация не отключает ограничения."""
    path = Path(root) / ".ai-ops.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ValueError(".ai-ops.yaml: нужен объект")
    policy = config.get("context", {})
    if not isinstance(policy, dict) or set(policy) - {"required", "optional", "forbidden"}:
        raise ValueError("context: допустимы только required/optional/forbidden")
    result = {"configured": "context" in config}
    for key in ("required", "optional", "forbidden"):
        values = policy.get(key, [])
        if not isinstance(values, list):
            raise ValueError(f"context.{key}: нужен список путей")
        result[key] = sorted({_relative(v, pattern=key == "forbidden") for v in values})
    budgets = config.get("context_budget", {})
    if not isinstance(budgets, dict):
        raise ValueError("context_budget: нужен объект")
    budget = budgets.get("run_tokens")
    if budget is not None and (type(budget) is not int or budget <= 0):
        raise ValueError("context_budget.run_tokens: нужно положительное целое")
    result["run_tokens"] = budget
    for rel in result["required"]:
        if forbidden(result, rel, root):
            raise ValueError(f"context.required запрещён политикой: {rel}")
    return result


def forbidden(policy, source, root=None):
    """Сопоставление до чтения: имя, целевой путь symlink и каталоги-предки."""
    names = {source}
    if root is not None:
        _relative(source)
        base = Path(root).resolve()
        target = (base / source).resolve()
        if not target.is_relative_to(base):
            raise ValueError(f"context: источник выходит за репозиторий: {source}")
        names.add(target.relative_to(base).as_posix())
    for name in names:
        for pattern in policy["forbidden"]:
            if fnmatchcase(name, pattern) or name == pattern.rstrip("/"):
                return True
            if any(fnmatchcase(str(parent), pattern.rstrip("/"))
                   for parent in PurePosixPath(name).parents if str(parent) != "."):
                return True
    return False


def relevance_metrics(items, relevance=None):
    """Источник = единица precision/miss; waste взвешен оценкой токенов источника.

    Разметка — отдельное свидетельство, не required/optional и не эвристика compiler.
    Без полной разметки ВСЕХ поданных источников доли остаются неизвестными.
    """
    unknown = {"status": "unknown", "precision": None, "waste": None, "miss": None,
               "basis": "explicit-source-labels", "unlabelled_sources": sorted({i["source"] for i in items})}
    if relevance is None:
        return unknown
    if not isinstance(relevance, dict) or not isinstance(relevance.get("evidence"), str) or not relevance["evidence"].strip():
        raise ValueError("relevance: нужна ссылка/описание evidence разметки")
    for key in ("relevant", "irrelevant"):
        if not isinstance(relevance.get(key), list) or any(not isinstance(x, str) or not x for x in relevance[key]):
            raise ValueError(f"relevance.{key}: нужен список source id")
    relevant, irrelevant = set(relevance["relevant"]), set(relevance["irrelevant"])
    if relevant & irrelevant:
        raise ValueError("relevance: противоречивая разметка")
    loaded = {i["source"] for i in items}
    unlabelled = sorted(loaded - relevant - irrelevant)
    missing = sorted(relevant - loaded)
    result = {**unknown, "evidence": relevance["evidence"], "unlabelled_sources": unlabelled,
              "missing_relevant": missing, "loaded_sources": len(loaded), "relevant_sources": len(relevant)}
    if unlabelled:
        result["status"] = "incomplete_labels"
        return result
    total_tokens = sum(i["tokens"] for i in items)
    return {**result, "status": "measured", "precision": len(loaded & relevant) / len(loaded) if loaded else None,
            "waste": sum(i["tokens"] for i in items if i["source"] in irrelevant) / total_tokens if total_tokens else None,
            "miss": len(missing) / len(relevant) if relevant else None}
