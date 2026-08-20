"""Own Medicine: проверка самоприменения и её РАЗВОДКА.

Три группы, по инженерному циклу репозитория («три теста на capability»):
  * positive     — валидатор даёт исходы по каждому пункту культуры и сходится с замером;
  * fail-closed  — подделать зелёный нельзя: «не применимо» без причины, шаг доставки без решения,
                   правило без резолвящегося основания и НОВЫЙ разрыв — каждый из четырёх краснеет;
  * side-effect  — валидатор ничего не пишет в репозиторий (он проверяет, а не устанавливает).

Плюс РАЗВОДКА: проверка, объявленная в `quality/gates.yaml`, обязана реально исполняться. В этом
репозитории CI не перечисляет команды — джобы гоняют pytest по маркерам (`.github/ci-groups/*.sh`),
и охранник `validate_agents_checklist` следит, чтобы проверки не запускались МИМО pytest. Поэтому
разводка здесь означает: гейт есть в реестре, его `# runnable:` указывает на существующий файл, и
этот файл исполняется тестом ниже — то есть CI-группой `fast`.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PKG = Path(__file__).resolve().parents[2]
VALIDATOR = PKG / "ai_ops_kit" / "validation" / "validate_own_medicine.py"
GATE_ID = "own_medicine"
LESSONS_REL = "rules/core/field-lessons.yaml"

_IGNORE = shutil.ignore_patterns(".venv", "node_modules", "__pycache__", "*.pyc",
                                 ".pytest_cache", ".hypothesis", "htmlcov", "*.egg-info")


def _load():
    """Импортировать валидатор как модуль (он двурежимный — зона-исключение `validation/`)."""
    spec = importlib.util.spec_from_file_location("_own_medicine_under_test", VALIDATOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def om():
    return _load()


@pytest.fixture(scope="module")
def repo_copy(tmp_path_factory):
    """Копия репозитория ВМЕСТЕ с `.git`: без неё `git check-ignore` не ответит, и пункт
    `gitignore` честно уходит в `unknown` — проверять эффект было бы нечем."""
    dst = tmp_path_factory.mktemp("om") / "copy"
    shutil.copytree(PKG, dst, ignore=_IGNORE, symlinks=True)
    return dst


# ─── positive ─────────────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_validator_is_green_on_this_repository():
    """Замер сошёлся: известные разрывы объявлены, новых нет."""
    r = subprocess.run([sys.executable, str(VALIDATOR)], cwd=str(PKG),
                       capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]
    assert "OWN-MEDICINE-OK" in r.stdout


@pytest.mark.unit
def test_every_item_has_one_of_the_honest_outcomes(om):
    rep = om.evaluate(PKG)
    assert rep["items"], "перечень культуры пуст — проверять нечего"
    allowed = {om.APPLIED, om.NOT_APPLICABLE, om.NOT_APPLIED, om.UNKNOWN}
    for it in rep["items"]:
        assert it["outcome"] in allowed, it


@pytest.mark.unit
def test_not_applicable_always_names_a_reason(om):
    """«Не применимо» без причины исходом не является — это записано в докстринге валидатора.

    Проверяются ОБА уровня: собранная строка И объявленная запись в таблице. Только собранной
    строки недостаточно — обёртка «культуру не доставляет: …» непуста даже при пустой записи, и
    мутация с `"pkg_version": ""` проходила мимо этого теста (поймано мутационным ревью).
    """
    rep = om.evaluate(PKG)
    silent = [it["item"] for it in rep["items"]
              if it["outcome"] == om.NOT_APPLICABLE and not it["reason"].strip()]
    assert not silent, f"«не применимо» без причины: {silent}"
    blank = [k for k, v in om.NOT_CULTURE.items() if not str(v).strip()]
    assert not blank, f"в NOT_CULTURE объявлено «не применимо» без причины: {blank}"
    assert not [e for e in rep["errors"] if "БЕЗ причины" in e], rep["errors"]


@pytest.mark.unit
def test_the_gap_is_visible_not_smoothed(om):
    """Смысл проверки — ПОКАЗАТЬ разрыв: ни один не появляется молча, мимо замера.

    ЗДЕСЬ БЫЛО ТРЕБОВАНИЕ НЕПУСТОГО ЗАМЕРА (`assert om.KNOWN_GAPS`), и 19.08.2026 оно стало
    падать: оба известных разрыва закрыли — кит завёл себе `./ai-ops` и получил блок политики
    общения. То есть проверка требовала, чтобы у кита ВСЕГДА оставался долг, и цель этой самой
    проверки — ноль разрывов — краснела как поломка.

    Страх, ради которого требование писалось, назван в его же формулировке: «ноль разрывов
    означал бы, что валидатор перестал их видеть». Но ослепший валидатор ловится не пустым
    замером, а прямой пробой — `test_a_new_gap_reddens_the_ratchet` ниже создаёт НАСТОЯЩИЙ разрыв
    в копии репозитория и требует красного. Непустой замер эту способность не доказывал: он
    доказывал только, что долг ещё есть.
    """
    rep = om.evaluate(PKG)
    gaps = [it["item"] for it in rep["items"] if it["outcome"] == om.NOT_APPLIED]
    assert set(gaps) <= set(om.KNOWN_GAPS), f"разрыв вне замера: {set(gaps) - set(om.KNOWN_GAPS)}"
    for item, reason in om.KNOWN_GAPS.items():
        assert reason.strip(), f"разрыв `{item}` в замере без причины, почему он ещё открыт"


@pytest.mark.unit
def test_the_blindness_check_that_replaced_the_non_empty_baseline_exists():
    """Требование непустого замера снято НЕ молча: его работу делает названная проба.

    Если `test_a_new_gap_reddens_the_ratchet` однажды уедет вместе с рефакторингом, снятие
    требования останется без замены — и валидатор сможет ослепнуть незамеченным.
    """
    src = Path(__file__).read_text(encoding="utf-8")
    assert "def test_a_new_gap_reddens_the_ratchet(" in src, (
        "проба «новый разрыв краснеет» исчезла — верните её или верните требование непустого "
        "замера: без одного из двух ослепший валидатор выглядит как чистый кит")


@pytest.mark.unit
def test_inventory_comes_from_the_delivery_code_not_from_a_hand_list(om):
    """Перечень культуры читается из `installer/ai_ops.py`, а не переписан руками.

    Проверяется тем, что источник ДЕЙСТВИТЕЛЬНО разбирается: ключи `deliver_assets` и вызовы
    `cmd_init` извлечены из AST и непусты, и каждый ключ доставки имеет решение.
    """
    steps = om.delivery_steps(PKG)
    calls = om.init_only_calls(PKG)
    assert steps, "ключи `deliver_assets` не извлечены — источник истины не разобран"
    assert calls, "вызовы `cmd_init` не извлечены — источник истины не разобран"
    assert set(steps) == set(om.DELIVERY_CHECKS), (
        f"расхождение доставки и проверок: {set(steps) ^ set(om.DELIVERY_CHECKS)}")
    assert set(calls) <= (set(om.INIT_CHECKS) | set(om.NOT_CULTURE))


@pytest.mark.unit
def test_scope_limits_are_named(om):
    """Урезанный охват обязан быть НАЗВАН — это одно из правил, которые валидатор же и стережёт."""
    rep = om.evaluate(PKG)
    assert rep["limitations"], "валидатор не называет, чего не покрывает"
    r = subprocess.run([sys.executable, str(VALIDATOR)], cwd=str(PKG),
                       capture_output=True, text=True)
    assert "Охват НАЗВАН" in r.stdout, "ограничения не доезжают до человека в выводе"


# ─── fail-closed ──────────────────────────────────────────────────────────────────────────────

def _run_in(copy, *args):
    return subprocess.run([sys.executable,
                           str(copy / "ai_ops_kit" / "validation" / "validate_own_medicine.py"),
                           *args], cwd=str(copy), capture_output=True, text=True)


@pytest.mark.unit
def test_new_delivery_step_without_a_decision_is_caught(repo_copy, tmp_path):
    """Доставка выросла — проверка обязана заметить, а не молча пропустить новый шаг.

    Это главный страж от дрейфа: без него список культуры разошёлся бы с доставкой при первом же
    изменении `deliver_assets`, а валидатор остался бы зелёным.
    """
    work = tmp_path / "grown"
    shutil.copytree(repo_copy, work, ignore=_IGNORE, symlinks=True)
    inst = work / "installer" / "ai_ops.py"
    text = inst.read_text(encoding="utf-8")
    text = text.replace('"planning_seeded": _seed_planning_contour(root),',
                        '"planning_seeded": _seed_planning_contour(root),\n'
                        '        "brand_new_step": None,', 1)
    inst.write_text(text, encoding="utf-8")
    r = _run_in(work)
    assert r.returncode == 1
    assert "brand_new_step" in r.stdout
    assert "нет" in r.stdout


@pytest.mark.unit
def test_removed_delivery_step_makes_a_stale_check_red(repo_copy, tmp_path):
    """Обратная сторона: шаг ушёл из доставки, а проверка осталась — тоже расхождение.

    Убирается ИМЕННО `planning_seeded` — шаг, которого нет в замере разрывов. Первая версия теста
    убирала `entry_point`, и он краснел по другой причине (пункт из KNOWN_GAPS перестал получать
    исход), то есть страж устаревшей проверки тестом не проверялся вовсе. Поймано мутацией.
    """
    work = tmp_path / "shrunk"
    shutil.copytree(repo_copy, work, ignore=_IGNORE, symlinks=True)
    inst = work / "installer" / "ai_ops.py"
    text = inst.read_text(encoding="utf-8")
    assert "planning_seeded" not in om_known_gaps(), "шаг попал в замер — тест выбирает другой"
    assert '"planning_seeded": _seed_planning_contour(root),' in text
    inst.write_text(text.replace('"planning_seeded": _seed_planning_contour(root),', "", 1),
                    encoding="utf-8")
    r = _run_in(work)
    assert r.returncode == 1
    assert "planning_seeded" in r.stdout
    assert "устарела" in r.stdout


@pytest.mark.unit
def test_a_new_gap_reddens_the_ratchet(repo_copy, tmp_path):
    """НОВЫЙ разрыв обязан краснеть: иначе долг растёт молча, и ратчет — украшение.

    Теста на эту половину ратчета не было: мутация «новый разрыв не краснеет» выживала, потому что
    зелёный на чистом репозитории её не замечает по построению. Разрыв создаётся настоящий —
    убирается обязательный документ контекста, которого дочка от кита требует.
    """
    work = tmp_path / "newgap"
    shutil.copytree(repo_copy, work, ignore=_IGNORE, symlinks=True)
    doc = work / ".ai" / "project" / "context" / "now.md"
    assert doc.is_file(), "исходный репозиторий уже без этого документа — тест выбирает другой"
    doc.unlink()
    r = _run_in(work)
    assert r.returncode == 1
    assert "НОВЫЙ разрыв" in r.stdout
    assert "context_backfilled" in r.stdout


def om_known_gaps():
    return set(_load().KNOWN_GAPS)


@pytest.mark.unit
def test_a_lesson_without_resolvable_grounding_is_caught(repo_copy, tmp_path):
    """Правило без основания — лозунг. Ссылка, которая никуда не ведёт, обязана краснеть."""
    work = tmp_path / "ungrounded"
    shutil.copytree(repo_copy, work, ignore=_IGNORE, symlinks=True)
    p = work / LESSONS_REL
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    data["lessons"][0]["grounding"] = [{"file": "docs/no-such-file.md", "contains": "нет"}]
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    r = _run_in(work)
    assert r.returncode == 1
    assert "несуществующий файл" in r.stdout


@pytest.mark.unit
def test_a_lesson_whose_quote_drifted_is_caught(repo_copy, tmp_path):
    """Основание есть, а цитаты в нём больше нет: правило пережило место, которым обосновано."""
    work = tmp_path / "drifted"
    shutil.copytree(repo_copy, work, ignore=_IGNORE, symlinks=True)
    p = work / LESSONS_REL
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    data["lessons"][0]["grounding"] = [{"file": "AGENTS.md",
                                        "contains": "такой строки в AGENTS.md нет и не было"}]
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    r = _run_in(work)
    assert r.returncode == 1
    assert "цитаты нет" in r.stdout


@pytest.mark.unit
def test_a_closed_gap_left_in_the_baseline_is_caught(repo_copy, tmp_path):
    """Ратчет ходит ТОЛЬКО ВНИЗ: закрытый разрыв обязан быть списан тем же коммитом.

    Иначе замер превращается в вечный список «известных проблем», который никто не сокращает.

    ПЕРЕПИСАН 19.08.2026. Прежде тест закрывал в копии НАСТОЯЩИЙ разрыв `entry_point` и ждал
    красного. Разрыв закрыли по-настоящему, `KNOWN_GAPS` опустел — и тест стал зелёным на пустом
    месте: закрывать было нечего, списывать нечего, красного не было. Тот же класс, что и
    `test_nothing_frozen_is_ever_offered`: проверка, привязанная к сегодняшнему состоянию
    репозитория, умирает от честной работы.

    Теперь тест ставит замер САМ — вписывает в копию разрыв на пункт, который заведомо ВЫПОЛНЕН,
    — и потому не зависит от того, есть ли у кита долг сегодня.
    """
    work = tmp_path / "closed"
    shutil.copytree(repo_copy, work, ignore=_IGNORE, symlinks=True)

    om = _load()
    applied = sorted(it["item"] for it in om.evaluate(PKG)["items"]
                     if it["outcome"] == om.APPLIED)
    assert applied, "нечего объявить закрытым разрывом — валидатор не отдал ни одного APPLIED"
    item = applied[0]

    validator = work / "ai_ops_kit" / "validation" / "validate_own_medicine.py"
    text = validator.read_text(encoding="utf-8")
    assert "KNOWN_GAPS = {" in text
    validator.write_text(
        text.replace("KNOWN_GAPS = {",
                     f'KNOWN_GAPS = {{\n    "{item}": "разрыв, вписанный тестом ратчета",', 1),
        encoding="utf-8")

    r = _run_in(work)
    assert r.returncode == 1, (r.stdout + r.stderr)[-1500:]
    assert "спиши" in r.stdout and item in r.stdout


@pytest.mark.unit
def test_unreadable_installer_is_not_reported_as_applied(repo_copy, tmp_path):
    """Не прочитали доставку -> «проверять нечего», а НЕ «всё применено». `unavailable != 0`."""
    work = tmp_path / "broken"
    shutil.copytree(repo_copy, work, ignore=_IGNORE, symlinks=True)
    (work / "installer" / "ai_ops.py").write_text("def broken(:\n", encoding="utf-8")
    r = _run_in(work)
    assert r.returncode == 1
    assert "OWN-MEDICINE-OK" not in r.stdout


@pytest.mark.unit
def test_missing_git_gives_unknown_not_applied(om, tmp_path):
    """Нет git — пункт `gitignore` НЕ имеет права стать ни «выполнено», ни «не выполнено»."""
    assert om._ignored(tmp_path, ".ai/usage/x.jsonl") is None


@pytest.mark.unit
def test_glob_probe_expands_character_classes(om):
    """Подстановка обязана давать путь, которому шаблон СООТВЕТСТВУЕТ.

    Первая версия строила из `.ai/**/*.py[co]` путь `.ai/x/x.py[co]`, шаблон его не покрывал, и
    валидатор объявлял разрыв там, где его нет, — ложный красный из собственной подстановки.
    """
    import fnmatch
    for pattern in (".ai/**/*.py[co]", ".ai/usage/*.jsonl", ".ai/runtime/backups/",
                    ".ai/reevaluate-evidence-*.json"):
        probe = om._probe_path(pattern)
        assert "[" not in probe and "*" not in probe, f"{pattern} -> {probe}: шаблон не раскрыт"
        tail = pattern.lstrip("/")
        if not pattern.endswith("/"):
            assert fnmatch.fnmatch(probe, tail.replace("**/", "*")), f"{pattern} -> {probe}"


# ─── side-effect proof ────────────────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_validator_does_not_install_anything(repo_copy, tmp_path):
    """Нужна ПРОВЕРКА, а не установка: валидатор не имеет права создать `.ai/managed/`,
    `.ai-ops.yaml`, `./ai-ops` или блок в CLAUDE.md — иначе он «починит» разрыв, вместо того
    чтобы его показать (и заодно заведёт копию кита внутри кита)."""
    work = tmp_path / "untouched"
    shutil.copytree(repo_copy, work, ignore=_IGNORE, symlinks=True)
    before = {p.relative_to(work).as_posix() for p in work.rglob("*") if p.is_file()}
    claude_before = (work / "CLAUDE.md").read_text(encoding="utf-8")
    _run_in(work)
    after = {p.relative_to(work).as_posix() for p in work.rglob("*") if p.is_file()}
    created = {p for p in (after - before) if "__pycache__" not in p and not p.endswith(".pyc")}
    assert not created, f"валидатор создал файлы: {sorted(created)}"
    assert (work / "CLAUDE.md").read_text(encoding="utf-8") == claude_before
    assert not (work / ".ai" / "managed").exists()


# ─── РАЗВОДКА: объявленная проверка исполняется ────────────────────────────────────────────────

@pytest.mark.unit
def test_gate_is_declared_in_the_registry():
    gates = yaml.safe_load((PKG / "quality" / "gates.yaml").read_text(encoding="utf-8"))["gates"]
    assert GATE_ID in gates, "гейт own_medicine не объявлен в quality/gates.yaml"
    g = gates[GATE_ID]
    assert g["id"] == GATE_ID
    # Новое в этом репозитории идёт advisory: сначала полевые доказательства, потом блокировка.
    assert g["blocking"] is False, "новый гейт не имеет права быть блокирующим до обкатки"
    # writer != judge: гейт проверяет репозиторий и не имеет права быть его писателем.
    assert g["review_mode"] == "read-only"
    assert g["validator"] == "validate-own-medicine"


@pytest.mark.unit
def test_gate_points_at_a_runnable_validator():
    """`# runnable:` — единственное место, где сказано, ЧЕМ гейт считается. Указатель обязан вести
    к существующему файлу, иначе гейт объявлен исполняемым и не исполняется."""
    text = (PKG / "quality" / "gates.yaml").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if "validate-own-medicine" in ln)
    assert "# runnable:" in line, "у гейта нет указателя на исполнитель"
    rel = line.split("# runnable:")[1].strip()
    assert (PKG / rel).is_file(), f"исполнитель гейта не найден: {rel}"
    assert (PKG / rel) == VALIDATOR


@pytest.mark.unit
def test_validator_is_covered_by_the_repository_wide_contract():
    """Валидатор обязан попасть в общий рантайм-контракт: иначе он не проверяется снаружи и
    выпадает из CI-групп, которые гоняют pytest целиком."""
    contract = (PKG / "tests" / "unit" / "test_validator_runtime_contract.py").read_text(
        encoding="utf-8")
    assert "validate_own_medicine" in contract


@pytest.mark.unit
def test_field_lessons_are_delivered_to_children():
    """Правило, не попавшее в `managed_set()`, остаётся культурой одного репозитория."""
    spec = importlib.util.spec_from_file_location("_inst_for_delivery_check",
                                                 PKG / "installer" / "ai_ops.py")
    inst = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inst)
    delivered = {rel for _src, rel in inst.managed_set()}
    assert LESSONS_REL in delivered, f"{LESSONS_REL} не доезжает до дочек"


@pytest.mark.unit
def test_every_field_lesson_is_grounded_in_this_repository():
    """Каждое правило поля — со ссылкой на место, где оно было оплачено, и ссылка резолвится."""
    data = yaml.safe_load((PKG / LESSONS_REL).read_text(encoding="utf-8"))
    lessons = data["lessons"]
    assert len(lessons) >= 6, "уроков поля меньше, чем было записано"
    for les in lessons:
        assert les.get("grounding"), f"{les.get('id')}: правило без основания"
        for g in les["grounding"]:
            target = PKG / g["file"]
            assert target.is_file(), f"{les['id']}: нет файла основания {g['file']}"
            assert g["contains"] in target.read_text(encoding="utf-8"), (
                f"{les['id']}: цитата не найдена в {g['file']}")
