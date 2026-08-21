"""Кит не говорит «можно ставить задачу», пока в конфиге стоит его собственная заготовка (B2-25).

ЗАМЕР 19.08.2026 (наблюдение второй дочки, третий прогон на brownfield). В живом продукте с 14.08 в
`.ai-ops.yaml` стоял `project.name: <project-name>` — заготовка, которую УСТАНОВКА ПРОСИТ заменить.
`doctor` возвращал 0 и печатал «Всё в порядке. Дальше: можно ставить задачу»; ни один валидатор
этого не требовал. Кит просит человека отредактировать файл и не проверяет, сделано ли это, — то
самое «правило без исполнения — пожелание», которого он требует от других.

ЧТО ПРОВЕРЯЕТСЯ И ЧТО НЕТ. Заготовка отличается от настоящего значения ровно тем, что кит её и
написал: `<...>`. Осмысленность имени не проверяется и проверяться не может — это была бы догадка
о продукте. Проверяется одно: значение больше не равно тому, что положил установщик.

ЧЕГО ПРАВКА НАМЕРЕННО НЕ ДЕЛАЕТ: код возврата `doctor` не меняется. Превратить заготовку в
«работать нельзя» — решение владельца о пороге, а не следствие этой работы; здесь закрывается
ровно названное в заголовке — кит перестаёт ГОВОРИТЬ, что можно ставить задачу.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

KIT = Path(__file__).resolve().parents[2]
INSTALLER = KIT / "installer" / "ai_ops.py"

from ai_ops_kit.validation import validate_child_config_filled as cfgfill

pytestmark = pytest.mark.unit


def _write(root: Path, doc):
    (root / ".ai-ops.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
                                       encoding="utf-8")


# ─────────────────────── что считается заготовкой ───────────────────────

def test_placeholder_left_by_the_installer_is_found(tmp_path):
    _write(tmp_path, {"project": {"name": "<project-name>", "documentation_language": "ru"}})
    r = cfgfill.assess(tmp_path)
    assert [f["field"] for f in r["placeholders"]] == ["project.name"], r
    assert cfgfill.main([str(tmp_path)]) == 1


def test_filled_config_is_clean(tmp_path):
    """Контроль: заполненный конфиг не краснеет — иначе проверку научатся не читать."""
    _write(tmp_path, {"project": {"name": "Больше не буду меньше", "documentation_language": "ru"}})
    assert cfgfill.assess(tmp_path)["placeholders"] == []
    assert cfgfill.main([str(tmp_path)]) == 0


def test_angle_brackets_inside_prose_are_not_a_placeholder(tmp_path):
    """Контроль границы: матчится ЗНАЧЕНИЕ ЦЕЛИКОМ, а не подстрока.

    Строка «работает с <legacy> API» — это описание, а не незаполненное поле. Проверка, краснеющая
    на описаниях, обесценивается ровно так же, как гейт, срабатывающий всегда."""
    _write(tmp_path, {"project": {"name": "Демо", "note": "работает с <legacy> API"}})
    assert cfgfill.assess(tmp_path)["placeholders"] == []


def test_no_config_is_not_a_finding(tmp_path):
    """Контроль: репозиторий без кита — проверять нечего, и это не «есть заготовки»."""
    r = cfgfill.assess(tmp_path)
    assert r["config_exists"] is False and r["placeholders"] == []
    assert cfgfill.main([str(tmp_path)]) == 0


def test_unreadable_config_is_not_reported_as_clean(tmp_path):
    """«Не прочитал» и «заготовок нет» — разные вещи; вторая была бы молчанием."""
    (tmp_path / ".ai-ops.yaml").write_text("project: [unclosed\n", encoding="utf-8")
    r = cfgfill.assess(tmp_path)
    assert r["readable"] is False and "НЕ" in r["reason"].upper()
    assert cfgfill.main([str(tmp_path)]) == 1
    assert "✗" in cfgfill.summary_line(tmp_path)


def test_summary_line_marks_the_gap(tmp_path):
    """Разметку ставит тот, кто печатает: вердикт `doctor` следует за ней."""
    _write(tmp_path, {"project": {"name": "<project-name>"}})
    assert "✗" in cfgfill.summary_line(tmp_path)
    _write(tmp_path, {"project": {"name": "Демо"}})
    assert "✓" in cfgfill.summary_line(tmp_path)


# ─────────────────────── шов: настоящая установка и настоящий doctor ───────────────────────

def _make_child_repo(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0.1"\n',
                                         encoding="utf-8")
    for c in (["init", "-q", "."], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["add", "-A"], ["commit", "-qm", "init"]):
        subprocess.run(["git", "-C", str(root), *c], capture_output=True, text=True)
    return root


def _isolated_env(tmp: Path):
    """Те же три шага изоляции, что у тестов инсталлятора: без них `doctor` мерил бы чистоту
    ноутбука (остаточный `.pth`-пояс кита в пользовательском site)."""
    home, deps = tmp / "home", tmp / "deps"
    home.mkdir(parents=True, exist_ok=True)
    deps.mkdir(parents=True, exist_ok=True)
    src = Path(yaml.__file__).resolve().parent
    dst = deps / src.name
    if not dst.exists():
        try:
            os.symlink(src, dst, target_is_directory=True)
        except (OSError, NotImplementedError):
            shutil.copytree(src, dst)
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PYTHONUSERBASE"] = str(home / "userbase")
    env["PYTHONPATH"] = str(deps)
    return env


def _cli(root: Path, *args, env=None):
    return subprocess.run([sys.executable, str(INSTALLER), *args], cwd=str(root),
                          capture_output=True, text=True, timeout=300, env=env)


@pytest.mark.critical_path
def test_doctor_on_a_real_install_does_not_greenlight_a_placeholder(tmp_path):
    """ШОВ, ровно поле: настоящая установка -> `doctor` НЕ говорит «можно ставить задачу», пока в
    конфиге стоит заготовка; после замены имени — говорит.

    До правки здесь печаталось «Всё в порядке. Дальше: можно ставить задачу» ПРИ
    `project.name: <project-name>` в файле, который установка сама и положила."""
    env = _isolated_env(tmp_path)
    child = _make_child_repo(tmp_path / "child")
    assert _cli(child, "init", ".", env=env).returncode == 0

    cfg = child / ".ai-ops.yaml"
    doc = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert str((doc.get("project") or {}).get("name", "")).startswith("<"), (
        "проба не дошла до дефекта: установка больше не оставляет заготовку имени — "
        "тогда предмет теста другой")

    before = _cli(child, "doctor", env=env)
    assert "конфиг дочки" in before.stdout, before.stdout
    assert "можно ставить задачу" not in before.stdout, (
        f"кит зовёт ставить задачу при своей же незаполненной заготовке:\n{before.stdout}")

    doc["project"]["name"] = "Демо-продукт"
    cfg.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    after = _cli(child, "doctor", env=env)
    assert "конфиг дочки: ✓" in after.stdout, after.stdout
