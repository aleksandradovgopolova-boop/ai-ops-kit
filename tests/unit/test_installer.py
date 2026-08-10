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

def test_doctor_ok_on_fresh_install(installed, tmp_path):
    """positive: сразу после init диагностика зелёная (rc=0), без трейсбеков.

    Окружение изолировано (см. `_isolated_env`) — иначе тест мерил бы чистоту site-packages
    разработчика, а не свежую установку."""
    r = _run_cli(installed, "doctor", env=_isolated_env(tmp_path))
    out = r.stdout + r.stderr
    assert "Traceback" not in out
    assert "пути окружения: ✓" in out, out[-2000:]
    assert "doctor: OK" in out, out[-2000:]
    assert r.returncode == 0, out[-2000:]


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
    assert "doctor: ЕСТЬ ПРОБЛЕМЫ" in out and r.returncode != 0, (
        "пояс делает зелёными fail-closed-проверки — doctor не вправе это пропускать")


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


def test_child_gets_a_runnable_entry_point(installed):
    """НАХОДКА РЕВЬЮ, ломавшая обещание слоя коммуникации на ПЕРВОЙ команде: все подсказки кита
    печатали `ai-ops …`, а такой команды не существует — ни `console_scripts`, ни файла. Владелец
    копировал строку и получал `command not found`.

    Политика требует в каждом сообщении «что дальше». Пункт, который нельзя выполнить, этому
    требованию не удовлетворяет: в подсказке обязано быть то, что копируется и запускается.
    """
    import os
    import subprocess
    entry = installed / "ai-ops"
    assert entry.is_file(), "в репозиторий не положена запускаемая точка входа"
    assert os.access(entry, os.X_OK), "точка входа не исполняемая"
    r = subprocess.run([str(entry), "status"], cwd=str(installed),
                       capture_output=True, text=True, timeout=120)
    assert r.returncode in (0, 1), f"./ai-ops status не работает: {r.returncode} {r.stderr[:300]}"
    assert "установлено" in (r.stdout + r.stderr), r.stdout[:300]


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
    assert substantive < 470, f"содержательных файлов в managed: {substantive} (потолок 470)"
    assert alias_bytes < 200 * 1024, f"алиасы разрослись: {alias_bytes / 1024:.0f} КиБ (потолок 200)"
    assert total < 3.2 * 1024 * 1024, f"объём managed: {total / 1024 / 1024:.2f} МБ"


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
