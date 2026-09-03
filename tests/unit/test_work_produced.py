"""Факт работы считается по git, а не по счётчику брокера.

НАХОДКА ИИ-СРЕДЫ, МЕШАВШАЯ КАЖДЫЙ ДЕНЬ. Движок брал «есть ли правки» из `loop.applied_writes` —
счётчика write-операций, прошедших через брокера. Но писать можно иначе: writer уровня `claude -p`
правит файлы своими инструментами, `sed -i` правит через shell, а модель может закоммитить сама.
Тогда счётчик ноль при живом коммите, и работа получала статус «blocked: код не написан — правок 0».
Дважды за один день. По отчёту выглядело, будто кит не работает, хотя он работал — и это путало не
только владельца, но и любого, кто читал бы такой отчёт.

Три обязательных теста на capability:
  * positive     — коммит с файлами считается работой, каким бы каналом она ни была произведена;
                   свой коммит модели (чистое дерево, HEAD ушёл от базы) виден движку;
  * fail-closed  — пустой прогон остаётся пустым: предикат не начинает возвращать True всегда;
  * side-effect  — статус активной работы и человеческий вывод следуют ТОМУ ЖЕ предикату, а не
                   каждый своему (иначе отчёт и реестр снова разойдутся).
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]

from ai_ops_kit.engine.pipeline_helpers import work_produced  # noqa: E402
from ai_ops_kit.engine.pipeline_git import _head_advanced     # noqa: E402


# ── positive ──────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rep,why", [
    ({"loop": {"applied_writes": 2}}, "правки через брокера"),
    ({"loop": {"applied_writes": 0},
      "commit": {"sha": "a" * 40, "changed_files": ["src/a.py"]}}, "writer своими инструментами"),
    ({"commit": {"sha": "b" * 40, "changed_files": ["x.ts", "y.ts"],
                 "produced_by": "model-commit"}}, "модель закоммитила сама"),
])
def test_any_channel_counts_as_work(rep, why):
    assert work_produced(rep) is True, f"работа не засчитана: {why}"


def test_model_own_commit_is_visible_to_the_engine(tmp_path):
    """Дерево ЧИСТОЕ, `applied` пусто — и всё же работа есть: HEAD ушёл от базы прогона.

    Именно так выглядит прогон, в котором модель сама позвала `git commit`.
    """
    root = tmp_path / "repo"
    root.mkdir()
    def git(*a):
        subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    git("config", "user.email", "t@t"); git("config", "user.name", "t")
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-qm", "base")
    base = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()

    # До правок HEAD на базе — движок не должен считать это работой.
    moved, _ = _head_advanced(root, base)
    assert moved is False

    # Модель правит и коммитит САМА.
    (root / "a.py").write_text("x = 2\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-qm", "модель сделала сама")

    moved, head = _head_advanced(root, base)
    assert moved is True, "свой коммит модели не виден: дерево чистое, и движок решит, что правок нет"
    assert head and head != base


# ── fail-closed ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rep", [
    {}, {"loop": {"applied_writes": 0}},
    {"commit": {"sha": None, "changed_files": []}},
    # Коммит есть, а файлов в нём нет — работы не произведено, и выдавать это за работу нельзя.
    {"loop": {"applied_writes": 0}, "commit": {"sha": "c" * 40, "changed_files": []}},
])
def test_empty_run_stays_empty(rep):
    assert work_produced(rep) is False, "предикат стал возвращать True на пустом прогоне"


def test_head_advanced_is_silent_without_a_base(tmp_path):
    """Без базы сравнивать не с чем — это «не знаю», а не «работа есть»."""
    moved, head = _head_advanced(tmp_path, None)
    assert moved is False and head is None


# ── side-effect proof ─────────────────────────────────────────────────────────────────────────

def test_status_and_human_output_use_the_same_predicate():
    """Реестр активной работы и человеческий вывод обязаны судить по ОДНОМУ правилу.

    Пока каждый считал по-своему, отчёт говорил «правок 0», статус — «код не написан», а в коммите
    лежали файлы. Проверяем разбором: `applied_writes` больше не является судьёй.
    """
    # Человекочитаемый вывод вынесен из ai_ops_run в ai_ops_run_print, а решение о статусе работы
    # (_finalize_run) — в ai_ops_run_lifecycle (v3.x, разрежение god-модуля): предикат зовут оба
    # (статус — жизненный цикл, печать — модуль вывода), и судить они обязаны по одному правилу.
    src = (KIT / "ai_ops_kit" / "engine" / "ai_ops_run.py").read_text(encoding="utf-8")
    src_print = (KIT / "ai_ops_kit" / "engine" / "ai_ops_run_print.py").read_text(encoding="utf-8")
    src_life = (KIT / "ai_ops_kit" / "engine" / "ai_ops_run_lifecycle.py").read_text(encoding="utf-8")
    calls = [n for mod in (src, src_print, src_life) for n in ast.walk(ast.parse(mod))
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "work_produced"]
    assert len(calls) >= 2, ("общий предикат зовётся реже двух раз — значит кто-то снова судит "
                             "по счётчику брокера")
    # И самого счётчика в роли судьи больше нет — ни в контроллере, ни в вынесенном жизненном цикле.
    _counter = '_wrote = ((rep.get("loop") or {}).get("applied_writes") or 0) > 0'
    assert _counter not in src and _counter not in src_life


def test_pipeline_reports_how_the_work_was_produced():
    """Канал работы назван в отчёте: «правок 0» рядом с живым коммитом читается как «кит не работает»."""
    src = (KIT / "ai_ops_kit" / "engine" / "execution_pipeline.py").read_text(encoding="utf-8")
    # deep-cut: фаза commit (_commit_work) вынесена в pipeline_setup — именование канала работы теперь
    # там, а секция отчёта и распознавание сдвига HEAD остаются в execution_pipeline.
    setup_src = (KIT / "ai_ops_kit" / "engine" / "pipeline_setup.py").read_text(encoding="utf-8")
    assert '"produced_by": work_produced_by' in src, "происхождение работы не попадает в отчёт"
    assert 'work_produced_by = "model-commit"' in setup_src, "свой коммит модели не называется в отчёте"
    tree = ast.parse(src)
    called = {getattr(n.func, "id", "") for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "_head_advanced" in called, "конвейер не проверяет, ушёл ли HEAD от базы"


# ── сквозное воспроизведение сценария ии-среды ────────────────────────────────────────────────

def _repo_with_history(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    (root / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for cfg in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(root), "config", *cfg], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"], check=True)
    return root


@pytest.mark.slow
def test_model_that_commits_itself_is_not_reported_as_empty(tmp_path):
    """СКВОЗНОЕ ВОСПРОИЗВЕДЕНИЕ ОБОИХ ПРОГОНОВ ИИ-СРЕДЫ.

    Модель правит файл через shell (`sed`) и **сама делает коммит** — ровно как writer уровня
    `claude -p`. После этого дерево чистое, `applied_writes` ноль, и до 3.36.4 отчёт говорил
    `commit.sha: null`, а работа получала «код не написан — правок 0» при живом коммите.

    Проверяем не рассуждение, а факт: отчёт настоящего прогона.
    """
    from ai_ops_kit.engine import execution_pipeline

    root = _repo_with_history(tmp_path / "prod")
    state = {"sent": False}

    def writer(ctx):
        """Живой writer: правит через shell и КОММИТИТ САМ, потом сообщает, что закончил."""
        if state["sent"]:
            return {"done": True, "summary": "правка внесена и закоммичена"}
        state["sent"] = True
        return {"op": "shell",
                "command": "echo '# правка модели' >> calc.py && git add -A "
                           "&& git commit -qm 'модель сделала сама'"}

    # commit=True + isolate=True — так конвейер зовёт продуктовый путь (`ai-ops run --execute`).
    # С умолчаниями `commit=False` тест проверял бы стенд, а не продукт.
    rep = execution_pipeline.run_pipeline(
        task="починить сложение", signals={"task_type": "QUICK", "size": "small", "risk": "low"},
        child_root=root, proposer=writer, commit=True, isolate=True)

    commit = rep.get("commit") or {}
    assert (rep.get("loop") or {}).get("applied_writes") == 0, \
        "предпосылка теста: через брокера правок не было"
    assert commit.get("sha"), "коммит модели не попал в отчёт — движок снова его не видит"
    assert commit.get("produced_by") == "model-commit", commit.get("produced_by")
    assert commit.get("changed_files"), "файлы коммита модели не названы"
    assert work_produced(rep) is True, "работа есть, а предикат говорит «ничего не написано»"


@pytest.mark.slow
def test_run_that_produced_nothing_still_says_so(tmp_path):
    """Обратная сторона: прогон без правок обязан остаться пустым.

    Иначе лечение хуже болезни — «работа есть» на пустом месте так же обесценивает отчёт.
    """
    from ai_ops_kit.engine import execution_pipeline

    root = _repo_with_history(tmp_path / "prod2")
    rep = execution_pipeline.run_pipeline(
        task="ничего не делать", signals={"task_type": "QUICK", "size": "small", "risk": "low"},
        child_root=root, proposer=lambda ctx: {"done": True, "summary": "нечего делать"},
        commit=True, isolate=True)

    assert not (rep.get("commit") or {}).get("sha"), "коммит появился там, где работы не было"
    assert work_produced(rep) is False


@pytest.mark.slow
def test_branch_already_ahead_of_base_is_not_mistaken_for_work(tmp_path):
    """ТОЧКА ОТСЧЁТА — HEAD НА СТАРТЕ, А НЕ БАЗА ВЕТКИ.

    Если сравнивать с `base_sha`, то на ветке, уже ушедшей вперёд базы (или при resume), HEAD
    отличается от базы ДО начала работы — и кит увидел бы работу там, где её не делали. Это ложь в
    обратную сторону, и она опаснее: «сделано» на пустом прогоне читается как успех.
    """
    from ai_ops_kit.engine import execution_pipeline

    root = _repo_with_history(tmp_path / "prod3")
    # Ветка уходит вперёд базы ДО прогона.
    subprocess.run(["git", "-C", str(root), "checkout", "-q", "-b", "feature"], check=True)
    (root / "calc.py").write_text("def add(a, b):\n    return a + b  # раньше\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "commit", "-qam", "работа до прогона"], check=True)

    rep = execution_pipeline.run_pipeline(
        task="ничего не делать", signals={"task_type": "QUICK", "size": "small", "risk": "low"},
        child_root=root, proposer=lambda ctx: {"done": True, "summary": "нечего делать"},
        commit=True, isolate=False)

    assert work_produced(rep) is False, \
        "прошлые коммиты ветки засчитаны как работа этого прогона"


@pytest.mark.slow
def test_resume_over_existing_branch_reports_only_new_work(tmp_path):
    """ПРОДОЛЖЕНИЕ ПОВЕРХ УЖЕ СДЕЛАННОГО: ветка ушла вперёд базы ДО прогона.

    Сравнение с `base_sha` здесь даёт ложное «работа произведена»: коммиты на ветке есть, но их
    сделал ПРОШЛЫЙ прогон. Точка отсчёта — HEAD на старте этого прогона, а не база ветки. Ложь в
    эту сторону опаснее исходной: «сделано» на пустом прогоне читается как успех.
    """
    from ai_ops_kit.engine import execution_pipeline

    root = _repo_with_history(tmp_path / "prod4")
    st = {"sent": False}

    def writer(ctx):
        if st["sent"]:
            return {"done": True, "summary": "готово"}
        st["sent"] = True
        return {"op": "shell",
                "command": "echo '# первый прогон' >> calc.py && git add -A "
                           "&& git commit -qm 'первый прогон'"}

    first = execution_pipeline.run_pipeline(
        task="первая правка", signals={"task_type": "QUICK", "size": "small", "risk": "low"},
        child_root=root, proposer=writer, commit=True, isolate=True, feature="wi-resume")
    assert work_produced(first) is True, "предпосылка: первый прогон должен произвести работу"

    # Второй прогон ПРОДОЛЖАЕТ ту же работу и не делает ничего нового.
    second = execution_pipeline.run_pipeline(
        task="первая правка", signals={"task_type": "QUICK", "size": "small", "risk": "low"},
        child_root=root, proposer=lambda ctx: {"done": True, "summary": "нечего добавить"},
        commit=True, isolate=True, feature="wi-resume", resume=True)

    assert work_produced(second) is False, (
        "коммиты ПРОШЛОГО прогона засчитаны как работа этого — «сделано» на пустом прогоне")
