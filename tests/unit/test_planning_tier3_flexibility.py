"""Тир 3: репозиторий вправе описать СЕБЯ, а не подстроиться под кит.

Пять дефектов одного корня — кит считал свою карту мира обязательной для чужого продукта:

  1. путь плана и направления был жёстким (`planning/plan.yaml`, `ROADMAP.md` в корне), и
     монорепозиторий, где продукт живёт в `apps/web/`, не мог описать себя ВООБЩЕ: `next` отвечал
     «плана нет» репозиторию, у которого план есть;
  2. дополнить сигналы кита было можно, снять — нельзя: `**/entities/**` в проекте на
     Feature-Sliced Design дал 6 ложных находок из 9 (обкатка niti), и убрать его можно было только
     правкой самого кита;
  3. опечатка в id контура внутри `affects` игнорировалась молча — заявление выглядело сделанным и
     не проверяло ничего;
  4. presenter держал свою копию словарей статусов и аудиторий — реестр перестал быть источником
     истины для собственной политики (проверяется в `test_ui_presenter.py`);
  5. присутствие сигналов считалось обходом дерева НА КАЖДЫЙ контур — до восьми обходов за один
     вызов гейта, а гейт зовут на каждом прогоне.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from ai_ops_kit.planning import contours as C
from ai_ops_kit.planning import delivery_plan as P
from ai_ops_kit.planning import next_work as NW
from ai_ops_kit.planning import roadmap as RM

MODEL = C.load_model()


def _cfg(root: Path, body: str):
    (root / ".ai-ops.yaml").write_text("schema_version: 1\nkind: ai-ops-child-config\n" + body,
                                       encoding="utf-8")


# ── 1. Пути объявляются репозиторием ──────────────────────────────────────────────────────────

@pytest.mark.unit
def test_monorepo_can_say_where_its_plan_lives(tmp_path):
    """План в `apps/web/planning/plan.yaml` — и кит его находит, а не сообщает, что плана нет."""
    _cfg(tmp_path, "product_operating_model:\n  paths:\n"
                   "    plan: apps/web/planning/plan.yaml\n    roadmap: apps/web/ROADMAP.md\n")
    assert P.plan_rel(tmp_path) == "apps/web/planning/plan.yaml"
    assert RM.roadmap_rel(tmp_path) == "apps/web/ROADMAP.md"

    d = tmp_path / "apps" / "web" / "planning"
    d.mkdir(parents=True)
    (d / "plan.yaml").write_text(
        "schema_version: 1\nkind: delivery-plan\n"
        "goals:\n  - {id: g1, title: Цель}\n"
        "work:\n  - {id: w-01, title: Работа, type: engineering, owner_role: engineer, "
        "status: todo, goal: g1}\n", encoding="utf-8")
    plan = P.load(tmp_path)
    assert plan and P.items(plan)[0]["id"] == "w-01", "объявленный план не прочитан"

    # И ответ «что дальше» больше не говорит про несуществующий путь.
    rep = NW.compute(tmp_path)
    assert rep["plan_present"] is True
    assert "planning/plan.yaml" not in (rep.get("gap") or ""), rep.get("gap")


@pytest.mark.unit
def test_default_paths_are_unchanged_without_a_declaration(tmp_path):
    """Положительный контроль: без объявления всё как было — дефолт кита."""
    assert P.plan_rel(tmp_path) == "planning/plan.yaml"
    assert RM.roadmap_rel(tmp_path) == "ROADMAP.md"


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["/etc/passwd", "../соседний-репозиторий/plan.yaml"])
def test_path_outside_the_repository_is_an_error_not_a_default(tmp_path, bad):
    """FAIL-CLOSED: абсолютный путь и выход за корень — ошибка.

    Взять дефолт значило бы читать НЕ ТОТ файл и уверенно отвечать по нему; а абсолютный путь в
    объявлении дочки — ещё и выход за её границы.
    """
    _cfg(tmp_path, f"product_operating_model:\n  paths:\n    plan: {bad}\n")
    with pytest.raises(P.PlanCorrupt):
        P.plan_rel(tmp_path)
    with pytest.raises(C.ConfigInvalid):
        C.declared_path(tmp_path, "plan", "planning/plan.yaml")


# ── 2. Сигнал кита можно СНЯТЬ, а не только дополнить ─────────────────────────────────────────

@pytest.mark.unit
def test_repository_can_remove_a_kit_signal(tmp_path):
    """Обкатка niti: `**/entities/**` — слой интерфейса в FSD, а не модель данных.

    До тира 3 снять чужой сигнал было нельзя ничем, кроме правки кита, — то есть нельзя.
    """
    sig = C.signals_for(MODEL, "data_contracts")
    victim = next((p for p in sig if "*" in p), None)
    assert victim, "у контура данных нет сигналов-шаблонов — тест потерял смысл"

    _cfg(tmp_path, "product_operating_model:\n  contours:\n    data_contracts:\n"
                   f"      change_signals_remove: ['{victim}']\n")
    rules = C.repo_signal_rules(tmp_path)
    after = C.signals_for(MODEL, "data_contracts", C.repo_overrides(tmp_path), rules)
    assert victim not in after, "снятие сигнала не сработало"
    assert len(after) == len(sig) - 1, "снялось больше, чем просили"


@pytest.mark.unit
def test_repository_can_declare_its_list_the_only_one(tmp_path):
    """`change_signals_replace: true` — «моя карта, а не твоя»; догадки кита выключены целиком."""
    _cfg(tmp_path, "product_operating_model:\n  contours:\n    data_contracts:\n"
                   "      change_signals_replace: true\n"
                   "      change_signals: ['db/schema/**']\n")
    got = C.signals_for(MODEL, "data_contracts", C.repo_overrides(tmp_path),
                        C.repo_signal_rules(tmp_path))
    assert got == ["db/schema/**"], got


@pytest.mark.unit
def test_removed_signal_changes_the_verdict_end_to_end(tmp_path):
    """Снятие обязано доезжать до ВЕРДИКТА, а не только до списка паттернов.

    Правка, которая меняет конфигурацию и не меняет ответ, — это не гибкость, а видимость гибкости.
    """
    (tmp_path / "src" / "entities" / "card").mkdir(parents=True)
    (tmp_path / "src" / "entities" / "card" / "ui.tsx").write_text("x\n", encoding="utf-8")
    files = ["src/entities/card/ui.tsx"]

    _cfg(tmp_path, "product_operating_model:\n  contours:\n    data_contracts:\n"
                   "      change_signals: ['**/entities/**']\n")
    before = C.derive_affects(tmp_path, files, MODEL)
    assert before["data_contracts"]["state"] == C.CHANGED

    _cfg(tmp_path, "product_operating_model:\n  contours:\n    data_contracts:\n"
                   "      change_signals: ['**/entities/**']\n"
                   "      change_signals_remove: ['**/entities/**']\n")
    after = C.derive_affects(tmp_path, files, MODEL)
    assert after["data_contracts"]["state"] != C.CHANGED, after["data_contracts"]["reason"]


# ── 3. Опечатка в id контура слышна ───────────────────────────────────────────────────────────

@pytest.mark.unit
def test_typo_in_affects_is_a_major_finding(tmp_path):
    """`data_contract` вместо `data_contracts` выглядит как заполненное поле и не проверяет НИЧЕГО.

    Поэтому major: опечатка создаёт ложную уверенность, а не просто пропуск.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x\n", encoding="utf-8")
    rep = C.reconcile(tmp_path, {"data_contract": True}, ["src/a.py"], MODEL)
    typos = [f for f in rep["findings"] if f["id"] == "unknown_contour_declared"]
    assert typos, "опечатка в id контура проигнорирована молча"
    assert typos[0]["severity"] == "major"
    assert "data_contracts" in typos[0]["detail"], "не подсказано правильное имя"
    assert rep["verdict"] == "inconsistent"

    # Положительный контроль: верное имя такой находки не даёт.
    ok = C.reconcile(tmp_path, {"data_contracts": True}, ["src/a.py"], MODEL)
    assert not [f for f in ok["findings"] if f["id"] == "unknown_contour_declared"]


@pytest.mark.unit
def test_typo_finding_is_declared_in_the_registry():
    """Находка объявлена там, где её считают: реестр модели + список гейта."""
    import yaml
    PKG = Path(__file__).resolve().parents[2]
    model = yaml.safe_load((PKG / "registry" / "product-operating-model.yaml")
                           .read_text(encoding="utf-8"))
    ids = {f["id"] for f in model["consistency"]["findings"]}
    assert "unknown_contour_declared" in ids
    gates = yaml.safe_load((PKG / "quality" / "gates.yaml").read_text(encoding="utf-8"))["gates"]
    assert "unknown_contour_declared" in gates["contour_consistency"]["findings"]


# ── 5. Один обход дерева на вызов ─────────────────────────────────────────────────────────────

@pytest.mark.unit
def test_presence_is_computed_in_one_walk(tmp_path, monkeypatch):
    """До тира 3 обход шёл ПО КОНТУРУ — до восьми за вызов гейта, который зовут каждый прогон.

    Считаем обходы, а не время: время зависит от машины, число обходов — от кода.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x\n", encoding="utf-8")

    walks = {"n": 0}
    real = C._product_dirs

    def counting(root):
        walks["n"] += 1
        return real(root)

    monkeypatch.setattr(C, "_product_dirs", counting)
    C.derive_affects(tmp_path, ["src/a.py"], MODEL, overrides={})
    assert walks["n"] <= 1, f"обходов дерева за один вызов: {walks['n']}"


@pytest.mark.unit
def test_one_walk_gives_the_same_answers_as_before(tmp_path):
    """Оптимизация не имеет права менять ответ: `signals_present` согласована с `_repo_has_signal`."""
    (tmp_path / "supabase" / "migrations").mkdir(parents=True)
    (tmp_path / "supabase" / "migrations" / "0001.sql").write_text("create;", encoding="utf-8")

    pats_by = {cid: C.signals_for(MODEL, cid) for cid in C.contour_ids(MODEL)}
    fast = C.signals_present(tmp_path, pats_by)
    slow = {cid for cid, pats in pats_by.items() if pats and C._repo_has_signal(tmp_path, pats)}
    assert fast == slow, f"быстрый путь расходится с прежним: {fast ^ slow}"


@pytest.mark.slow
@pytest.mark.unit
def test_gate_stays_fast_on_a_monorepo(tmp_path_factory):
    """Стоимость вызова гейта не должна быть линейна по размеру вендора (обкатка niti: 12 с)."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from realistic import build_realistic_repo

    repo = build_realistic_repo(tmp_path_factory.mktemp("mono3") / "repo")
    t0 = time.time()
    for _ in range(3):
        C.derive_affects(repo, ["apps/web/src/pages/p1.tsx"], MODEL, overrides={})
    dt = (time.time() - t0) / 3
    assert dt < 1.0, f"{dt:.2f} c на вызов"
