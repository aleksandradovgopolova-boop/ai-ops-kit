"""Отсутствие базы сравнения: подбирается или называется причиной — но не падает и не берёт весь репозиторий.

ПОЛЕ 17-18.08.2026, дочка ИИ-Среда, заявки #136 и #139 — ОДНА ПРИЧИНА, ДВА ЗАЯВЛЕННЫХ ДЕФЕКТА.
Замерено на 3.36.12 (версия важна: заявки писались по 3.36.8, проверялось «живо ли ещё»):
  * `review` без `--base` РОНЯЛ `TypeError: expected str … not NoneType` — `--base` в CLI имеет
    default `None`, и он перекрывал дефолт функции, уходя аргументом в `git rev-parse --verify`.
    При этом справка CLI ОБЕЩАЛА автоподбор («auto: upstream/remote-default/текущая»), которого на
    этом пути не существовало;
  * `security_pack.run_pack` при `base=None` брал НЕ ДИФ, А ВЕСЬ РЕПОЗИТОРИЙ (`git ls-files`).
    Замер с контролем на пробном репозитории: правка одного безобидного файла -> без базы
    `overall=blocked` (находка в ДАВНЕМ файле, которого правка не касалась), с базой -> `clear`.
    Вот почему заявка читалась как «блокирует без находок»: находки были настоящие, но чужие —
    врал не вердикт, а ОХВАТ.

КАЖДЫЙ ПУТЬ ПРОВЕРЯЕТСЯ ПАРОЙ (без базы И с базой): «работает без базы» в одиночку ничего не значит,
потому что тихо пустой охват выглядит так же зелено, как проверенный.

ЛОВУШКА, НА КОТОРОЙ ОШИБЛАСЬ ПЕРВАЯ ПРОБА (записана в плане): у `review` при отсутствии ветки
`ai-ops/<wid>` выход происходит РАНЬШЕ разбора базы — проба обязана СОЗДАВАТЬ ветку, иначе она
измеряет `no-branch`, а не базу. Здесь ветка создаётся и несёт свой коммит, поэтому диф непустой:
пустой список файлов не смог бы отличить «посчитано» от «не посчитано».

ДЕФОЛТНАЯ ВЕТКА ПРОБ — `master`, НАМЕРЕННО: тихая подстановка `main` (прежний дефолт функции) на
таком репозитории обязана быть видна, а не совпасть с правильным ответом.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ai_ops_kit.delivery import review_branch
from ai_ops_kit.security import security_pack

WID = "probe-wid"
BRANCH = f"ai-ops/{WID}"
INJECTION = "el.innerHTML = userInput\n"


def _git(root, *a):
    return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True)


def _repo(tmp_path: Path, branch_commit: bool = True) -> Path:
    """Пробный репозиторий: корневой коммит с ЧУЖИМ legacy (injection), затем безобидная правка,
    затем ветка работы со своим файлом. Ровно форма замера поля."""
    root = tmp_path / "child"
    root.mkdir()
    subprocess.run(["git", "-c", "init.defaultBranch=master", "init", "-q", str(root)], check=True)
    _git(root, "config", "user.email", "probe@example.com")
    _git(root, "config", "user.name", "Probe")
    (root / "src").mkdir()
    (root / "src" / "legacy.tsx").write_text(INJECTION, encoding="utf-8")
    (root / "src" / "ok.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", "-A"); _git(root, "commit", "-qm", "initial: чужой legacy с injection")
    (root / "src" / "ok.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    _git(root, "add", "-A"); _git(root, "commit", "-qm", "безобидная правка одного файла")
    if branch_commit:
        _git(root, "checkout", "-q", "-b", BRANCH)
        (root / "src" / "feature.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        _git(root, "add", "-A"); _git(root, "commit", "-qm", "работа: свой файл")
        _git(root, "checkout", "-q", "master")
    return root


def _root_sha(root: Path) -> str:
    return _git(root, "rev-list", "--max-parents=0", "HEAD").stdout.strip().splitlines()[0]


# ─────────────────────────── review: подбирается ───────────────────────────

def test_review_without_base_auto_resolves_as_the_help_promises(tmp_path):
    """Без базы: не падает, база подобрана, источник назван, диф ПОСЧИТАН (непустой)."""
    root = _repo(tmp_path)
    rep = review_branch.review(root, WID, reviewer_proposer=None, base=None, persist=False)
    assert rep["verdict"] != "error", rep.get("note")
    assert rep["base"] == "master", f"ожидалась подобранная база master, получено {rep['base']!r}"
    assert rep["base_source"] == "current-branch"
    assert rep.get("base_note") is None
    assert rep["changed_files"] == ["src/feature.py"], rep["changed_files"]


def test_review_pair_explicit_base_gives_the_same_diff(tmp_path):
    """ВТОРАЯ ПОЛОВИНА ПАРЫ: с базой ответ тот же — значит автоподбор не «работает» вместо дифа."""
    root = _repo(tmp_path)
    auto = review_branch.review(root, WID, reviewer_proposer=None, base=None, persist=False)
    explicit = review_branch.review(root, WID, reviewer_proposer=None, base="master", persist=False)
    assert explicit["base_source"] == "explicit"
    assert explicit["changed_files"] == auto["changed_files"] == ["src/feature.py"]
    assert explicit["verdict"] == auto["verdict"]


def test_review_unknown_base_is_refused_by_name_not_by_crash(tmp_path):
    """Выдуманная база: причина названа, диф пуст, исключения нет (прежде — TypeError со стеком)."""
    root = _repo(tmp_path)
    rep = review_branch.review(root, WID, reviewer_proposer=None, base="нет-такой-ветки", persist=False)
    assert rep["verdict"] != "error"
    assert rep["changed_files"] == []
    assert "нет-такой-ветки" in (rep.get("base_note") or ""), rep.get("base_note")


def test_review_never_silently_substitutes_main(tmp_path):
    """Хардкод 'main' запрещён: на репозитории с master он дал бы «изменений нет» вместо ответа."""
    root = _repo(tmp_path)
    import inspect
    assert inspect.signature(review_branch.review).parameters["base"].default is None
    rep = review_branch.review(root, WID, reviewer_proposer=None, persist=False)
    assert rep["base"] == "master"
    assert 'base="main"' not in Path(review_branch.__file__).read_text(encoding="utf-8")


def test_auto_base_equal_to_reviewed_branch_is_named_not_empty(tmp_path):
    """Человек стоит НА ревьюируемой ветке: диф против себя пуст, и это ОТКАЗ, а не «изменений нет»."""
    root = _repo(tmp_path)
    _git(root, "checkout", "-q", BRANCH)
    based = review_branch._base_for_review(root, None, BRANCH)
    assert based["resolved"] is False
    assert BRANCH in (based.get("reason") or ""), based


def test_probe_must_create_the_branch_otherwise_it_measures_no_branch(tmp_path):
    """ЛОВУШКА ИЗ ПЛАНА, зафиксированная тестом: без ветки выход РАНЬШЕ разбора базы."""
    root = _repo(tmp_path, branch_commit=False)
    rep = review_branch.review(root, "нет-такой-работы", reviewer_proposer=None, base=None, persist=False)
    assert rep["verdict"] == "no-branch"
    assert "base" not in rep or rep.get("base") is None


def test_review_artifact_carries_the_base(tmp_path):
    """Артефакт вердикта несёт базу: список изменённых файлов без неё непроверяем."""
    import yaml
    root = _repo(tmp_path)
    rep = review_branch.review(root, WID, reviewer_proposer=None, base=None, persist=True)
    rec = yaml.safe_load((root / "features" / WID / "branch-review.yaml").read_text(encoding="utf-8"))
    assert rec["base"] == "master" and rec["base_source"] == "current-branch"
    assert rec["changed_files"] == ["src/feature.py"] == rep["changed_files"]


def test_review_seam_through_the_cli(tmp_path):
    """ШОВ: путь человека — `ai-ops review`. Если CLI не проводит подобранную базу до механизма,
    механизм есть, а на пути человека он мёртв (и тихая 'main' на master-репозитории это скрыла бы)."""
    root = _repo(tmp_path)
    from ai_ops_kit.cli import ai_ops_cli
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ai_ops_cli.main(["review", str(root), "--feature", WID, "--json"])
    out = buf.getvalue()
    rep = json.loads(out[out.index("{"):])
    assert rep["base"] == "master", f"CLI не провёл подобранную базу: {rep.get('base')!r}"
    assert rep["base_source"] == "current-branch"
    assert rep["changed_files"] == ["src/feature.py"]


# ─────────────────────────── security: отказывается ───────────────────────────

def test_security_pack_without_base_refuses_naming_the_reason(tmp_path):
    """Без базы — ОТКАЗ с причиной. Прежде здесь был `blocked` по чужому legacy (заявка #139)."""
    root = _repo(tmp_path, branch_commit=False)
    with pytest.raises(RuntimeError) as ei:
        security_pack.run_pack(root, base=None, signals={})
    msg = str(ei.value)
    assert "без базы сравнения" in msg, msg
    assert "fail-closed" in msg, msg


def test_security_pack_pair_with_base_is_clear_and_names_its_scope(tmp_path):
    """ВТОРАЯ ПОЛОВИНА ПАРЫ и весь смысл заявки #139: находка НАСТОЯЩАЯ, но не в охвате правки."""
    root = _repo(tmp_path, branch_commit=False)
    res = security_pack.run_pack(root, base="HEAD~1", signals={})
    assert res["overall"] == "clear", res["blocking"]
    assert res["scan_scope"] == {"mode": "diff", "base": "HEAD~1"}
    # контроль: тот же файл, поданный как изменённый, находку даёт — значит охват, а не слепота
    same_file = security_pack.run_pack(files_content={"src/legacy.tsx": INJECTION}, signals={})
    assert same_file["overall"] == "blocked"
    assert any(f.get("path") == "src/legacy.tsx" for r in same_file["results"] for f in r["findings"])


def test_security_pack_unresolvable_base_refuses_instead_of_whole_repo(tmp_path):
    """Явная база, которой нет: отказ с её именем — не молчаливый скан всего репозитория."""
    root = _repo(tmp_path, branch_commit=False)
    with pytest.raises(RuntimeError) as ei:
        security_pack.run_pack(root, base="нет-такой-базы", signals={})
    assert "нет-такой-базы" in str(ei.value) and "fail-closed" in str(ei.value)


def test_security_pack_initial_commit_scope_is_that_commit_not_the_repo(tmp_path):
    """ЕДИНСТВЕННЫЙ законный случай неразрешимой базы — `<корень>~1`: охват = файлы того коммита.
    Файл, добавленный ПОЗЖЕ, в охват не входит, иначе это снова аудит чужого кода."""
    root = _repo(tmp_path, branch_commit=False)
    (root / "src" / "later.tsx").write_text(INJECTION, encoding="utf-8")
    _git(root, "add", "-A"); _git(root, "commit", "-qm", "позже: ещё один injection")
    res = security_pack.run_pack(root, base=f"{_root_sha(root)}~1", signals={})
    assert res["scan_scope"]["mode"] == "initial-commit"
    paths = {f.get("path") for r in res["results"] for f in r["findings"]}
    assert "src/legacy.tsx" in paths, paths
    assert "src/later.tsx" not in paths, f"в охват первого коммита попал позднейший файл: {paths}"


def test_security_pack_cli_refusal_says_the_truth(tmp_path):
    """Отказ человеку — названная причина и код 2, а не стек трассировки."""
    root = _repo(tmp_path, branch_commit=False)
    proc = subprocess.run([sys.executable, "-m", "ai_ops_kit.security.security_pack", str(root)],
                          capture_output=True, text=True, cwd=str(Path(security_pack.__file__).parents[2]))
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)
    assert "Traceback" not in proc.stderr
    assert "без базы сравнения" in proc.stderr, proc.stderr
