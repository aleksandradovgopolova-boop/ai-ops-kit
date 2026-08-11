"""Остаточный `.pth`-пояс кита виден и снимаем (дополнение к v3.33.1).

3.33.1 убрал из `setup.py` запись пояса в site-packages пользователя — но не убрал пояса, уже
написанные на машинах: файл лежит вне репозитория и вне учёта pip, поэтому обновление пакета его
не касается. У каждого, кто ставил кит раньше, он продолжает подкладывать корень репозитория,
`tools/` и `validation/` в КАЖДЫЙ процесс Python.

Почему это не косметика — замерено в этом же файле (`test_belt_really_hides_a_defect`): с поясом
`import _bootstrap` из чужого каталога проходит, без пояса падает. Ровно на этом
`test_validator_bootstrap.py::test_missing_bootstrap_is_caught` перестал краснеть на удалённом
файле: fail-closed-проверка теряет зубы, а выглядит зелёной.

Тесты подают проверке КАТАЛОГИ ЯВНО. Проверка, которая на машине владельца обязана краснеть, не
может проверяться на этой же машине — иначе она мерила бы ноутбук, а не разбор.

Три обязательных теста на capability (AGENTS.md):
  * positive     — настоящий пояс найден, названы его пути и команда удаления;
  * fail-closed  — чистые site-каталоги дают `clean` (иначе проверка красит всё и её выключат),
                   а переименованный пояс всё равно пойман по содержимому;
  * side-effect  — `remove_belts()` РЕАЛЬНО удаляет файл с диска, и только пояс: editable-установку
                   снимает pip, чужие `.pth` не наши.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PKG = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PKG))
from ai_ops_kit.shared import path_hygiene as ph  # noqa: E402

pytestmark = pytest.mark.unit

# Ровно то, что писал `setup.py` до v3.33.1 (см. git show v3.33.1~1:setup.py). Шаблон, а не
# пересказ: проверка обязана ловить настоящий файл, а не свою идею о нём.
BELT_TEMPLATE = (
    "import os, sys; [sys.path.insert(0, p) for p in ['{root}'] + "
    "[os.path.join('{root}', d) for d in ('tools', 'validation')] "
    "if os.path.isdir(p) and p not in sys.path]\n"
)


def _write_belt(site_dir: Path, root=PKG, name=ph.BELT_FILENAME) -> Path:
    site_dir.mkdir(parents=True, exist_ok=True)
    pth = site_dir / name
    pth.write_text(BELT_TEMPLATE.format(root=root), encoding="utf-8")
    return pth


def _write_noise(site_dir: Path):
    """Соседи по каталогу, которые проверка трогать не вправе."""
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "distutils-precedence.pth").write_text(
        "import os; var = 'SETUPTOOLS_USE_DISTUTILS'\n", encoding="utf-8")
    (site_dir / "__editable__.someone_else-1.0.pth").write_text(
        "import __editable___someone_else_finder; __editable___someone_else_finder.install()\n",
        encoding="utf-8")
    (site_dir / "plain.pth").write_text(f"{site_dir / 'not-a-kit'}\n", encoding="utf-8")


# ---------------------------------------------------------------- positive

def test_residual_belt_is_found(tmp_path):
    """positive: пояс найден, названы подложенные пути и команда удаления."""
    user_site = tmp_path / "user-site"
    belt = _write_belt(user_site)
    _write_noise(user_site)

    rep = ph.assess(user_site_dirs=[str(user_site)], env_site_dirs=[])

    assert rep["status"] == "belt_found", rep
    belts = [f for f in rep["findings"] if f["rule"] == "path_belt"]
    assert len(belts) == 1, f"пояс не опознан однозначно: {rep['findings']}"
    found = belts[0]
    assert found["severity"] == "blocking", "пояс не может быть advisory: он красит проверки зелёным"
    assert found["path"] == str(belt)
    # Пояс подкладывает корень И два родовых каталога — отчёт обязан показать все три.
    assert set(found["injected_paths"]) == {
        str(PKG), f"{PKG}/tools", f"{PKG}/validation"}, found["injected_paths"]
    assert "rm -f" in found["fix"] and str(belt) in found["fix"], found["fix"]
    assert "pip uninstall" in found["fix"], "инструкция молчит о том, что pip файл не заберёт"


def test_doctor_summary_names_the_file_and_the_command(tmp_path):
    """Строка для doctor бесполезна без пути и команды — проверяем именно её, а не отчёт."""
    user_site = tmp_path / "user-site"
    belt = _write_belt(user_site)
    rep = ph.assess(user_site_dirs=[str(user_site)], env_site_dirs=[])

    line = ph.summary_line(rep)

    assert str(belt) in line and "rm -f" in line, line


# ---------------------------------------------------------------- fail-closed

def test_clean_site_dirs_are_clean(tmp_path):
    """fail-closed (в обе стороны): чужие .pth не находка. Проверка, красящая всё, будет выключена."""
    user_site = tmp_path / "user-site"
    _write_noise(user_site)

    rep = ph.assess(user_site_dirs=[str(user_site)], env_site_dirs=[])

    assert rep["status"] == "clean", rep["findings"]
    assert rep["counts"]["scanned_dirs"] == 1, "каталог не просмотрен — «чисто» ничего не значит"


def test_renamed_belt_is_still_caught(tmp_path):
    """fail-closed: опознание не сводится к имени файла — иначе достаточно переименовать."""
    user_site = tmp_path / "user-site"
    belt = _write_belt(user_site, name="whatever.pth")

    rep = ph.assess(user_site_dirs=[str(user_site)], env_site_dirs=[])

    assert [f["path"] for f in rep["findings"] if f["rule"] == "path_belt"] == [str(belt)], rep


def test_editable_in_user_site_is_advisory_and_in_venv_is_not_a_finding(tmp_path):
    """Разное происхождение — разный вердикт: pip снимает editable, пояс не снимает никто.

    В venv editable-установка вообще не находка: она ограничена своим окружением — ровно то,
    ради чего venv существует. Иначе проверка ругалась бы на нормальную разработку кита."""
    user_site = tmp_path / "user-site"
    venv_site = tmp_path / "venv-site"
    for d in (user_site, venv_site):
        d.mkdir(parents=True, exist_ok=True)
        (d / "__editable__.ai_ops_kit-3.27.7.pth").write_text(
            "import __editable___ai_ops_kit_3_27_7_finder; "
            "__editable___ai_ops_kit_3_27_7_finder.install()\n", encoding="utf-8")

    user = ph.assess(user_site_dirs=[str(user_site)], env_site_dirs=[])
    venv = ph.assess(user_site_dirs=[], env_site_dirs=[str(venv_site)])

    assert user["status"] == "advisory" and user["counts"]["blocking"] == 0, user
    assert user["findings"][0]["rule"] == "editable_in_user_site"
    assert "pip uninstall" in user["findings"][0]["fix"]
    assert venv["status"] == "clean", f"editable в venv — не находка: {venv['findings']}"


def test_static_path_editable_install_is_not_mistaken_for_a_belt(tmp_path):
    """fail-closed на РАЗРУШИТЕЛЬНОМ исходе (находка ревью).

    `pip install -e . --config-settings editable_mode=compat` пишет `__editable__.ai_ops_kit-*.pth`
    ОБЫЧНОЙ строкой пути — текстуально это неотличимо от пояса. Принять её за пояс значит советовать
    `rm` на файл, который значится в RECORD: установка сломается, а pip об этом не узнает.
    Владение решается по хозяину файла, а не по форме содержимого."""
    venv_site = tmp_path / "venv-site"
    user_site = tmp_path / "user-site"
    for d in (venv_site, user_site):
        (d / "ai_ops_kit-3.33.2.dist-info").mkdir(parents=True)
        (d / "__editable__.ai_ops_kit-3.33.2.pth").write_text(f"{PKG}\n", encoding="utf-8")
        (d / "ai_ops_kit-3.33.2.dist-info" / "RECORD").write_text(
            "__editable__.ai_ops_kit-3.33.2.pth,sha256=x,42\n", encoding="utf-8")

    venv = ph.assess(user_site_dirs=[], env_site_dirs=[str(venv_site)])
    user = ph.assess(user_site_dirs=[str(user_site)], env_site_dirs=[])

    assert venv["status"] == "clean", f"editable-установка в venv стала находкой: {venv['findings']}"
    assert user["counts"]["blocking"] == 0, user["findings"]
    assert user["findings"][0]["rule"] == "editable_in_user_site", user["findings"][0]
    # И под удаление такой файл не попадает ни при каких условиях.
    assert ph.remove_belts(user) == []
    assert (user_site / "__editable__.ai_ops_kit-3.33.2.pth").exists()


def test_pth_recorded_by_pip_is_never_removable(tmp_path):
    """Тот же замок по общему признаку: имя из RECORD не наше, как бы файл ни назывался."""
    user_site = tmp_path / "user-site"
    (user_site / "somepkg-1.0.dist-info").mkdir(parents=True)
    owned = _write_belt(user_site, name="somepkg.pth")     # содержимое пояса, но хозяин — pip
    (user_site / "somepkg-1.0.dist-info" / "RECORD").write_text(
        "somepkg.pth,sha256=x,10\nsomepkg/__init__.py,,\n", encoding="utf-8")

    rep = ph.assess(user_site_dirs=[str(user_site)], env_site_dirs=[])

    assert rep["counts"]["blocking"] == 0, rep["findings"]
    assert ph.remove_belts(rep) == [] and owned.exists()


def test_relative_pth_entry_is_resolved_against_site_dir(tmp_path, monkeypatch):
    """По семантике `.pth` относительная запись отсчитывается от site-каталога, не от cwd.

    Иначе чужой `.pth` со строкой `.` объявлялся поясом кита всякий раз, когда проверку запускают
    из корня кита, — и предлагал `rm` на него."""
    user_site = tmp_path / "user-site"
    user_site.mkdir(parents=True)
    (user_site / "someproject.pth").write_text(".\n", encoding="utf-8")
    monkeypatch.chdir(PKG)                                  # cwd = корень кита: маркеры VERSION тут

    rep = ph.assess(user_site_dirs=[str(user_site)], env_site_dirs=[])

    assert rep["status"] == "clean", f"относительная запись разрешена от cwd: {rep['findings']}"

    # Обратная сторона: настоящую относительную запись НА кит проверка обязана находить.
    kit_link = user_site / "kit"
    kit_link.symlink_to(PKG, target_is_directory=True)
    (user_site / "someproject.pth").write_text("kit\n", encoding="utf-8")
    assert ph.assess(user_site_dirs=[str(user_site)], env_site_dirs=[])["counts"]["blocking"] == 1


def test_same_dir_via_symlink_is_counted_once(tmp_path):
    """Один каталог, видимый двумя путями, не даёт двух находок: второе удаление падало бы с ENOENT,
    и doctor печатал «пояс НЕ удалён» про уже удалённый файл."""
    real = tmp_path / "real" / "site-packages"
    belt = _write_belt(real)
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "real", target_is_directory=True)

    rep = ph.assess(user_site_dirs=[str(real), str(link / "site-packages")], env_site_dirs=[])

    assert rep["counts"]["blocking"] == 1, rep["findings"]
    assert rep["counts"]["scanned_dirs"] == 1, rep["scanned_dirs"]
    results = ph.remove_belts(rep)
    assert not belt.exists()
    assert [r["removed"] for r in results] == [True], results


def test_nothing_scanned_is_not_clean():
    """«Не знаю» не выдаётся за «чисто» — иначе doctor зелёный там, где не проверено ничего.

    Так выглядит окружение старого virtualenv: `getusersitepackages()` бросает, `getsitepackages`
    отсутствует, в `sys.path` нет ни одного site-packages."""
    rep = ph.assess(user_site_dirs=[], env_site_dirs=[])

    assert rep["status"] == "unknown", rep
    assert rep["counts"]["scanned_dirs"] == 0
    line = ph.summary_line(rep)
    assert "НЕ ПРОВЕРЕНО" in line and "✓" not in line, line


def test_shared_easy_install_pth_is_never_removable(tmp_path):
    """fail-closed на РАЗРУШИТЕЛЬНОМ исходе: `easy-install.pth` общий для всех editable-установок
    окружения. Опознать в нём кит — правильно, предложить `rm` — значит снести чужие пакеты."""
    user_site = tmp_path / "user-site"
    user_site.mkdir(parents=True)
    shared = user_site / "easy-install.pth"
    shared.write_text(f"{PKG}\n/somewhere/else/project\n", encoding="utf-8")

    rep = ph.assess(user_site_dirs=[str(user_site)], env_site_dirs=[])
    results = ph.remove_belts(rep)

    assert shared.exists() and results == [], "общий easy-install.pth попал под удаление"
    assert rep["counts"]["blocking"] == 0, rep["findings"]
    found = rep["findings"][0]
    assert found["rule"] == "editable_in_user_site", found
    assert "rm -f" not in found["fix"] and "pip uninstall" in found["fix"], found["fix"]


def test_removal_policy_is_declared_on_the_public_surface():
    """Решение «pip не заберёт, installer не должен, удаляем по явной просьбе» — не деталь кода.

    Если оно живёт только здесь, о нём узнают из теста. Границы кита объявлены в
    `registry/release-claims.yaml -> standing_boundaries` — там же и эта."""
    claims = yaml.safe_load(
        (PKG / "registry" / "release-claims.yaml").read_text(encoding="utf-8"))
    boundaries = claims.get("standing_boundaries") or []

    assert "residual_pth_belt_removed_only_on_explicit_request" in boundaries, (
        "политика удаления остаточного пояса не объявлена в standing_boundaries — "
        f"есть только: {boundaries}")


def test_scan_limits_are_declared(tmp_path):
    """«Чисто» не должно читаться как «чисто на машине»: граница объявлена в самом отчёте."""
    rep = ph.assess(user_site_dirs=[], env_site_dirs=[])

    assert "venv" in rep["scan_limits"], rep["scan_limits"]
    assert ph.summary_line(rep).startswith("пути окружения:")


# ---------------------------------------------------------------- side-effect proof

def test_remove_belts_really_deletes_only_the_belt(tmp_path):
    """side-effect proof: сначала доказываем, что файла НЕТ на диске, потом смотрим на вердикт."""
    user_site = tmp_path / "user-site"
    belt = _write_belt(user_site)
    _write_noise(user_site)
    editable = user_site / "__editable__.ai_ops_kit-3.27.7.pth"
    editable.write_text("import __editable___ai_ops_kit_3_27_7_finder\n", encoding="utf-8")
    neighbours = sorted(p.name for p in user_site.glob("*.pth") if p != belt)

    rep = ph.assess(user_site_dirs=[str(user_site)], env_site_dirs=[])
    results = ph.remove_belts(rep)

    # --- side-effect: пояса на диске нет, соседи целы ---
    assert not belt.exists(), "remove_belts вернул успех, а файл на диске остался"
    assert sorted(p.name for p in user_site.glob("*.pth")) == neighbours, (
        "удалено больше, чем пояс: editable-установку снимает pip, чужие .pth не наши")
    # --- и только теперь вердикт ---
    assert results == [{"path": str(belt), "removed": True, "error": None}], results
    after = ph.assess(user_site_dirs=[str(user_site)], env_site_dirs=[])
    assert after["counts"]["blocking"] == 0, after["findings"]


def test_dry_run_removes_nothing(tmp_path):
    """fail-closed для удаления: dry_run не вправе тронуть диск."""
    user_site = tmp_path / "user-site"
    belt = _write_belt(user_site)

    results = ph.remove_belts(ph.assess(user_site_dirs=[str(user_site)], env_site_dirs=[]),
                              dry_run=True)

    assert belt.exists(), "dry_run удалил файл"
    assert results and results[0]["removed"] is False


# ---------------------------------------------------------------- предмет проверки существует

def test_belt_really_hides_a_defect(tmp_path):
    """Пояс действительно правит чужие процессы — иначе вся проверка выдумана.

    Замер, а не пересказ: один и тот же `import _bootstrap` из постороннего каталога проходит с
    поясом и падает без него. `_bootstrap` — тот самый модуль, на котором пояс замаскировал
    fail-closed-проверку (`test_validator_bootstrap.py`).

    HOME и PYTHONUSERBASE уводятся в tmp: без этого подопытным окружением стал бы настоящий
    пользовательский site, где у разработчика кита пояс может лежать по-настоящему.
    """
    home = tmp_path / "home"
    userbase = tmp_path / "userbase"
    home.mkdir()
    env = {"HOME": str(home), "PYTHONUSERBASE": str(userbase),
           "PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"}

    # Ревизия 2026-08-11: предмет замера — ПОЯС В USER-SITE, а он существует только там, где
    # user-site вообще включён. В venv (`python -m venv`) он выключен по построению
    # (`site.ENABLE_USER_SITE is False`), пояс не срабатывает — и тест краснел на исправном коде.
    # Ложное красное дороже пропуска: оно приучает не смотреть на красное. В CI кит ставится в
    # системный интерпретатор, там проверка исполняется.
    ask = subprocess.run([sys.executable, "-c",
                          "import site; print(site.ENABLE_USER_SITE); print(site.getusersitepackages())"],
                         capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=60)
    assert ask.returncode == 0, ask.stderr
    enabled, _, site_path = ask.stdout.strip().partition("\n")
    if enabled.strip() != "True":
        pytest.skip("user-site выключен у этого интерпретатора (venv) — пояса в нём не бывает, "
                    "замерять нечего")
    user_site = Path(site_path.strip())

    def probe():
        return subprocess.run([sys.executable, "-c", "import _bootstrap; print(_bootstrap.__file__)"],
                              capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=60)

    without = probe()
    assert without.returncode != 0 and "No module named '_bootstrap'" in without.stderr, (
        "без пояса импорт прошёл — окружение теста не изолировано, замер ничего не показывает:\n"
        f"{without.stdout}\n{without.stderr}")

    _write_belt(user_site)
    with_belt = probe()

    assert with_belt.returncode == 0 and str(PKG) in with_belt.stdout, (
        "пояс не изменил поведение чужого процесса — проверка ищет то, чего не бывает:\n"
        f"{with_belt.stdout}\n{with_belt.stderr}")
    # И этот же пояс проверка обязана видеть — тот файл, что реально сработал.
    rep = ph.assess(user_site_dirs=[str(user_site)], env_site_dirs=[])
    assert rep["counts"]["blocking"] == 1, rep["findings"]


# ------------------------------------------------- подсказку можно ВЫПОЛНИТЬ, а не только прочитать

def test_pip_command_for_current_interpreter_is_runnable():
    """positive + side-effect proof: команда для СВОЕГО user-site называет существующий бинарник.

    Прежняя подсказка выводила имя из пути (`…/Python/3.9/…` -> `python3.9`), а на macOS этот
    user-site обслуживает `python3`, и `python3.9` в PATH отсутствует: напечатанную команду нельзя
    было выполнить. Подсказка, которую нельзя выполнить, хуже отсутствующей — пользователь верит,
    что снял установку, а ничего не произошло.

    Проверяем не форму строки, а РАБОТОСПОСОБНОСТЬ: тем же интерпретатором вызываем `pip --version`.
    """
    import site as _site

    cmd = ph.pip_command(_site.getusersitepackages())

    exe = cmd.split(" -m pip")[0].strip('"')
    assert exe == sys.executable, f"названа не текущая программа: {cmd}"
    assert "-m pip uninstall -y ai-ops-kit" in cmd, cmd
    probe = subprocess.run([exe, "-m", "pip", "--version"], capture_output=True, text=True,
                           timeout=120)
    assert probe.returncode == 0, (
        f"подсказка называет неработающую команду: {cmd}\n{probe.stderr[-400:]}")


def test_pip_command_for_foreign_interpreter_admits_the_guess():
    """fail-closed для подсказки: про ЧУЖОЙ интерпретатор имя бинарника угадать нельзя.

    Версию называем (она в пути и это факт), но `python3` молча подставить не вправе: это была бы
    команда снять установку у ДРУГОГО интерпретатора. Значит — сказать прямо, что имя своё."""
    cmd = ph.pip_command("/Users/somebody/Library/Python/3.11/lib/python/site-packages")

    assert cmd.startswith("python3.11 -m pip uninstall -y ai-ops-kit"), cmd
    assert "подставьте свой" in cmd, f"подсказка выдаёт догадку за факт: {cmd}"


def test_pip_command_without_version_in_path_does_not_invent_one(tmp_path):
    """Из пути версия не выводится — не выдумываем: называем каталог, чтобы владельца можно было
    найти самому."""
    cmd = ph.pip_command(tmp_path / "site-packages")

    assert "python3 -m pip" not in cmd, f"подставлен наугад python3: {cmd}"
    assert str(tmp_path) in cmd and "pip uninstall -y ai-ops-kit" in cmd, cmd
