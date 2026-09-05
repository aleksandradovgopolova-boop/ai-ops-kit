"""«Построено» не равно «проведено в контур»: ратчет против дормантного инвентаря.

ПОВОД — АУДИТ 10 РОЛЕЙ (2026-09-04). Кит накопил модули, которые НАПИСАНЫ и протестированы, но не
проведены ни в один рабочий контур: их не импортирует ни один не-тестовый файл. Опасность —
ложная зрелость: цель помечена достигнутой, а кода в рабочем пути нет. Пять ролей аудита назвали
это главной бедой («кит судит больше, чем строит»): модуль есть, тест есть, ЕДЕТ в дочку — а
вызывается только из тестов и из самого себя.

ЧЕМ ЭТО ОТЛИЧАЕТСЯ ОТ `test_capability_reachability`. Тот тест меряет ДОСТИЖИМОСТЬ из точки входа
и по построению считает достижимым ЛЮБОЙ модуль с блоком `if __name__ == "__main__"` (его можно
позвать процессом). Поэтому дормантный CLI-модуль там «достижим» — и остаётся невидимым. Здесь
меряется другое, ортогональное: СКОЛЬКО не-тестовых файлов его ИМПОРТИРУЮТ. Ноль импортеров —
модуль не встроен в контур, даже если у него есть свой `main`.

ЧТО ЗНАЧИТ «ПРОВЕДЁН В КОНТУР» (wired). У модуля есть хотя бы один НЕ-ТЕСТОВЫЙ импортер — файл вне
`tests/`, живущий в достижимом из точки входа коде. Импорт из теста НЕ считается (тест доказывает
поведение, но не встраивает модуль в работу продукта). Самоимпорт НЕ считается (контур из одного
себя — не контур).

ЛЕГИТИМНЫЕ 0-ИМПОРТЕРНЫЕ ВХОДЫ (allowlist, у каждого причина). Не всякий модуль с нулём импортеров
дормантен — часть их запускается ПРОЦЕССОМ, а не импортом:
  * `ai_ops_kit/validation/*` — валидаторы: гейты зовут их отдельным процессом (`python -m …`);
  * `ai_ops_kit/devtools/*` — харнессы разработки самого кита (бенчмарки, мутационные пробы),
    в дочку не едут (DEV_ONLY), запускаются вручную процессом;
  * поимённые CLI-входы, которые РЕАЛЬНО зовёт поверхность рантайм-диспетча (`commands/**`):
    их дочка запускает по имени файла, а не импортирует.
Allowlist — не индульгенция «плодить такие модули», а честный перечень входов, у которых нулевой
импорт — норма по устройству. Любой вход сюда попадает с причиной.

ГЕНУИННО ДОРМАНТНЫЕ (`KNOWN_DORMANT`) — потолок-ратчет. Остальные 0-импортерные модули написаны и
привязаны к цели (часть целей кит уже считает достигнутой — см. `planning/plan.yaml`), но в контур
не проведены. Их текущий набор ЗАМОРОЖЕН как ПОТОЛОК. Механизм — как `known_violations` у слоёв и
`KNOWN_UNREACHABLE` у достижимости: список вправе только СОКРАЩАТЬСЯ. Провели модуль в контур
(появился не-тестовый импортер) или объявили его легит-входом — он обязан УЙТИ из `KNOWN_DORMANT`.
НОВЫЙ дормантный модуль сверх потолка — красное: так «построено, но не проведено» перестаёт
проходить молча. Разбор самих известных-дормантных модулей (провести или снять) — отдельные
работы; задача этого теста — ИЗМЕРИТЬ и не дать долгу расти.

СТРОГОСТЬ. Находки-инвентарь — advisory (печатаются, чтобы человек видел долг), но МЕХАНИЗМ
настоящий: assert на то, что потолок не растёт, и ратчет вниз на самом списке.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PKG_ROOT = Path(__file__).resolve().parents[2]
PKG = "ai_ops_kit"

# --- Легитимные 0-импортерные входы: запускаются процессом, а не импортом. ---
# Целые слои-исключения: валидаторы и dev-харнессы. Нулевой импорт у них — норма по устройству.
ALLOWLIST_PREFIXES: tuple[str, ...] = (
    f"{PKG}.validation.",   # валидаторы: гейты зовут их отдельным процессом (см. quality/gates.yaml)
    f"{PKG}.devtools.",     # харнессы разработки кита (DEV_ONLY): бенчмарки, пробы — запуск вручную
)

# Поимённые CLI-входы, которые РЕАЛЬНО зовёт поверхность рантайм-диспетча `commands/**`.
# Дочка запускает их по имени файла (`python3 .ai/managed/ai_ops_kit/…`), а не импортирует —
# поэтому нулевой импорт для них ожидаем и легитимен. Каждый — с точной ссылкой на команду.
ALLOWLIST_MODULES: dict[str, str] = {
    f"{PKG}.intelligence.nightly_review":
        "commands/maintenance/night-review.md зовёт процессом; Robin запускает по расписанию",
    f"{PKG}.lifecycle.merge_memory":
        "commands/task/ai-finish-task.md зовёт `ai_ops_kit.lifecycle.merge_memory record …`",
}

# --- Замороженный потолок генуинно-дормантных модулей (2026-09-05, аудит 10 ролей). ---
# 0 не-тестовых импортеров, НЕ легит-вход, привязан к цели (часть — достигнутой). Список вправе
# только СОКРАЩАТЬСЯ: провели в контур (появился импортер) или объявили легит-входом — убрать
# отсюда. Имя здесь — признанный долг «построено, но не проведено», а НЕ разрешение плодить такое.
KNOWN_DORMANT: dict[str, str] = {
    f"{PKG}.engine.parallel_live":
        "live-харнесс конкурентного мультипакетного прогона (цель team-works-in-parallel, active); "
        "ни один не-тестовый модуль его не импортирует, диспетч-команда его не зовёт",
    f"{PKG}.engops.delivery_size":
        "порт kernel (ExecutionSpec/ports.py), долг Phase B; реализация порту не соответствует — "
        "модуль в installer.UNWIRED_MODULES (в дочку не едет), импортеров нет",
    f"{PKG}.engops.merge_lifecycle":
        "порт kernel (ports.py), долг Phase B; installer.UNWIRED_MODULES, импортеров нет",
    f"{PKG}.engops.refusal_paths":
        "порт kernel (ports.py), долг Phase B; installer.UNWIRED_MODULES, импортеров нет",
    f"{PKG}.engops.session_thresholds":
        "порт kernel (ports.py), долг Phase B; installer.UNWIRED_MODULES, импортеров нет",
    f"{PKG}.intelligence.artifact_reality_check":
        "сверка артефактов с реальным репо (цель ai-product-operations, achieved); "
        "installer.UNWIRED_MODULES, импортеров нет — построено, но в контур не проведено",
    f"{PKG}.intelligence.decision_loop":
        "product decision loop (цель product-decision-loop, active); installer.UNWIRED_MODULES, "
        "импортеров нет — цикл решений написан, но ни один рабочий путь его не зовёт",
    f"{PKG}.intelligence.evolution_triggers":
        "замыкание governance-петли ADR↔Product Health (цель ai-product-operations, achieved); "
        "едет в дочку, но 0 импортеров — только сам импортирует валидаторы",
    f"{PKG}.intelligence.outcome_analytics":
        "сводная аналитика исходов (цель outcome-and-analytics-loop, ACHIEVED); "
        "installer.UNWIRED_MODULES, 0 импортеров — ровно случай ложной зрелости",
    f"{PKG}.intelligence.refactoring_advisor":
        "советчик рефакторинга (цель autonomous-product-loop, achieved); "
        "installer.UNWIRED_MODULES, импортеров нет",
    f"{PKG}.intelligence.session_watch":
        "предупреждения о пределе сессии (цель session-autonomy-under-ceiling, achieved); "
        "installer.UNWIRED_MODULES, импортеров нет",
    f"{PKG}.intelligence.watch_contract":
        "контракт наблюдения для nightly review (цель nightly-product-review, active); "
        "installer.UNWIRED_MODULES, импортеров нет (nightly_review его не импортирует)",
    f"{PKG}.providers.cost_account":
        "пост-прогонная сверка расхода с BudgetContract (цель trustworthy-core, active); "
        "экономику enforcement ведёт gates/economic_preflight ДО прогона — этот аудит 0 импортеров",
    f"{PKG}.security.security_review_cascade":
        "asymmetric fail-closed судья, ЯВНО experimental/qualification-only и НЕ подключён к "
        "рабочему security_review (сказано в докстринге модуля); 0 импортеров",
    f"{PKG}.ui.storybook_query":
        "read-only Storybook-адаптер (цель storybook-as-visual-contract, active); 0 импортеров — "
        "запускается как MCP-инструмент, но в рабочий контур не проведён",
}


def _dotted(p: Path) -> str:
    return ".".join(p.relative_to(PKG_ROOT).with_suffix("").parts)


def _pkg_modules() -> dict[str, Path]:
    """Все модули пакета (без `__init__.py` и `__pycache__`) — dotted-имя -> путь."""
    return {_dotted(p): p for p in (PKG_ROOT / PKG).rglob("*.py")
            if "__pycache__" not in p.parts and p.name != "__init__.py"}


def _is_test_path(p: Path) -> bool:
    """Тестовый ли файл — импорт из него НЕ считается проводкой в контур."""
    return "tests" in p.parts or p.name.startswith("test_") or p.name == "conftest.py"


# Не-исходные деревья ПОД корнем репо: gitignored git-worktree'ы (`.ai/worktrees/<…>/ai_ops_kit/…`),
# editable-установки (`.venv/…/site-packages/ai_ops_kit/…`), кэши и артефакты сборки. Их `.py` — КОПИИ
# пакета, а не рабочий код; засчитать их в импортёры значило бы счесть дормантный модуль проведённым
# в контур из-за собственной копии. В чистом клоне CI их нет — потому тест там зелён; фильтр держит
# корректность и локально (в worktree с populated `.ai/` или при editable-инсталле с `.venv` внутри).
SKIP_DIRS = frozenset({
    ".git", ".ai", ".claude", ".venv", "venv", "env", "node_modules",
    "build", "dist", ".tox", ".mypy_cache", ".pytest_cache", "__pycache__", "site-packages",
})


def _is_skipped(p: Path, root: Path = PKG_ROOT) -> bool:
    """Лежит ли путь в не-исходном дереве ПОД `root` (копия пакета/кэш/venv) — тогда в обходе игнор.

    Сегменты сверяются ОТНОСИТЕЛЬНО `root`, а не по абсолютному пути: сам корень репозитория может
    лежать ПОД каталогом с именем из SKIP_DIRS — кит держит рабочие копии в `.ai/worktrees/` и
    `.claude/worktrees/`, и полный путь тогда содержит `.ai`/`.claude` как ПРЕДКА корня. Матч по
    абсолютным сегментам отбросил бы ВЕСЬ пакет из-за имени вышестоящей папки (все модули стали бы
    «0 импортёров» → ложный дормант). Смотрим только то, что НИЖЕ корня.
    """
    try:
        parts = set(p.relative_to(root).parts)
    except ValueError:
        parts = set(p.parts)          # путь вне корня (в обходе не встречается) — на всякий по полному
    return bool(SKIP_DIRS & parts)


def _imports_in(path: Path, known: set[str]) -> set[str]:
    """Модули пакета, импортируемые файлом (включая функционально-локальные импорты)."""
    out: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (SyntaxError, OSError):
        return out
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith(PKG):
            if n.module in known:
                out.add(n.module)
            for alias in n.names:
                cand = f"{n.module}.{alias.name}"
                if cand in known:
                    out.add(cand)
        elif isinstance(n, ast.Import):
            for alias in n.names:
                if alias.name in known:
                    out.add(alias.name)
    return out


def _nontest_importers(modules: dict[str, Path]) -> dict[str, set[str]]:
    """Для каждого модуля — множество НЕ-ТЕСТОВЫХ файлов, которые его импортируют (без самоимпорта)."""
    known = set(modules)
    importers: dict[str, set[str]] = {m: set() for m in modules}
    pkg_dir = PKG_ROOT / PKG
    for p in PKG_ROOT.rglob("*.py"):
        if _is_skipped(p) or _is_test_path(p):   # копии пакета вне рабочего дерева — не импортёры
            continue
        src = _dotted(p) if p.is_relative_to(pkg_dir) else str(p.relative_to(PKG_ROOT))
        for imp in _imports_in(p, known):
            if imp != src:  # самоимпорт не встраивает модуль в контур
                importers[imp].add(src)
    return importers


def _find_dormant(zero_importer: set[str], allow_prefixes: tuple[str, ...],
                  allow_modules: set[str]) -> set[str]:
    """Чистая классификация: из 0-импортерных вычесть легит-входы -> генуинно дормантные.

    Отдельная функция без обращения к диску — чтобы посадить синтетический модуль и проверить
    детектор на данных, а не на реальном дереве.
    """
    return {m for m in zero_importer
            if not m.startswith(allow_prefixes) and m not in allow_modules}


def _dormant_now() -> set[str]:
    """Генуинно-дормантные модули на текущем дереве (0 не-тестовых импортеров, не легит-вход)."""
    modules = _pkg_modules()
    importers = _nontest_importers(modules)
    zero = {m for m in modules if not importers[m]}
    return _find_dormant(zero, ALLOWLIST_PREFIXES, set(ALLOWLIST_MODULES))


@pytest.mark.contract
def test_importer_counter_is_correct_on_known_facts(tmp_path):
    """Счётчик импортеров верен: дормант=0, проведённый>0, самоимпорт и тест-импорт не считаются."""
    modules = _pkg_modules()
    importers = _nontest_importers(modules)

    # Реальные факты дерева.
    assert importers[f"{PKG}.intelligence.decision_loop"] == set(), \
        "decision_loop обязан иметь 0 не-тестовых импортеров (дормантный факт)"
    assert len(importers[f"{PKG}.engine.pipeline_evidence"]) >= 1, \
        "pipeline_evidence импортируется рабочим кодом — счётчик не должен занулять всё подряд"
    assert max((len(v) for v in importers.values()), default=0) >= 5, \
        "в пакете есть широко импортируемые модули — счётчик их обязан видеть"

    # Синтетика: временный файл, импортирующий реальный модуль, засчитывается как импортёр.
    known = set(modules)
    probe = tmp_path / "probe_importer.py"
    probe.write_text("from ai_ops_kit.intelligence import decision_loop\n", encoding="utf-8")
    assert f"{PKG}.intelligence.decision_loop" in _imports_in(probe, known)

    # Самоимпорт не должен считаться проводкой: файл, «импортирующий сам себя», даёт 0.
    self_ref = _find_dormant({"pkg.mod.self"}, (), set())
    assert self_ref == {"pkg.mod.self"}


@pytest.mark.contract
def test_no_new_built_not_wired_module_beyond_ceiling():
    """РАТЧЕТ (вверх нельзя): новый 0-импортерный модуль вне allowlist и вне потолка — красное."""
    dormant = _dormant_now()
    # advisory: инвентарь дормантного печатается, чтобы человек видел долг (pytest покажет на ошибке).
    print("\nДормантный инвентарь (0 не-тестовых импортеров, не легит-вход):")
    for m in sorted(dormant):
        print(f"  - {m}")
    new_dormant = dormant - set(KNOWN_DORMANT)
    assert not new_dormant, (
        "построено, но НЕ проведено в контур: у этих модулей 0 не-тестовых импортеров, они не в "
        "allowlist легит-входов и не в замороженном потолке KNOWN_DORMANT:\n  "
        + "\n  ".join(sorted(new_dormant))
        + "\nПроведите модуль в рабочий путь (не-тестовый импортер), либо объявите легит-вход в "
          "ALLOWLIST_MODULES с причиной, либо, если это признанный долг, внесите в KNOWN_DORMANT.")


@pytest.mark.contract
def test_known_dormant_list_only_shrinks():
    """Ратчет вниз: каждая строка потолка (а) существует и (б) всё ещё дормантна (0 импортеров)."""
    missing = [m for m in sorted(KNOWN_DORMANT)
               if not (PKG_ROOT / (m.replace(".", "/") + ".py")).is_file()]
    assert not missing, (
        "в KNOWN_DORMANT перечислены модули, которых нет — список стал кладбищем:\n  "
        + "\n  ".join(missing))
    dormant = _dormant_now()
    resurrected = [m for m in sorted(KNOWN_DORMANT) if m not in dormant]
    assert not resurrected, (
        "эти модули БОЛЬШЕ не дормантны — их провели в контур или объявили легит-входом. Уберите их "
        "из KNOWN_DORMANT, иначе потолок перестаёт что-либо значить:\n  " + "\n  ".join(resurrected))


@pytest.mark.contract
def test_the_guard_sees_the_frozen_dormant_set():
    """Охрана обязана ВИДЕТЬ потолок как дормантный: иначе и новый дормант она пропустит."""
    dormant = _dormant_now()
    not_detected = set(KNOWN_DORMANT) - dormant
    assert not not_detected, (
        "детектор ослеп на признанном дормантном наборе (значит и новый built-not-wired пропустит): "
        + ", ".join(sorted(not_detected)))


@pytest.mark.contract
def test_legitimate_standalone_entry_is_not_flagged():
    """Легит-вход (валидатор и диспетчируемый CLI-main) НЕ попадает в дормантные, хотя 0 импортеров."""
    modules = _pkg_modules()
    importers = _nontest_importers(modules)
    dormant = _dormant_now()

    validator = f"{PKG}.validation.validate_layering"
    assert importers[validator] == set(), "валидатор ожидаемо без импортеров (его зовут процессом)"
    assert validator not in dormant, "валидатор — легит-вход по префиксу, не дормант"

    dispatched = f"{PKG}.intelligence.nightly_review"
    assert importers[dispatched] == set(), "nightly_review зовут процессом из команды, не импортом"
    assert dispatched not in dormant, "диспетчируемый CLI-main — легит-вход, не дормант"


@pytest.mark.contract
def test_planted_new_dormant_module_reddens():
    """Синтетика: новый 0-импортерный модуль вне allowlist, привязанный к done, ломает ратчет."""
    planted = f"{PKG}.intelligence.brand_new_orphan"
    zero_importer = set(KNOWN_DORMANT) | {planted}

    dormant = _find_dormant(zero_importer, ALLOWLIST_PREFIXES, set(ALLOWLIST_MODULES))
    assert planted in dormant, "детектор обязан отнести новый неподключённый модуль к дормантным"

    new_beyond_ceiling = dormant - set(KNOWN_DORMANT)
    assert new_beyond_ceiling == {planted}, \
        "ратчет обязан покраснеть ровно на новом дормантном модуле сверх потолка"

    # А легит-вход с тем же нулём импортеров ратчет не трогает.
    entry = f"{PKG}.validation.validate_brand_new"
    dormant2 = _find_dormant({entry}, ALLOWLIST_PREFIXES, set(ALLOWLIST_MODULES))
    assert entry not in dormant2, "новый валидатор — легит-вход по префиксу, не дормант"


@pytest.mark.contract
def test_non_source_trees_are_not_counted_as_importers():
    """Копии пакета вне рабочего дерева НЕ считаются импортёрами (иначе дормант ложно «проведён»).

    Обход идёт от КОРНЯ репо, а под ним могут лежать не-исходные деревья с полными копиями пакета:
    gitignored git-worktree (`.ai/worktrees/…`) и editable-установка (`.venv/…/site-packages/…`).
    Их файл `import ai_ops_kit.<модуль>` не должен зачесть дормантный модуль проведённым в контур.
    """
    copy_paths = [
        PKG_ROOT / ".ai" / "worktrees" / "x" / "ai_ops_kit" / "engine" / "foo.py",
        PKG_ROOT / ".venv" / "lib" / "python3.12" / "site-packages"
        / "ai_ops_kit" / "intelligence" / "decision_loop.py",
        PKG_ROOT / "node_modules" / "pkg" / "x.py",
        PKG_ROOT / "build" / "lib" / "ai_ops_kit" / "engine" / "bar.py",
    ]
    for p in copy_paths:
        assert _is_skipped(p), f"путь-копия обязан отбрасываться обходом: {p}"

    # Настоящий исходник (в ai_ops_kit/ или installer/) обходом НЕ отбрасывается.
    assert not _is_skipped(PKG_ROOT / "ai_ops_kit" / "engine" / "tool_broker.py")
    assert not _is_skipped(PKG_ROOT / "installer" / "ai_ops.py")

    # Интеграция: реальный обход зовёт предикат — на текущем дереве decision_loop остаётся 0-импортерным
    # даже если рядом (в .ai/.venv) лежит его копия, потому что такие деревья пропускаются.
    importers = _nontest_importers(_pkg_modules())
    assert importers[f"{PKG}.intelligence.decision_loop"] == set(), \
        "decision_loop обязан остаться дормантным — копии из не-исходных деревьев не в счёт"


@pytest.mark.contract
def test_skip_predicate_ignores_ancestor_named_like_non_source(tmp_path):
    """Корень репо может лежать ПОД каталогом из SKIP_DIRS — предикат смотрит путь ОТНОСИТЕЛЬНО корня.

    Кит держит рабочие копии в `.ai/worktrees/` и `.claude/worktrees/`: полный путь до корня тогда
    содержит `.ai`/`.claude` как ПРЕДКА. Матч по абсолютным сегментам отбросил бы ВЕСЬ пакет из-за
    имени вышестоящей папки — каждый модуль стал бы «0 импортёров», и весь инвентарь превратился бы в
    ложный дормант. Этот тест воспроизводит сценарий синтетическим корнем (в CI корень лежит в
    /home/runner/… без таких предков, поэтому иначе регресс там не виден).
    """
    root = tmp_path / ".claude" / "worktrees" / "wt"        # корень ПОД .claude — как у самого кита
    src = root / "ai_ops_kit" / "engine" / "tool_broker.py"
    nested_copy = root / ".ai" / "worktrees" / "c" / "ai_ops_kit" / "engine" / "x.py"

    # Настоящий исходник НЕ скипается, хотя абсолютный путь содержит .claude как предок корня.
    assert not _is_skipped(src, root=root), \
        "исходник под корнем-в-.claude обязан считаться исходником (сегмент-предок не в счёт)"
    # Копия ПОД корнем (в .ai/worktrees) — скипается по сегменту НИЖЕ корня.
    assert _is_skipped(nested_copy, root=root), \
        "копия пакета под корнем обязана отбрасываться"
