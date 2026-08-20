#!/usr/bin/env python3
"""Тесты инсталлятора `installer/ai_ops.py` — единственной точки входа пользователя кита.

Почему отдельный файл: инсталлятор до v3.28 покрывался только собственным `--selftest`
(самоаттестация). Здесь — ВНЕШНИЕ тесты на реальных временных git-репозиториях, без сети.

Три обязательных теста на capability (AGENTS.md → инженерный цикл):
  * positive        — установка действительно создаёт рабочую managed-зону;
  * fail-closed     — сбой (не-git каталог, битый конфиг, повторная установка) НЕ выдаётся
                      за успех: rc≠0 и внятное сообщение вместо трейсбека;
  * side-effect proof — сначала доказываем, что файлы РЕАЛЬНО записаны на диск и их
                      содержимое осмысленно (sha256 сходится с .checksums.json), и только
                      потом смотрим на код возврата и печать.
"""

import ast
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
INSTALLER = KIT / "installer" / "ai_ops.py"

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------- инфраструктура

def _load_installer():
    """Импортировать installer/ai_ops.py как модуль (он не пакет — грузим по пути)."""
    spec = importlib.util.spec_from_file_location("installer_ai_ops_under_test", INSTALLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ai_ops():
    return _load_installer()


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


# ---------------------------------------------------------------- 1. чистый репозиторий

def test_init_clean_repo_writes_real_files(child):
    """positive + side-effect proof: init на чистом репозитории реально пишет managed-зону.

    Порядок важен: СНАЧАЛА доказываем факт записи на диск и осмысленность содержимого,
    и только потом смотрим на rc и вывод."""
    r = _run_cli(child, "init", ".")

    # --- side-effect proof: файлы на диске, содержимое осмысленное ---
    managed = child / ".ai" / "managed"
    engine = managed / "tools" / "ai_ops_run.py"
    assert engine.is_file(), "движок .ai/managed/tools/ai_ops_run.py не записан на диск"
    engine_src = engine.read_text(encoding="utf-8")
    # v3.30: код движка переехал в ai_ops_kit/engine/, плоский путь остался входной точкой
    # (её знают документация и doctor). Проверяем обе стороны: алиас записан И код доехал.
    if "sys.modules[__name__]" in engine_src:
        real = managed / "ai_ops_kit" / "engine" / "ai_ops_run.py"
        assert real.is_file(), "алиас записан, а кода движка в поставке нет"
        engine_src = real.read_text(encoding="utf-8")
    assert "def main(" in engine_src and len(engine_src) > 1000, \
        "движок записан, но содержимое не похоже на исполняемый модуль"

    checksums = json.loads((managed / ".checksums.json").read_text(encoding="utf-8"))
    files = checksums["files"]
    assert len(files) > 100, f"под контролем подозрительно мало файлов: {len(files)}"
    # каждая запись контрольной суммы соответствует РЕАЛЬНОМУ файлу с тем же содержимым
    for rel, digest in files.items():
        p = managed / rel
        assert p.is_file(), f"в .checksums.json есть {rel}, но файла на диске нет"
    sample = sorted(files)[: min(25, len(files))]
    for rel in sample:
        actual = hashlib.sha256((managed / rel).read_bytes()).hexdigest()
        assert actual == files[rel], f"содержимое {rel} не совпадает с записанной sha256"

    cfg = yaml.safe_load((child / ".ai-ops.yaml").read_text(encoding="utf-8"))
    assert str((cfg.get("parent") or {}).get("installed_version")) == \
        (KIT / "VERSION").read_text(encoding="utf-8").strip()

    prov = json.loads((managed / ".provenance.json").read_text(encoding="utf-8"))
    assert prov["managed_root"] == ".ai/managed"

    for zone in ("managed", "project", "custom", "generated", "runtime"):
        assert (child / ".ai" / zone).is_dir(), f"зона .ai/{zone} не создана"

    cmds = list((child / ".claude" / "commands").glob("*.md"))
    assert cmds, ".claude/commands/ пуст — среда не увидит маршруты кита"

    # --- и только теперь реакция ---
    assert r.returncode == 0, f"init вернул {r.returncode}: {r.stdout}\n{r.stderr}"
    assert "Traceback" not in (r.stdout + r.stderr)


# ---------------------------------------------------------------- 2. повторный init

def test_second_init_is_blocked_and_changes_nothing(child):
    """Идемпотентность: второй init не ломает установку и не дублирует содержимое.

    Фактическое поведение — честный БЛОК (rc≠0 + подсказка про update), а не молчаливая
    перезапись. Фиксируем и блок, и неизменность дерева."""
    assert _run_cli(child, "init", ".").returncode == 0
    before = _tree_digest(child)

    r = _run_cli(child, "init", ".")

    after = _tree_digest(child)
    assert after == before, "повторный init изменил содержимое установки"
    assert r.returncode != 0, "повторный init выдал успех — это молчаливая переустановка"
    assert "update" in (r.stdout + r.stderr), "нет подсказки, что делать вместо повторного init"
    assert "Traceback" not in (r.stdout + r.stderr)


# ---------------------------------------------------------------- 3. правка в managed-зоне

def test_init_over_edited_managed_does_not_silently_overwrite(child):
    """fail-closed: пользователь правил файл в .ai/managed/ — повторный init НЕ затирает правку.

    Это самая опасная точка: молчаливая перезапись означала бы потерю работы пользователя."""
    assert _run_cli(child, "init", ".").returncode == 0
    edited = child / ".ai" / "managed" / "quality" / "gates.yaml"
    marker = "\n# LOCAL-EDIT-DO-NOT-LOSE\n"
    edited.write_text(edited.read_text(encoding="utf-8") + marker, encoding="utf-8")

    r = _run_cli(child, "init", ".")

    # side-effect proof: правка ФИЗИЧЕСКИ на месте после повторного init
    assert marker in edited.read_text(encoding="utf-8"), \
        "init молча затёр пользовательскую правку в managed-зоне"
    assert r.returncode != 0, "init поверх изменённой managed-зоны отчитался успехом"
    assert "Traceback" not in (r.stdout + r.stderr)

    # а `status` честно показывает дрейф (правка не выдаётся за целостную установку)
    st = _run_cli(child, "status")
    assert st.returncode != 0
    assert "ДРИФТ" in st.stdout


# ---------------------------------------------------------------- 4. не-git каталог

def test_init_in_non_git_dir_reports_clear_error(tmp_path):
    """fail-closed: каталог без git — внятная ошибка, а не трейсбек и не «успешная» установка.

    Без git движок кита нерабочий (worktree/коммит/evidence), поэтому установка туда —
    заведомо ложный зелёный."""
    plain = tmp_path / "plain"
    plain.mkdir()

    r = _run_cli(plain, "init", ".")

    out = r.stdout + r.stderr
    assert "Traceback" not in out, f"инсталлятор упал трейсбеком:\n{out}"
    assert r.returncode != 0, "установка в не-git каталог отчиталась успехом"
    assert "git" in out.lower(), "в сообщении нет причины отказа (git)"
    # side-effect proof: ничего не установлено — полу-состояния не осталось
    assert not (plain / ".ai" / "managed").exists()
    assert not (plain / ".ai-ops.yaml").exists()


# ---------------------------------------------------------------- 5. битый .ai-ops.yaml

@pytest.mark.parametrize("command", ["doctor", "status"])
def test_broken_child_config_reports_clear_error(child, command):
    """fail-closed: невалидный YAML в .ai-ops.yaml — понятное сообщение, а не yaml-трейсбек."""
    assert _run_cli(child, "init", ".").returncode == 0
    (child / ".ai-ops.yaml").write_text("parent:\n  installed_version: [unclosed\n",
                                        encoding="utf-8")

    r = _run_cli(child, command)

    out = r.stdout + r.stderr
    assert "Traceback" not in out, f"{command} упал трейсбеком:\n{out}"
    assert r.returncode != 0, f"{command} на битом конфиге вернул успех"
    assert ".ai-ops.yaml" in out, "в сообщении не назван виноватый файл"


# ---------------------------------------------------------------- 6. doctor на свежей установке

def test_doctor_ok_on_fresh_install(installed_copy, tmp_path):
    """positive: сразу после init диагностика без трейсбеков и без блокеров (rc=0), а единственное
    замечание — то, о чём установка САМА просит человека: заполнить имя проекта.

    ИЗМЕНЕНО 19.08.2026 (B2-25, `doctor-requires-a-real-project-name`). Прежде тест требовал
    «Всё в порядке» сразу после init — и это было верно ровно до тех пор, пока кит не проверял свои
    же заготовки: в живом продукте `project.name: <project-name>` простоял пять дней при зелёном
    вердикте. Утверждение не ослаблено, а усилено: теперь тест доказывает, что заготовка имени —
    ЕДИНСТВЕННОЕ, что отделяет свежую установку от зелёного, и что после её замены зелёный настаёт.

    Окружение изолировано (см. `_isolated_env`) — иначе тест мерил бы чистоту site-packages
    разработчика, а не свежую установку."""
    env = _isolated_env(tmp_path)
    r = _run_cli(installed_copy, "doctor", env=env)
    out = r.stdout + r.stderr
    assert "Traceback" not in out
    assert "пути окружения: ✓" in out, out[-2000:]
    assert "конфиг дочки: ✗" in out, f"кит не заметил своей же заготовки: {out[-2000:]}"
    assert "можно ставить задачу" not in out, out[-2000:]
    assert r.returncode == 0, out[-2000:]

    # делаем ровно то, о чём просит установка, — и больше замечаний быть не должно
    cfg = installed_copy / ".ai-ops.yaml"
    doc = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    doc["project"]["name"] = "Демо-продукт"
    cfg.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    r = _run_cli(installed_copy, "doctor", env=env)
    out = r.stdout + r.stderr
    # Вердикт печатает человекочитаемый слой (v3.35.2), поэтому проверяем СМЫСЛ, а не строку
    # `doctor: OK`: код возврата и отсутствие БЛОКЕРОВ — то, что этот тест защищает.
    assert "Всё в порядке" in out, out[-2000:]
    assert "замечани" not in out.lower(), out[-2000:]
    assert r.returncode == 0, out[-2000:]
    # НОВОЕ ТРЕБОВАНИЕ (14.08.2026): doctor обязан НАЗЫВАТЬ источник установки. В поле кит поставился
    # из черновой ветки и промолчал, хотя знает, откуда себя берёт; у дочки не оказалось правил
    # игнорирования, и первый коммит утащил в историю три десятка служебных файлов. Это ФАКТ в
    # отчёте, а не замечание: делать из него замечание значило бы красить каждую dev-установку.
    assert "источник:" in out, f"doctor не называет, откуда поставлен кит: {out[-2000:]}"
    assert ("выпуск" in out or "НЕ ВЫПУСК" in out), out[-2000:]


def test_doctor_blocks_on_residual_path_belt(installed, tmp_path):
    """fail-closed: остаточный пояс в site-packages красит doctor и называет команду удаления.

    Пара к тесту выше: то же окружение, та же установка, единственное отличие — подложенный пояс.
    Значит красным doctor делает именно он, а не что-то ещё."""
    env = _isolated_env(tmp_path)
    belt = _write_belt(_user_site_of(env))

    r = _run_cli(installed, "doctor", env=env)

    out = r.stdout + r.stderr
    assert "Traceback" not in out
    assert "path_belt" in out and str(belt) in out, out[-2000:]
    assert f'rm -f "{belt}"' in out, "doctor нашёл пояс, но не сказал, как его убрать"
    assert r.returncode != 0, (
        "пояс делает зелёными fail-closed-проверки — doctor не вправе это пропускать")
    # Вердикт обязан НАЗВАТЬ причину, а не сосчитать строки с `✗` (v3.35.2).
    assert "подменяет пути импорта" in out, out[-2000:]
    assert "ничего не доказывает" in out, "не сказано, почему остальному выводу нельзя верить"


def test_doctor_removes_the_belt_on_explicit_request(installed, tmp_path):
    """side-effect proof: `--remove-path-belt` РЕАЛЬНО удаляет файл, и только по явной просьбе.

    Порядок инвертирован намеренно: сначала доказываем, что без флага файл на диске остаётся
    (пакет, молча удаляющий файлы вне своего окружения, — тот же дефект, что и молча пишущий),
    и лишь потом — что с флагом он исчезает."""
    env = _isolated_env(tmp_path)
    belt = _write_belt(_user_site_of(env))

    dry = _run_cli(installed, "doctor", env=env)
    assert belt.exists(), "doctor без флага удалил файл в site-packages — этого он делать не вправе"
    # Предохранитель: удаляющий флаг запускаем только убедившись, что в области видимости нет
    # НАСТОЯЩИХ site-каталогов. Ровно на этом тест однажды снёс пояс на машине разработчика:
    # изоляция передавала реальный site-packages через PYTHONPATH, он попал под скан, и удаление
    # оказалось настоящим. Тест, способный удалить файл вне tmp, — не тест, а грабли.
    outside = [ln for ln in dry.stdout.splitlines()
               if "path_belt" in ln and str(tmp_path) not in ln]
    assert not outside, f"в области видимости настоящие site-каталоги, удаление опасно: {outside}"

    r = _run_cli(installed, "doctor", "--remove-path-belt", env=env)

    assert not belt.exists(), f"флаг не удалил пояс:\n{r.stdout[-2000:]}"
    assert "пояс удалён" in r.stdout, r.stdout[-2000:]


def test_status_ok_on_fresh_install(installed):
    """Свежая установка не имеет дрейфа: checksums сняты с того, что реально записано."""
    r = _run_cli(installed, "status")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "целостность managed: OK" in r.stdout


# ---------------------------------------------------------------- разделение поставки

def test_delivery_contains_full_engine_closure(installed, ai_ops):
    """fail-closed для разделения поставки: рантайм-замыкание движка целиком в child.

    Источник истины — ENGINE_CLOSURE из ai_ops_kit/validation/validate_standalone_engine.py: если
    из поставки выпадет файл движка, тест падает здесь, а не у пользователя в проде."""
    sys.path.insert(0, str(KIT / "validation"))
    try:
        import validate_standalone_engine as vse
    finally:
        sys.path.pop(0)
    managed = installed / ".ai" / "managed"
    missing = [rel for rel in vse.ENGINE_CLOSURE if not (managed / rel).is_file()]
    assert not missing, f"из поставки выпали файлы движка: {missing}"


def test_delivery_contains_runtime_validators(installed, ai_ops):
    """Валидаторы, которые движок вызывает в child (гейты, отчёт), обязаны доехать."""
    managed = installed / ".ai" / "managed"
    missing = [name for name in sorted(ai_ops.RUNTIME_VALIDATORS)
               if not (managed / "ai_ops_kit" / "validation" / f"{name}.py").is_file()]
    assert not missing, f"из поставки выпали рантайм-валидаторы: {missing}"


def test_delivery_contains_bootstrap_for_every_shipped_importer(installed):
    """Уехал модуль с `import _bootstrap` — обязан уехать и сам _bootstrap (v3.31.1).

    Белый список поставки перечисляет ВАЛИДАТОРЫ, а `_bootstrap` — их загрузчик путей, и по
    имени на валидатор не похож. В v3.31.0 из-за этого в child уехали валидаторы, умирающие
    на первой строке: `ModuleNotFoundError: No module named '_bootstrap'`. Проверка привязана
    к факту импорта, а не к списку имён.

    Проверяются каталоги, ИЗ КОТОРЫХ запускают скрипты (`tools/`, `ai_ops_kit/validation/`): там sys.path[0]
    — сам каталог, и `_bootstrap` обязан лежать рядом. Модули внутри `ai_ops_kit/**` сюда не
    входят намеренно: в них входят через алиас, который путь уже поставил, — требовать копию
    загрузчика в каждом пакете значило бы разводить его по дереву без нужды.
    """
    managed = installed / ".ai" / "managed"
    missing = []
    for d in ("tools", "validation"):
        for f in sorted((managed / d).glob("*.py")):
            if f.name == "_bootstrap.py":
                continue
            if "import _bootstrap" in f.read_text(encoding="utf-8"):
                if not (f.parent / "_bootstrap.py").is_file():
                    missing.append(f.relative_to(managed).as_posix())
    assert not missing, (
        "в поставке есть точки входа, импортирующие _bootstrap, которого рядом нет — "
        f"в child они падают на первой строке: {missing[:8]}")


def test_delivery_excludes_kit_development_assets(installed):
    """Ассеты РАЗРАБОТКИ КИТА не едут в child-репозиторий (P2-7)."""
    managed = installed / ".ai" / "managed"
    assert not (managed / "qualification").exists(), \
        "пакет квалификации движка (данные разработки кита) уехал в child"
    assert not (managed / "containers").exists(), \
        "эталонный контейнер кита уехал в child"
    for dev_tool in ("bench_lite.py", "qual_run.py", "changelog_gen.py"):
        assert not (managed / "tools" / dev_tool).exists(), f"dev-инструмент {dev_tool} в поставке"
    for dev_val in ("validate_package_boundaries.py", "validate_qualification.py",
                    "validate_release_claims.py", "validate_container_assets.py"):
        assert not (managed / "validation" / dev_val).exists(), \
            f"валидатор внутренних инвариантов кита {dev_val} в поставке"


def test_communication_adapter_reaches_claude_md(installed):
    """Находка ревью: политика коммуникации объявляла адаптер `claude-code-memory` («Claude Code
    подхватывает его автоматически») и обещание «правьте политику и перегенерируйте» — при этом
    ни одна строка кода блок не доставляла и не генерировала. Он доезжал статическим шаблоном в
    managed-слой, а в CLAUDE.md не попадал никогда."""
    md = installed / "CLAUDE.md"
    assert md.is_file(), "CLAUDE.md не создан — адаптер политики коммуникации не доехал"
    text = md.read_text(encoding="utf-8")
    assert "AI-OPS-COMMUNICATION-POLICY" in text          # блок помечен маркерами
    assert "product" in text                              # уровень по умолчанию назван


def test_communication_adapter_is_idempotent_and_keeps_user_text(installed, ai_ops):
    """Повторная установка не дублирует блок и не трогает текст ВНЕ маркеров."""
    md = installed / "CLAUDE.md"
    md.write_text("# Мои правила\n\nНе трогать это.\n\n" + md.read_text(encoding="utf-8"),
                  encoding="utf-8")
    ai_ops._install_communication_adapter(installed)
    text = md.read_text(encoding="utf-8")
    assert text.count(ai_ops.COMM_MARK_BEGIN) == 1, "блок продублирован"
    assert text.count(ai_ops.COMM_MARK_END) == 1
    assert "Не трогать это." in text, "текст пользователя вне маркеров затронут"


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


def test_child_gets_a_runnable_entry_point(installed):
    """НАХОДКА РЕВЬЮ, ломавшая обещание слоя коммуникации на ПЕРВОЙ команде: все подсказки кита
    печатали `ai-ops …`, а такой команды не существует — ни `console_scripts`, ни файла. Владелец
    копировал строку и получал `command not found`.

    Политика требует в каждом сообщении «что дальше». Пункт, который нельзя выполнить, этому
    требованию не удовлетворяет: в подсказке обязано быть то, что копируется и запускается.
    """
    import os
    import subprocess
    if not _path_python_with_pyyaml():
        pytest.skip("в PATH нет python3 с pyyaml — на этой машине кит не запускается, "
                    "и тест обёртки мерил бы окружение, а не её")
    entry = installed / "ai-ops"
    assert entry.is_file(), "в репозиторий не положена запускаемая точка входа"
    assert os.access(entry, os.X_OK), "точка входа не исполняемая"
    r = subprocess.run([str(entry), "status"], cwd=str(installed),
                       capture_output=True, text=True, timeout=120)
    assert r.returncode in (0, 1), f"./ai-ops status не работает: {r.returncode} {r.stderr[:300]}"
    # `status` — ПРОДУКТОВЫЙ вопрос («что идёт прямо сейчас»), а не отчёт о слое кита: у владельца
    # это первое значение слова. Состояние самого кита спрашивают реже и зовут `kit-status`.
    assert "идёт" in r.stdout or "не начата" in r.stdout, r.stdout[:300]
    assert "managed" not in r.stdout, "продуктовый вопрос ответил отчётом о внутренностях кита"


def test_entry_point_without_usable_python_says_what_to_do(installed):
    """fail-closed: нет интерпретатора с pyyaml -> внятное сообщение, а НЕ трейсбек.

    До ревизии 2026-08-11 обёртка звала голое `python3` из PATH. На машине, где pyyaml стоит в
    другом интерпретаторе (brew поднял минорную версию; кит ставили из venv), владелец получал
    `ModuleNotFoundError: No module named 'yaml'` — трейсбек вместо сообщения, на ПЕРВОЙ команде.
    Пустой PATH здесь моделирует именно это: ни один кандидат не пригоден.
    """
    import subprocess
    entry = installed / "ai-ops"
    env = {"PATH": str(installed / "no-python-here"), "HOME": os.environ.get("HOME", "/tmp")}
    r = subprocess.run([str(entry), "status"], cwd=str(installed), env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 2, f"ожидался fail-closed rc=2, получено {r.returncode}"
    err = r.stderr
    assert "Traceback" not in err and "ModuleNotFoundError" not in err, (
        f"вместо сообщения показан трейсбек:\n{err[:400]}")
    assert "pyyaml" in err, f"не названа причина:\n{err[:400]}"
    assert "AI_OPS_PYTHON" in err and "pip install" in err, (
        f"сказано, что сломано, но не сказано, что делать:\n{err[:400]}")


def test_entry_point_honours_explicit_interpreter(installed):
    """positive + side-effect proof: AI_OPS_PYTHON сильнее перебора PATH.

    Явное слово владельца обязано работать даже когда в PATH пригодного python3 нет вообще —
    иначе на машине с нестандартным окружением кит остаётся незапускаемым при живом интерпретаторе.
    """
    import subprocess
    entry = installed / "ai-ops"
    # PYTHONDONTWRITEBYTECODE в env НЕ передаём намеренно — так запускает владелец, и именно так
    # был найден дефект: успешная команда роняла 11 `.pyc` в checksummed managed-слой.
    env = {"PATH": str(installed / "no-python-here"), "HOME": os.environ.get("HOME", "/tmp"),
           "AI_OPS_PYTHON": sys.executable}

    # side-effect proof: кит не сорит в чужом репозитории. `.gitignore` установщик в дочку не
    # пишет, поэтому байткод в managed уехал бы в коммит владельца по `git add -A`.
    # R-39: замеряем ТОЛЬКО эффект своей команды — снимок до/до сравнивается со снимком после.
    # Фикстура `installed` общая на модуль, и раньше этот assert краснел из-за байткода СОСЕДА,
    # показывая при этом на обёртку, которая байткод как раз подавляет.
    def _pyc():
        return {str(p.relative_to(installed)) for p in (installed / ".ai" / "managed").rglob("*.pyc")}

    before = _pyc()
    r = subprocess.run([str(entry), "status"], cwd=str(installed), env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode in (0, 1), (
        f"AI_OPS_PYTHON={sys.executable} не был использован: rc={r.returncode}\n{r.stderr[:400]}")
    assert "идёт" in r.stdout or "не начата" in r.stdout, r.stdout[:300]
    left = sorted(_pyc() - before)
    assert not left, f"команда оставила байткод кита в managed-слое дочки: {left[:5]}"


def test_direct_installer_call_leaves_no_bytecode(installed):
    """R-39: у кита ДВА документированных входа, а защита стояла на одном.

    Обёртка `./ai-ops` экспортирует `PYTHONDONTWRITEBYTECODE=1` с ревизии 11.08, но прямой вызов
    `python3 ~/ai-ops-kit/installer/ai_ops.py doctor` описан наравне с ней — и оставлял байткод.
    Замер до правки: 19 файлов `.pyc` в checksummed `.ai/managed` за одну команду. Так и должно
    быть по устройству: `doctor` намеренно импортирует доставленную копию из managed, а не свою.
    """
    import subprocess

    def _pyc():
        return {str(p.relative_to(installed)) for p in (installed / ".ai" / "managed").rglob("*.pyc")}

    before = _pyc()
    r = subprocess.run([sys.executable, str(INSTALLER), "doctor"], cwd=str(installed),
                       capture_output=True, text=True, timeout=180)
    assert "Traceback" not in (r.stdout + r.stderr), (r.stdout + r.stderr)[-400:]
    left = sorted(_pyc() - before)
    assert not left, (
        f"прямой вызов установщика оставил байткод в checksummed managed-слое: {left[:5]} "
        f"(всего {len(left)}); `.gitignore` в дочку не пишется — это уедет в коммит владельца")


@pytest.mark.parametrize("script", [
    pytest.param("ai_ops_kit/validation/validate_ai_ops_child.py", id="валидатор"),
    pytest.param("tools/ai_ops_cli.py", id="плоский-алиас"),
])
def test_running_from_managed_leaves_no_bytecode(installed, script):
    """R-39, третий и четвёртый входы: человек зовёт код ИЗ managed напрямую.

    Так это описано в документации и так родился F-025. Обёртка `./ai-ops` тут не участвует,
    поэтому защита живёт в самих `_bootstrap` — условно, только когда корень оказался
    managed-слоем дочки. В дереве самого кита байткод остаётся нормой.

    Переменную `PYTHONDONTWRITEBYTECODE` из окружения СНИМАЕМ намеренно: её ставят группы CI, и
    без снятия тест был бы зелёным в CI по чужой причине, ничего не проверяя.
    """
    import subprocess

    def _pyc():
        return {str(p.relative_to(installed)) for p in (installed / ".ai" / "managed").rglob("*.pyc")}

    env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
    before = _pyc()
    r = subprocess.run([sys.executable, str(installed / ".ai" / "managed" / script)],
                       cwd=str(installed), capture_output=True, text=True, timeout=300, env=env)
    left = sorted(_pyc() - before)
    assert not left, (
        f"запуск `{script}` из managed оставил байткод в checksummed-слое: {left[:5]} "
        f"(всего {len(left)}); слой сверяется контрольными суммами — кит примет это за правку "
        f"владельца (F-025). rc={r.returncode}")


def test_hints_point_to_something_runnable(installed, ai_ops):
    """Ни одна подсказка не должна учить неработающей команде."""
    import subprocess
    out = subprocess.run(["python3", str(ai_ops.PKG / "installer" / "ai_ops.py"), "doctor"],
                         cwd=str(installed), capture_output=True, text=True, timeout=180).stdout
    bad = [ln for ln in out.splitlines()
           if "`ai-ops " in ln and "./ai-ops" not in ln and "python3" not in ln]
    assert not bad, f"подсказки учат несуществующей команде: {bad[:3]}"


def test_delivery_footprint_is_smaller_than_legacy(installed):
    """Поставка ощутимо меньше монолитной (baseline ревью: 503 файла / ~3.6 МБ managed)."""
    managed = installed / ".ai" / "managed"
    files = [p for p in managed.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    # v3.30: код переехал в пакеты ai_ops_kit/*, а плоские tools/*.py остались тонкими алиасами
    # обратной совместимости — их в поставке ~87 файлов на 39 КиБ. Считать их в потолок значило бы
    # либо ослабить потолок, либо запретить переходный слой. Поэтому потолок применяется к
    # СОДЕРЖАТЕЛЬНЫМ файлам, а алиасы ограничены отдельно по объёму: раздуться незаметно не смогут.
    aliases = [p for p in files if p.suffix == ".py"
               and "sys.modules[__name__]" in p.read_text(encoding="utf-8", errors="ignore")]
    alias_bytes = sum(p.stat().st_size for p in aliases)
    substantive = len(files) - len(aliases)
    # v3.35: потолок ПОДНЯТ 450 -> 470 осознанно. Product Operating Model едет в child по существу:
    # `ai-ops next`/`ai-ops model` работают В продуктовом репозитории, значит туда обязаны попасть
    # пакет `planning` (6 файлов), presenter, валидатор модели, две реестровые декларации, три
    # шаблона и скилл — 14 содержательных файлов, замерено, а не оценено. Смысл потолка сохранён:
    # baseline монолита 503, и 456 по-прежнему ощутимо меньше. Поднимать его молча нельзя — это то
    # же число класса DERIVED, что и замеры слоёв.
    # 2026-08-17: потолок ПОДНЯТ 470 -> 475 осознанно, замер — 470 содержательных файлов. Причина
    # ровно та же, что у поднятия 3.35, и она содержательная, а не «нужен запас»: короткий путь для
    # уже описанной работы (`planning/short_path`) и потолок траты на описание до первой правки кода
    # (`engops/process_spend`) РАБОТАЮТ В ПРОДУКТОВОМ РЕПОЗИТОРИИ — это два файла, которые обязаны
    # доехать до дочки, иначе решение владельца 2026-08-17 останется механизмом, зелёным только у
    # кита (класс F-030/F-032, самый дорогой из найденных полем). Плоские алиасы в потолок не идут.
    # Запас оставлен видимым (5 файлов), а не в один файл: 887 байт запаса уже дважды роняли этот
    # тест на первой же следующей работе.
    # 2026-08-17, ПОЗЖЕ В ТОТ ЖЕ ДЕНЬ: замер УПАЛ, и это записано, а не оставлено про себя.
    # Новая проверка поставки (`test_delivered_engine_does_not_import_undelivered_validators`)
    # показала, что в дочку едет `ai_ops_kit/devtools/` — инструменты разработки самого кита.
    # Исключение существовало, но проверялось только для путей `tools/`, а код переехал в пакеты.
    # После исключения: 563 файла, 462 содержательных, 3.4515 МБ (было 470 и 3.5257 МБ).
    # Потолки НЕ опускаю до нового замера намеренно: 3.5 оставило бы 50 КиБ, а этот файл дважды
    # ронялся ровно из-за такого запаса. 475/3.7 держат смысл (baseline монолита 503 не тронут).
    # 2026-08-20: ПОТОЛОК ОБЪЁМА ПОДНЯТ 3.7 -> 3.75, потолок ФАЙЛОВ не тронут (471 при 475).
    # Причина содержательная, а не «нужен запас» — тот же критерий, что при 470 -> 475: едет то,
    # что в дочке РАБОТАЕТ. Приехали два файла работы `experience-contract-drives-stories`:
    # `ai_ops_kit/ui/experience_contract.py` и `schemas/experience-contract.schema.json`.
    # Они не украшение: сторона доказательства (`ui/storybook_adapter`) ЧИТАЕТ Experience Contract
    # дочки и берёт из него обязательные состояния — без модуля в поставке это был бы вызов файла,
    # которого там нет (класс F-033).
    # ЗАМЕР: main 3.6878 МБ / 469 файлов -> ветка 3.7125 МБ / 471. Запас по объёму на main был
    # 12 КБ, то есть потолок был исчерпан ДО этой работы, а не ею.
    # НАЙДЕНО ПО ДОРОГЕ И НЕ СДЕЛАНО ОСОЗНАННО: `registry/release-claims.yaml` — 78 КБ собственных
    # заявлений кита о своих выпусках — едет в КАЖДУЮ дочку и кодом там не читается (проверено
    # grep по поставке: только упоминание в докстроке валидатора). Это в шесть раз больше, чем
    # стоила эта работа. Но на файл ссылаются `основания` правил поля
    # (`rules/core/field-lessons.yaml`), и прежде чем исключать, надо проверить, резолвятся ли они
    # в дочке. Сломать дочку ради 78 КБ нельзя — заведено работой `release-claims-stays-in-the-kit`.
    # 2026-08-20, ВТОРОЙ ПОДЪЁМ ЗА ДЕНЬ: файлы 475 -> 490, объём 3.75 -> 3.8.
    # Причина содержательная, критерий тот же: едет то, что в дочке РАБОТАЕТ. Приехали четыре
    # файла работ `night-review-v0-read-only` и `events-verified-in-runtime`:
    #   ai_ops_kit/intelligence/nightly_review.py   — обзор, его зовёт команда рантайма и Robin;
    #   ai_ops_kit/intelligence/event_arrival.py    — проверка поступления событий, зовёт обзор;
    #   commands/maintenance/night-review.md        — маршрут рантайма к обзору;
    #   templates/analytics/EventArrivalEvidence.json — форма выгрузки, которую кладёт дочка.
    # ЗАМЕР: main 471 файл / 3.7125 МБ -> ветка 475 / 3.7558 МБ (+4 файла, +43 КБ).
    #
    # ЭТО ВТОРОЙ ПОДЪЁМ ЗА ОДИН ДЕНЬ, И ЭТО САМО ПО СЕБЕ СИГНАЛ. Потолок держит не рост
    # продукта, а отсутствие обратного движения: за день из поставки ушло только то, что было
    # заведомо мёртвым (12 неподключённых модулей). Крупнейший названный кандидат —
    # `registry/release-claims.yaml`, 78 КБ собственных заявлений кита, которые в дочке кодом не
    # читаются: это вшестеро больше всей сегодняшней прибавки. Он не тронут осознанно (на файл
    # ссылаются основания правил поля) и заведён работой второй ленты
    # `release-claims-stays-in-the-kit`. Пока она не сделана, потолок будет упираться снова.
    assert substantive < 490, f"содержательных файлов в managed: {substantive} (потолок 490)"
    assert alias_bytes < 200 * 1024, f"алиасы разрослись: {alias_bytes / 1024:.0f} КиБ (потолок 200)"
    # 2026-08-13: потолок объёма ПОДНЯТ 3.2 -> 3.3 МБ осознанно, и это замер, а не округление.
    # Запаса не оставалось вовсе: на базе e71a0c2 поставка занимала 3 354 556 Б при потолке
    # 3 355 443 Б — 887 БАЙТ, то есть следующий доставляемый файл любого размера уронил бы тест
    # независимо от того, нужен он дочке или нет.
    # ПОВОД БЫЛ ДВОЙНОЙ — две работы одного дня упёрлись в один и тот же потолок, и обе причины
    # настоящие (не сглаживаю до одной при слиянии):
    #   * измерение расхода сессии по транскрипту рантайма (+26 КиБ в пяти модулях) — код обязан
    #     ехать в дочку, потому что политику экономии сессии применяют в продуктовом репозитории;
    #   * `rules/core/field-lessons.yaml` (12.8 КиБ) — шесть правил, оплаченных полем, с
    #     основаниями; без доставки они остались бы культурой одного репозитория.
    # Замер после: 3.2171 МБ (554 файла, 459 содержательных).
    # Смысл потолка сохранён: baseline монолита — ориентир по ЧИСЛУ файлов (503), он не тронут;
    # объём стережёт «раздувание незаметно», и 3.3 оставляет ~85 КиБ видимого запаса вместо 887 байт.
    # Молча поднимать нельзя — это число класса DERIVED, как и замеры слоёв.
    #
    # 2026-08-13, ТОТ ЖЕ ДЕНЬ: потолок ПОДНЯТ 3.3 -> 3.5 МБ, и повод — не одна правка, а замер.
    # Запас в 72 КиБ, оставленный поднятием выше, был съеден ЗА СУТКИ. Замерено по коммитам (тот же
    # тест, значение вместо потолка), а не оценено:
    #   567f963 (само поднятие 3.2->3.3)  3 386 631 Б   запас 73 670
    #   c9ca718 (#96..#99: подсессия, самоприменение, точка входа автономии)  3 452 769   +66 138
    #   a497a50 (#101 канонизация путей в брокере)       3 458 306   +5 537
    #   0b63041 (#100 деривируемые числа связности)      3 460 003   +1 697
    #   086b9df, 9700179 (документация и план)           3 460 003   +0
    # Итог: на main оставалось 297 БАЙТ. Ровно то состояние, которое абзац выше описывает про
    # прошлый раз («887 байт — следующий доставляемый файл любого размера уронил бы тест»), то есть
    # история повторилась через один цикл.
    #
    # ПОЧЕМУ ЭТО НЕ «ПОДНЯТЬ, ЧТОБЫ ПРОШЛО». Правка, упёршаяся в потолок (перенос комментариев
    # владельца, F-020, +6 520 Б в `repo_audit.py`), даёт 2% прироста; 90% съели уже смерженные
    # работы, и ни одна из них об этом не узнала — тест краснеет только на СЛЕДУЮЩЕМ коммите.
    # Наказывать за это того, кто пришёл последним, значит мерить очередь, а не размер.
    # Замер после: 3 466 523 Б (3.3062 МБ); 3.5 оставляет ~199 КиБ видимого запаса.
    # Смысл потолка сохранён: baseline монолита по ЧИСЛУ файлов (503) не тронут.
    #
    # НАЗВАННАЯ ГРАНИЦА: потолок ловит раздувание ПОСЛЕ пробоя и не умеет предупреждать до него —
    # поэтому дрейф в 72 КиБ прошёл незамеченным через четыре PR. Это объявлено работой
    # (`planning/plan.yaml` -> delivery-size-warns-before-breach), а не оставлено «на подумать».
    #
    # R-39 (та же дата, отдельная работа): защита «байткода в managed быть не должно» живёт в
    # ДОСТАВЛЯЕМОМ дереве — три `_bootstrap` — и стоит 1746 Б (замер: 3 460 003 -> 3 461 749 на
    # базе до подъёма). Своего подъёма она НЕ потребовала: при потолке 3.5 запас есть. Строка
    # здесь не ради истории, а ради ленты замеров выше — она должна оставаться полной.
    #
    # 2026-08-17: потолок ПОДНЯТ 3.5 -> 3.7 МБ, и это снова ЗАМЕР, а не округление.
    #   origin/main до работы     3 640 091 Б (3.4715 МБ)   запас до 3.5 — 28 261 Б
    #   короткий путь + потолок   3 697 009 Б (3.5257 МБ)   +56 918 Б
    # Доставляется по существу: `planning/short_path` и `engops/process_spend` применяются В
    # продуктовом репозитории (решение владельца 2026-08-17), и оставить их у кита значило бы
    # повторить самый дорогой класс находок поля — механизм зелёный у нас, отсутствующий у дочки.
    # 3.7 оставляет ~178 КиБ видимого запаса.
    # ЗАМЕР ПОДТВЕРЖДАЕТ УЖЕ ОБЪЯВЛЕННУЮ РАБОТУ: на базе оставалось 28 КиБ — то есть предупреждать
    # «до пробоя» этот потолок по-прежнему не умеет, и очередная работа снова узнала о нём падением.
    # Это `delivery-size-warns-before-breach` в плане, и она не выдумана задним числом.
    assert total < 3.8 * 1024 * 1024, f"объём managed: {total / 1024 / 1024:.2f} МБ (потолок 3.8)"


def test_managed_set_excludes_are_declared_not_implicit(ai_ops):
    """Честность декларации: исключения из поставки — явный список, а не побочный эффект."""
    assert ai_ops.DEV_ONLY_PREFIXES, "список dev-only префиксов пуст"
    pairs = ai_ops.managed_set()
    rels = {rel for _, rel in pairs}
    assert not any(r.startswith("qualification/") for r in rels)
    assert not any(r.startswith("containers/") for r in rels)
    assert "tools/ai_ops_run.py" in rels
    assert "ai_ops_kit/engine/ai_route.py" in rels


# ---------------------------------------------------------------- внутренние функции

@pytest.mark.parametrize("version,rng,expected", [
    ("2.14.1", ">=2.0.0 <3.0.0", True),
    ("2.14.1", ">=1.0.0 <2.0.0", False),
    ("9.9.9", "", True),
    ("3.0.0", ">=3.0.0", True),
])
def test_version_in_range(ai_ops, version, rng, expected):
    assert ai_ops.version_in_range(version, rng) is expected


def test_broken_child_config_raises_named_error(ai_ops, child, monkeypatch):
    """Битый конфиг даёт доменную ошибку с именем файла — её и ловит main()."""
    cfg = child / ".ai-ops.yaml"
    cfg.write_text("parent: [oops\n", encoding="utf-8")
    monkeypatch.setattr(ai_ops, "CHILD_CONFIG", cfg)
    with pytest.raises(ai_ops.ChildConfigError) as exc:
        ai_ops.installed_version()
    assert ".ai-ops.yaml" in str(exc.value)


@pytest.mark.slow   # тяжёлая обёртка селфтеста: в быстрый профиль не входит
def test_installer_selftest_passes():
    """Собственный selftest инсталлятора остаётся зелёным (не подменяем его этими тестами)."""
    r = subprocess.run([sys.executable, str(INSTALLER), "--selftest"],
                       cwd=str(KIT), capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout[-4000:] + r.stderr[-2000:]

def test_fresh_install_does_not_report_planning_as_ready(installed, ai_ops):
    """F-018 (живой прогон severnaya_traektoriya, 2026-08-12): doctor рапортовал «✓ артефакты на
    месте» СРАЗУ после установки — про черновики, которые сам же и положил.

    Кит собственным кодом знает разницу (`delivery_plan.is_template()` на этом же файле даёт True),
    но doctor спрашивал только `Path.exists()`. Владелец на свежей установке читал зелёное про
    пустой контур. Комментарий над проверкой обещал обратное: «пробел ВИДЕН, а не молчит».
    """
    req, gaps, unfilled = ai_ops._planning_gaps(installed)
    assert req, "контур планирования не объявлен в манифесте — тест потерял предмет"
    assert unfilled, "свежая установка объявлена заполненной: заготовки посчитаны за план"
    assert not gaps, f"заготовки посчитаны ПРОБЕЛОМ — это испортит первый экран: {gaps}"


def test_filled_planning_artifacts_are_not_reported_as_gap(installed, ai_ops):
    """Обратная сторона: заполненные артефакты пробелом не считаются.

    Без этой проверки F-018 можно было бы «закрыть», объявив контур пустым всегда.
    """
    (installed / "ROADMAP.md").write_text(
        "# ROADMAP\n\n## Сейчас\n\n- `real-goal` — настоящая цель\n\n"
        "## Следующий результат\n\n- `next-goal` — пользователь сможет…\n\n"
        "## Дальше\n\n- крупная возможность\n\n## Later\n\n- идея — не берём\n",
        encoding="utf-8")
    (installed / "planning").mkdir(exist_ok=True)
    (installed / "planning" / "plan.yaml").write_text(
        "schema_version: 1\nkind: delivery-plan\ngoals:\n  - id: real-goal\n    status: active\n"
        "work:\n  - id: w-01\n    title: Работа\n    type: engineering\n    goal: real-goal\n"
        "    status: todo\n    owner_role: engineer\n    write_scope: [src/]\n",
        encoding="utf-8")

    _req, gaps, unfilled = ai_ops._planning_gaps(installed)
    assert not gaps and not unfilled, f"заполненные артефакты объявлены незаполненными: {gaps} {unfilled}"


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


def test_init_hides_kit_service_state_from_child_git(installed):
    """side-effect proof: после install git САМ говорит, что служебное состояние скрыто."""
    assert (installed / ".gitignore").is_file(), "install не создал .gitignore в дочке"
    not_hidden = [f"{rel} ({why})" for rel, why in LEAKY_PATHS if not _check_ignored(installed, rel)]
    assert not not_hidden, (
        "служебное состояние кита уедет в коммит владельца по `git add -A`:\n  "
        + "\n  ".join(not_hidden))


def test_init_does_not_hide_product_artifacts(installed):
    """Обратная сторона, обязательная: правило не вправе спрятать продукт.

    Без неё F-021 «закрывался» бы строкой `.ai/` — и вместе с мусором из истории исчезли бы
    managed-слой, ответы владельца и история эффекта.
    """
    hidden = [f"{rel} ({why})" for rel, why in KEPT_PATHS if _check_ignored(installed, rel)]
    assert not hidden, "правило спрятало от git продуктовые артефакты:\n  " + "\n  ".join(hidden)


def test_existing_gitignore_is_appended_not_overwritten(child, ai_ops):
    """`.gitignore` — документ владельца: его правила обязаны выжить, а блок не должен дублироваться."""
    gi = child / ".gitignore"
    gi.write_text("# правила владельца\nnode_modules/\n*.log\n", encoding="utf-8")

    assert ai_ops.ensure_gitignore(child) == "appended"
    text = gi.read_text(encoding="utf-8")
    assert "# правила владельца" in text and "node_modules/" in text, "правила владельца утрачены"
    assert ".ai/worktrees/" in text, "блок кита не дописан"

    assert ai_ops.ensure_gitignore(child) == "present", "повторный вызов не распознал свой блок"
    assert gi.read_text(encoding="utf-8") == text, "повторный вызов изменил файл"
    assert text.count(".ai/worktrees/") == 1, "блок кита продублирован"


def test_gitignore_is_created_when_child_has_none(child, ai_ops):
    assert not (child / ".gitignore").exists()
    assert ai_ops.ensure_gitignore(child) == "created"
    assert ".ai/runtime/active-work.yaml" in (child / ".gitignore").read_text(encoding="utf-8")


def test_gitignore_change_is_named_in_the_report(child, ai_ops):
    """Дописка в чужой файл обязана быть НАЗВАНА: иначе владелец узнаёт о ней из диффа."""
    line = ai_ops._assets_report_line({"gitignore": "appended"})
    assert ".gitignore" in line and "дополнен" in line, line
    assert "не затронуты" in line, "отчёт не говорит, что продуктовые артефакты не тронуты"
    assert ai_ops._assets_report_line({"gitignore": "present"}).strip() == "", (
        "нечего сообщать, а отчёт говорит — это шум, из-за которого перестают читать отчёты")


# ---------------------------------------------------------------- F-024: опт-аут CI уважается
#
# НАХОДКА (живая установка в дочку, 2026-08-12). Шапка `ai-ops-record.yml` объявляет опт-аут
# ДОСЛОВНО: «Опт-аут: удалить этот файл». Владелец удаляет — и файл ВОЗВРАЩАЕТСЯ на первом же
# `ai-ops update`, потому что отсутствие читалось как `absent` -> «не установлен» -> «установить».
# Объявленный опт-аут не исполнялся, и цена у этого не косметическая: рекордер коммитит и пушит на
# каждый push, то есть в боте он жёг бы общие минуты Actions (в их же workflow написано, что минуты
# однажды кончились посреди работы).
#
# Различить два смысла «файла нет» кит может БЕЗ новых полей в схеме: у него уже есть отпечатки
# того, что он ставил сам. Есть отпечаток и нет файла -> владелец удалил (решение);
# нет ни файла, ни отпечатка -> просто ещё не ставили.

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


def test_deleted_workflow_is_opted_out_not_absent(installed_copy, ai_ops):
    """Состояние различает решение владельца и «ещё не ставили»."""
    _record_path(installed_copy).unlink()
    state = {r["file"]: r["state"] for r in ai_ops.ci_workflow_state(installed_copy)}
    assert state["ai-ops-record.yml"] == "opted-out", state
    # обратная сторона: файл, которого кит НИКОГДА не ставил, остаётся absent
    prints = ai_ops._ci_prints(installed_copy)
    prints.pop("ai-ops-record.yml", None)
    ai_ops._ci_prints_path(installed_copy).write_text(
        __import__("json").dumps(prints, ensure_ascii=False), encoding="utf-8")
    state2 = {r["file"]: r["state"] for r in ai_ops.ci_workflow_state(installed_copy)}
    assert state2["ai-ops-record.yml"] == "absent", (
        "без отпечатка отсутствие обязано читаться как «не установлен» — иначе первая установка "
        "перестанет ставить шаблоны вовсе")


def test_opt_out_survives_sync_and_is_named(installed_copy, ai_ops):
    """Доставка не возвращает удалённое и ГОВОРИТ об этом, а не молчит."""
    _record_path(installed_copy).unlink()
    acts = ai_ops.sync_ci_workflows(installed_copy)
    assert not _record_path(installed_copy).exists(), "удалённый владельцем workflow вернулся"
    kept = [a for a in acts if a["file"] == "ai-ops-record.yml"]
    assert kept and kept[0]["action"] == "kept-opted-out", acts


def test_opt_out_survives_refresh_ci(installed_copy, ai_ops):
    """`--refresh-ci` означает «перезапиши мои правки», а НЕ «верни удалённое».

    Иначе флаг об обновлении толковал бы согласие шире выданного.
    """
    _record_path(installed_copy).unlink()
    ai_ops.sync_ci_workflows(installed_copy, refresh=True)
    assert not _record_path(installed_copy).exists(), "--refresh-ci отменил решение владельца"


def test_first_install_still_delivers_the_workflow(child, ai_ops):
    """positive, обязательный: на репозитории без кита шаблон по-прежнему ставится."""
    r = _run_cli(child, "init", ".")
    assert r.returncode == 0, r.stdout[-400:]
    assert _record_path(child).exists(), "первая установка перестала ставить рекордер"


# ------------------------------------------- 12. установка не выглядит началом работы

def test_fresh_install_is_not_a_code_change(installed):
    """Свежая установка НЕ читается как «код уже правится» (проба шва 2026-08-17).

    Потолок траты на описание применяется только пока код не тронут, а «тронут» выводится из
    `git status`. Пока список путей кита состоял из трёх каталогов, свежеустановленная дочка давала
    `code_changed=True` — и потолок не срабатывал НИКОГДА. Ни один тест этого не видел: все они
    мерили репозиторий кита, где своей же поставки в `git status` нет. Поймалось установкой в пустую
    дочку, и проверка живёт ЗДЕСЬ — рядом с установкой, а не рядом с механизмом.
    """
    from ai_ops_kit.engops import process_spend
    assert process_spend.code_changed(installed) is False, \
        "поставка кита принята за правку кода: " + subprocess.run(
            ["git", "-C", str(installed), "status", "--porcelain"],
            capture_output=True, text=True, check=False).stdout

    (installed / "src" / "calc.py").write_text("def add(a, b):\n    return b + a\n", encoding="utf-8")
    try:
        assert process_spend.code_changed(installed) is True, \
            "правка кода продукта в той же дочке не замечена — исключения съели всё"
    finally:
        _git(installed, "checkout", "--", "src/calc.py")


def test_delivered_engine_does_not_import_undelivered_validators(installed):
    """Что поставка ЗОВЁТ, то она обязана и СОДЕРЖАТЬ (F-033, поле 15.08.2026).

    Белый список `RUNTIME_VALIDATORS` — память автора, а не проверяемый факт. Цена этого уже
    заплачена: `validate_acceptance_result` (механизм против ложного green, построенный 14.08 и
    починенный 15.08) в дочке падал `ImportError` и не исполнялся НИКОГДА, потому что имя в список
    не внесли. Механизм был зелёным в ките и отсутствующим у владельца.

    Проверка идёт по УСТАНОВЛЕННОЙ копии, а не по репозиторию кита, — иначе она снова мерила бы кит.
    Из этого свойство получается бесплатно: `devtools/` в дочку не едет, поэтому его импорты сюда и
    не попадают, а исключать их вручную не нужно.
    """
    managed = installed / ".ai" / "managed"
    delivered = {p.stem for p in (managed / "ai_ops_kit" / "validation").glob("*.py")}
    assert delivered, "в поставке нет ни одного валидатора — измерять нечего"

    wanted = {}
    for py in sorted(managed.rglob("*.py")):
        rel = py.relative_to(managed).as_posix()
        if rel.startswith("ai_ops_kit/validation/"):
            continue                     # валидатор, зовущий валидатора, — их внутреннее дело
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"), filename=rel)
        except SyntaxError:               # синтаксис поставки стережёт отдельная проверка
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith(
                    "ai_ops_kit.validation"):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name.rsplit(".", 1)[-1] for a in node.names
                         if a.name.startswith("validate_")]
            for n in names:
                if n.startswith("validate_") or n == "ai_managed_checksums":
                    wanted.setdefault(n, rel)

    missing = {n: where for n, where in sorted(wanted.items()) if n not in delivered}
    assert not missing, (
        "поставка зовёт валидаторы, которых в ней нет — механизм будет падать ImportError "
        "у владельца: " + "; ".join(f"{n} (из {w})" for n, w in missing.items()))
