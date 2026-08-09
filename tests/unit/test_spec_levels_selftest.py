"""Селфтест spec_levels, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from spec_levels import (  # noqa: F401 — имена, которые использует тело
    LEVEL_SECTIONS,
    Path,
    assess,
    assess_from_artifacts,
    classify,
    create_spec,
    provided_from_artifacts,
    required_sections,
    validate_spec,
)


@pytest.mark.slow
def test_spec_levels_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    expect("QUICK -> L0", classify({"task_type": "QUICK"})["level"] == 0)
    expect("ENGINEERING -> L1", classify({"task_type": "ENGINEERING"})["level"] == 1)
    expect("PRODUCT -> L2", classify({"task_type": "PRODUCT"})["level"] == 2)
    expect("CRITICAL -> L3", classify({"task_type": "CRITICAL"})["level"] == 3)
    # эскалация по риску
    esc = classify({"task_type": "QUICK", "risk": "critical"})
    expect("QUICK + risk=critical -> эскалация до L3", esc["level"] == 3
           and any("эскалация" in r for r in esc["reason"]))
    esc2 = classify({"task_type": "ENGINEERING", "secret_boundary": True})
    expect("ENGINEERING + secret_boundary -> L3", esc2["level"] == 3)
    esc3 = classify({"task_type": "QUICK", "measurable_behavior": True, "user_facing_change": True})
    expect("QUICK + измеримое польз. изменение -> L2", esc3["level"] == 2)
    # нельзя понизить молча
    low = classify({"task_type": "ENGINEERING", "requested_level": 0})
    expect("запрос L0 при ENGINEERING -> остаётся L1 + note (не понизили молча)",
           low["level"] == 1 and low["escalated_from"] == 0)
    high = classify({"task_type": "QUICK", "requested_level": 2})
    expect("запрос выше -> принят (повышение разрешено)", high["level"] == 2)

    # кумулятивность разделов
    expect("L1 включает разделы L0 и L1", set(LEVEL_SECTIONS[0]) <= set(required_sections(1))
           and "verification_strategy" in required_sections(1))
    expect("L3 включает threat_model + разделы всех уровней",
           "threat_model" in required_sections(3) and "goal" in required_sections(3))

    # assess: пустой QUICK -> все missing -> не готов к реализации
    a0 = assess({"task_type": "QUICK"})
    expect("пустой QUICK -> blocking_missing непуст, ready_to_implement=False",
           a0["blocking_missing"] and a0["ready_to_implement"] is False)
    # полный QUICK -> готов
    full = {s: {"status": "complete"} for s in LEVEL_SECTIONS[0]}
    a1 = assess({"task_type": "QUICK"}, full)
    expect("полный QUICK -> ready_to_implement=True", a1["ready_to_implement"] is True
           and a1["blocking_missing"] == [])
    # not_applicable закрывает раздел (не блокирует)
    na = {s: {"status": "not_applicable", "note": "нет UI"} for s in LEVEL_SECTIONS[0]}
    expect("not_applicable не блокирует", assess({"task_type": "QUICK"}, na)["ready_to_implement"] is True)
    # declined без note -> form_error
    dec = dict(full); dec["scope"] = {"status": "declined"}
    expect("declined без объяснения -> form_error + не готов",
           assess({"task_type": "QUICK"}, dec)["form_errors"] and
           assess({"task_type": "QUICK"}, dec)["ready_to_implement"] is False)
    # needs_human фиксируется
    nh = dict(full); nh["constraints"] = {"status": "needs_human", "note": "нужен владелец"}
    expect("needs_human зафиксирован", "constraints" in assess({"task_type": "QUICK"}, nh)["needs_human"])

    # v2.110 Real Spec-First: create_spec реально создаёт артефакт нужной глубины
    import tempfile
    import yaml
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sig_eng = {"task_type": "ENGINEERING", "affected_areas": ["core"]}
        sp, created = create_spec(root, "sf", sig_eng)
        expect("v2.110 create_spec: артефакт создан на диске", created and sp.is_file())
        doc = yaml.safe_load(sp.read_text(encoding="utf-8"))
        expect("v2.110 create_spec: разделы уровня L1 в артефакте (заготовки missing)",
               "requirements" in doc["sections"] and doc["sections"]["goal"]["status"] == "missing"
               and doc["level"] == 1)
        # повторный create без overwrite не перезаписывает (не теряем описанное)
        _, created2 = create_spec(root, "sf", sig_eng)
        expect("v2.110 create_spec: без overwrite не перезаписывает", created2 is False)

        # пустой spec (всё missing) -> assess_from_artifacts НЕ готов, spec_artifact=True
        cov0 = assess_from_artifacts(sig_eng, root, "sf")
        expect("v2.110 from_artifacts: пустой spec -> ready_to_implement=False + spec_artifact=True",
               cov0["ready_to_implement"] is False and cov0["spec_artifact"] is True
               and cov0["blocking_missing"])

        # заполнить разделы L0/L1 в spec.yaml -> покрытие растёт (из РЕАЛЬНОГО артефакта)
        for sid in doc["sections"]:
            doc["sections"][sid] = {"status": "complete", "content": "x"}
        sp.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
        cov1 = assess_from_artifacts(sig_eng, root, "sf")
        expect("v2.110 from_artifacts: заполненный spec.yaml -> ready_to_implement=True (реально из файла)",
               cov1["ready_to_implement"] is True and not cov1["blocking_missing"])

        # засчёт по артефакту прогона: requirements.yaml закрывает раздел requirements
        with tempfile.TemporaryDirectory() as td2:
            wr = Path(td2)
            (wr / ".ai" / "runplan" / "art").mkdir(parents=True)
            (wr / ".ai" / "runplan" / "art" / "requirements.yaml").write_text("k: v\n", encoding="utf-8")
            prov = provided_from_artifacts(root, "art", work_root=wr)
            expect("v2.110 credit: requirements.yaml засчитывает раздел requirements",
                   prov.get("requirements", {}).get("status") == "complete"
                   and "requirements.yaml" in (prov["requirements"].get("note") or ""))

        # validate_spec без артефакта -> честная пометка об отсутствии (не притворяется)
        cov_none = validate_spec(root, "never", sig_eng)
        expect("v2.110 validate_spec: нет spec.yaml -> spec_artifact=False + note (честно)",
               cov_none["spec_artifact"] is False and "note" in cov_none)

    assert ok, "перенесённый селфтест spec_levels: см. строки FAIL в выводе"
