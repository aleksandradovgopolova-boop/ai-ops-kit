"""`./ai-ops verify-scope` — какой объём проверки нужен ТЕКУЩЕМУ изменению (решение tier/stage).

Доставляемый (child-facing) вход к уже доставленной политике верификации: по текущему diff
(база + локальные правки) командой отвечает, нужен ли продуктовый тест вообще и какого объёма —
только документация (skip) / затронутые тесты (affected|module) / полный обязательный набор (full),
плюс человеческая причина и — когда это осмысленно — точечный набор тестов.

ЗАЧЕМ ОН ЕСТЬ. Прямой «impact»-вход был только у разработки самого кита
(`ai_ops_kit/devtools/impact_check_cli.py`): он НЕ едет в дочку (installer DEV_ONLY_PREFIXES) и тянет
страж слотов хоста (`devtools/host_resource_cli`). Политика-ядро давно доставлена — решение tier
(`ai_ops_kit/gates/verification_tiers`) и граф зависимостей (`ai_ops_kit/context/repo_graph`) уже
лежат в `.ai/managed/` у дочек. Не хватало доставляемой точки входа, чтобы разработчик в дочке
получил ответ ЛОКАЛЬНО, не клонируя кит и не завися от dev-слоя.

ЧЕСТНАЯ ГРАНИЦА (см. change-brief). Граф строится из Python-AST. Для JS/TS и монорепо-дочек
per-test выбор по Python-графу невозможен — для них ценность команды это РЕШЕНИЕ tier/stage
(docs-only / backend / cross-cutting ⇒ какой обязательный набор и на каком гейте), а не иллюзия
JS-тест-селекции. Команда это называет прямо: tier + «точечный выбор тестов для этого стека
недоступен ⇒ консервативный набор».

FAIL-CLOSED. Неизвестное влияние ⇒ консервативный ответ (full / «гони обязательный набор»), никогда
не тихо-пустой или неверный выбор. Если git не отвечает или стек не Python — объём честно считается
неопределённым и возвращается полный набор с объяснением.

Слой: это `cli` (entrypoints). Импортирует ТОЛЬКО доставляемые слои (`gates`, `shared`, `ui`); ни
одного импорта из `ai_ops_kit.devtools.*` — страж слотов хоста (dev-only) сюда не приезжает и не
нужен (команда только читает diff, ничего не исполняет). Границу стережёт `validate_layering`
(правило no-product-depends-on-devtools) и тест `tests/unit/test_verify_scope_cli.py`.

CLI:
  ./ai-ops verify-scope [stage] [--base origin/main] [--json]
  stage ∈ explore|draft|ready_for_review|merge_candidate|release_candidate (по умолчанию — по diff+риску)
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

# Доставляемая политика-ядро. НИКАКИХ импортов из ai_ops_kit.devtools.* (dev-only, не едет в дочку).
from ai_ops_kit.context import repo_graph
from ai_ops_kit.gates import verification_tiers

# Стадии жизненного цикла, которые понимает decide_tier (+ короткие алиасы merge/release).
_STAGES = ("explore", "draft", "ready_for_review", "merge_candidate", "release_candidate",
           "merge", "release")


def changed_paths(root: Path, base: str | None):
    """Полный охват изменения: committed-diff к HEAD, индекс, worktree и untracked (включая удаления),
    и — если задана база — diff базы к HEAD. Зеркалит охват impact_check_cli, но без импорта из него.

    -> отсортированный список путей, либо None если git не ответил (не репозиторий / нет HEAD) — тогда
    вызывающий обязан ответить консервативно (fail-closed), а не выдумать «изменений нет»."""
    commands = [["git", "diff", "--no-renames", "--name-only", "-z", "HEAD"],
                ["git", "ls-files", "--others", "--exclude-standard", "-z"]]
    if base:
        commands.append(["git", "diff", "--no-renames", "--name-only", "-z", f"{base}...HEAD"])
    paths: set[str] = set()
    for command in commands:
        try:
            output = subprocess.check_output(command, cwd=str(root), stderr=subprocess.DEVNULL)
        except (subprocess.CalledProcessError, OSError):
            return None
        paths.update(p for p in output.decode("utf-8", "replace").split("\0") if p)
    return sorted(paths)


def _stacks(root: Path):
    """Языки стека дочки (из того же project_detector, что и выбор команд). Пусто — определить не вышло."""
    try:
        from ai_ops_kit.shared import project_detector
        profile = project_detector.detect(root)
    except Exception:  # noqa: BLE001 — определение стека не должно ронять read-only команду
        return []
    return [s.get("language") for s in (profile.get("stacks") or []) if s.get("language")]


def scope(root: Path, base: str | None, stage: str | None) -> dict:
    """Решение объёма проверки для текущего изменения. Всегда возвращает ответ (fail-closed)."""
    changed = changed_paths(root, base)
    if changed is None:
        # git не ответил — объём неизвестен. Консервативно: полный обязательный набор.
        return {"tier": "full", "full_command": True,
                "impact_status": verification_tiers.IMPACT_TARGETED_TESTS_NOT_FOUND,
                "changed_files": [], "affected_tests": [], "targeted_command": None,
                "note": "Scope unknown: git не ответил (не репозиторий или нет HEAD) — "
                        "консервативно полный обязательный набор",
                "degraded": True, "degrade_reason": "git-unavailable", "stacks": []}
    result = verification_tiers.select_tests(changed, str(root), lifecycle_intent=stage)
    result["stacks"] = _stacks(root)
    # Честный маркер деградации: объём не сузился (полный fallback при неизвестном влиянии).
    non_python_sources = any(f.endswith(repo_graph.JS_TS_EXTENSIONS) for f in changed)
    result["degraded"] = (result["tier"] == "full"
                          and result["impact_status"] == verification_tiers.IMPACT_TARGETED_TESTS_NOT_FOUND)
    if result["degraded"]:
        result["degrade_reason"] = (
            "non-python-stack" if (non_python_sources or "python" not in result["stacks"])
            else "incomplete-graph")
    return result


# ── Человеческий вывод через общий presenter (как lint-profile): смысл всегда, разбор — по запросу ──
def _say(root: Path, msg: dict) -> None:
    from ai_ops_kit.ui import presenter
    print(presenter.render(msg, audience=presenter.audience_from_config(root)))


def _message(*args, **kwargs) -> dict:
    from ai_ops_kit.ui import presenter
    return presenter.message(*args, **kwargs)


_TIER_HUMAN = {
    "skip": "только документация/конфиг allowlist",
    "affected": "затронутые тесты",
    "module": "тесты затронутых модулей",
    "full": "полный обязательный набор",
}


def _present(root: Path, result: dict) -> None:
    tier = result["tier"]
    affected = result.get("affected_tests") or []
    technical = {k: result.get(k) for k in
                 ("tier", "impact_status", "changed_files", "affected_tests", "targeted_command",
                  "risk_classes", "check_plan", "dependency_status", "stacks", "degrade_reason")
                 if result.get(k) is not None}
    if tier == "skip":
        _say(root, _message(
            "done",
            "Для этого изменения продуктовые тесты не нужны — это только документация или "
            "allowlist-проза.",
            why_it_matters="Обязательные lint и валидаторы всё равно применяются — они дешёвые и "
                           "ловят то, что к продуктовым тестам отношения не имеет.",
            technical=technical))
        return
    if tier == "full":
        if result.get("degraded"):
            reason = result.get("degrade_reason")
            why = ("Объём влияния определить точно нельзя, поэтому берём полный набор, а не угадываем "
                   "сужение.")
            if reason == "non-python-stack":
                why += (" Точечный выбор тестов кит делает по Python-графу зависимостей; для вашего "
                        "стека он недоступен — решение остаётся на уровне tier/стадии, а не отдельных "
                        "тестов.")
            elif reason == "incomplete-graph":
                why += " Граф зависимостей неполон (динамические или нечитаемые входы)."
            elif reason == "git-unavailable":
                why = result["note"]
            _say(root, _message(
                "degraded",
                "Нужен полный обязательный набор проверок — сузить объём для этого изменения "
                "безопасно нельзя.",
                why_it_matters=why, technical=technical))
        else:
            _say(root, _message(
                "done",
                "Нужен полный обязательный набор проверок: изменение затрагивает критическую "
                "инфраструктуру или слишком много файлов.",
                why_it_matters="Полный набор на слиянии и выпуске обязателен по построению — это не "
                               "деградация, а правильный объём для такого изменения.",
                technical=technical))
        return
    # affected / module — есть точечный выбор
    cmd = result.get("targeted_command")
    summary = (f"Для итерации достаточно {_TIER_HUMAN[tier]}: {len(affected)} тест-файл(ов). "
               "Полный набор остаётся обязателен на слиянии и выпуске.")
    _say(root, _message(
        "done", summary,
        why_it_matters="Это ускоряет локальную обратную связь, не ослабляя гейты: быстрый прогон для "
                       "итерации, полная регрессия — на слиянии.",
        next_steps=([f"Локально: {cmd}"] if cmd else None),
        technical=technical))


def run_verify_scope(child_root, stage: str | None = None, base: str | None = None,
                     as_json: bool = False) -> int:
    """Точка входа команды. -> 0 (всегда отвечает; это диагностика объёма, не гейт)."""
    root = Path(child_root).resolve()
    stage = stage if stage in _STAGES else None
    result = scope(root, base, stage)
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _present(root, result)
    return 0


def _intent_verify_scope(task, child_root, signals, a) -> int:
    """Обработчик интента `verify-scope` (регистрируется в ai_ops_cli).

    Позиционный `task` (если это известная стадия) -> lifecycle_intent; `--base` зеркалит охват
    impact_check_cli; `--json` даёт машинный объект решения."""
    return run_verify_scope(Path(child_root), stage=(task or None),
                            base=getattr(a, "base", None), as_json=bool(getattr(a, "json", False)))
