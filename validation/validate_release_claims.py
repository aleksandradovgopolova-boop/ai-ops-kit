#!/usr/bin/env python3
from __future__ import annotations
"""Release Truth Alignment (v3.8.1): machine-readable claims о ТЕКУЩЕМ релизе -> CI ловит ДРЕЙФ между
публичной поверхностью (README/ROADMAP/registry) и фактическим состоянием кода. Инвариант: источники
правды НЕ отстают от runtime (README v3.0.x при коде 3.8 — это дефект, который должен ловить CI).

Проверки (детерминированно, только stdlib+pyyaml):
  1. claims.version == файл VERSION;
  2. claims.checks_count == число `python3 ` команд в AGENTS.md (DERIVED — ловит устаревшие «91+»);
  3. claims.agents_count == число агентов в registry/agents.yaml (DERIVED);
  4. каждый файл из docs_must_reference_version РЕАЛЬНО содержит claims.version (публичная поверхность
     ссылается на текущую версию, а не на прошлый продукт);
  5. каждый runtime_capabilities-claim == фактический status в registry/runtimes.yaml (ловит дрейф
     заявленных возможностей адаптеров: parallel/resume и т.п.);
  6. claims.gates_count / claims.mvp_blocking_count == quality/gates.yaml (DERIVED), и каждый гейт
     из mvp_blocking_gates реально blocking: true (список MVP-блокеров без силы — та же ложь
     публичной поверхности, что и устаревшее число).

  validate_release_claims.py [registry/release-claims.yaml] | --selftest
"""

import sys
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]
DEFAULT = PKG / "registry" / "release-claims.yaml"


def derived_counts(pkg=PKG):
    """Фактические числа из источников (не из claims): (checks_count, agents_count).
    v3.28.0: checks_count считается из docs/agent-guides/pre-commit-checklist.md
    (AGENTS.md сокращён до карты, полный список команд вынесен в гид)."""
    checks = 0
    try:
        checklist = pkg / "docs" / "agent-guides" / "pre-commit-checklist.md"
        if checklist.exists():
            for ln in checklist.read_text(encoding="utf-8").splitlines():
                if ln.strip().startswith("python3 "):
                    checks += 1
        else:
            # Fallback: старый AGENTS.md (до v3.28.0)
            for ln in (pkg / "AGENTS.md").read_text(encoding="utf-8").splitlines():
                if ln.strip().startswith("python3 "):
                    checks += 1
    except OSError:
        pass
    agents = 0
    try:
        ad = yaml.safe_load((pkg / "registry" / "agents.yaml").read_text(encoding="utf-8"))
        if isinstance(ad, dict) and isinstance(ad.get("agents"), list):
            agents = len(ad["agents"])
    except OSError:
        pass
    return checks, agents


def derived_gate_counts(pkg=PKG):
    """(gates_count, mvp_blocking_count) из quality/gates.yaml.

    v3.28.x: ROADMAP заявлял «MVP-blocking = 8; счётчик запиннен claim
    gate-count/mvp-blocking-count» — но таких claim'ов не существовало и никто их не сверял.
    Заявление о том, что число запиннено, само было незапиннено. Числа гейтов — публичная
    поверхность (их называют README/ROADMAP), значит они обязаны дериверироваться, как
    checks_count и agents_count."""
    gates_total, mvp = 0, 0
    try:
        gd = yaml.safe_load((pkg / "quality" / "gates.yaml").read_text(encoding="utf-8")) or {}
        gates = gd.get("gates") or {}
        gates_total = len(gates)
        mvp = len(gd.get("mvp_blocking_gates") or [])
    except OSError:
        pass
    return gates_total, mvp


def derived_verification_counts(pkg=PKG):
    """(validators_total, externally_tested) — сколько валидаторов есть и сколько проверяются
    ВНЕШНИМ тестом, а не только собственным --selftest.

    Рекомендация №6 внешнего ревью: 74 валидатора — продуктовое обещание качества, но проверяются
    они самоаттестацией (валидатор подтверждает сам себя). Закрыть все разом нельзя, поэтому
    закрывается главное: число перестаёт быть неизвестным. Claim обязан совпадать с фактом, значит
    и добавление внешнего теста, и его удаление требуют осознанной правки claims — молча ни
    вырасти, ни просесть покрытие не может.

    «Внешне протестирован» = имя модуля валидатора буквально упоминается в tests/. Параметризованный
    прогон selftest'ов сюда не попадает: он обнаруживает файлы в рантайме и ничьего имени не
    содержит — то есть самоаттестация за внешнюю проверку не засчитывается."""
    import re as _re
    vdir = pkg / "validation"
    if not vdir.is_dir():
        return 0, 0
    names = sorted(p.stem for p in vdir.glob("validate_*.py"))
    covered = set()
    tdir = pkg / "tests"
    if tdir.is_dir():
        for t in tdir.rglob("test_*.py"):
            try:
                txt = t.read_text(encoding="utf-8")
            except OSError:
                continue
            for n in names:
                if n not in covered and _re.search(rf"\b{_re.escape(n)}\b", txt):
                    covered.add(n)
    return len(names), len(covered)


def mvp_gates_are_blocking(pkg=PKG):
    """Гейты из mvp_blocking_gates обязаны иметь blocking: true. Иначе список MVP-блокеров —
    декларация без силы: гейт числится блокирующим, а прогон он не останавливает."""
    try:
        gd = yaml.safe_load((pkg / "quality" / "gates.yaml").read_text(encoding="utf-8")) or {}
    except OSError:
        return []
    gates = gd.get("gates") or {}
    return [g for g in (gd.get("mvp_blocking_gates") or [])
            if not (gates.get(g) or {}).get("blocking")]


def _runtime_status(pkg, runtime, capability):
    try:
        rt = yaml.safe_load((pkg / "registry" / "runtimes.yaml").read_text(encoding="utf-8"))
    except OSError:
        return None
    runtimes = (rt or {}).get("runtimes") or {}
    return (((runtimes.get(runtime) or {}).get("capabilities") or {}).get(capability) or {}).get("status")


def check(data, pkg=PKG):
    e = []
    if not isinstance(data, dict) or data.get("registry_type") != "release-claims":
        return ["registry_type должен быть release-claims"]
    ver = str(data.get("version") or "").strip()
    vf = (pkg / "VERSION").read_text(encoding="utf-8").strip() if (pkg / "VERSION").exists() else None
    if vf and ver != vf:
        e.append(f"claims.version '{ver}' != VERSION '{vf}' (claims отстали от релиза)")
    checks, agents = derived_counts(pkg)
    if data.get("checks_count") != checks:
        e.append(f"claims.checks_count={data.get('checks_count')} != python3-проверок в чеклисте={checks} (устаревшее число)")
    if data.get("agents_count") != agents:
        e.append(f"claims.agents_count={data.get('agents_count')} != агентов в registry/agents.yaml={agents}")
    gates_total, mvp = derived_gate_counts(pkg)
    if data.get("gates_count") != gates_total:
        e.append(f"claims.gates_count={data.get('gates_count')} != гейтов в quality/gates.yaml={gates_total}")
    if data.get("mvp_blocking_count") != mvp:
        e.append(f"claims.mvp_blocking_count={data.get('mvp_blocking_count')} != "
                 f"mvp_blocking_gates в quality/gates.yaml={mvp}")
    vtotal, vtested = derived_verification_counts(pkg)
    if data.get("validators_count") != vtotal:
        e.append(f"claims.validators_count={data.get('validators_count')} != валидаторов в validation/={vtotal}")
    if data.get("validators_externally_tested") != vtested:
        e.append(f"claims.validators_externally_tested={data.get('validators_externally_tested')} "
                 f"!= фактически покрытых внешним тестом={vtested} (покрытие изменилось — "
                 f"обнови claim осознанно, молча просесть оно не должно)")
    _weak = mvp_gates_are_blocking(pkg)
    if _weak:
        e.append(f"mvp_blocking_gates без blocking: true — {', '.join(_weak)} "
                 f"(числятся блокерами, но прогон не останавливают)")
    for name in (data.get("docs_must_reference_version") or []):
        p = pkg / name
        if not p.exists():
            e.append(f"{name}: файл из docs_must_reference_version не найден"); continue
        if ver and ver not in p.read_text(encoding="utf-8"):
            e.append(f"{name} не ссылается на текущую версию {ver} (публичная поверхность отстала от кода)")
    for rc in (data.get("runtime_capabilities") or []):
        r, cap, st = rc.get("runtime"), rc.get("capability"), rc.get("status")
        actual = _runtime_status(pkg, r, cap)
        if actual != st:
            e.append(f"runtime_capabilities {r}.{cap}: claim '{st}' != runtimes.yaml '{actual}' (дрейф заявленных возможностей)")
    # v3.9.1/v3.9.2: устаревшие маркеры «текущего статуса» НЕ должны присутствовать в публичной поверхности.
    # Сканируем НАСТРАИВАЕМЫЙ набор файлов (stale_marker_files — README/ROADMAP/NOTICE/docs/*), а не только
    # docs_must_reference_version. Так дрейф вроде «sequential-only» ловится и в docs/, не только вверху.
    _scan = list(data.get("stale_marker_files") or data.get("docs_must_reference_version") or [])
    for marker in (data.get("forbidden_stale_markers") or []):
        for name in _scan:
            p = pkg / name
            if p.exists() and marker in p.read_text(encoding="utf-8"):
                e.append(f"{name}: устаревший маркер текущего статуса '{marker}' — дрейф источника правды "
                         f"(удалить или пометить ИСТОРИЧЕСКИМ)")
    return e


def selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and bool(cond)
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    checks, agents = derived_counts(PKG)
    vf = (PKG / "VERSION").read_text(encoding="utf-8").strip()
    # берём реальный runtime-claim, который точно есть (parallel_execution generic-orchestrator)
    st = _runtime_status(PKG, "generic-orchestrator", "parallel_execution")
    _g, _m = derived_gate_counts()
    _vt, _vc = derived_verification_counts()
    base = {"registry_type": "release-claims", "version": vf, "checks_count": checks,
            "agents_count": agents, "gates_count": _g, "mvp_blocking_count": _m,
            "validators_count": _vt, "validators_externally_tested": _vc,
            "docs_must_reference_version": ["README.md"],
            "runtime_capabilities": [{"runtime": "generic-orchestrator",
                                      "capability": "parallel_execution", "status": st}]}
    expect("согласованные claims -> без ошибок", check(base) == [])
    expect("version != VERSION -> ошибка",
           any("claims отстали" in x for x in check({**base, "version": "0.0.0"})))
    expect("checks_count устарел -> ошибка",
           any("checks_count" in x for x in check({**base, "checks_count": 91})))
    expect("agents_count устарел -> ошибка",
           any("agents_count" in x for x in check({**base, "agents_count": 1})))
    # v3.28.x: числа гейтов — тоже публичная поверхность, тоже DERIVED.
    expect("gates_count устарел -> ошибка",
           any("gates_count" in x for x in check({**base, "gates_count": 999})))
    expect("mvp_blocking_count устарел -> ошибка",
           any("mvp_blocking_count" in x for x in check({**base, "mvp_blocking_count": 999})))
    expect("MVP-блокеры реально blocking: true в реестре", mvp_gates_are_blocking() == [])
    expect("просадка внешнего покрытия валидаторов -> ошибка",
           any("validators_externally_tested" in x
               for x in check({**base, "validators_externally_tested": 0})))
    expect("runtime capability дрейф -> ошибка",
           any("дрейф" in x for x in check({**base, "runtime_capabilities": [
               {"runtime": "generic-orchestrator", "capability": "parallel_execution", "status": "unsupported"}]})))
    # v3.9.1: forbidden_stale_markers — стейл-маркер, реально присутствующий в README -> ошибка
    expect("forbidden_stale_markers: присутствующий в README -> ошибка",
           any("устаревший маркер" in x for x in check({**base, "forbidden_stale_markers": ["Открытая"]})))
    expect("forbidden_stale_markers: отсутствующий -> без ошибки",
           not any("устаревший маркер" in x for x in check({**base, "forbidden_stale_markers": ["NONEXISTENT-STALE-XYZ-9999"]})))
    _bad_doc = {**base, "version": "vNONEXISTENT-9.9.9", "checks_count": checks, "agents_count": agents}
    # version mismatch И doc-reference оба сработают; проверяем doc-reference-ветку отдельно на фейковой версии,
    # подложив её и в VERSION-независимую проверку: используем несуществующую строку -> README её не содержит
    expect("README не ссылается на версию -> ошибка (среди прочих)",
           any("не ссылается на текущую версию" in x for x in check(_bad_doc)))

    if DEFAULT.exists():
        errs = check(yaml.safe_load(DEFAULT.read_text(encoding="utf-8")))
        expect("реальный release-claims.yaml согласован с кодом", errs == [])
        for x in errs:
            print("   -", x)

    print("validate_release_claims selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    args = [a for a in argv if not a.startswith("--")]
    path = Path(args[0]) if args else DEFAULT
    errs = check(yaml.safe_load(path.read_text(encoding="utf-8")))
    if errs:
        print(f"RELEASE-CLAIMS {path.name}: дрейф источников правды:")
        for x in errs:
            print(f"  - {x}")
        return 1
    print(f"RELEASE-CLAIMS-OK: {path.name} — публичная поверхность согласована с кодом.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
