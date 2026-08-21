"""Дочка САМА говорит, что отстала — гейтом с кодом возврата, а не отчётом.

Работа `child-lag-is-a-gate-not-a-hope`. Повод — замер EV-1110: второй по размеру класс находок поля
это «исправление живёт в ките и не доезжает до установленной копии» — 8 из 48 (F-030, F-031, F-032,
F-033, B2-15, B2-19, B2-29, OK-01). F-032 показал форму точнее всего: в дочке лежали ОБЕ версии точки
входа — обновлённый шаблон и старый корневой `./ai-ops`, — и отчёт обновления об этом МОЛЧАЛ.

Не хватало не механизма обновления (он есть) и не миграций (есть с 17.08), а ГЕЙТА: команды, которая
ПАДАЕТ, когда копия отстала. `status` считает то же самое и возвращает 0 при любой разнице версий.

ЧЕТЫРЕ ИСХОДА, И ОНИ РАЗНЫЕ (замерены на настоящих установках 18.08.2026):
  0 — копия актуальна;
  2 — отстала (версия, содержимое или дрейф) — отдельный код, чтобы CI отличал это от поломки гейта;
  1 — «не знаю»: гейт запущен из самой копии, или репозиторий не является установкой.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
INSTALLER = KIT / "installer" / "ai_ops.py"

pytestmark = pytest.mark.unit


def _gate(cwd, *args):
    return subprocess.run([sys.executable, str(INSTALLER), "check-update", *args],
                          cwd=str(cwd), capture_output=True, text=True, timeout=300)


@pytest.fixture(scope="module")
def child(tmp_path_factory):
    """Настоящая установка, как у человека: git-репозиторий + `init` из ЭТОГО дерева кита."""
    root = tmp_path_factory.mktemp("laggate") / "child"
    root.mkdir(parents=True)
    (root / "a.py").write_text("print(1)\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.1"\n',
                                         encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    for a in (["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)
    r = subprocess.run([sys.executable, str(INSTALLER), "init", "."], cwd=str(root),
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"init упал: {r.stdout}\n{r.stderr}"
    return root


@pytest.mark.slow
class TestFourOutcomesOnRealInstalls:
    def test_fresh_install_is_up_to_date(self, child):
        r = _gate(child)
        assert r.returncode == 0, f"свежая установка объявлена отставшей:\n{r.stdout}{r.stderr}"
        assert "актуальна" in r.stdout

    def test_quiet_says_nothing_when_all_is_well(self, child):
        r = _gate(child, "--quiet")
        assert r.returncode == 0
        assert r.stdout.strip() == "", f"тихий режим всё равно шумит: {r.stdout!r}"

    def test_declared_version_ahead_of_reality_is_behind(self, child, tmp_path):
        """Копия и её ОПИСАНИЕ разошлись — ровно то, чего не замечал прежний отчёт."""
        broken = tmp_path / "declared"
        shutil.copytree(child, broken)
        cfg = broken / ".ai-ops.yaml"
        data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
        data["parent"]["installed_version"] = "99.0.0"
        cfg.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        r = _gate(broken)
        assert r.returncode == 2, f"расхождение версий не остановило CI:\n{r.stdout}{r.stderr}"
        assert "99.0.0" in r.stdout, r.stdout

    def test_missing_managed_file_is_behind(self, child, tmp_path):
        """Содержимое разошлось при ТОМ ЖЕ номере версии (класс B2-17): номера совпадают, а файла
        из пакета в копии нет."""
        broken = tmp_path / "content"
        shutil.copytree(child, broken)
        victim = next((broken / ".ai" / "managed" / "rules").rglob("*.md"))
        victim.unlink()
        r = _gate(broken)
        assert r.returncode == 2, f"пропавший файл managed-слоя не остановил CI:\n{r.stdout}"
        assert "содержимое разошлось" in r.stdout, r.stdout

    def test_edited_managed_file_is_behind_and_named_as_drift(self, child, tmp_path):
        """Правка managed-слоя на месте: обновление затрёт её молча, поэтому это тоже «отстала» —
        но с ДРУГОЙ причиной, и причина обязана быть названа."""
        broken = tmp_path / "drift"
        shutil.copytree(child, broken)
        victim = next((broken / ".ai" / "managed" / "rules").rglob("*.md"))
        victim.write_text(victim.read_text(encoding="utf-8") + "\n<!-- правка владельца -->\n",
                          encoding="utf-8")
        r = _gate(broken)
        assert r.returncode == 2, f"правка managed-слоя прошла незамеченной:\n{r.stdout}"
        assert "правили на месте" in r.stdout, r.stdout

    def test_running_from_inside_the_copy_is_unknown_not_ok(self, child, tmp_path):
        """САМАЯ ОПАСНАЯ ФОРМА: гейт, запущенный из самой копии, сравнивал бы её с собой и всегда
        говорил «актуально». Зелёный гейт хуже отсутствующего — поэтому здесь «не знаю» и как узнать."""
        inside = tmp_path / "inside"
        shutil.copytree(child, inside)
        dst = inside / ".ai" / "managed" / "installer"
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy(INSTALLER, dst / "ai_ops.py")
        r = subprocess.run([sys.executable, str(dst / "ai_ops.py"), "check-update"],
                           cwd=str(inside), capture_output=True, text=True, timeout=300)
        assert r.returncode == 1, f"самосравнение выдало вердикт вместо «не знаю»: {r.returncode}"
        assert "запустите гейт из клона кита" in r.stdout.lower(), r.stdout


class TestNonInstallIsNotAFailure:
    def test_repository_without_install_says_so(self, tmp_path):
        """Кит в себя не ставится (рекурсия и вечный дрейф чек-сумм), и `build_diff` там честно
        показывает ВСЕ файлы пакета как неустановленные. Без этой развилки гейт объявлял бы
        «ОТСТАЛА» на репозитории, который отставать не может, — а гейт, краснеющий всегда,
        отключают целиком."""
        r = _gate(tmp_path)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "не установлен" in r.stdout.lower(), r.stdout

    def test_kit_itself_is_not_reported_as_behind(self):
        r = _gate(KIT)
        assert r.returncode != 2, f"кит объявлен отставшей дочкой:\n{r.stdout}"


class TestGateIsWiredIntoChildCI:
    """Гейт, который никто не зовёт, — это отчёт. Проверяется по УСТАНОВЛЕННОМУ workflow."""

    def test_template_calls_the_gate(self):
        tpl = (KIT / "templates" / "ci" / "ai-ops-validate.yml").read_text(encoding="utf-8")
        assert "check-update" in tpl, "CI дочки не зовёт гейт отставания"
        assert "installer/ai_ops.py" in tpl

    @pytest.mark.slow
    def test_installed_workflow_command_runs_on_a_fresh_child(self, child):
        """Берём команду из УСТАНОВЛЕННОГО у дочки workflow и исполняем её — как это сделает CI.
        Клон кита подменяем корнем этого репозитория: проверяем путь и работу гейта, а не `git clone`."""
        wf = (child / ".github" / "workflows" / "ai-ops-validate.yml").read_text(encoding="utf-8")
        steps = yaml.safe_load(wf)["jobs"]["validate"]["steps"]
        cmds = [str(s.get("run", "")) for s in steps if "check-update" in str(s.get("run", ""))]
        assert cmds, "в установленном workflow нет шага с гейтом отставания"
        cmd = cmds[0].strip().replace('"$RUNNER_TEMP"/ai-ops-kit', str(KIT)).replace("python3", sys.executable)
        r = subprocess.run(cmd, shell=True, cwd=str(child), capture_output=True, text=True,
                           timeout=300)
        assert r.returncode == 0, f"шаг CI упал на свежей установке:\n{r.stdout}\n{r.stderr}"

    @pytest.mark.slow
    def test_installed_workflow_command_fails_on_a_lagging_child(self, child, tmp_path):
        """Обратная сторона того же шага: на отставшей копии он обязан КРАСНЕТЬ. Иначе предыдущий
        тест доказывал бы только то, что команда завершается."""
        broken = tmp_path / "lagging"
        shutil.copytree(child, broken)
        victim = next((broken / ".ai" / "managed" / "rules").rglob("*.md"))
        victim.unlink()
        wf = (broken / ".github" / "workflows" / "ai-ops-validate.yml").read_text(encoding="utf-8")
        steps = yaml.safe_load(wf)["jobs"]["validate"]["steps"]
        cmd = next(str(s["run"]).strip() for s in steps if "check-update" in str(s.get("run", "")))
        cmd = cmd.replace('"$RUNNER_TEMP"/ai-ops-kit', str(KIT)).replace("python3", sys.executable)
        r = subprocess.run(cmd, shell=True, cwd=str(broken), capture_output=True, text=True,
                           timeout=300)
        assert r.returncode == 2, f"отставшая копия прошла шаг CI (rc={r.returncode}):\n{r.stdout}"


class TestJsonAnswerIsMachineReadable:
    def test_json_names_verdict_and_reasons(self, tmp_path):
        import json
        r = _gate(tmp_path, "--json")
        rep = json.loads(r.stdout)
        assert rep["kind"] == "lag-report"
        assert rep["verdict"] == "not_installed"
        assert rep["unknown"], "вердикт без основания — это заявление, а не проверка"
