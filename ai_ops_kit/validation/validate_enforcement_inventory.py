#!/usr/bin/env python3
"""Инвентарь «объявлено → исполняется»: каждый заявленный механизм контроля доказывает, что работает.

Аудит 2026-09-09 (§6) назвал КОРЕНЬ, а не находку: три из трёх старших находок — один класс
«объявлено, но не исполняется» (mypy в [dev] и нигде не гоняется; число в README не подключено к
заверению; гейт слоёв мерил не предмет). Каждый раз это ловил внешний глаз, а не машина. Здесь класс
держится машиной.

Проверяется два инварианта против `registry/enforcement-inventory.yaml`:
  * ОХВАТ — каждый dev-инструмент (requirements-dev.txt + pyproject `dev = [...]`), каждый
    pre-commit-ХУК (`.pre-commit-config.yaml`) и каждый ратчет-baseline (`packages/*baseline*.yaml`)
    перечислен в инвентаре; лишняя запись (объявления уже нет) тоже краснеет — реестр, разрешающий
    несуществующее, перестаёт что-либо значить;
  * РЕЗОЛЮЦИЯ — `enforced` инструмент/хук обязан иметь `enforced_at`, чей паттерн реально находится в
    названном файле (доказательство «вызывается вот здесь» не может протухнуть молча); `unenforced`
    (для dev-инструмента) и `local_only` (для хука — гоняется локально pre-commit'ом, в CI не
    зеркалён) обязаны иметь причину; каждый baseline обязан реально читаться своим
    `consumed_by`-валидатором.

Использование:
  validate_enforcement_inventory.py            # проверить
  validate_enforcement_inventory.py --report   # напечатать опись объявленного и её статусы
Возврат 0 — чисто, 1 — есть нарушения.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[1])
SPEC = PKG / "registry" / "enforcement-inventory.yaml"


def load_spec(path=SPEC):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _normalize(dep: str) -> str:
    """Имя пакета из строки зависимости: `pytest-cov>=4.0` -> `pytest-cov`."""
    return re.split(r"[>=<~!\[ ]", dep.strip(), maxsplit=1)[0].strip().lower()


def declared_dev_tools(pkg=PKG) -> set[str]:
    """Объявленные dev-инструменты: requirements-dev.txt + строка `dev = [...]` из pyproject.toml.

    Оба источника, а не один: разойдись они — расхождение само есть дефект охвата.
    """
    names: set[str] = set()
    req = pkg / "requirements-dev.txt"
    if req.is_file():
        for line in req.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-r ") or line.startswith("-"):
                continue
            names.add(_normalize(line))
    pyproject = pkg / "pyproject.toml"
    if pyproject.is_file():
        m = re.search(r"^dev\s*=\s*\[([^\]]*)\]", pyproject.read_text(encoding="utf-8"), re.M)
        if m:
            for dep in re.findall(r'"([^"]+)"', m.group(1)):
                names.add(_normalize(dep))
    return {n for n in names if n}


def declared_hooks(pkg=PKG) -> set[str]:
    """Объявленные pre-commit-хуки: id всех хуков из `.pre-commit-config.yaml`.

    Источник — сам конфиг pre-commit'а: объявлен хук — обязан быть в инвентаре либо с доказательством
    зеркала в CI (`enforced`), либо честно `local_only` с причиной, почему в CI его нет.
    """
    cfg = pkg / ".pre-commit-config.yaml"
    if not cfg.is_file():
        return set()
    data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    ids: set[str] = set()
    for repo in data.get("repos") or []:
        for hook in repo.get("hooks") or []:
            hid = hook.get("id")
            if hid:
                ids.add(hid)
    return ids


def declared_baselines(pkg=PKG) -> set[str]:
    """Ратчет-baseline'ы по факту дерева: packages/*baseline*.yaml (относительные пути)."""
    d = pkg / "packages"
    if not d.is_dir():
        return set()
    return {p.relative_to(pkg).as_posix() for p in d.glob("*baseline*.yaml")}


def _resolves(pkg, file_rel, pattern) -> bool:
    p = pkg / file_rel
    if not p.is_file():
        return False
    return pattern in p.read_text(encoding="utf-8", errors="replace")


def check(spec, pkg=PKG):
    errors = []
    spec = spec or {}
    tools = spec.get("dev_tools") or []
    hooks = spec.get("pre_commit_hooks") or []
    baselines = spec.get("ratchet_baselines") or []

    # ─── охват: объявленное == инвентаризованное ───
    inv_tools = {t.get("name", "").lower() for t in tools}
    declared = declared_dev_tools(pkg)
    for missing in sorted(declared - inv_tools):
        errors.append(f"dev-инструмент '{missing}' объявлен в зависимостях, но не в инвентаре — "
                      "молча необъявленное исполнение (или неисполнение) невидимо")
    for stale in sorted(inv_tools - declared):
        errors.append(f"dev-инструмент '{stale}' есть в инвентаре, но не объявлен в зависимостях — "
                      "мёртвая запись, удалить")

    inv_hooks = {h.get("id", "") for h in hooks}
    declared_h = declared_hooks(pkg)
    for missing in sorted(declared_h - inv_hooks):
        errors.append(f"pre-commit-хук '{missing}' объявлен в .pre-commit-config.yaml, но не в "
                      "инвентаре — молча необъявленное исполнение (или неисполнение) невидимо")
    for stale in sorted(inv_hooks - declared_h):
        errors.append(f"pre-commit-хук '{stale}' есть в инвентаре, но не объявлен в "
                      ".pre-commit-config.yaml — мёртвая запись, удалить")

    inv_bl = {b.get("name", "") for b in baselines}
    real_bl = declared_baselines(pkg)
    for missing in sorted(real_bl - inv_bl):
        errors.append(f"ратчет-baseline '{missing}' существует, но не в инвентаре — "
                      "заратчено может оказаться никем не прочитанным")
    for stale in sorted(inv_bl - real_bl):
        errors.append(f"ратчет-baseline '{stale}' в инвентаре, но файла нет — мёртвая запись")

    # ─── резолюция: доказательство реально находится ───
    for t in tools:
        name = t.get("name", "?")
        status = t.get("status")
        if status == "enforced":
            ea = t.get("enforced_at") or {}
            if not (ea.get("file") and ea.get("pattern")):
                errors.append(f"'{name}': status enforced без enforced_at.file/pattern — "
                              "заявленное исполнение ничем не подтверждено")
            elif not _resolves(pkg, ea["file"], ea["pattern"]):
                errors.append(f"'{name}': enforced_at не резолвится — паттерна {ea['pattern']!r} "
                              f"нет в {ea['file']}; доказательство протухло")
        elif status == "unenforced":
            if not (t.get("reason") or "").strip():
                errors.append(f"'{name}': status unenforced без причины — необъяснённое «объявлено, "
                              "но не исполняется» и есть тот самый класс дефекта")
        else:
            errors.append(f"'{name}': неизвестный status {status!r} (ожидается enforced/unenforced)")

    for h in hooks:
        hid = h.get("id", "?")
        status = h.get("status")
        if status == "enforced":
            ea = h.get("enforced_at") or {}
            if not (ea.get("file") and ea.get("pattern")):
                errors.append(f"хук '{hid}': status enforced без enforced_at.file/pattern — "
                              "заявленное зеркало в CI ничем не подтверждено")
            elif not _resolves(pkg, ea["file"], ea["pattern"]):
                errors.append(f"хук '{hid}': enforced_at не резолвится — паттерна {ea['pattern']!r} "
                              f"нет в {ea['file']}; доказательство зеркала протухло")
        elif status == "local_only":
            if not (h.get("reason") or "").strip():
                errors.append(f"хук '{hid}': status local_only без причины — необъяснённое «в CI не "
                              "зеркалён» и есть тот самый класс дефекта")
        else:
            errors.append(f"хук '{hid}': неизвестный status {status!r} (ожидается enforced/local_only)")

    for b in baselines:
        name = b.get("name", "?")
        consumer = b.get("consumed_by")
        if not consumer:
            errors.append(f"baseline '{name}': нет consumed_by — некому его читать")
            continue
        cp = pkg / consumer
        if not cp.is_file():
            errors.append(f"baseline '{name}': consumed_by '{consumer}' — файла нет")
        elif Path(name).name not in cp.read_text(encoding="utf-8", errors="replace"):
            errors.append(f"baseline '{name}': '{consumer}' его не упоминает — заявленный потребитель "
                          "его не читает, ратчет может быть мёртвым")
    return errors


def _report(spec, pkg=PKG):
    lines = ["Инвентарь «объявлено -> исполняется»:"]
    for t in spec.get("dev_tools") or []:
        where = (t.get("enforced_at") or {}).get("file", t.get("reason", "")[:60])
        lines.append(f"  dev  {t.get('name'):16} {t.get('status'):11} {where}")
    for h in spec.get("pre_commit_hooks") or []:
        where = (h.get("enforced_at") or {}).get("file", h.get("reason", "")[:60])
        lines.append(f"  hook {h.get('id'):24} {h.get('status'):11} {where}")
    for b in spec.get("ratchet_baselines") or []:
        lines.append(f"  base {Path(b.get('name','')).name:34} <- {b.get('consumed_by')}")
    return "\n".join(lines)


def main(argv):
    spec = load_spec()
    if "--report" in argv:
        print(_report(spec))
        return 0
    errors = check(spec)
    for e in errors:
        print(f"  [FAIL] {e}")
    if errors:
        print(f"ENFORCEMENT-INVENTORY-FAIL: нарушений {len(errors)}")
        return 1
    tools = spec.get("dev_tools") or []
    hooks = spec.get("pre_commit_hooks") or []
    unenf = sum(1 for t in tools if t.get("status") == "unenforced")
    local = sum(1 for h in hooks if h.get("status") == "local_only")
    print(f"ENFORCEMENT-INVENTORY-OK: {len(tools)} dev-инструментов "
          f"({unenf} честно unenforced), {len(hooks)} pre-commit-хуков ({local} честно local_only), "
          f"{len(spec.get('ratchet_baselines') or [])} baseline'ов — "
          "все объявления покрыты, доказательства резолвятся.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
