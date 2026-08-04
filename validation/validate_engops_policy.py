#!/usr/bin/env python3
"""validate_engops_policy.py (v3.19.0 Engineering Operating Model, срез 1) — well-formedness политики
EngOps и ПАРИТЕТ дефолтов «код ↔ правило».

Две проверки, каждая ловит свой класс дрейфа:

1. **Политика репозитория связна.** `engineering_operating_model` в `.ai-ops.yaml` (если объявлен) не
   должен содержать взаимно противоречащих порогов. Пример настоящего противоречия:
   `base_drift_advisory >= base_drift_stale` — тогда предупреждение об отставании не срабатывает
   никогда, а репозиторий уверен, что настроил контроль. Молча «работающая» политика, которая ничего
   не проверяет, хуже отсутствующей.

2. **Правило не расходится с кодом.** `rules/core/EngineeringOperatingModel.md` печатает пороги
   в yaml-блоке; `tools/commit_policy.py` и `tools/branch_policy.py` держат их в `DEFAULTS`. Это два
   места для одного числа — ровно тот шов, на котором кит уже ловил дрейф (release-claims). Валидатор
   сверяет их дословно.

Использование:  validate_engops_policy.py [child_root]   — проверить политику репозитория + паритет
                validate_engops_policy.py --selftest
Возврат 0 — связно и без дрейфа, 1 — есть нарушение.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]
RULE_DOC = PKG / "rules" / "core" / "EngineeringOperatingModel.md"

_ENFORCE_VALUES = ("advise", "block")
_COMMIT_KEYS = ("enforce", "max_files", "max_top_level_dirs", "min_message_chars",
                "require_workitem", "require_evidence")
_BRANCH_KEYS = ("enforce", "branch_prefix", "protected_refs", "base_drift_advisory",
                "base_drift_stale", "max_branch_age_days", "one_workitem_per_branch")


def _load_tool_defaults():
    """DEFAULTS из обоих инструментов. -> (commit_defaults, branch_defaults)."""
    sys.path.insert(0, str(PKG / "tools"))
    import branch_policy
    import commit_policy
    return dict(commit_policy.DEFAULTS), dict(branch_policy.DEFAULTS)


def check_policy(policy):
    """Связность объявленной политики. -> список нарушений (строк). policy может быть {} / None."""
    errs = []
    pol = policy or {}
    if not isinstance(pol, dict):
        return ["engineering_operating_model: ожидался объект"]

    unknown = set(pol) - {"commit", "branch"}
    if unknown:
        errs.append(f"engineering_operating_model: неизвестные ключи {sorted(unknown)} "
                    f"(допустимы commit, branch)")

    commit = pol.get("commit") or {}
    branch = pol.get("branch") or {}
    if not isinstance(commit, dict):
        errs.append("engineering_operating_model.commit: ожидался объект")
        commit = {}
    if not isinstance(branch, dict):
        errs.append("engineering_operating_model.branch: ожидался объект")
        branch = {}

    for name, block, allowed in (("commit", commit, _COMMIT_KEYS), ("branch", branch, _BRANCH_KEYS)):
        bad = set(block) - set(allowed)
        if bad:
            errs.append(f"engineering_operating_model.{name}: неизвестные ключи {sorted(bad)}")
        enf = block.get("enforce")
        if enf is not None and enf not in _ENFORCE_VALUES:
            errs.append(f"engineering_operating_model.{name}.enforce='{enf}' вне {list(_ENFORCE_VALUES)}")
        for key in allowed:
            if key in ("enforce", "branch_prefix", "protected_refs",
                       "require_workitem", "require_evidence", "one_workitem_per_branch"):
                continue
            val = block.get(key)
            if val is not None and (not isinstance(val, int) or isinstance(val, bool) or val < 1):
                errs.append(f"engineering_operating_model.{name}.{key}={val!r}: ожидалось целое ≥ 1")

    adv, stale = branch.get("base_drift_advisory"), branch.get("base_drift_stale")
    if isinstance(adv, int) and isinstance(stale, int) and not isinstance(adv, bool) \
            and not isinstance(stale, bool) and adv >= stale:
        errs.append(f"base_drift_advisory ({adv}) >= base_drift_stale ({stale}): предупреждение об "
                    f"отставании не сработает никогда — политика выглядит настроенной, но не проверяет")

    refs = branch.get("protected_refs")
    if refs is not None:
        if not isinstance(refs, list) or not refs:
            errs.append("protected_refs: ожидался непустой список (пустой = защиты нет)")
        elif not all(isinstance(r, str) and r.strip() for r in refs):
            errs.append("protected_refs: все записи — непустые строки")

    prefix = branch.get("branch_prefix")
    if prefix is not None:
        if not isinstance(prefix, str) or not prefix.strip():
            errs.append("branch_prefix: ожидалась непустая строка")
        elif isinstance(refs, list) and any(isinstance(r, str) and r == prefix.rstrip("/")
                                            for r in refs):
            errs.append(f"branch_prefix '{prefix}' совпадает с защищённой веткой — ветка доставки "
                        f"обязана быть и правильно названной, и незащищённой одновременно")
    return errs


def _rule_doc_defaults(doc_text):
    """Достать yaml-блок конфигурации из правила. -> {'commit': {...}, 'branch': {...}} либо {}."""
    for block in re.findall(r"```yaml\n(.*?)```", doc_text, re.DOTALL):
        if "engineering_operating_model:" not in block:
            continue
        cleaned = re.sub(r"[ \t]+#.*$", "", block, flags=re.MULTILINE)
        try:
            data = yaml.safe_load(cleaned) or {}
        except yaml.YAMLError as e:
            return {"__error__": f"yaml-блок правила не парсится: {e}"}
        return data.get("engineering_operating_model") or {}
    return {}


def check_parity(rule_doc=RULE_DOC):
    """Пороги в правиле == DEFAULTS в коде. -> список нарушений."""
    doc = Path(rule_doc)
    if not doc.is_file():
        return [f"{doc}: правило EngineeringOperatingModel отсутствует"]
    declared = _rule_doc_defaults(doc.read_text(encoding="utf-8"))
    if "__error__" in declared:
        return [declared["__error__"]]
    if not declared:
        return [f"{doc.name}: не найден yaml-блок с engineering_operating_model"]

    commit_defaults, branch_defaults = _load_tool_defaults()
    errs = []
    for name, code in (("commit", commit_defaults), ("branch", branch_defaults)):
        doc_block = declared.get(name) or {}
        missing = set(code) - set(doc_block)
        if missing:
            errs.append(f"{doc.name} → {name}: в правиле не описаны пороги {sorted(missing)} "
                        f"(есть в DEFAULTS кода)")
        for key, doc_val in doc_block.items():
            if key not in code:
                errs.append(f"{doc.name} → {name}.{key}: правило описывает порог, которого нет в коде")
            elif code[key] != doc_val:
                errs.append(f"дрейф {name}.{key}: правило={doc_val!r}, код={code[key]!r}")
    return errs


def check_child(child_root):
    """Политика из .ai-ops.yaml репозитория (если он есть) + паритет правила и кода."""
    errs = list(check_parity())
    for name in (".ai-ops.yaml", ".ai-ops.yml"):
        cfg = Path(child_root) / name
        if not cfg.is_file():
            continue
        try:
            data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            return errs + [f"{name}: не парсится ({e})"]
        if "engineering_operating_model" in data:
            errs += check_policy(data.get("engineering_operating_model"))
        break
    return errs


def selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    expect("пустая политика связна", check_policy({}) == [])
    expect("None связна", check_policy(None) == [])
    expect("политика-не-объект отклоняется", check_policy(["x"]) != [])

    full = {"commit": {"enforce": "block", "max_files": 10},
            "branch": {"enforce": "advise", "base_drift_advisory": 20, "base_drift_stale": 100,
                       "protected_refs": ["main"], "branch_prefix": "ai-ops/"}}
    expect("полная корректная политика связна", check_policy(full) == [])

    bad_order = {"branch": {"base_drift_advisory": 100, "base_drift_stale": 20}}
    expect("advisory >= stale отклоняется (немой контроль)",
           any("не сработает никогда" in e for e in check_policy(bad_order)))
    expect("advisory == stale тоже отклоняется",
           check_policy({"branch": {"base_drift_advisory": 50, "base_drift_stale": 50}}) != [])

    expect("enforce вне перечисления отклоняется",
           any("enforce" in e for e in check_policy({"commit": {"enforce": "force"}})))
    expect("неизвестный ключ верхнего уровня отклоняется",
           any("неизвестные ключи" in e for e in check_policy({"deploy": {}})))
    expect("неизвестный ключ в commit отклоняется",
           any("неизвестные ключи" in e for e in check_policy({"commit": {"max_lines": 5}})))
    expect("нулевой/отрицательный порог отклоняется",
           check_policy({"commit": {"max_files": 0}}) != []
           and check_policy({"branch": {"max_branch_age_days": -3}}) != [])
    expect("bool вместо числа отклоняется", check_policy({"commit": {"max_files": True}}) != [])
    expect("пустой protected_refs отклоняется (защиты нет)",
           any("непустой список" in e for e in check_policy({"branch": {"protected_refs": []}})))
    expect("protected_refs не список -> отклоняется",
           check_policy({"branch": {"protected_refs": "main"}}) != [])
    expect("branch_prefix == защищённая ветка -> противоречие",
           any("совпадает с защищённой" in e for e in check_policy(
               {"branch": {"branch_prefix": "main/", "protected_refs": ["main"]}})))
    expect("пустой branch_prefix отклоняется",
           check_policy({"branch": {"branch_prefix": "  "}}) != [])

    expect("паритет правила и кода соблюдён (реальные файлы)", check_parity() == [])

    with tempfile.TemporaryDirectory() as td:
        doc = Path(td) / "rule.md"
        doc.write_text("```yaml\nengineering_operating_model:\n  commit:\n    max_files: 999\n"
                       "  branch:\n    base_drift_stale: 100\n```\n", encoding="utf-8")
        errs = check_parity(doc)
        expect("дрейф порога правило↔код ловится", any("дрейф commit.max_files" in e for e in errs))
        expect("непокрытые правилом пороги ловятся", any("не описаны пороги" in e for e in errs))
        doc.write_text("нет yaml-блока\n", encoding="utf-8")
        expect("правило без yaml-блока отклоняется",
               any("не найден yaml-блок" in e for e in check_parity(doc)))
        doc.write_text("```yaml\nengineering_operating_model:\n  commit:\n   {{битый\n```\n",
                       encoding="utf-8")
        expect("битый yaml-блок правила отклоняется", check_parity(doc) != [])
        expect("отсутствующее правило отклоняется", check_parity(Path(td) / "нет.md") != [])

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        expect("репозиторий без .ai-ops.yaml -> только паритет", check_child(root) == [])
        (root / ".ai-ops.yaml").write_text(
            "engineering_operating_model:\n  branch:\n    base_drift_advisory: 200\n"
            "    base_drift_stale: 100\n", encoding="utf-8")
        expect("противоречие в .ai-ops.yaml репозитория ловится", check_child(root) != [])
        (root / ".ai-ops.yaml").write_text("engineering_operating_model:\n  commit:\n    enforce: block\n",
                                           encoding="utf-8")
        expect("корректная политика репозитория проходит", check_child(root) == [])
        (root / ".ai-ops.yaml").write_text("{{ битый", encoding="utf-8")
        expect("битый .ai-ops.yaml отклоняется", check_child(root) != [])

    print("validate_engops_policy selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    root = argv[0] if argv and not argv[0].startswith("--") else "."
    errs = check_child(root)
    if errs:
        for e in errs:
            print(f"  FAIL {e}")
        print(f"validate_engops_policy: FAIL ({len(errs)})")
        return 1
    print("validate_engops_policy: OK (политика связна, правило не расходится с кодом)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
