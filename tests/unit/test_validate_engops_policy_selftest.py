"""Селфтест validate_engops_policy, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from validate_engops_policy import (  # noqa: F401 — имена, которые использует тело
    Path,
    check_child,
    check_parity,
    check_policy,
)


@pytest.mark.slow
def test_validate_engops_policy_selftest():
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
           any("неизвестные ключи" in e for e in check_policy({"observability": {}})))
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

    # --- v3.20.0 срез 2: окружения и deploy -------------------------------------------------------
    expect("environments отсутствуют -> связно", check_policy({"environments": None}) == [])
    expect("окружения строками связны", check_policy({"environments": ["staging", "production"]}) == [])
    ok_envs = {"environments": [{"name": "production", "kind": "production", "approvers": ["owner"],
                                 "secret_names": ["DEPLOY_TOKEN"]}]}
    expect("полное объявление окружения связно", check_policy(ok_envs) == [])
    expect("environments не список -> отклоняется", check_policy({"environments": {}}) != [])
    expect("окружение без name -> отклоняется",
           check_policy({"environments": [{"kind": "staging"}]}) != [])
    expect("дубль окружения -> отклоняется",
           any("дважды" in e for e in check_policy({"environments": ["prod", "prod"]})))
    expect("неизвестный kind окружения -> отклоняется",
           check_policy({"environments": [{"name": "x", "kind": "чепуха"}]}) != [])
    expect("неизвестный ключ окружения -> отклоняется",
           check_policy({"environments": [{"name": "x", "url": "https://x"}]}) != [])
    expect("approvers не список строк -> отклоняется",
           check_policy({"environments": [{"name": "x", "approvers": "owner"}]}) != [])
    expect("secret_names как ЗНАЧЕНИЕ секрета -> отклоняется",
           any("значения запрещены" in e or "ЗНАЧЕНИЕ" in e for e in check_policy(
               {"environments": [{"name": "x", "secret_names": ["sk-abcdefghijklmnopqrstuvwx"]}]})))
    expect("secret_names с пробелом/дефисом -> отклоняется (не имя переменной)",
           check_policy({"environments": [{"name": "x", "secret_names": ["MY KEY"]}]}) != [])

    expect("deploy отсутствует -> связно", check_policy({"deploy": None}) == [])
    expect("deploy_command + rollback связны",
           check_policy({"deploy": {"deploy_command": "make deploy", "rollback": "make rollback"}}) == [])
    expect("deploy_command БЕЗ rollback -> отклоняется (нельзя отменить = не готовность)",
           any("нельзя отменить" in e for e in check_policy({"deploy": {"deploy_command": "make deploy"}})))
    expect("rollback без deploy_command допустим", check_policy({"deploy": {"rollback": "make undo"}}) == [])
    expect("deploy не объект -> отклоняется", check_policy({"deploy": []}) != [])
    expect("неизвестный ключ deploy -> отклоняется",
           check_policy({"deploy": {"strategy": "canary"}}) != [])
    expect("пустая строка в deploy_command -> отклоняется",
           check_policy({"deploy": {"deploy_command": "  ", "rollback": "x"}}) != [])
    expect("литеральный секрет в deploy_command -> отклоняется",
           any("литеральный секрет" in e for e in check_policy(
               {"deploy": {"deploy_command": "deploy --token ghp_abcdefghijklmnopqrstuvwxyz012345",
                           "rollback": "undo"}})))

    # --- v3.21.0 срез 3: экономика -----------------------------------------------------------------
    expect("economics отсутствует -> связно", check_policy({"economics": None}) == [])
    expect("корректная экономика связна",
           check_policy({"economics": {"enforce": "advise", "confirm_over_cost_usd": 5,
                                       "min_history_tasks": 3}}) == [])
    expect("confirm_over_cost_usd: null допустим (подтверждение не требуется)",
           check_policy({"economics": {"confirm_over_cost_usd": None}}) == [])
    expect("economics не объект -> отклоняется", check_policy({"economics": []}) != [])
    expect("неизвестный ключ economics -> отклоняется",
           check_policy({"economics": {"max_cost": 5}}) != [])
    expect("отрицательный порог подтверждения -> отклоняется",
           check_policy({"economics": {"confirm_over_cost_usd": -1}}) != [])
    expect("min_history_tasks=0 -> отклоняется",
           check_policy({"economics": {"min_history_tasks": 0}}) != [])
    expect("require_estimate не boolean -> отклоняется",
           check_policy({"economics": {"require_estimate": "да"}}) != [])
    expect("require_estimate=true при enforce=advise -> противоречие (заблокирует первый прогон)",
           any("противоречие" in e for e in check_policy(
               {"economics": {"require_estimate": True, "enforce": "advise"}})))
    expect("require_estimate=true при enforce=block -> осознанный выбор, связно",
           check_policy({"economics": {"require_estimate": True, "enforce": "block"}}) == [])

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

    assert ok, "перенесённый селфтест validate_engops_policy: см. строки FAIL в выводе"
