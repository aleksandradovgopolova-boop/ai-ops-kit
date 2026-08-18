"""Выпуск проверяется механизмом, а не памятью.

Работа `release-has-a-gate`. Повод — замер EV-1112: 236 версий за 40 календарных дней и НИ ОДНОГО
механизма, проверяющего выпуск; `CHANGELOG.md` правлен 401 раз — в 4.5 раза больше любого файла кода.
Находок поля этот класс не дал ни одной: механизма не было вовсе.

ТРИ ВОРОТ, И КАЖДЫЕ ЗАКРЫВАЮТ СВОЮ ДЫРУ:
  1. запись для CHANGELOG добавлена в этой ветке (`towncrier check` — единственный из шести
     рассмотренных инструментов с таким гейтом, EV-1137);
  2. формат новых коммитов (`cz check` от точки включения — только новые, решение владельца
     17.08.2026: в истории 72 коммита без conventional-префикса из 594);
  3. выпуск БЕЗ раздела CHANGELOG для своей версии отказывается — раньше он выходил «с краткими
     записками», то есть с пустой историей, и никто об этом не узнавал.

Согласованность версии (VERSION ↔ manifest ↔ release-claims) НЕ дублируется здесь: замер 18.08.2026
показал, что её уже проверяют `validate_ai_first_registry` (п. 7) и `validate_release_claims` (п. 1).
Второй механизм на то же место был бы второй правдой.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]


def _toml_table(text, table):
    """Значения одной таблицы pyproject без `tomllib`.

    ПОЧЕМУ НЕ `tomllib`: он в stdlib только с 3.11, а объявленный пол репозитория — 3.9, и это ловит
    собственная проверка `validate_python_compat`. Локально (3.11) тест был зелёным, CI на 3.9 упал
    `ModuleNotFoundError` — тот же класс «локально зелено, в CI красно», из-за которого версии
    инструментов здесь пинуются. Значения таблицы простые (строка/число), поэтому разбор строкой
    честнее новой зависимости."""
    body = text.split(f"[{table}]", 1)[1].split("\n[", 1)[0]
    out = {}
    for line in body.splitlines():
        m = re.match(r'\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$', line)
        if not m or line.lstrip().startswith("#"):
            continue
        raw = m.group(2)
        out[m.group(1)] = int(raw) if raw.isdigit() else raw.strip('"\'')
    return out


GATES = _toml_table((KIT / "pyproject.toml").read_text(encoding="utf-8"), "tool.ai_ops.release_gates")

pytestmark = pytest.mark.unit


def _lint_steps():
    wf = yaml.safe_load((KIT / ".github" / "workflows" / "package-quality.yml").read_text(encoding="utf-8"))
    return wf["jobs"]["lint"]["steps"]


class TestGatesAreWiredWhereTheyAreEnforced:
    def test_gates_live_in_an_already_required_job(self):
        """Новая джоба не попадает в обязательные статусы защиты ветки без действия владельца — то
        есть гейт исполнялся бы «по желанию». Поэтому шаги стоят в уже обязательной `lint`."""
        runs = " ".join(str(s.get("run", "")) for s in _lint_steps())
        assert "towncrier check" in runs, "гейт записи для CHANGELOG не вызывается в обязательной джобе"
        assert "cz check" in runs, "гейт формата коммитов не вызывается в обязательной джобе"

    def test_versions_of_tools_are_pinned(self):
        """Тот же урок, что с ruff (12.08.2026): непинованный инструмент — это два разных инструмента
        локально и в CI, и «локально чисто / в CI красное»."""
        installs = [str(s.get("run", "")) for s in _lint_steps() if "pip install" in str(s.get("run", ""))]
        joined = " ".join(installs)
        assert "towncrier==" in joined and "commitizen==" in joined, joined

    def test_full_history_is_fetched_for_the_comparison(self):
        """`towncrier check --compare-with origin/main` на shallow-клоне не найдёт базу и молча не
        увидит diff — гейт стал бы зелёным всегда."""
        wf = yaml.safe_load((KIT / ".github" / "workflows" / "package-quality.yml").read_text(encoding="utf-8"))
        checkout = next(s for s in wf["jobs"]["lint"]["steps"] if "checkout" in str(s.get("uses", "")))
        assert str(checkout.get("with", {}).get("fetch-depth")) == "0", checkout

    def test_empty_range_is_tolerated_by_measured_code(self):
        """`cz check` на пустом диапазоне отдаёт 3 («No commit found with range») — ЗАМЕРЕНО. Это
        «проверять нечего», а не нарушение: гейт, краснеющий на пустоте, отключают целиком."""
        assert GATES["commit_format_empty_range_code"] == 3
        step = next(str(s["run"]) for s in _lint_steps() if "cz check" in str(s.get("run", "")))
        assert "-eq 3" in step, "код пустого диапазона не обработан — джоба будет краснеть на пустоте"

    def test_switch_on_point_is_a_real_commit(self):
        """Точка включения — не строка «на глаз»: SHA обязан существовать в истории, иначе гейт
        сравнивает с ничем.

        ПРОПУСК, А НЕ ЗЕЛЁНОЕ, БЕЗ ИСТОРИИ: прогон мутационных проб копирует дерево БЕЗ `.git`
        (`devtools/mutation_probe.py -> SKIP`), и там проверить SHA нечем. Первая версия этого теста
        падала именно там и сделала базовый прогон проб красным — то есть две пробы остались
        НЕПРОВЕРЕННЫМИ. Честный пропуск с причиной лучше и красноты не по делу, и тихого успеха."""
        if not (KIT / ".git").exists():
            pytest.skip("нет истории git (копия дерева) — точку включения здесь проверить нечем")
        sha = GATES["commit_format_enforced_after"]
        r = subprocess.run(["git", "-C", str(KIT), "cat-file", "-e", f"{sha}^{{commit}}"],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"точка включения {sha} не существует в истории"

    def test_switch_on_point_is_read_from_config_not_hardcoded(self):
        """Точку включения читают ДВА потребителя (CI и этот тест). Если она вписана в workflow
        строкой, второй потребитель её не видит, и они разъезжаются молча."""
        step = next(str(s["run"]) for s in _lint_steps() if "cz check" in str(s.get("run", "")))
        assert "pyproject.toml" in step and "release_gates" in step, step
        assert GATES["commit_format_enforced_after"] not in step, \
            "SHA вписан в workflow — конфиг перестал быть единственным источником"


class TestChangelogFragmentsAreConfigured:
    def test_fragment_types_include_service_changes(self):
        """Гейт строгий (решение владельца), поэтому у служебных изменений — плана, истории, реестра
        решений — обязан быть свой тип. Иначе строгий гейт заставляет придумывать «новость» там, где
        её нет, и его начинают обходать."""
        text = (KIT / "pyproject.toml").read_text(encoding="utf-8")
        dirs = set(re.findall(r'\[\[tool\.towncrier\.type\]\]\s*\ndirectory = "([^"]+)"', text))
        assert {"feat", "fix", "quality", "chore"} <= dirs, dirs

    def test_fragments_directory_exists_with_instructions(self):
        d = KIT / GATES["changelog_fragments_dir"]
        assert d.is_dir(), "каталога фрагментов нет — гейт не с чем сравнивать"
        assert (d / "README.md").is_file(), \
            "нет объяснения, как называть фрагмент: гейт, требующий угадать формат, обходят"

    def test_towncrier_build_is_never_called_in_ci(self):
        """Ретро-миграция 364 КБ истории не нужна и не делается: старый CHANGELOG.md остаётся как
        есть. `build` перезаписал бы его — поэтому в CI его нет нигде."""
        for wf in (KIT / ".github" / "workflows").glob("*.yml"):
            text = wf.read_text(encoding="utf-8")
            assert "towncrier build" not in text, f"{wf.name}: вызов towncrier build перезапишет CHANGELOG"


@pytest.mark.slow
class TestGatesActuallyFailAndPass:
    """Поведение, а не объявление: оба гейта проверяются в ОБОИХ состояниях."""

    def _repo_with_gates(self, tmp_path):
        root = tmp_path / "repo"
        root.mkdir()
        shutil.copy(KIT / "pyproject.toml", root / "pyproject.toml")
        (root / "CHANGELOG.md").write_text("# CHANGELOG\n\n## [0.1.0] — 2026-01-01\n\nначало\n",
                                           encoding="utf-8")
        (root / "newsfragments").mkdir()
        (root / "a.txt").write_text("x\n", encoding="utf-8")
        for a in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"],
                  ["config", "user.name", "t"], ["add", "-A"], ["commit", "-qm", "chore: init"]):
            subprocess.run(["git", *a], cwd=root, capture_output=True, check=False)
        # база для сравнения: towncrier сравнивает с ветвью, а не с рабочим деревом
        subprocess.run(["git", "branch", "base"], cwd=root, capture_output=True)
        return root

    def _towncrier(self, root, *args):
        exe = shutil.which("towncrier", path=str(Path(sys.executable).parent))
        if not exe:
            pytest.skip("towncrier не установлен в этом окружении — гейт проверяется в CI")
        return subprocess.run([exe, "check", "--compare-with", "base", *args],
                              cwd=root, capture_output=True, text=True, timeout=120)

    def test_branch_without_fragment_fails(self, tmp_path):
        root = self._repo_with_gates(tmp_path)
        (root / "a.txt").write_text("изменено без записи\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "fix: правка без записи"], cwd=root, capture_output=True)
        r = self._towncrier(root)
        assert r.returncode != 0, f"ветка без записи прошла гейт:\n{r.stdout}{r.stderr}"
        assert "newsfragment" in (r.stdout + r.stderr).lower()

    def test_branch_with_fragment_passes(self, tmp_path):
        """КОНТРОЛЬ: та же ветка с записью проходит. Без этой половины первый тест доказывал бы лишь
        то, что инструмент умеет краснеть."""
        root = self._repo_with_gates(tmp_path)
        (root / "a.txt").write_text("изменено с записью\n", encoding="utf-8")
        (root / "newsfragments" / "something.fix.md").write_text("правка описана\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "fix: правка с записью"], cwd=root, capture_output=True)
        r = self._towncrier(root)
        assert r.returncode == 0, f"ветка с записью не прошла гейт:\n{r.stdout}{r.stderr}"


class TestReleaseRefusesWithoutChangelogSection:
    """Третьи ворота — на самом выпуске. Логика извлекается ИЗ workflow и исполняется, а не
    пересказывается: пересказ проверял бы мои слова, а не то, что поедет в CI."""

    def _release_snippet(self):
        wf = yaml.safe_load((KIT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))
        step = next(s for s in wf["jobs"]["release"]["steps"]
                    if "CHANGELOG" in str(s.get("name", "")) and s.get("run"))
        body = str(step["run"])
        # отрезаем всё после подготовки записок: `gh release create` в тесте не зовём
        cut = body.index("PRERELEASE=")
        return body[:cut]

    def _run(self, tmp_path, changelog, version):
        script = self._release_snippet()
        script = script.replace('VERSION="${{ steps.check_release.outputs.version }}"',
                                f'VERSION="{version}"')
        script = script.replace('TAG="${{ steps.check_release.outputs.tag }}"', f'TAG="v{version}"')
        script = script.replace("/tmp/notes.md", str(tmp_path / "notes.md"))
        (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
        return subprocess.run(["bash", "-e", "-c", script], cwd=tmp_path,
                              capture_output=True, text=True, timeout=60)

    def test_missing_section_refuses_with_a_named_reason(self, tmp_path):
        r = self._run(tmp_path, "# CHANGELOG\n\n## [1.0.0] — 2026-01-01\n\nстарое\n", "9.9.9")
        assert r.returncode != 0, "выпуск без раздела CHANGELOG прошёл — как это было до 18.08.2026"
        out = r.stdout + r.stderr
        assert "нет раздела" in out and "9.9.9" in out, out
        assert "перезапустите" in out, f"отказ без выхода — это тупик: {out}"

    def test_present_section_is_used_as_notes(self, tmp_path):
        """КОНТРОЛЬ: раздел есть — выпуск идёт, и записки берутся из него."""
        r = self._run(tmp_path, "# CHANGELOG\n\n## [9.9.9] — 2026-08-18\n\nчто изменилось\n\n"
                                "## [1.0.0] — 2026-01-01\n\nстарое\n", "9.9.9")
        assert r.returncode == 0, r.stdout + r.stderr
        notes = (tmp_path / "notes.md").read_text(encoding="utf-8")
        assert "что изменилось" in notes and "старое" not in notes, notes

    def test_the_release_step_is_actually_wired(self):
        """ШОВ: ворота на выпуске существуют, только если шаг ВЫЗЫВАЕТСЯ. Проверку потребовал сам кит
        (`validate_mutation_probes`: «есть охранные пробы, но НЕТ пробы шва»), и он прав — снятие
        условия шага не поймал бы ни один тест выше."""
        wf = yaml.safe_load((KIT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))
        job = wf["jobs"]["release"]
        step = next(s for s in job["steps"]
                    if "CHANGELOG" in str(s.get("name", "")) and s.get("run"))
        assert str(step.get("if")) == "steps.check_release.outputs.needed == 'true'", \
            f"шаг выпуска перестал быть условным на своей проверке: {step.get('if')!r}"
        # `on` в YAML разбирается как True (ключ-булево) — берём оба варианта ключа
        trig = wf.get("on") or wf.get(True) or {}
        assert "workflow_run" in trig, "выпуск больше не привязан к успешному прогону проверок"
        assert "package-quality" in str(trig["workflow_run"].get("workflows")), trig["workflow_run"]

    def test_the_old_shrug_is_gone(self):
        """Проверяем ИСПОЛНЯЕМЫЕ строки, а не текст файла: первая версия этого теста поймала мой же
        комментарий, который цитирует прежнюю формулировку, — то есть проверяла слова, а не код."""
        text = (KIT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        code = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
        assert "AI Ops Kit $TAG\" > " not in code, \
            "прежнее поведение вернулось: пустые записки вместо отказа"
        assert "записки будут краткими" not in code, \
            "прежнее поведение вернулось: выпуск снова выходит с пустой историей"
