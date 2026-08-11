"""CI, который кит отдаёт ребёнку, обязан ИСПОЛНЯТЬСЯ — а не только устанавливаться.

ДЕФЕКТ, ПРОЖИВШИЙ ДВА РЕЛИЗА. В 3.34 каталог валидаторов переехал из корневого `validation/` в
`ai_ops_kit/validation/`. Шаблон `templates/ci/ai-ops-validate.yml` остался на старом пути, и каждый
child, установленный с 3.34, получал workflow, падающий на «No such file». Кит при этом был зелёным
на всех охватах: `clean-install` проверяет, что установка КЛАДЁТ файлы, и ни одна проверка не
ЗАПУСКАЛА то, что установка ребёнку отдала. Разрыв ровно на границе между китом и продуктом — там же,
где жили почти все находки живых обкаток.

Поэтому здесь два уровня, и второй обязателен:
  * СТАТИКА  — каждый путь внутрь клона кита, упомянутый в шаблонах, существует в этом репозитории;
  * ИСПОЛНЕНИЕ — команда валидатора из сгенерированного workflow реально запускается на свежем
    child и даёт 0.

Первый уровень поймал бы этот дефект, второй ловит ещё и «файл есть, а падает».
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[2]
INSTALLER = KIT / "installer" / "ai_ops.py"
TEMPLATES = KIT / "templates" / "ci"

# Путь внутрь клона кита: `$RUNNER_TEMP/ai-ops-kit/<что-то>` или `"$RUNNER_TEMP"/ai-ops-kit/<…>`.
KIT_PATH = re.compile(r'"?\$(?:RUNNER_TEMP|\{RUNNER_TEMP\})"?/ai-ops-kit/([\w./-]+)')


def _kit_paths(text: str):
    return sorted({m.group(1) for m in KIT_PATH.finditer(text)})


@pytest.mark.unit
def test_every_kit_path_in_templates_exists():
    """Статика: шаблон не вправе ссылаться на то, чего в ките нет.

    Проверяются ВСЕ шаблоны сразу — переезд каталога ломает их одинаково, а замечают по одному.
    """
    missing = []
    checked = 0
    for tpl in sorted(TEMPLATES.glob("*.yml")):
        for rel in _kit_paths(tpl.read_text(encoding="utf-8")):
            checked += 1
            if not (KIT / rel).exists():
                missing.append(f"{tpl.name}: {rel}")
    assert checked >= 3, f"пути внутрь кита перестали находиться разбором ({checked}) — правило ослепло"
    assert not missing, ("шаблон child-CI ссылается на несуществующее в ките: "
                         + "; ".join(missing))


@pytest.mark.unit
def test_no_template_clones_into_shared_tmp():
    """`/tmp` считает раннер одноразовым. На своём раннере каталог живёт между джобами, и клон
    падает на «destination path already exists» (находка PR #53)."""
    offenders = [t.name for t in sorted(TEMPLATES.glob("*.yml"))
                 if "/tmp/ai-ops-kit" in t.read_text(encoding="utf-8")]
    assert not offenders, f"клон в общий /tmp остался в шаблонах: {offenders}"


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture(scope="module")
def child(tmp_path_factory):
    """Свежий child: настоящий git-репозиторий + настоящий `init`, как у пользователя."""
    root = tmp_path_factory.mktemp("childci") / "child"
    root.mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.1"\n',
                                         encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    r = subprocess.run([sys.executable, str(INSTALLER), "init", "."], cwd=str(root),
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"init упал: {r.stdout}\n{r.stderr}"
    return root


@pytest.mark.unit
@pytest.mark.slow
def test_generated_validate_workflow_actually_runs(child):
    """ГЛАВНОЕ: берём команду из УСТАНОВЛЕННОГО workflow и исполняем её на этом же child.

    Не пересказываем шаблон своими словами — читаем то, что реально положено в репозиторий
    пользователя. Клон кита подменяем корнем этого репозитория: сеть в тестах не нужна, а проверяем
    мы путь и работоспособность валидатора, а не `git clone`.
    """
    wf = child / ".github" / "workflows" / "ai-ops-validate.yml"
    assert wf.is_file(), "установка не положила ребёнку workflow валидации"
    text = wf.read_text(encoding="utf-8")

    rels = [r for r in _kit_paths(text) if r.endswith(".py")]
    assert rels, "в установленном workflow не нашлось ни одной команды к валидатору кита"

    for rel in rels:
        script = KIT / rel
        assert script.is_file(), f"{rel}: workflow ребёнка зовёт то, чего в ките нет"
        r = subprocess.run([sys.executable, str(script)], cwd=str(child),
                           capture_output=True, text=True, timeout=180)
        assert r.returncode == 0, (
            f"валидатор из child-CI упал на свежей установке ({rel}):\n"
            f"{r.stdout[-1500:]}\n{r.stderr[-1500:]}")


@pytest.mark.unit
@pytest.mark.slow
def test_child_validator_is_fail_closed_on_a_broken_install(child, tmp_path):
    """Обратная сторона: на СЛОМАННОЙ установке тот же прогон обязан краснеть.

    Иначе предыдущий тест доказывал бы только то, что команда завершается, — а «завершается» и
    «проверяет» это разные вещи (ровно так `doctor: OK` жил рядом со строками с крестиком).
    """
    import shutil
    broken = tmp_path / "broken"
    shutil.copytree(child, broken)
    cfg = broken / ".ai-ops.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace(
        "installed_version:", "installed_version: 0.0.1  # подменено тестом\nold_installed:"),
        encoding="utf-8")

    script = KIT / "ai_ops_kit" / "validation" / "validate_ai_ops_child.py"
    r = subprocess.run([sys.executable, str(script)], cwd=str(broken),
                       capture_output=True, text=True, timeout=180)
    assert r.returncode != 0, "рассогласование версий прошло как чистая установка"
