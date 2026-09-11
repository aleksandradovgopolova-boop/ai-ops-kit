"""Состав поставки и её бюджет: managed_set (что едет в дочку), владение пакетами, runtime-vs-dev фильтр, разбивка/потолки объёма поставки.

Под-хаб установщика (вынесен из монолита `installer/ai_ops.py`). `installer/` — НЕ пакет: модуль
грузит фасад `installer/core.py` ленивым sibling-импортом и проставляет сюда живые глобалы
работающего экземпляра установщика (`_AO_NS`). Глобалы и мелкие хелперы установщика
(`PKG`/`AI_DIR`/`REPO_ROOT`/`MANAGED`/`CHILD_CONFIG`/`CI`, `ChildConfigError`, загрузчики сателлитов
`_plan_merge_setup`/`_ci_setup`/`_child_scaffolding`) читаются через `_ao()`; хаб-функции из ДРУГИХ
под-хабов — через `_core().X` (фасад находит нужный под-хаб). Функции этого же под-хаба зовутся по
имени. Дробление на под-хабы <700 строк держит хаб ниже ратчета размера модуля — монолит не
возрождается одним core.py.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve()
_AO_NS = None


class _AoView:
    """Атрибутный доступ (чтение и запись) к namespace-словарю установщика (`ai_ops.__dict__`)."""
    __slots__ = ("_d",)

    def __init__(self, d):
        object.__setattr__(self, "_d", d)

    def __getattr__(self, name):
        try:
            return self._d[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        self._d[name] = value


def _ao():
    """Модуль установщика через живой экземпляр, хранимый на ФАСАДЕ (`core._AO_NS`) — ЕДИНЫЙ источник
    истины. Своя копия `_AO_NS` замораживалась бы, если бы ссылку на функцию под-хаба кто-то закэшировал
    в обход фасадного `__getattr__` (так делает monkeypatch на фасаде в тестах) — тогда `_load` не
    переставил бы её, и под-хаб читал бы устаревший экземпляр установщика. Фасад же переставляется на
    КАЖДОМ обращении `ai_ops.__getattr__`/`_core()`."""
    if str(_HERE.parent) not in sys.path:
        sys.path.insert(0, str(_HERE.parent))
    import core
    ns = core._AO_NS
    if ns is not None:
        return _AoView(ns)
    import ai_ops
    return ai_ops


def _core():
    """Фасад хаба (installer/core.py) — маршрутизирует к соседним под-хабам."""
    return _ao()._core()


def parent_source():
    """URL parent-репозитория для parent.source ('git+<url>'), из git remote пакета.
    userinfo (креды) вырезается — секреты в конфиг не попадают. None, если remote недоступен."""
    import re as _re
    r = subprocess.run(["git", "-C", str(_ao().PKG), "config", "--get", "remote.origin.url"],
                       capture_output=True, text=True)
    url = r.stdout.strip()
    if r.returncode != 0 or not url:
        return None
    url = _re.sub(r"^(https?://)[^/@]*@", r"\1", url)   # убрать user[:pass]@ из http(s)
    url = _re.sub(r"^(ssh://)[^/@]*@", r"\1", url)
    return f"git+{url}"


def _child_cfg_data():
    return _core()._read_child_cfg()


def _configured_runtimes():
    """v3.14.0 срез 3: какие рантаймы репозиторий настроил (адаптеры только для них).
    runtimes.configured (список) > [runtimes.default] > None (=все известные, back-compat)."""
    rt = (_child_cfg_data().get("runtimes") or {})
    conf = rt.get("configured")
    if isinstance(conf, list) and conf:
        return [str(x) for x in conf]
    d = rt.get("default")
    return [str(d)] if isinstance(d, str) and d else None


def _surface_filter(kind):
    """runtime_surface.<kind>.enabled -> set имён или None (=экспортировать всё). kind: skills|commands."""
    rs = (_child_cfg_data().get("runtime_surface") or {}).get(kind) or {}
    en = rs.get("enabled")
    if isinstance(en, list):
        return set(str(x) for x in en)
    return None                                      # 'all' или отсутствие -> всё


def materialize_runtime(child_root: Path):
    """Сгенерировать runtime-команды и УСТАНОВИТЬ их туда, где их находит раннер.
    generate_runtime пишет source of truth в .ai/generated/<runtime>/…; здесь мы
    ставим команды claude-code в .claude/commands/ (command_loading из runtimes.yaml),
    иначе после установки среда не видит сгенерированные точки входа. Возвращает число
    установленных команд. v3.14.0: адаптеры только для настроенных рантаймов + фильтр поверхности."""
    import os
    if str(_ao().PKG) not in sys.path:
        sys.path.insert(0, str(_ao().PKG))
    from ai_ops_kit.shared import generate_runtime
    generate_runtime.generate(child_root, verbose=False,
                              runtimes=_configured_runtimes(),
                              command_filter=_surface_filter("commands"))
    # claude-code -> .claude/commands/ (command_loading из runtimes.yaml)
    src = child_root / ".ai" / "generated" / "claude-code" / "commands"
    dst = child_root / ".claude" / "commands"
    dst.mkdir(parents=True, exist_ok=True)
    claude = 0
    if src.is_dir():
        for f in sorted(src.glob("*.md")):
            shutil.copy2(f, dst / f.name)
            claude += 1
    # codex -> $CODEX_HOME/prompts/ (env-var путь ВНЕ репо), только если CODEX_HOME задан
    xsrc = child_root / ".ai" / "generated" / "codex" / "prompts"
    codex_generated = len(list(xsrc.glob("*.md"))) if xsrc.is_dir() else 0
    codex = 0
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home and xsrc.is_dir():
        xdst = Path(codex_home) / "prompts"
        xdst.mkdir(parents=True, exist_ok=True)
        for f in sorted(xsrc.glob("*.md")):
            shutil.copy2(f, xdst / f.name)
            codex += 1
    # qwen-code -> .qwen/commands/ (in-repo путь, command_loading из runtimes.yaml), ТОЛЬКО если
    # рантайм ЯВНО включён в .ai-ops.yaml. Как codex гейтится на CODEX_HOME, так qwen — на явное
    # включение: иначе каждая дочка получала бы каталог .qwen/, которым не пользуется.
    qsrc = child_root / ".ai" / "generated" / "qwen-code" / "commands"
    qwen_generated = len(list(qsrc.glob("*.md"))) if qsrc.is_dir() else 0
    qwen = 0
    enabled = _configured_runtimes()
    if qsrc.is_dir() and enabled is not None and "qwen-code" in enabled:
        qdst = child_root / ".qwen" / "commands"
        qdst.mkdir(parents=True, exist_ok=True)
        for f in sorted(qsrc.glob("*.md")):
            shutil.copy2(f, qdst / f.name)
            qwen += 1
    return {"claude_commands": claude, "codex_prompts": codex, "codex_generated": codex_generated,
            "qwen_commands": qwen, "qwen_generated": qwen_generated}


def manifest():
    return yaml.safe_load((_ao().PKG / "manifest" / "ai-ops-manifest.yaml").read_text(encoding="utf-8"))


def package_ownership(pkg_root=None):
    """v2.48 (3.0-срез 2): {relative_path: package_name} из packages/*/package.yaml.
    Пусто, если деклараций нет. Паттерн 'dir/**' нормализуется в 'dir/**/*' (pathlib)."""
    root = Path(pkg_root or _ao().PKG)
    owned = {}
    for pf in sorted(root.glob("packages/*/package.yaml")):
        try:
            decl = yaml.safe_load(pf.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        name = decl.get("name", pf.parent.name)
        for pat in decl.get("includes", []) or []:
            eff = pat + "/*" if pat.endswith("/**") else pat
            for p in root.glob(eff):
                if p.is_file():
                    owned[p.relative_to(root).as_posix()] = name
    return owned


def selected_packages():
    """Опциональный список пакетов из child .ai-ops.yaml -> packages. None -> все (дефолт).
    Обратная совместимость: поля нет -> None -> ставится всё (footprint как раньше)."""
    pkgs = _core()._read_child_cfg().get("packages")
    return list(pkgs) if isinstance(pkgs, list) and pkgs else None


def filter_by_packages(pairs, selected, ownership):
    """Оставить managed-файлы по выбору пакетов. Инвариант честности: файл, не назначенный
    НИ ОДНОМУ пакету, ставится ВСЕГДА (структура ещё не разбита целиком — срез 3); файл,
    принадлежащий пакету, ставится только если пакет выбран. selected=None -> всё."""
    if not selected:
        return pairs
    sel = set(selected)
    return [(src, rel) for (src, rel) in pairs
            if ownership.get(rel) is None or ownership.get(rel) in sel]


# ─── Разделение поставки: runtime vs dev (v3.28.x, P2-7) ────────────────────────────────
# В child-репозиторий едет только то, что нужно для ИСПОЛНЕНИЯ (`ai-ops run/plan/status/
# doctor/onboard` + гейты). Ассеты РАЗРАБОТКИ САМОГО КИТА остаются в parent: они проверяют
# кит, а не продукт пользователя, и раздували поставку (503 файла / ~3.6 МБ managed).
#
# Инвариант честности (failure mode №5 Change Brief): исключать можно ТОЛЬКО файл, который
# ни один поставляемый модуль/политика/реестр не вызывает в child. Полнота рантайм-замыкания
# движка доказывается ai_ops_kit/validation/validate_standalone_engine.py (ENGINE_CLOSURE) и
# tests/unit/test_installer.py — регресс упадёт там, а не молча у пользователя.

DEV_ONLY_PREFIXES = (
    "qualification/",   # пакет живых сценариев квалификации движка — данные разработки кита
    "containers/",      # эталонный контейнер изоляции движка (P0.2 jail) — ассет parent-репозитория
    # 2026-08-17: НАЙДЕНО НОВОЙ ПРОВЕРКОЙ ПОСТАВКИ, не чтением кода. `devtools` — инструменты
    # разработки САМОГО кита (бенчмарки, харнессы квалификации, мутационные пробы). Их исключение
    # существовало (DEV_ONLY_TOOLS ниже), но проверялось ТОЛЬКО для путей `tools/` — а в v3.30 код
    # переехал в пакеты, и в `tools/` остались тонкие алиасы. Итог: алиасы отсекались, а сам код
    # `ai_ops_kit/devtools/*.py` уезжал в дочку целиком, вместе с импортом валидатора, которого в
    # поставке нет (`promotion_qual` -> `validate_promotion_qualification`) — то есть в дочке лежал
    # мёртвый груз с гарантированным ImportError.
    # Ровно тот класс, что и F-032: переезд дал новые пути, а фильтр остался на старых.
    # Безопасно по построению: слой `entrypoints` продуктовый код импортировать не вправе, и это
    # проверяет `validate_layering` (правило no-product-depends-on-devtools).
    "ai_ops_kit/devtools/",
)

# НЕ ПОДКЛЮЧЁННОЕ НЕ ЕДЕТ (19.08.2026, разбор после аудита).
#
# Двенадцать модулей, добавленных 19.08, уезжали в дочку и были там НЕДОСТИЖИМЫ: ни один
# поставляемый модуль их не импортирует, ни один реестр, гейт, workflow или команда не называет,
# и ни один документ кита о них не упоминает. Замер на свежей установке: 0 импортов из поставки
# (единственная ссылка была внутри самой группы), 0 упоминаний в
# registry/quality/config/commands/workflows, 0 в README.md и docs/.
#
# Цена была видна сразу: потолок поставки пробит — 479 содержательных файлов при 475 и 3.7449 МБ
# при 3.7. Поднимать потолок здесь было бы неправдой: он поднимается, когда в дочку едет то, что
# в дочке РАБОТАЕТ (так его поднимали в v3.35 и 17.08), а не то, что до неё просто дотянулось.
#
# ЭТО НЕ ПРИГОВОР МОДУЛЯМ. Они задуманы работать именно в продуктовом репозитории; им не хватает
# подключения — интента, гейта или записи в реестре. Как только подключение появится, модуль
# обязан уехать обратно, и об этом скажет не память автора, а проверка: тест
# `test_unwired_modules_are_really_unwired` краснеет, если имя из этого списка кто-то начал звать.
# Список вправе только СОКРАЩАТЬСЯ — как ратчет слоёв и как потолок поставки.
UNWIRED_MODULES = frozenset({
    # `kernel/ports.py` побывал здесь ровно один коммит (2026-08-25) и УШЁЛ проводкой, а не решением:
    # транзакционный контроллер `ai_ops_run` сверяет свои параметры прогона с ExecutionSpec на каждом
    # запуске (страж дрейфа контракта). `kernel/ports.py` — контракт ТИПОВ, не шов с реализациями.
    # Четыре модуля-заготовки под Phase B (engops/{delivery_size,merge_lifecycle,refusal_paths,
    # session_thresholds}) СНЯТЫ 2026-09-05: 0 импортеров, порту не соответствовали, дормантный
    # инвентарь. Понадобится Phase B — реализации восстановят против Protocol'ов ports.py.
    # `intelligence/artifact_reality_check.py` СНЯТ ИЗ ПОСТАВКИ 2026-09-07 (#589, веха 4.2): не
    # проведён решением, а УДАЛЁН как дормантный дубль. 0 импортеров, без своих тестов; его предмет
    # (ссылки артефактов ведут в существующие файлы) уже покрывают ШИПНУТЫЕ валидаторы
    # validate_references/validate_cross_artifacts, которые агрегирует nightly_review. Вторая
    # реализация той же проверки — вторая правда, ровно то, что кит запрещает. Файл удалён вместе с
    # именем; `test_every_unwired_module_still_exists` не даст имени пережить файл.
    # `intelligence/decision_loop.py` УБРАН ИЗ СПИСКА 2026-09-07 (#564): он ПОДКЛЮЧЁН. Маршрут
    # `run --execute`/`do` (ai_ops_kit/cli/ai_ops_cli.py, `_decision_contract_gate`) импортирует его
    # и зовёт `has_feature_decision_contract` — fail-closed присутствие Decision-контракта для
    # триггерного профиля (сигнал feature_decision_declared). Значит модуль обязан ехать в дочку:
    # оставить его в UNWIRED значило бы дать дочке cli, зовущий отсутствующий файл (класс F-033).
    # Список сокращён ФАКТОМ подключения, а не решением — об этом сказал бы тест
    # `test_unwired_modules_are_really_unwired` (краснел бы, останься имя, раз cli его называет).
    # `intelligence/nightly_review.py` УБРАН 20.08.2026: он подключён. Команда рантайма
    # `commands/maintenance/night-review.md` зовёт его в дочке, и Robin запускает по расписанию
    # (`runtime/robin/duties.example.yaml`, обязанность `nightly-review`). Не поставить его
    # значило бы дать дочке команду, которая ссылается на отсутствующий файл — класс F-033.
    # Собственных импортов из кита у модуля нет, второй файл он за собой не тянет (проверено).
    #
    # ГРАНИЦА ПЕРЕСЕЧЕНА ОСОЗНАННО И НАЗВАНА: `installer/` — территория ленты B. Правка на одну
    # строку списка; оставить её несделанной было нельзя, иначе работа ленты A уехала бы в дочку
    # наполовину. Ленте B сказано.
    # `intelligence/outcome_analytics.py` УБРАН ИЗ СПИСКА 2026-09-07 (#584): он ПОДКЛЮЧЁН. Пост-релизный
    # путь `ai_ops_kit/cli/post_release_loop.py` (`_assess_cost_analytics`) импортирует его и зовёт
    # `collect_analytics` в `run_post_release` — стоимостная/эффект-аналитика ПОД пост-релизным путём
    # (не второй outcome-вердикт: тот остаётся за #566). Значит модуль обязан ехать в дочку: cli его
    # зовёт, оставить в UNWIRED значило бы дать дочке cli, вызывающий отсутствующий файл (класс F-033).
    # Список сокращён ФАКТОМ подключения — об этом сказал бы `test_unwired_modules_are_really_unwired`.
    # СНЯТЫ ИЗ ПОСТАВКИ 2026-09-07 (#589, веха 4.2) — УДАЛЕНЫ как дормантный груз, не «отложены»:
    #   · `intelligence/refactoring_advisor.py` — 0 импортеров, без своих тестов; грубые строковые
    #     эвристики (большие файлы/сложные функции) дублируют РЕАЛЬНЫЕ защёлки func-size/file-size
    #     кита. Общий совет без полевого пути к вызову.
    #   · `intelligence/session_watch.py` — 0 импортеров, без своих тестов; ДУБЛЬ уже проведённого
    #     `engops/session_guardrails` (classify_context/recommend, пороги compact/new_session),
    #     который зовут cli (ai_ops_cli) и engine (ai_ops_run_lifecycle). Порог сессии УЖЕ считается
    #     и всплывает — второй счётчик не нужен.
    #   · `intelligence/watch_contract.py` — 0 импортеров, без своих тестов; его заявленный
    #     потребитель `nightly_review` его НЕ импортирует и пошёл другим устройством (жёсткий кортеж
    #     CHECKS + реальное CI-расписание install_schedule). Схема WatchContract, которую никто не
    #     производит и не читает. Ночной МЕХАНИЗМ (nightly_review) при этом цел и проведён.
    # `planning/artifact_registry.py` и `planning/passport_generator.py` УБРАНЫ ИЗ СПИСКА 20.08.2026
    # (работа `product-layer-bootstrap`): они ПОДКЛЮЧЕНЫ. `_seed_product_layer` в этом установщике
    # читает реестр артефактов и генерирует Product Passport из фактического состояния дочки при
    # `ai-ops init`/`update` — значит оба обязаны быть в поставке, иначе установка вызовет файл,
    # которого в дочке нет (класс F-033). Список сократился фактом подключения, не решением автора.
    # `planning/product_templates.py` УБРАН ИЗ СПИСКА 20.08.2026 (работа `product-layer-validation`):
    # он ПОДКЛЮЧЁН. `validate_product_layer` зовёт его подпроцессом при `ai-ops validate product-layer`
    # В дочке, чтобы посчитать состояние Missing/Invalid/Outdated/Valid по её артефактам. Без него в
    # поставке валидация вызвала бы файл, которого в дочке нет (F-033). Список сокращён фактом подключения.
    # 2026-08-20: ЧЕТЫРЕ модуля ленты 4 УБРАНЫ ИЗ СПИСКА — они ПОДКЛЮЧЕНЫ (#241). Команды `ai-ops roadmap`
    # и `ai-ops delivery` (ai_ops_kit/cli/ai_ops_cli.py, DIRECT_INTENTS) зовут их в дочке:
    # roadmap_manager (roadmap), roadmap_milestones + delivery_planning + delivery_planning_blockers
    # (delivery). Не поставить их теперь значило бы дать дочке команду, ссылающуюся на отсутствующий
    # файл (класс F-033). Сокращение списка — фактом подключения, а не решением: об этом сказал тест
    # `test_unwired_modules_are_really_unwired` (краснел бы, останься имя, раз cli его зовёт).
    # `ui/experience_contract.py` УБРАН ИЗ СПИСКА 20.08.2026: он подключён. Сторона доказательства
    # (`ui/storybook_adapter`) читает Experience Contract дочки и берёт из него обязательные
    # состояния — значит модуль обязан быть в поставке, иначе у дочки будет вызов файла, которого
    # там нет (класс F-033). Список сокращается только так: не решением, а фактом подключения,
    # и об этом сказал не автор, а тест `test_unwired_modules_are_really_unwired`.
})

DEV_ONLY_TOOLS = frozenset({
    "bench_lite", "bench_performance", "retrieval_bench",  # бенчмарки самого движка/ретрива
    "model_comparison",                                    # сравнение моделей (исследование кита)
    "changelog_gen",                                       # генератор CHANGELOG кита
    "qual_run", "promotion_qual",                          # харнессы квалификации (данные — qualification/)
    "kit_observability",                                   # наблюдаемость самого кита
    "mutation_probe",                                      # мутационные пробы охран кита
})

# Валидаторы, которые РЕАЛЬНО вызываются в child-репозитории. Источники (проверяемо grep'ом):
#   ai_managed_checksums          — drift-detection managed-зоны (manifest.update_policy)
#   validate_ai_ops_child         — валидация установки (child-CI, `ai-ops validate`)
#   validate_claims/_references/_freshness            — ai_ops_kit/gates/gate_executor.py
#   validate_cross_artifacts/_feature_blueprint       — ai_ops_kit/lifecycle/run_report.py
#   validate_plan_artifact/_requirements_artifact     — ai_ops_kit/engine/pipeline_helpers.py
#   validate_spec_artifact/_reviewer_result           — ai_ops_kit/engine/pipeline_evidence.py, orchestrator
#   validate_memory_governance                        — ai_ops_kit/security/security_enforcement.py
#   validate_adr_registry/_quality_attributes         — ai_ops_kit/intelligence/evolution_triggers.py
#   validate_surface_wiring/_scenario_evidence/_event_catalog/_openspec_change — quality/gates.yaml
#   validate_engops_policy/_duties/_knowledge_graph/_storybook_evidence — политики и реестры в поставке
#   validate_architecture_decision                    — транзитивный импорт из keep-set
# Остальные (validate_package_boundaries, validate_qualification, validate_release_claims,
# validate_container_*, validate_ai_first_*, …) проверяют ВНУТРЕННИЕ инварианты кита и гоняются
# только в parent-CI — в child они мёртвый груз.
RUNTIME_VALIDATORS = frozenset({
    "__init__", "ai_managed_checksums", "validate_ai_ops_child",
    "validate_claims", "validate_references", "validate_freshness",
    "validate_cross_artifacts", "validate_feature_blueprint",
    "validate_plan_artifact", "validate_requirements_artifact",
    "validate_spec_artifact", "validate_reviewer_result", "validate_memory_governance",
    "validate_adr_registry", "validate_quality_attributes", "validate_architecture_decision",
    "validate_surface_wiring", "validate_scenario_evidence", "validate_event_catalog",
    "validate_openspec_change", "validate_engops_policy", "validate_duties",
    "validate_knowledge_graph", "validate_storybook_evidence",
    # F-033 (поле 15.08.2026): сверка критериев приёмки с результатом — механизм ПРОТИВ ложного
    # green, построенный 14.08 и починенный 15.08, — в дочке не исполнялся НИКОГДА: его зовёт
    # `engine/acceptance_verify` (строка `from ai_ops_kit.validation import
    # validate_acceptance_result`), а в поставку он не попадал, потому что имя не внесли сюда.
    # Список был памятью автора, а не проверяемым фактом; теперь его сторожит
    # `test_delivered_engine_does_not_import_undelivered_validators`.
    "validate_acceptance_result",
    # B2-25 (19.08.2026): проверку «в конфиге дочки не осталось заготовок установки» зовёт `doctor`,
    # который исполняется ИМЕННО У ДОЧКИ. Не внести имя сюда значило бы починить кит и не починить
    # дочку — тот же класс, что F-033. Поймано не рассуждением, а тестом на НАСТОЯЩЕЙ установке:
    # `doctor` в свежепоставленной копии печатал «НЕ ПРОВЕРЕНО (cannot import name …)».
    "validate_child_config_filled",
    # 20.08.2026, работа `product-layer-validation` (PR-5): `ai-ops validate product-layer`
    # исполняется У ДОЧКИ — считает состояние `.ai-ops/` (Missing/Invalid/Outdated/Valid). Не внести
    # имя сюда значило бы починить кит и не починить дочку (F-033), как было с validate_acceptance_result.
    "validate_product_layer",
    # 2026-09-02, issue #439 (tests-verify-behavior): метрика «поведенческие vs структурные тесты»
    # и ратчет её доли. Валидатор едет в дочку, чтобы она мерила ТАКСОНОМИЮ СВОИХ тестов тем же
    # инструментом — перекос «читаем свои файлы вместо исполнения поведения» не должен быть виден
    # только у кита. Standalone (stdlib+pyyaml, `import _bootstrap` не нужен), запускается процессом
    # у дочки.
    "validate_test_taxonomy",
    # 2026-09-02 (module-size-ratchet): ратчет размера МОДУЛЯ — заморозить монолиты вниз. Валидатор
    # едет в дочку, чтобы она стерегла размеры СВОИХ файлов ai_ops_kit/**/*.py тем же инструментом:
    # ужатый монолит не должен молча отрастать только потому, что замок стоит у кита, а не у неё.
    # Standalone (stdlib+pyyaml, `import _bootstrap` не нужен), запускается процессом у дочки.
    "validate_module_size",
    # 2026-09-07, issue #545 (outcome-loop): пост-релизный путь `ai-ops readout` исполняется У ДОЧКИ
    # (после её выпуска владелец сверяет приход событий в аналитику и сводит вердикт). Доставляемый
    # оркестратор ai_ops_kit/cli/post_release_loop.py импортирует эти два валидатора; не внести их сюда
    # значило бы починить кит и оставить дочке ImportError — ровно класс F-033, тот же, что
    # validate_acceptance_result. Оба standalone (stdlib+pyyaml, `import _bootstrap` не нужен). Поймано
    # тестом test_delivered_engine_does_not_import_undelivered_validators, а не рассуждением.
    "validate_post_release_readout", "validate_product_objects",
    # #678 (built≠wired -> wired): access-filter и key-lifecycle стерегут РЕАЛЬНЫЕ политики ДОЧКИ
    # (.ai/policies/access-filter.yaml, .ai/policies/key-lifecycle.yaml — их читает рантайм:
    # load_child_policies / _load_klp_by_env). Раньше форму этих политик сверял только parent-CI по
    # ПРИМЕРАМ кита; форму политики дочки не проверял никто. Теперь едут в поставку и зовутся advisory
    # из `child_doctor` ПРОЦЕССОМ (не импортом — слой-инвариант рантайм↛validation). Оба standalone
    # (stdlib+pyyaml). budget_contract/context_architecture НЕ вносим: у дочки нет BudgetContract/CAD
    # (её `budget.yaml` — токенный бюджет, другой kind), они остаются parent-only (parent-CI).
    "validate_access_filter", "validate_key_lifecycle",
})


# ОТДЕЛЬНЫЕ ФАЙЛЫ, А НЕ ПРЕФИКСЫ: исключить каталог целиком нельзя — рядом лежат реестры, которые
# дочке нужны. Список ЯВНЫЙ по тому же правилу, что DEV_ONLY_PREFIXES: исключение из поставки не
# должно быть побочным эффектом (`test_managed_set_excludes_are_declared_not_implicit`).
DEV_ONLY_FILES = frozenset({
    # 20.08.2026, работа `release-claims-stays-in-the-kit`. Замер: `registry/release-claims.yaml`
    # весил 82 214 Б и ехал в КАЖДУЮ дочку, из них 61 336 Б (75%) — ключ `patch_note`, одна строка
    # релизной прозы на 37 080 символов. В дочке его не читает НИКТО: единственный потребитель —
    # `validate_release_claims`, а он не входит в RUNTIME_VALIDATORS. Проза переехала сюда; сам
    # claims остался в поставке, потому что у него ЕСТЬ читатель в дочке — `package_channel`
    # смотрит `channel` (18 Б) из `init`/`update`/`doctor`.
    "registry/release-notes.yaml",
    # 20.08.2026: `registry/artifact-registry.yaml` УБРАН отсюда (работа `product-layer-bootstrap`) —
    # теперь `_seed_product_layer` читает его в дочке при `ai-ops init`/`update`, чтобы знать состав
    # слоя и куда его класть; значит реестр обязан ехать в поставку. Схему кит в рантайме не читает
    # (`check` загрузчика самодостаточен) — это публичный контракт формы, и она остаётся dev-only.
    "schemas/artifact-registry.schema.json",
    # `product-audit.schema.json` — контракт формы отчёта аудита (PR-21). Кит в рантайме её не
    # читает (форма проверяется в самом `product_audit` и тестом), значит в дочку её слать незачем.
    "schemas/product-audit.schema.json",
    # `ai_ops_kit/cli/entry.py` — консольный вход `ai-ops` для pip/pipx
    # (`pyproject.toml -> [project.scripts]`). Дочка ставится КОПИРОВАНИЕМ и водит кит своей обёрткой
    # `./ai-ops` (`.ai/managed`, зовёт `ai_ops_cli` напрямую) — console_scripts у неё нет и этот вход
    # она не использует. В дочке файл был бы инертным (0 импортеров, вызывается только процессом
    # через pip). В pip-колесо он по-прежнему едет (packages.find, не managed_set), поэтому команда
    # `ai-ops` после установки пакета работает; в дочку слать незачем.
    "ai_ops_kit/cli/entry.py",
    # 07.09.2026, issue #615. `registry/decision-boundary.yaml` НАЗЫВАЕТ модель границы решений
    # (три класса действий × три оси) для governance и документации САМОГО кита. В дочке его пока
    # НЕ читает никто: единый классификатор, который считал бы класс из трёх осей, помечен в файле
    # `status: planned`, а исполняют границу уже едущие механизмы (policy_engine, routing-policy,
    # workflows, spec_levels). По тому же правилу, что `release-claims-stays-in-the-kit`, реестр без
    # читателя в дочке не едет в поставку — поедет, когда появится child-side читатель классификатора.
    "registry/decision-boundary.yaml",
})


def is_runtime_asset(rel):
    """Едет ли файл managed_set в child-репозиторий? False — ассет разработки кита."""
    if rel.startswith(DEV_ONLY_PREFIXES) or rel in DEV_ONLY_FILES:
        return False
    if rel in UNWIRED_MODULES:          # построено, но в дочке недостижимо — см. UNWIRED_MODULES
        return False
    stem = rel.rsplit("/", 1)[-1][:-3] if rel.endswith(".py") else None
    if rel.startswith("tools/") and stem in DEV_ONLY_TOOLS:
        return False
    if rel.startswith("ai_ops_kit/validation/") and stem is not None:
        # Белый список перечисляет ВАЛИДАТОРЫ. `_bootstrap` — не валидатор, а их загрузчик путей:
        # без него каждый уехавший валидатор умирает на `import _bootstrap` в первой же строке.
        # Так и вышло в v3.31.0: файл добавили в кит, а в поставку он не попал, потому что имя не
        # похоже на валидатор. Поймано прогоном установки в чистом окружении (v3.31.1).
        return stem in RUNTIME_VALIDATORS or stem == "_bootstrap"
    return True


def managed_set():
    """Список (source_path, relative_target) managed-файлов — из манифеста.
    v2.48: при заданном .ai-ops.yaml -> packages фильтруется по выбранным пакетам (аддитивно;
    дефолт — все пакеты, footprint без изменений).
    v3.28.x: отсекаются dev-ассеты кита (is_runtime_asset) — поставка = только исполнение."""
    pairs = []
    for pattern in manifest().get("update_policy", {}).get("managed_set", []):
        for src in sorted(_ao().PKG.glob(pattern)):
            if src.is_file():
                rel = src.relative_to(_ao().PKG).as_posix()
                if is_runtime_asset(rel):
                    pairs.append((src, rel))
    return filter_by_packages(pairs, selected_packages(), package_ownership())


def delivery_breakdown(top=10):
    """ЧТО занимает поставку: разбивка по каталогам и крупнейшие файлы. -> dict.

    ЗАЧЕМ (замер 20.08.2026). Потолок объёма ловил РОСТ и не показывал СОСТАВ: четыре подъёма подряд
    обсуждались числом «3.5 -> 3.7 -> 3.75 -> 3.8», и ни в одном не было видно, что именно лежит в
    поставке. Первый же взгляд на состав дал находку, которую до этого не называл никто:
    `manifest/ai-ops-manifest.yaml` — 252 581 Б в ОДНОМ файле, 6.6% поставки, вчетверо больше
    релизной прозы, из-за которой отдельно велась работа.

    Разбивка считается по тому же списку, что и сама поставка (`managed_set`), поэтому не может
    разойтись с ней: одна формула, а не два подсчёта.
    """
    by_dir, count = {}, {}
    files = []
    for src, rel in managed_set():
        size = src.stat().st_size
        head = rel.split("/")[0] if "/" in rel else "(корень)"
        by_dir[head] = by_dir.get(head, 0) + size
        count[head] = count.get(head, 0) + 1
        files.append((size, rel))
    total = sum(by_dir.values())
    files.sort(reverse=True)
    return {"total_bytes": total, "file_count": sum(count.values()),
            "by_dir": [{"dir": k, "bytes": v, "files": count[k],
                        "share": round(100.0 * v / total, 1) if total else 0.0}
                       for k, v in sorted(by_dir.items(), key=lambda kv: -kv[1])],
            "largest": [{"path": r, "bytes": b,
                         "share": round(100.0 * b / total, 1) if total else 0.0}
                        for b, r in files[:top]]}


def delivery_breakdown_lines(top=10):
    """Та же разбивка человеку — строками. Печатается там, где потолок пробит: узнав ЧИСЛО, человек
    первым делом спрашивает «а что там лежит», и ответ должен быть в том же сообщении."""
    rep = delivery_breakdown(top=top)
    out = [f"ПОСТАВКА: {rep['total_bytes']} Б в {rep['file_count']} файлах.",
           "  по каталогам:"]
    for d in rep["by_dir"]:
        out.append(f"    {d['bytes']:8d} Б  {d['share']:5.1f}%  {d['files']:4d} файл(ов)  {d['dir']}")
    out.append(f"  крупнейшие файлы (top {top}):")
    for f in rep["largest"]:
        out.append(f"    {f['bytes']:8d} Б  {f['share']:5.1f}%  {f['path']}")
    return out


def delivery_budget(pkg_root=None):
    """Объявленные потолки поставки и лента подъёмов. -> dict или None (реестра нет).

    Потолки живут В РЕЕСТРЕ, а не числами в тесте: до 20.08.2026 они были вписаны в assert, а записи
    о подъёмах лежали в двух разных блоках комментариев одного файла — и на вопрос «записан ли этот
    подъём» нельзя было ответить, посмотрев в одно место."""
    p = Path(pkg_root or _ao().PKG) / "quality" / "delivery-budget.yaml"
    if not p.is_file():
        return None
    try:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    return doc if isinstance(doc, dict) else None


# «Нужен запас» причиной не считается — правило записано с 13.08.2026 и до 20.08 исполнялось ровно
# настолько, насколько о нём помнили. Ловится дословно, а не «по духу»: список закрытый и короткий.
BUDGET_NON_REASONS = ("нужен запас", "чтобы прошло", "для запаса", "на будущее")
BUDGET_RAISE_REQUIRED = ("at", "what", "measured_before", "measured_after", "files",
                         "why_it_works_in_the_child")


def delivery_budget_errors(doc, shipped=None, exists=None):
    """Что не так с объявленным бюджетом поставки. -> список проблем (пустой = всё названо).

    ЛОГИКА ЖИВЁТ ЗДЕСЬ, А НЕ В ТЕСТЕ, И ЭТО ЗАМЕР 20.08.2026: первая версия этих охран стояла прямо
    в тесте и проверяла, что НАСТОЯЩИЙ реестр в порядке. Три мутационные пробы ВЫЖИЛИ — снятие
    охраны не роняло тест, потому что у проверки не было отрицательного случая. Проверка без «а вот
    так — нельзя» непробиваема по построению; ровно тот класс, ради которого весь контур проб и стоит.

    `shipped` — множество путей, которые реально едут в дочку; `exists` — предикат существования
    файла. Оба передаются, чтобы функцию можно было спросить и про выдуманный реестр.
    """
    problems = []
    if not isinstance(doc, dict):
        return ["реестр бюджета не разобран — проверять нечего"]
    ceilings = doc.get("ceilings") or {}
    raises = doc.get("raises") or []
    for key in ("volume_bytes", "substantive_files"):
        if not isinstance(ceilings.get(key), int):
            problems.append(f"ceilings.{key} не объявлен числом — потолка нет")
    vol = [r for r in raises if isinstance(r, dict) and r.get("what") == "volume"]
    if not vol:
        problems.append("в ленте нет ни одного подъёма объёма — потолок появился без записи")
    elif isinstance(ceilings.get("volume_bytes"), int) and \
            vol[-1].get("to_bytes") != ceilings["volume_bytes"]:
        problems.append(
            f"последний подъём объёма ведёт к {vol[-1].get('to_bytes')}, а потолок "
            f"{ceilings['volume_bytes']} — значит потолок поднят БЕЗ записи")
    for r in raises:
        if not isinstance(r, dict):
            problems.append("запись подъёма не словарь")
            continue
        tag = f"{r.get('at')} {r.get('work')}"
        for k in BUDGET_RAISE_REQUIRED:
            if not r.get(k):
                problems.append(f"{tag}: нет обязательного поля '{k}'")
        at = str(r.get("at") or "")
        if not (len(at) == 10 and at[4:5] == "-" and at[7:8] == "-"):
            problems.append(f"{tag}: дата не ISO ({at!r}) — без даты замер выдаёт себя за текущий")
        for k in ("measured_before", "measured_after"):
            if k in r and not isinstance(r.get(k), int):
                problems.append(f"{tag}: {k} не число")
        why = str(r.get("why_it_works_in_the_child") or "").lower()
        if any(f in why for f in BUDGET_NON_REASONS):
            problems.append(f"{tag}: причина подъёма — не причина, а запас: {why[:60]!r}")
        elif why and len(why) < 80:
            problems.append(f"{tag}: причина короче 80 символов — она обязана назвать РАБОТУ файла "
                            f"в дочке, а не факт его добавления")
        for rel in r.get("files") or []:
            if exists is not None and not exists(rel):
                problems.append(f"{tag}: названного файла нет — {rel}")
            elif shipped is not None and rel not in shipped:
                problems.append(f"{tag}: файл НЕ едет в дочку, а причина подъёма ссылается на его "
                                f"работу там — {rel}")
        if r.get("what") == "volume" and isinstance(r.get("from_bytes"), int) \
                and isinstance(r.get("to_bytes"), int) and r["to_bytes"] <= r["from_bytes"]:
            problems.append(f"{tag}: подъём не поднимает ({r['from_bytes']} -> {r['to_bytes']})")
    return problems


def footprint_breach_message(what, actual, ceiling, unit="Б", top=8):
    """Сообщение о пробитом потолке: число, правило подъёма И СОСТАВ поставки. -> str.

    ЗАМЕР 20.08.2026: четыре подъёма подряд обсуждались одним числом, и состав поставки не смотрел
    никто. Первый же взгляд дал находку — `manifest/ai-ops-manifest.yaml` 252 581 Б, 6.6% поставки в
    ОДНОМ файле. Узнав число, человек первым делом спрашивает «а что там лежит»; ответ обязан быть в
    том же сообщении, иначе его не ищут."""
    head = f"{what}: {actual} {unit}, потолок {ceiling} {unit}."
    rule = ("ПОДНЯТЬ ПОТОЛОК МОЖНО ТОЛЬКО ЗАПИСЬЮ в quality/delivery-budget.yaml: дата, замеры до и "
            "после, КАКИЕ файлы добавлены и ПОЧЕМУ они работают в дочке. «Нужен запас» причиной не "
            "считается, и проверка это ловит.")
    return "\n".join([head, rule, "Что занимает поставку сейчас:"] +
                      delivery_breakdown_lines(top=top))
