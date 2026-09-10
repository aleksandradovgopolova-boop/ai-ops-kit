"""Offline self-test установщика — команда `selftest`. Вынесено из `installer/ai_ops.py`.

Сценарий отката установки: ставит кит во временный репозиторий, ломает обновление и проверяет
ТРАНЗАКЦИОННЫЙ откат (версия конфига, целостность managed-слоя, runtime-ассеты). Зовётся только из
диспетчера `main`. Монолит `ai_ops.py` стоит на потолке module-size — держим его ниже, вынося
когезивные кластеры в сателлиты (тот же приём, что `doctor`/`aux_commands`/`update_ops`).

`installer/` — НЕ пакет; модуль грузится по sibling-пути. Общие с ядром функции и глобалы читаются
через `_ao()`. Загрузчик `ai_ops._selftest_ops()` кладёт сюда ЖИВЫЕ глобалы установщика (`_AO_NS`).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve()

# Живые глобалы установщика; проставляет `ai_ops._selftest_ops()`. None -> прямой вызов (fallback).
_AO_NS = None


class _AoView:
    """Атрибутный доступ к namespace-словарю установщика (`ai_ops.__dict__`).

    Поддерживает и ЗАПИСЬ: `selftest` временно подменяет глобалы установщика (REPO_ROOT/AI_DIR/…),
    чтобы прогнать сценарий во временном репозитории, и восстанавливает их; присваивание пишет прямо
    в живой namespace установщика, поэтому `cmd_init` и прочие видят подмену.
    """
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
    """Доступ к модулю установщика (его глобалы и мелкие хелперы). См. модульный docstring."""
    if _AO_NS is not None:
        return _AoView(_AO_NS)
    if str(_HERE.parent) not in sys.path:
        sys.path.insert(0, str(_HERE.parent))
    import ai_ops
    return ai_ops


def selftest():
    """Offline self-test инсталлера: диапазоны версий + e2e init во временный child,
    затем прогон child-валидатора на свежей установке (главный путь пользователя)."""
    import tempfile, io, contextlib
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # 1. семантика диапазонов
    expect("2.14.1 ∈ '>=2.0.0 <3.0.0'", _ao().version_in_range("2.14.1", ">=2.0.0 <3.0.0"))
    expect("2.14.1 ∉ '>=1.0.0 <2.0.0'", not _ao().version_in_range("2.14.1", ">=1.0.0 <2.0.0"))
    expect("пустой диапазон -> без ограничений", _ao().version_in_range("9.9.9", ""))
    expect("_ao().compatible_range_for(2.14.1)", _ao().compatible_range_for("2.14.1") == ">=2.0.0 <3.0.0")

    # 1b. per-package install (3.0-срез 2): фильтр по выбору пакетов, аддитивно
    own = _ao().package_ownership()
    expect("ownership читает декларации пакетов (registry -> core)",
           own.get("registry/agents.yaml") == "ai-ops-core")
    sample = [(None, "registry/agents.yaml"),      # core
              (None, "agents/core/context-builder.md"),  # product
              (None, "security/permission-levels.yaml")]  # не назначен ни пакету
    only_core = _ao().filter_by_packages(sample, ["ai-ops-core"], own)
    only_core_rels = {rel for _, rel in only_core}
    expect("выбор [core] оставляет core-файл", "registry/agents.yaml" in only_core_rels)
    expect("выбор [core] отсекает product-файл", "agents/core/context-builder.md" not in only_core_rels)
    expect("неназначенный файл ставится ВСЕГДА (честность до срез 3)",
           "security/permission-levels.yaml" in only_core_rels)
    expect("selected=None -> ставится всё (обратная совместимость)",
           len(_ao().filter_by_packages(sample, None, own)) == len(sample))

    # 2. e2e: init во временный child, затем child-валидатор
    with tempfile.TemporaryDirectory() as td:
        child = Path(td) / "child"
        # child обязан быть git-репозиторием (init это требует — движок работает через worktree)
        child.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "-C", str(child), "init", "-q"], capture_output=True)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = _ao().cmd_init(str(child))
        expect("init вернул 0", rc == 0)
        with contextlib.redirect_stdout(io.StringIO()):
            rc_nogit = _ao().cmd_init(str(Path(td) / "not-a-repo"))
        expect("init в несуществующий/не-git каталог -> rc=2 (fail-closed)", rc_nogit == 2)
        cfg = yaml.safe_load((child / ".ai-ops.yaml").read_text(encoding="utf-8"))
        prov = json.loads((child / ".ai" / "managed" / ".provenance.json").read_text(encoding="utf-8"))
        expect("config.installed_version == версия пакета",
               str((cfg.get("parent") or {}).get("installed_version")) == _ao().pkg_version())
        expect("provenance.installed_version == версия пакета",
               str(prov.get("installed_version")) == _ao().pkg_version())
        expect("allowed_version_range покрывает текущую версию",
               _ao().version_in_range(_ao().pkg_version(), (cfg.get("parent") or {}).get("allowed_version_range")))
        exp_src = _ao().parent_source()
        if exp_src:
            expect("parent.source заполнен реальным URL (без плейсхолдера и кредов)",
                   str((cfg.get("parent") or {}).get("source")) == exp_src
                   and "<" not in exp_src and "@" not in exp_src)
        expect("runtime-команда установлена в .claude/commands/",
               (child / ".claude" / "commands" / "ai-engineering.md").exists())
        expect("единая точка входа /ai-start-task установлена",
               (child / ".claude" / "commands" / "ai-start-task.md").exists())
        # полные контракты (тела агентов, правила, шаблоны) доезжают в child managed
        expect("тело агента установлено в .ai/managed/agents/",
               (child / ".ai" / "managed" / "agents" / "core" / "context-builder.md").exists())
        expect("правило установлено в .ai/managed/rules/",
               (child / ".ai" / "managed" / "rules" / "core" / "DefinitionOfDone.md").exists())
        expect("шаблон установлен в .ai/managed/templates/",
               any((child / ".ai" / "managed" / "templates").rglob("*.md")))
        # Codex: при заданном CODEX_HOME промпты реально ставятся в $CODEX_HOME/prompts
        import os as _os
        codex_home = child / ".codex-home"
        _old = _os.environ.get("CODEX_HOME")
        _os.environ["CODEX_HOME"] = str(codex_home)
        try:
            _mat = _ao().materialize_runtime(child)
            expect("Codex-промпты установлены в $CODEX_HOME/prompts при заданном CODEX_HOME",
                   _mat["codex_prompts"] > 0 and (codex_home / "prompts" / "ai-engineering.md").exists())
        finally:
            _os.environ.pop("CODEX_HOME", None) if _old is None else _os.environ.update(CODEX_HOME=_old)
        r = subprocess.run([sys.executable, str(_ao().CI / "validate_ai_ops_child.py")],
                           cwd=str(child), capture_output=True, text=True)
        expect("validate_ai_ops_child PASS на свежей установке", r.returncode == 0)
        if r.returncode != 0:
            print("  " + (r.stdout + r.stderr).strip()[-600:])

        # cross-OS (Windows-патч): ключи checksums — только POSIX '/', ни одного '\'
        cs_doc = json.loads((child / ".ai" / "managed" / ".checksums.json").read_text(encoding="utf-8"))
        cs_keys = list((cs_doc.get("files") or {}).keys())
        expect("checksums: ключи только с '/' (нет '\\', кросс-ОС)",
               cs_keys and not any("\\" in k for k in cs_keys))
        # cross-OS инвариант: checksums со '\'-ключами (как с Windows) не дают ложного дрейфа
        managed_child = child / ".ai" / "managed"
        win_style = {"schema_version": cs_doc.get("schema_version", 1),
                     "files": {k.replace("/", "\\"): v for k, v in cs_doc["files"].items()}}
        (managed_child / ".checksums.json").write_text(
            json.dumps(win_style, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        expect("cross-OS: Windows-стиль ключей ('\\') -> нет ложного дрейфа",
               _ao().detect_drift(managed_child) == [])

        # 2b. shipped skill с локальной правкой -> backup перед перезаписью (не теряем молча)
        skills_dir = child / ".claude" / "skills"
        some = sorted(p.name for p in skills_dir.iterdir() if p.is_dir()) if skills_dir.is_dir() else []
        if some:
            sid = some[0]
            edited = skills_dir / sid / "SKILL.md"
            if edited.exists():
                edited.write_text(edited.read_text(encoding="utf-8") + "\n<!-- local edit -->\n",
                                  encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()):
                    _ao().sync_skills(child)
                backup = child / ".ai" / "runtime" / "backups" / "skills" / sid
                expect("skill-drift: локальная правка сохранена в backup", backup.exists())
                expect("skill-drift: shipped-скилл перезаписан из пакета",
                       "<!-- local edit -->" not in edited.read_text(encoding="utf-8"))
                expect("skill-drift: backup содержит правку",
                       backup.exists() and "<!-- local edit -->" in (backup / "SKILL.md").read_text(encoding="utf-8"))

        # 3. rollback-safe update: провал smoke -> откат managed-слоя и версии.
        # Подмену глобалов установщика пишем через _ao() (живой namespace), поэтому объявление
        # `global` здесь не нужно — оно осталось бы от версии, где selftest жил в самом ai_ops.
        saved = (_ao().REPO_ROOT, _ao().CHILD_CONFIG, _ao().AI_DIR, _ao().MANAGED)
        _ao().REPO_ROOT = child
        _ao().CHILD_CONFIG = child / ".ai-ops.yaml"
        _ao().AI_DIR = child / ".ai"
        _ao().MANAGED = _ao().AI_DIR / "managed"
        try:
            # эмулируем более старую установку, чтобы тело update отработало (inst != target)
            import re as _re
            t = _ao().CHILD_CONFIG.read_text(encoding="utf-8")
            t = _re.sub(r"(installed_version:\s*)\S+", r"\g<1>2.0.0", t, count=1)
            _ao().CHILD_CONFIG.write_text(t, encoding="utf-8")
            before = _ao().sha256(_ao().MANAGED / ".checksums.json")
            # sentinel в runtime-ассете (.claude/commands) — update перезапишет, откат обязан вернуть
            cmd_file = child / ".claude" / "commands" / "ai-engineering.md"
            cmd_file.write_text("SENTINEL-PRE-UPDATE", encoding="utf-8")
            # `in_place=True` НАЗЫВАЕТ проверяемый путь (F-022): предмет здесь —
            # транзакционный откат применённого обновления, а не политика доставки.
            rc = _ao()._update_ops().cmd_update(force=False, smoke_checks=[["__does_not_exist__.py"]],
                            in_place=True)
            rep = json.loads((_ao().AI_DIR / "runtime" / "last-update-report.json").read_text(encoding="utf-8"))
            cfg_after = yaml.safe_load(_ao().CHILD_CONFIG.read_text(encoding="utf-8"))
            expect("provalen smoke -> rc=1", rc == 1)
            expect("статус rolled_back", rep["status"] == "rolled_back")
            expect("версия в конфиге откачена к 2.0.0",
                   str((cfg_after.get("parent") or {}).get("installed_version")) == "2.0.0")
            expect("managed-слой восстановлен (checksums без изменений)",
                   _ao().sha256(_ao().MANAGED / ".checksums.json") == before)
            expect("runtime-ассет (.claude/commands) откачен транзакционно",
                   cmd_file.read_text(encoding="utf-8") == "SENTINEL-PRE-UPDATE")
        finally:
            _ao().REPO_ROOT, _ao().CHILD_CONFIG, _ao().AI_DIR, _ao().MANAGED = saved

    print("ai_ops selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1
