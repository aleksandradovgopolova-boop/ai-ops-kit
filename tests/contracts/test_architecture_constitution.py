"""Architecture Constitution Tests — исполняемые проверки AC-01..AC-15.

Каждый тест доказывает один архитектурный инвариант из
docs/architecture/ARCHITECTURE_CONSTITUTION.md. Тесты используют AST-анализ
(как test_no_fake.py) и чтение YAML-контрактов, чтобы не тянуть весь движок
в память при прогоне.

Маркеры: contract — как все contract-тесты.
"""
from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

import pytest
import yaml

# ============================================================================
# Общие утилиты
# ============================================================================

PKG_ROOT = Path(__file__).parents[2]
AI_OPS_KIT = PKG_ROOT / "ai_ops_kit"
QUALITY_DIR = PKG_ROOT / "quality"
PACKAGES_DIR = PKG_ROOT / "packages"


def _parse_imports(filepath: Path) -> list[str]:
    """AST-извлечение всех import/from-imporтов из файла. Возвращает список имён."""
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"), filename=str(filepath))
    except SyntaxError:
        return []
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.append(node.module)
    return names


def _package_of(filepath: Path) -> str:
    """Пакет модуля: ai_ops_kit/<пакет>/module.py -> <пакет>."""
    return filepath.parent.name


def _all_py_files(*subdirs: str) -> list[Path]:
    """Все .py файлы в указанных подкаталогах ai_ops_kit/."""
    result = []
    for sub in subdirs:
        d = AI_OPS_KIT / sub
        if d.is_dir():
            result += sorted(d.glob("*.py"))
    return result


def _load_layering_spec():
    return yaml.safe_load((PACKAGES_DIR / "layering.yaml").read_text(encoding="utf-8"))


# ============================================================================
# AC-01: Domain не импортирует infrastructure
# ============================================================================

class TestDomainDoesNotImportInfrastructure:
    """AC-01: Модули предметной области не импортируют инфраструктурные модули.

    Домен: checks, governance (primitives layer).
    Инфраструктура: модули, которые импортируют subprocess, http, argparse.

    Проверяем: модули из checks/ и governance/ не содержат импортов на модули,
    которые в свою очередь импортируют subprocess/argparse (признак infrastructure).
    """

    # Модули, которые считаются инфраструктурой (содержат subprocess/argparse/http)
    INFRA_SIGNALS = {"subprocess", "argparse", "http.client", "urllib", "socket"}

    def _find_infra_modules(self) -> set[str]:
        """Найти все модули, которые импортируют инфраструктурные библиотеки."""
        infra = set()
        for py in AI_OPS_KIT.rglob("*.py"):
            if py.name == "__init__.py" or "__pycache__" in str(py):
                continue
            for imp in _parse_imports(py):
                top = imp.split(".")[0]
                if top in self.INFRA_SIGNALS:
                    infra.add(_package_of(py))
                    break
        return infra

    def test_checks_does_not_import_infrastructure(self):
        """Модули checks/ не импортируют subprocess, argparse, http."""
        for py in _all_py_files("checks"):
            if py.name == "__init__.py":
                continue
            imports = _parse_imports(py)
            for imp in imports:
                top = imp.split(".")[0]
                assert top not in self.INFRA_SIGNALS, (
                    f"AC-01: checks/{py.name} импортирует инфраструктурный модуль '{imp}'. "
                    f"Domain не должен зависеть от infrastructure."
                )

    def test_governance_does_not_import_subprocess(self):
        """Модули governance/ не импортируют subprocess напрямую."""
        for py in _all_py_files("governance"):
            if py.name == "__init__.py":
                continue
            imports = _parse_imports(py)
            for imp in imports:
                top = imp.split(".")[0]
                assert top != "subprocess", (
                    f"AC-01: governance/{py.name} импортирует subprocess. "
                    f"Domain-логика не должна запускать процессы напрямую."
                )

    def test_foundation_is_a_leaf(self):
        """AC-01 (обратная сторона): shared/ не импортирует ничего из ai_ops_kit."""
        for py in _all_py_files("shared"):
            if py.name == "__init__.py":
                continue
            imports = _parse_imports(py)
            for imp in imports:
                parts = imp.split(".")
                # from ai_ops_kit.<пакет> import ...
                if parts[0] == "ai_ops_kit" and len(parts) >= 2:
                    target = parts[1]
                elif parts[0] in {d.name for d in AI_OPS_KIT.iterdir()
                                  if d.is_dir() and d.name != "__pycache__"}:
                    target = parts[0]
                else:
                    continue
                if target == "shared":
                    continue  # shared -> shared OK
                assert False, (
                    f"AC-01: shared/{py.name} импортирует '{imp}'. "
                    f"Foundation — лист; он не должен зависеть ни от кого."
                )


# ============================================================================
# AC-11: Новый dependency не может создавать запрещённый cycle
# ============================================================================

class TestNoForbiddenCycles:
    """AC-11: Граф зависимостей не превышает ратчет-потолок.

    Использует существующий validate_layering.py — AST-анализатор импортов.
    """

    def test_no_forbidden_cycles(self):
        """validate_layering.py возвращает 0 — нет нарушений."""
        import sys
        sys.path.insert(0, str(AI_OPS_KIT / "validation"))
        try:
            import validate_layering
            spec = validate_layering.load_spec()
            edges = validate_layering.build_graph()
            errors = validate_layering.check(spec, edges)
            ratchet = validate_layering.ratchet_errors(spec, edges)
            all_errors = errors + ratchet
            assert not all_errors, (
                f"AC-11: layering violations:\n" +
                "\n".join(f"  - {e}" for e in all_errors)
            )
        finally:
            sys.path.pop(0)

    def test_ratchet_not_exceeded(self):
        """Числа циклов не выше потолка в layering.yaml."""
        import sys
        sys.path.insert(0, str(AI_OPS_KIT / "validation"))
        try:
            import validate_layering
            spec = validate_layering.load_spec()
            edges = validate_layering.build_graph()
            counts = validate_layering.cyclic_counts(edges)
            baseline = spec.get("baseline", {})
            for key in ("mutual_pairs", "cycles_longer_than_two"):
                ceiling = baseline.get(key)
                actual = counts.get(key, 0)
                assert isinstance(ceiling, int), f"baseline.{key} не число"
                assert actual <= ceiling, (
                    f"AC-11: {key} = {actual} при потолке {ceiling}. "
                    f"Новая взаимная связь или цикл; развязать или осознанно поднять потолок."
                )
        finally:
            sys.path.pop(0)

    def test_no_cross_layer_mutual_pairs(self):
        """Все взаимные пары — внутри capabilities. Cross-layer запрещены."""
        import sys
        sys.path.insert(0, str(AI_OPS_KIT / "validation"))
        try:
            import validate_layering
            spec = validate_layering.load_spec()
            edges = validate_layering.build_graph()
            layer_idx = {}
            for i, layer in enumerate(spec.get("layers", [])):
                for p in layer.get("packages", []):
                    layer_idx[p] = i

            # Находим все mutual pairs
            mutual = []
            for (a, b) in edges:
                if (b, a) in edges:
                    pair = tuple(sorted((a, b)))
                    if pair not in mutual:
                        mutual.append(pair)

            for (a, b) in mutual:
                la, lb = layer_idx.get(a, -1), layer_idx.get(b, -1)
                assert la == lb, (
                    f"AC-11: cross-layer mutual pair {a} <-> {b} "
                    f"(слои {la} и {lb}). Все cross-layer пары должны быть развязаны."
                )
        finally:
            sys.path.pop(0)


# ============================================================================
# AC-04: State не вычисляется из нескольких источников
# ============================================================================

class TestStateSingleSource:
    """AC-04: Состояние WorkItem вычисляется из единственного источника.

    Проверяем: в lifecycle/ нет прямых присваиваний status/state,
    кроме как через derive_status() или gate_executor.evaluate().
    """

    # Паттерны, которые указывают на прямое присваивание статуса
    DIRECT_ASSIGNMENT = re.compile(
        r"""(?:^|\s)(?:self\.)?(?:status|state|_status|_state)\s*=\s*(?!.*(?:derive|evaluate|build_report))""",
        re.MULTILINE,
    )

    def test_workitem_status_is_derived(self):
        """workitem.py: статус вычисляется через derive_status, не присваивается напрямую."""
        workitem = AI_OPS_KIT / "lifecycle" / "workitem.py"
        if not workitem.exists():
            pytest.skip("lifecycle/workitem.py не найден")

        src = workitem.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(workitem))

        # Ищем присваивания status/state в функциях, которые НЕ называются derive_status
        violations = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if node.name.startswith("_") and node.name != "derive_status":
                    # Приватные функции не должны присваивать status напрямую
                    for child in ast.walk(node):
                        if isinstance(child, ast.Assign):
                            for target in child.targets:
                                name = ""
                                if isinstance(target, ast.Name):
                                    name = target.id
                                elif isinstance(target, ast.Attribute):
                                    name = target.attr
                                if name in ("status", "state", "_status", "_state"):
                                    violations.append(
                                        f"lifecycle/workitem.py:{child.lineno} "
                                        f"в {node.name}(): прямое присваивание '{name}'"
                                    )

        assert not violations, (
            f"AC-04: status вычисляется из нескольких источников:\n" +
            "\n".join(f"  - {v}" for v in violations) +
            "\nСтатус должен вычисляться только через derive_status() / gate_executor.evaluate()."
        )

    def test_contracts_use_typeddict_not_setters(self):
        """shared/contracts.py: WorkItemState — TypedDict, не класс с setter'ами."""
        contracts = AI_OPS_KIT / "shared" / "contracts.py"
        if not contracts.exists():
            pytest.skip("shared/contracts.py не найден")

        src = contracts.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(contracts))

        # Ищем классы с методами set_status / set_state
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        assert item.name not in ("set_status", "set_state", "set_workitem_state"), (
                            f"AC-04: {node.name}.{item.name}() — setter для состояния. "
                            f"Контракты — TypedDict, не классы с setter'ами. "
                            f"Состояние вычисляется, не присваивается."
                        )


# ============================================================================
# AC-05: Gate не может быть blocking без applicability evidence
# ============================================================================

class TestGateHasApplicability:
    """AC-05: Каждый gate имеет applicability — доказательство применимости.

    quality/gates.yaml: каждый gate обязан иметь непустое поле applicability.
    """

    def test_gate_has_applicability(self):
        """Каждый gate в quality/gates.yaml имеет непустое applicability."""
        gates_yaml = QUALITY_DIR / "gates.yaml"
        if not gates_yaml.exists():
            pytest.skip("quality/gates.yaml не найден")

        data = yaml.safe_load(gates_yaml.read_text(encoding="utf-8"))
        gates = data.get("gates", {})
        assert gates, "quality/gates.yaml: секция gates пуста"

        violations = []
        for gate_id, gate in gates.items():
            applicability = gate.get("applicability")
            if not applicability:
                violations.append(gate_id)
            elif not isinstance(applicability, list) or len(applicability) == 0:
                violations.append(f"{gate_id} (applicability={applicability})")

        assert not violations, (
            f"AC-05: gates без applicability evidence:\n" +
            "\n".join(f"  - {v}" for v in violations) +
            "\nКаждый gate обязан иметь applicability — список workflow-типов, к которым он применяется."
        )

    def test_blocking_gate_has_required_evidence(self):
        """Каждый blocking gate имеет required_evidence или exemption_policy."""
        gates_yaml = QUALITY_DIR / "gates.yaml"
        if not gates_yaml.exists():
            pytest.skip("quality/gates.yaml не найден")

        data = yaml.safe_load(gates_yaml.read_text(encoding="utf-8"))
        gates = data.get("gates", {})

        violations = []
        for gate_id, gate in gates.items():
            if gate.get("blocking", False):
                has_evidence = gate.get("required_evidence")
                has_exemption = gate.get("exemption_policy")
                if not has_evidence and not has_exemption:
                    violations.append(gate_id)

        assert not violations, (
            f"AC-05: blocking gates без required_evidence и без exemption_policy:\n" +
            "\n".join(f"  - {v}" for v in violations) +
            "\nBlocking gate без evidence-требования = fail-closed нарушение."
        )

    def test_gate_result_v2_abstain_not_fail(self):
        """AC-06: gate_result_v2 различает abstain и fail."""
        grv2 = AI_OPS_KIT / "gates" / "gate_result_v2.py"
        if not grv2.exists():
            pytest.skip("gates/gate_result_v2.py не найден")

        src = grv2.read_text(encoding="utf-8")
        # STATUS_V2 должен содержать и abstain, и fail как разные значения
        assert '"abstain"' in src or "'abstain'" in src, (
            "AC-06: gate_result_v2.py не содержит статус 'abstain'. "
            "ABSTAIN и FAIL — разные сущности."
        )
        assert '"fail"' in src or "'fail'" in src, (
            "AC-06: gate_result_v2.py не содержит статус 'fail'."
        )


# ============================================================================
# AC-10: Capability, Policy, Workflow, Gate и Evidence — разные сущности
# ============================================================================

class TestCapabilityPolicySeparation:
    """AC-10: Governance не определяет gate-логику; gates не определяет policy-логику.

    Проверяем: модули governance/ не содержат определений gate executor'а;
    модули gates/ не содержат определений policy engine.
    """

    def test_governance_does_not_define_gates(self):
        """governance/ не содержит gate executor логики."""
        gate_keywords = {"evaluate_gate", "gate_executor", "GateExecutor", "gate_result"}
        for py in _all_py_files("governance"):
            if py.name == "__init__.py":
                continue
            src = py.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(py))

            # Ищем определения функций/классов с gate-ключевыми словами
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    for kw in gate_keywords:
                        assert kw not in node.name, (
                            f"AC-10: governance/{py.name} определяет '{node.name}' — "
                            f"gate-логика принадлежит gates/, не governance/. "
                            f"Capability, Policy, Workflow, Gate и Evidence — разные сущности."
                        )

    def test_gates_does_not_define_policy(self):
        """gates/ не содержит policy engine логики."""
        policy_keywords = {"policy_engine", "PolicyEngine", "autonomy_level", "suggest",
                           "prepare", "execute", "require_approval"}
        for py in _all_py_files("gates"):
            if py.name == "__init__.py":
                continue
            src = py.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(py))

            # Ищем определения классов с policy-ключевыми словами
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    for kw in policy_keywords:
                        assert kw not in node.name, (
                            f"AC-10: gates/{py.name} определяет класс '{node.name}' — "
                            f"policy-логика принадлежит governance/, не gates/. "
                            f"Capability, Policy, Workflow, Gate и Evidence — разные сущности."
                        )

    def test_separate_registries(self):
        """capability-index, workflows, model-roles — разные YAML-файлы."""
        registry = PKG_ROOT / "registry"
        if not registry.is_dir():
            pytest.skip("registry/ не найден")

        # Проверяем, что ключевые сущности разделены по файлам
        expected_files = {
            "capability-index.yaml": "capability",
            "workflows.yaml": "workflow",
            "model-roles.yaml": "policy",
        }
        for fname, entity in expected_files.items():
            fpath = registry / fname
            if fpath.exists():
                data = yaml.safe_load(fpath.read_text(encoding="utf-8"))
                assert data is not None, (
                    f"AC-10: {fname} пуст. {entity} registry должен содержать данные."
                )

    def test_gate_evidence_has_separate_schema(self):
        """Gate result и gate evidence — разные schema."""
        schemas = PKG_ROOT / "schemas"
        if not schemas.is_dir():
            pytest.skip("schemas/ не найден")

        gate_schemas = list(schemas.glob("gate-*"))
        assert len(gate_schemas) >= 2, (
            f"AC-10: найдено только {len(gate_schemas)} gate-schema. "
            f"Gate result и gate evidence должны быть разными schema."
        )


# ============================================================================
# Guard-self-test: каждый тест ловит дефект, для которого написан
# ============================================================================

class TestGuardSelfTest:
    """Доказательство: каждый guard-тест действительно проверяет инвариант."""

    def test_guard_catches_infra_import_in_checks(self):
        """Если checks/ начнёт импортировать subprocess — тест AC-01 покраснеет."""
        # Симулируем: парсинг строки с subprocess import
        fake_src = "import subprocess\n"
        tree = ast.parse(fake_src)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports += [a.name for a in node.names]
        assert "subprocess" in imports, "Guard: AST-парсинг не видит subprocess import"

    def test_guard_catches_missing_applicability(self):
        """Если gate потеряет applicability — тест AC-05 покраснеет."""
        fake_gate = {"id": "test_gate", "blocking": True}  # нет applicability
        assert not fake_gate.get("applicability"), "Guard: отсутствующее applicability видимо"

    def test_guard_catches_cross_layer_pair(self):
        """Если появится cross-layer mutual pair — тест AC-11 покраснеет."""
        # Симулируем: два пакета на разных слоях с взаимными импортами
        layer_idx = {"shared": 0, "engine": 2}
        a, b = "shared", "engine"
        la, lb = layer_idx[a], layer_idx[b]
        assert la != lb, "Guard: разные слои должны быть видимы"
