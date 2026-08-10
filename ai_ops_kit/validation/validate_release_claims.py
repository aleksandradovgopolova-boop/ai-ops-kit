#!/usr/bin/env python3
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
from __future__ import annotations

import sys
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
            Path(__file__).resolve().parents[1])
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

    ПОПРАВКА: claim'ы gate-count/mvp-blocking-count, на которые ссылается ROADMAP, существуют —
    в knowledge/claims.yaml, их проверяет validate_claims (тип count по паттерну строк). Здешние
    счётчики дублируют значение, но добавляют проверку, которой там нет: каждый гейт из
    mvp_blocking_gates обязан быть blocking: true. Число гейтов — публичная поверхность, поэтому
    деривируется, как checks_count и agents_count; при его изменении править ОБА реестра."""
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
    vdir = pkg / "ai_ops_kit" / "validation"
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


REQUIRED_SCOPES = ("full-current-python", "compatibility-matrix")
# Заявление о полноте проверки. Ищется в тексте релиза; допустимо только с именем охвата.
_FULL_CLAIM = ("полный контур", "полного контура", "полный набор проверок", "все проверки зелен")


def evidence_scope_errors(data, pkg=PKG):
    """Охват доказательства объявлен и не подменяется словом «полный».

    Кит весь август чинил проверки, смотревшие не туда, — и на 3.33.2 сам сделал ту же ошибку в
    тексте релиза: «полный контур зелёный» означало один интерпретатор, а опровергла его джоба
    3.9 в том же PR. Слово «полный» без величины охвата — не преувеличение, а другое утверждение.

    Проверяется:
      * оба охвата объявлены, у каждого сказано, чем получен и чего НЕ покрывает (охват без
        границы — снова «полный»);
      * obtained_by, ссылающийся на файл репозитория, указывает на существующий файл;
      * заявление о полноте в patch_note называет охват.
    """
    errors = []
    scopes = data.get("evidence_scopes")
    if not isinstance(scopes, dict) or not scopes:
        return ["evidence_scopes отсутствует: охват доказательства не объявлен, поэтому "
                "«полный контур зелёный» ничем не ограничен"]
    for name in REQUIRED_SCOPES:
        s = scopes.get(name)
        if not isinstance(s, dict):
            errors.append(f"evidence_scopes.{name} не объявлен — доказательство релиза не может "
                          "различить охваты, которых нет")
            continue
        for field in ("obtained_by", "covers", "does_not_cover"):
            if not str(s.get(field) or "").strip():
                errors.append(f"evidence_scopes.{name}.{field} пуст — охват без этого поля "
                              "снова означает «полный»")
        got = str(s.get("obtained_by") or "")
        rel = got.lstrip("./").split()[0] if got.startswith("./") else ""
        if rel and not (pkg / rel).exists():
            errors.append(f"evidence_scopes.{name}.obtained_by ссылается на {rel} — файла нет")

    note = str(data.get("patch_note") or "").lower()
    if any(c in note for c in _FULL_CLAIM) and not any(n in note for n in REQUIRED_SCOPES):
        errors.append("patch_note заявляет полноту проверки, не называя охват "
                      f"({' | '.join(REQUIRED_SCOPES)}) — то же заявление шире полученного, "
                      "которое python39-compat опроверг на 3.33.2")
    return errors


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
    e += evidence_scope_errors(data, pkg)
    _scan = list(data.get("stale_marker_files") or data.get("docs_must_reference_version") or [])
    for marker in (data.get("forbidden_stale_markers") or []):
        for name in _scan:
            p = pkg / name
            if p.exists() and marker in p.read_text(encoding="utf-8"):
                e.append(f"{name}: устаревший маркер текущего статуса '{marker}' — дрейф источника правды "
                         f"(удалить или пометить ИСТОРИЧЕСКИМ)")
    return e


def main(argv):
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
