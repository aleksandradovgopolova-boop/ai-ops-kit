"""Общая инфраструктура для разрезанных тестов инсталлятора (не собирается pytest).

Функции и фикстуры перенесены сюда ВЕРБАТИМ из монолита tests/unit/test_installer.py, чтобы
пять тематических файлов делили один источник фикстур. Файл с префиксом `_` — pytest его не
собирает и таксономия его не сканирует (проверяются только `test_*.py`).
"""

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
INSTALLER = KIT / "installer" / "ai_ops.py"


# ---------------------------------------------------------------- инфраструктура

def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=False)


def _make_child_repo(root: Path):
    """Чистый python-репозиторий с одним коммитом — типовой вход пользователя."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.1"\n',
                                         encoding="utf-8")
    _git(root, "init", "-q", ".")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")
    return root


def _run_cli(root: Path, *args, timeout=180, env=None):
    """Запустить инсталлятор ОТДЕЛЬНЫМ процессом из каталога root (как это делает пользователь).
    Отдельный процесс важен: только так видно трейсбек, который не поймал бы in-process вызов."""
    return subprocess.run([sys.executable, str(INSTALLER), *args],
                          cwd=str(root), capture_output=True, text=True, timeout=timeout,
                          env=env)


def _isolated_env(tmp: Path):
    """Окружение с ЧИСТЫМИ и СВОИМИ site-каталогами — предусловие тестов про `doctor`.

    С v3.33.3 `doctor` судит и о гигиене путей МАШИНЫ: остаточный `.pth`-пояс кита в site-packages
    (см. tests/unit/test_path_hygiene.py). Проверка блокирующая — пояс делает зелёными
    fail-closed-тесты. Значит без изоляции тест «doctor зелёный на свежей установке» мерил бы
    чистоту ноутбука: у любого, кто ставил кит до v3.33.1, пояс лежит в пользовательском site.
    Тест, который краснеет от постороннего файла в HOME, рано или поздно соврёт в обе стороны —
    класс, разобранный в 3.33.2 («тест, зелёный от версии git»).

    Изоляция — три шага, и третий обязателен:
      HOME              → tmp: обнуляет glob по ~/Library/Python и ~/.local;
      PYTHONUSERBASE    → tmp: уводит site.getusersitepackages() в свой каталог, куда тест вправе
                          подложить пояс;
      PYTHONPATH        → каталог со СИМЛИНКАМИ на зависимости, а НЕ сам site-packages. Наивная
                          изоляция уносит вместе с поясом и pyyaml (если тот стоит в
                          пользовательском site) — инсталлятор падает на `import yaml` до первой
                          проверки. Передать сам каталог site-packages тоже нельзя: он вернулся бы
                          в sys.path и попал под скан — тест снова зависел бы от чужого файла.
    """
    home, deps = tmp / "home", tmp / "deps"
    home.mkdir(parents=True, exist_ok=True)
    deps.mkdir(parents=True, exist_ok=True)
    src = Path(yaml.__file__).resolve().parent
    dst = deps / src.name
    if not dst.exists():
        try:
            os.symlink(src, dst, target_is_directory=True)
        except (OSError, NotImplementedError):     # Windows без прав на симлинки
            shutil.copytree(src, dst)
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PYTHONUSERBASE"] = str(home / "userbase")
    env["PYTHONPATH"] = str(deps)
    return env


# Ровно то, что писал `setup.py` кита до v3.33.1 (git show v3.33.1~1:setup.py).
_BELT_TEMPLATE = (
    "import os, sys; [sys.path.insert(0, p) for p in ['{root}'] + "
    "[os.path.join('{root}', d) for d in ('tools', 'validation')] "
    "if os.path.isdir(p) and p not in sys.path]\n"
)


def _write_belt(user_site: Path) -> Path:
    user_site.mkdir(parents=True, exist_ok=True)
    belt = user_site / "ai_ops_kit.pth"
    belt.write_text(_BELT_TEMPLATE.format(root=KIT), encoding="utf-8")
    return belt


def _user_site_of(env: dict) -> Path:
    """Каталог пользовательского site для заданного окружения — спрашиваем интерпретатор,
    а не собираем путь вручную (раскладка разная на macOS/Linux/Windows)."""
    r = subprocess.run([sys.executable, "-c", "import site; print(site.getusersitepackages())"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    return Path(r.stdout.strip())


def _tree_digest(root: Path):
    """{относительный путь: sha256} — снимок содержимого дерева для сравнения до/после."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and ".git/" not in p.relative_to(root).as_posix():
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


@pytest.fixture
def child(tmp_path):
    return _make_child_repo(tmp_path / "child")


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    """Одна свежая установка на модуль — для read-only проверок (init дорогой)."""
    root = _make_child_repo(tmp_path_factory.mktemp("installed") / "child")
    r = _run_cli(root, "init", ".")
    assert r.returncode == 0, f"init упал: {r.stdout}\n{r.stderr}"
    return root


def _path_python_with_pyyaml():
    """Есть ли в PATH интерпретатор, которым обёртка `./ai-ops` реально сможет работать.

    Обёртка выбирает интерпретатор по способности импортировать pyyaml — единственную рантайм-
    зависимость кита (см. `templates/runtime/ai-ops-entry.sh`). Если такого в PATH нет, кит на
    этой машине не запускается ВООБЩЕ, и тест обёртки проверять нечем: он мерил бы окружение,
    а не предмет. В CI интерпретатор с pyyaml есть всегда, там проверка исполняется.
    """
    import shutil
    import subprocess
    for cand in ("python3", "python3.13", "python3.12", "python3.11", "python3.10", "python3.9", "python"):
        exe = shutil.which(cand)
        if exe and subprocess.run([exe, "-c", "import yaml"], capture_output=True).returncode == 0:
            return exe
    return None


# ---------------------------------------------------------------- F-021: кит не сорит в истории дочки
#
# НАХОДКА ЖИВОГО ПРОГОНА (ии-среда, 2026-08-12). Кит не писал в дочку `.gitignore` вовсе, и это
# было ОБЪЯВЛЕННОЙ границей — она записана прямо в этом файле, в
# `test_entry_point_honours_explicit_interpreter`. В поле граница обошлась дорого: за один прогон в
# коммит владельца дважды пытались уехать `.ai/worktrees/` (как вложенный репозиторий),
# `.ai/runtime/active-work.yaml` и `.lock`, `.ai/usage/product-ledger.jsonl`,
# `.ai/reevaluate-evidence-*.json`. Владелец правил это руками — то есть становился техническим
# оператором кита, а это ровно та метрика, которую считает квалификация.
#
# Проверяем НЕ строками в файле, а вопросом К GIT (`git check-ignore`): правило, которое выглядит
# верным и не срабатывает, — это тот самый класс «объявлено, но не исполняется».

# Пути, которые в поле реально пытались уехать. Слева — путь, справа — почему он служебный.
LEAKY_PATHS = [
    (".ai/worktrees/wi-1/README.md", "вложенный репозиторий изолированного прогона"),
    (".ai/runtime/active-work.yaml", "координация параллельных сессий этой машины"),
    (".ai/runtime/ai-ops.lock", "лок"),
    (".ai/usage/product-ledger.jsonl", "локальный учёт стоимости"),
    (".ai/reevaluate-evidence-wi-1.json", "кеш переоценки гейтов"),
    (".ai/repository-profile.yaml", "машинный кеш детекции стека"),
    (".ai/managed/ai_ops_kit/__pycache__/x.cpython-314.pyc", "байткод в checksummed слое"),
    # ЗАМЕР F-022: без этих двух подготовленный update-PR содержал 612 файлов, из которых 609 —
    # копия managed-слоя из бэкапа. Дифф, который нельзя отсмотреть, — тот же ложный green.
    (".ai/runtime/backups/3.36.8/managed/agents/core/x.md", "транзакционный бэкап managed-слоя"),
    (".ai/runtime/last-update-report.json", "отчёт последнего обновления — состояние прогона"),
]

# Обратная сторона: это НЕ служебное состояние, а продукт — прятать его нельзя.
KEPT_PATHS = [
    (".ai/project/report-history/wi-1.jsonl", "историю эффекта коммитит workflow ai-ops-record"),
    (".ai/managed/agents/core/context-builder.md", "managed-слой — предмет доставки"),
    (".ai/project/ProductStatus.md", "факты о продукте, данные человеком"),
    (".ai/custom/overlay.md", "оверлей владельца"),
    ("features/wi-1/blueprint.yaml", "продуктовый артефакт задачи"),
]


def _check_ignored(root, rel):
    """Спросить у git, скрыт ли путь. -> bool. `check-ignore -q`: 0 — скрыт, 1 — нет."""
    return _git(root, "check-ignore", "-q", rel).returncode == 0


def _record_path(root):
    return root / ".github" / "workflows" / "ai-ops-record.yml"


@pytest.fixture
def installed_copy(installed, tmp_path):
    """Своя копия установленной дочки: тесты ниже УДАЛЯЮТ файлы и правят отпечатки.

    Фикстура `installed` модульная и общая — первый же такой тест ломал следующие, и это была моя
    ошибка того же класса, что тест, зависящий от индекса репозитория: результат зависел от порядка,
    а не от предмета.
    """
    import shutil as _sh
    dst = tmp_path / "installed-copy"
    _sh.copytree(installed, dst)
    return dst
