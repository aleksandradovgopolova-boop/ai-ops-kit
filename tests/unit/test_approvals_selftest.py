"""Селфтест approvals, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from approvals import (  # noqa: F401 — имена, которые использует тело
    Path,
    _is_high_risk,
    check,
    covers_dependency,
    covers_paths,
    load_domains,
    plan_binding_hash,
    recheck_after_diff,
    recheck_dependencies,
    required_approvals,
    signals_from_findings,
    write_record,
)


def _plant_plan(root, wid, body="base_workflow: ENGINEERING\ngates: [a]\n"):
    """План на диске — предусловие ЛЮБОГО одобрения с v3.37: привязка к содержимому безусловна,
    поэтому связывать одобрение не с чем, пока нет run-plan.yaml/spec.yaml."""
    fdir = Path(root) / "features" / str(wid)
    fdir.mkdir(parents=True, exist_ok=True)
    (fdir / "run-plan.yaml").write_text(body, encoding="utf-8")
    return fdir


def _plant_legacy_record(root, wid, approval, **fields):
    """Запись БЕЗ binds_to — такие лежат на дисках дочек с версий до v3.37. Пишем YAML напрямую:
    `write_record` создать её больше не может, а проверять поведение на ней надо."""
    import yaml
    d = Path(root) / "features" / str(wid) / "approvals"
    d.mkdir(parents=True, exist_ok=True)
    rec = {"schema_version": 1, "kind": "ApprovalRecord", "approval": approval,
           "approved_by": "u@x", "scope": "package.json", "reason": "legacy",
           "created_at": "2026-07-05T00:00:00Z", **fields}
    (d / f"{approval}.yaml").write_text(yaml.safe_dump(rec, allow_unicode=True), encoding="utf-8")


@pytest.mark.slow
def test_approvals_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    doms = load_domains()
    expect("домены загружены с human_approval_conditions",
           any(d.get("human_approval_conditions") for d in doms))

    # required: secret_boundary -> secrets; dependency_addition -> dependencies; auth_change -> auth+authz
    req_s = {r["domain"] for r in required_approvals({"secret_boundary": True})}
    expect("required: secret_boundary -> домен secrets", "secrets" in req_s)
    req_d = {r["domain"] for r in required_approvals({"dependency_addition": True})}
    expect("required: dependency_addition -> домен dependencies", "dependencies" in req_d)
    req_a = {r["domain"] for r in required_approvals({"auth_change": True})}
    expect("required: auth_change -> authentication + authorization", "authentication" in req_a and "authorization_idol" in req_a)
    expect("required: чистые сигналы -> одобрений не требуется", required_approvals({"task_type": "QUICK"}) == [])

    # v2.123 (P0.2): findings-derived сигналы — новая зависимость/секрет из РЕАЛЬНОГО диффа
    spr = {"results": [{"domain": "dependencies", "findings": [{"type": "new_dependency", "name": "requests"}]},
                       {"domain": "secrets", "findings": [{"type": "secret", "path": "x", "line": 1, "id": "s"}]}]}
    dsig = signals_from_findings(spr)
    expect("v2.123: new_dependency finding -> dependency_addition", dsig.get("dependency_addition") is True)
    expect("v2.123: secret finding -> secret_boundary", dsig.get("secret_boundary") is True)
    expect("v2.123: находка новой зависимости -> требуется одобрение dependencies (пост-дифф)",
           "dependencies" in {r["domain"] for r in required_approvals(dsig)})
    expect("v2.123: пустой pack -> нет производных сигналов", signals_from_findings({}) == {})

    # v3.0-rc5 (P1.2): semantic dependency approval — покрытие по имени пакета, не по пути файла
    _f = {"type": "new_dependency", "name": "requests", "version": "2.32.0", "manifest": "requirements.txt"}
    expect("v3.0-rc5: covers_dependency — approval без covers_packages НЕ покрывает (path-only мало)",
           covers_dependency({"scope": "requirements.txt"}, _f) is False)
    expect("v3.0-rc5: covers_dependency — covers_packages с ДРУГИМ пакетом НЕ покрывает",
           covers_dependency({"covers_packages": ["flask"]}, _f) is False)
    expect("v3.0-rc5: covers_dependency — covers_packages называет пакет -> покрывает",
           covers_dependency({"covers_packages": ["requests"]}, _f) is True)
    expect("v3.0-rc5: covers_dependency — точная версия совпала -> покрывает",
           covers_dependency({"covers_packages": ["requests@2.32.0"]}, _f) is True)
    expect("v3.0-rc5: covers_dependency — иная зафиксированная версия НЕ покрывает",
           covers_dependency({"covers_packages": ["requests@9.9.9"]}, _f) is False)
    with tempfile.TemporaryDirectory() as _tdd:
        _r = Path(_tdd)
        _plant_plan(_r, "wd")
        rc_no = recheck_dependencies(_r, "wd", [_f])
        expect("v3.0-rc5: recheck_dependencies — нет approval для пакета -> uncovered",
               rc_no["ok"] is False and rc_no["uncovered"][0]["name"] == "requests")
        write_record(_r, "wd", "dependencies", "u@x", "requirements.txt", "нужен http-клиент",
                     created_at="2026-07-20T00:00:00Z", source="user", covers_packages=["requests"])
        rc_yes = recheck_dependencies(_r, "wd", [_f])
        expect("v3.0-rc5: recheck_dependencies — approval с covers_packages=[requests] -> covered",
               rc_yes["ok"] is True)
        # другая зависимость в том же манифесте НЕ покрыта старым approval (широкое переиспользование закрыто)
        _f2 = {"type": "new_dependency", "name": "evil-pkg", "version": None, "manifest": "requirements.txt"}
        rc_other = recheck_dependencies(_r, "wd", [_f2])
        expect("v3.0-rc5: approval requests НЕ покрывает другую зависимость (evil-pkg) в том же манифесте",
               rc_other["ok"] is False and rc_other["uncovered"][0]["name"] == "evil-pkg")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _plant_plan(root, "wi")
        # базовые + binding-механики (v2.121) тестируем на MEDIUM-risk домене (dependencies): он аддитивен
        # (binding не обязателен). strict schema v2 для HIGH-risk — отдельным блоком ниже.
        sig = {"dependency_addition": True}
        c0 = check(sig, root, "wi")
        expect("check: требуется dependencies, записи нет -> missing + ok=False",
               c0["ok"] is False and any(m["domain"] == "dependencies" for m in c0["missing"]))
        write_record(root, "wi", "dependencies", approved_by="u@x", scope="pkg", reason="")
        c1 = check(sig, root, "wi")
        expect("check: невалидный ApprovalRecord (пустой reason) НЕ засчитан",
               c1["ok"] is False and "невалиден" in c1["missing"][0]["reason"])
        write_record(root, "wi", "dependencies", approved_by="u@x", scope="package.json",
                     reason="новая зависимость согласована", created_at="2026-07-18T10:00:00Z")
        c2 = check(sig, root, "wi")
        expect("check: валидный ApprovalRecord (medium, аддитивно) -> ok=True", c2["ok"] is True and not c2["missing"])
        c3 = check({"auth_change": True}, root, "wi")
        expect("check: запись dependencies НЕ закрывает authentication",
               c3["ok"] is False and any(m["domain"] == "authentication" for m in c3["missing"]))

        # ── v2.121 (P1.2): связывание одобрения (механика на dependencies, аддитивно) ──────────────
        write_record(root, "wi", "dependencies", "u@x", "package.json", "деп",
                     created_at="2026-07-01T00:00:00Z", expires_at="2026-07-10T00:00:00Z")
        c_exp = check(sig, root, "wi", now="2026-07-18T00:00:00Z")
        expect("v2.121: просроченное одобрение НЕ засчитано (expires_at в прошлом)",
               c_exp["ok"] is False and "просроч" in c_exp["missing"][0]["reason"])
        c_ok = check(sig, root, "wi", now="2026-07-05T00:00:00Z")
        expect("v2.121: одобрение в пределах срока -> ok", c_ok["ok"] is True)

        write_record(root, "wi", "dependencies", "u@x", "package.json", "деп",
                     created_at="2026-07-05T00:00:00Z", binds_to="planhashA")
        c_bind_ok = check(sig, root, "wi", now="2026-07-05T00:00:00Z", plan_hash="planhashA")
        c_bind_bad = check(sig, root, "wi", now="2026-07-05T00:00:00Z", plan_hash="planhashB")
        expect("v2.121: binds_to совпал с планом -> ok", c_bind_ok["ok"] is True)
        expect("v2.121: binds_to НЕ совпал (план изменился) -> одобрение невалидно",
               c_bind_bad["ok"] is False and "ревизи" in c_bind_bad["missing"][0]["reason"])

        fdir = root / "features" / "wi"
        fdir.mkdir(parents=True, exist_ok=True)
        (fdir / "run-plan.yaml").write_text("base_workflow: ENGINEERING\ngates: [a]\n", encoding="utf-8")
        h1 = plan_binding_hash(root, "wi")
        (fdir / "run-plan.yaml").write_text("base_workflow: ENGINEERING\ngates: [a, b]\n", encoding="utf-8")
        h2 = plan_binding_hash(root, "wi")
        expect("v2.121: plan_binding_hash меняется при смене плана", bool(h1) and bool(h2) and h1 != h2)

        write_record(root, "wi", "dependencies", "u@x", "package.json", "деп",
                     created_at="2026-07-05T00:00:00Z", bind_to_plan=True)
        c_live_ok = check(sig, root, "wi", now="2026-07-05T00:00:00Z")   # plan_hash берётся с диска
        (fdir / "run-plan.yaml").write_text("base_workflow: ENGINEERING\ngates: [a, b, c]\n", encoding="utf-8")
        c_live_bad = check(sig, root, "wi", now="2026-07-05T00:00:00Z")
        expect("v2.121: bind_to_plan -> ok на исходном плане", c_live_ok["ok"] is True)
        expect("v2.121: bind_to_plan -> невалидно после правки run-plan.yaml", c_live_bad["ok"] is False)

        # ── v2.121 (P1.2 п.4): recheck после диффа — scope обязан покрыть изменённые пути ─────────
        with tempfile.TemporaryDirectory() as td2:
            r2 = Path(td2)
            _plant_plan(r2, "w2")
            write_record(r2, "w2", "dependencies", "u@x", "package.json", "деп",
                         created_at="2026-07-05T00:00:00Z")
            rc_cov = recheck_after_diff(r2, "w2", ["package.json"], signals=sig, now="2026-07-05T00:00:00Z")
            rc_unc = recheck_after_diff(r2, "w2", ["src/other.py"], signals=sig, now="2026-07-05T00:00:00Z")
            expect("v2.121: recheck — scope покрывает изменённый путь -> ok", rc_cov["ok"] is True)
            expect("v2.121: recheck — изменён путь ВНЕ scope одобрения -> uncovered",
                   rc_unc["ok"] is False and rc_unc["uncovered"][0]["domain"] == "dependencies")

        # covers_paths: префикс-покрытие директории
        expect("v2.121: covers_paths — путь под scope-префиксом покрыт",
               covers_paths({"scope": "src/auth"}, ["src/auth/login.py"]) is True)
        expect("v2.121: covers_paths — путь вне scope НЕ покрыт",
               covers_paths({"scope": "src/auth"}, ["src/billing/pay.py"]) is False)

        # ── v3.37: привязка к содержимому БЕЗУСЛОВНА (отменяет аддитивность v2.121) ────────────────
        # Раньше здесь стояло обратное утверждение: «medium-домен без binds_to валиден (нет
        # регрессии)». Решение владельца 13.08.2026 по RR-014/EV-1105: одобрение без привязки не
        # отвечает на вопрос, ЧТО одобрено, и не принимается ни в одном домене.
        with tempfile.TemporaryDirectory() as td3:
            r3 = Path(td3)
            _plant_plan(r3, "w3")
            _plant_legacy_record(r3, "w3", "dependencies")           # запись с дисков до v3.37
            c_legacy = check(sig, r3, "w3", now="2026-07-18T00:00:00Z")
            expect("v3.37: medium-домен без binds_to БОЛЬШЕ НЕ валиден (привязка безусловна)",
                   c_legacy["ok"] is False and "не привязано к содержимому" in c_legacy["missing"][0]["reason"])

            # связанная запись в том же домене принимается — правило про привязку, не про домен
            write_record(r3, "w3", "dependencies", "u@x", "package.json", "деп",
                         created_at="2026-07-05T00:00:00Z")
            expect("v3.37: та же запись со связыванием -> принята",
                   check(sig, r3, "w3", now="2026-07-18T00:00:00Z")["ok"] is True)

            # привязка есть, но сверить её не с чем -> отказ (прежде такой вызов молча пропускал)
            c_unverifiable = check(sig, r3, "w3", now="2026-07-18T00:00:00Z", plan_hash="")
            expect("v3.37: привязку не с чем сверить -> запись отклонена, а не принята молча",
                   c_unverifiable["ok"] is False
                   and "не с чем сверить" in c_unverifiable["missing"][0]["reason"])

        # несвязываемое одобрение не СОЗДАЁТСЯ: отказ на записи, а не отложенный отказ на проверке
        with tempfile.TemporaryDirectory() as td3b:
            r3b = Path(td3b)
            try:
                write_record(r3b, "w3b", "dependencies", "u@x", "package.json", "деп",
                             created_at="2026-07-05T00:00:00Z")
                refused = False
            except ValueError as e:
                refused = "нечем связать" in str(e)
            expect("v3.37: без плана/спеки запись одобрения ОТКЛОНЕНА (не создаём заведомо невалидную)",
                   refused)

        # ── v2.123 (Approval schema v2): HIGH-risk (secrets) требует ПОЛНОГО binding + доверенный source ──
        with tempfile.TemporaryDirectory() as td4:
            r4 = Path(td4)
            _plant_plan(r4, "w4")
            hsig = {"secret_boundary": True}
            expect("v2.123: _is_high_risk(secrets)=True, dependencies=False (medium)",
                   _is_high_risk("secrets") and not _is_high_risk("dependencies"))
            # legacy: нет binding/source -> high-risk БОЛЬШЕ НЕ принимается
            _plant_legacy_record(r4, "w4", "secrets", scope="config/s.py")
            c_legacy = check(hsig, r4, "w4", now="2026-07-05T00:00:00Z", plan_hash="P")
            expect("v3.37: high-risk legacy-запись без binding -> НЕ принята (теперь общим правилом)",
                   c_legacy["ok"] is False and "не привязано к содержимому" in c_legacy["missing"][0]["reason"])
            # strict-ветка не растворилась в общем правиле: привязка ЕСТЬ, но нет expires_at/risk/source
            _plant_legacy_record(r4, "w4", "secrets", scope="config/s.py", binds_to="P")
            c_partial = check(hsig, r4, "w4", now="2026-07-05T00:00:00Z", plan_hash="P")
            expect("v2.123: high-risk со связыванием, но без expires_at/risk/source -> НЕ принята",
                   c_partial["ok"] is False and "schema v2" in c_partial["missing"][0]["reason"])
            # полностью связанная + доверенный source -> принята
            write_record(r4, "w4", "secrets", "u@x", "config/s.py", "ротация",
                         created_at="2026-07-05T00:00:00Z", binds_to="P",
                         expires_at="2027-01-01T00:00:00Z", risk="secret_rotation", source="user")
            c_bound = check(hsig, r4, "w4", now="2026-07-05T00:00:00Z", plan_hash="P")
            expect("v2.123: high-risk полностью связанная (binds_to+expires+risk+source=user) -> ok",
                   c_bound["ok"] is True)
            # source не из доверенного контекста (модель) -> отклонено
            write_record(r4, "w4", "secrets", "u@x", "config/s.py", "ротация",
                         created_at="2026-07-05T00:00:00Z", binds_to="P",
                         expires_at="2027-01-01T00:00:00Z", risk="secret_rotation", source="model")
            c_untrusted = check(hsig, r4, "w4", now="2026-07-05T00:00:00Z", plan_hash="P")
            expect("v2.123: high-risk source='model' (недоверенный) -> отклонено",
                   c_untrusted["ok"] is False and "source" in c_untrusted["missing"][0]["reason"])

    assert ok, "перенесённый селфтест approvals: см. строки FAIL в выводе"
