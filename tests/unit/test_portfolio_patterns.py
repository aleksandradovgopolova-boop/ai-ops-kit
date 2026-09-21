"""Гранулярные тесты portfolio_patterns (T5, направление portfolio-intelligence).

Ядро направления — ГРАНИЦА ОБЕЗЛИЧИВАНИЯ: повторяющиеся классы отказов дочек поднимаются наверх
ТОЛЬКО как паттерны и числа + обезличенный ключ дочки, без кода, путей, коммитов, имён и вывода
команд. Тесты поведенческие: импортируют продукт и зовут его на настоящих наблюдениях канала.

Главные доказательства:
  * BOUNDARY — наблюдение с `child.path`/`child.commit`/сырым выводом даёт запись, где НЕТ ни одной
    из этих сырых строк (проверяется по точному вхождению), только анон-ключ + класс + счётчики;
  * MUTATION — если идентификацию впрыснуть в портфельную запись, сторож ОБЯЗАН покраснеть (кусается);
  * честные РАЗНЫЕ пустые состояния «нет дочек» vs «дочки есть, отказов нет».
"""
from __future__ import annotations

import json

import yaml

from ai_ops_kit.engops import kit_feedback
from ai_ops_kit.intelligence import portfolio_patterns as pp

# Точные сырые строки, которых в портфельном виде быть НЕ ДОЛЖНО ни при каких условиях.
_RAW_PATH = "/Users/sasad/private-products/bnbm"
_RAW_COMMIT = "a5be32fcdead"
_RAW_OUTPUT = "Traceback (most recent call last):\n  File secret.py line 1\n    boom"
_RAW_NAME = "bnbm"


def _write_obs(kit_root, oid, *, cls="defect", state="delivered",
               name=_RAW_NAME, path=_RAW_PATH, commit=_RAW_COMMIT, with_output=False):
    d = kit_root / kit_feedback.KIT_DIR
    d.mkdir(parents=True, exist_ok=True)
    evidence = [{"kind": "note", "text": "e"}]
    if with_output:
        evidence = [{"kind": "command", "command": "pytest", "output": _RAW_OUTPUT}]
    doc = {"schema_version": 1, "kind": "KitObservation", "id": oid,
           "at": "2026-09-21T00:00:00+00:00", "statement": f"наблюдение {oid}",
           "observation_class": cls, "severity": "p1", "state": state,
           "child": {"name": name, "path": path, "commit": commit},
           "evidence": evidence}
    (d / f"{oid}.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")


def _register_child(kit_root, cid="proj-0000000000000001"):
    from ai_ops_kit.engops import child_registry
    d = kit_root / child_registry.KIT_DIR
    d.mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": 1, "kind": "ChildRegistration", "id": cid,
           "project": "some-child", "kit_version": "4.3.2", "registered_at": "2026-09-21"}
    (d / f"{cid}.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")


# ── Позитив: агрегация классов со счётчиками ──────────────────────────────────────────────────────

def test_portfolio_aggregates_classes_with_counts(tmp_path):
    """Пара наблюдений одного класса от разных дочек → одна запись с case_count и child_count."""
    _write_obs(tmp_path, "o1", cls="defect", path="/m/a", name="a", commit="aaaaaaa")
    _write_obs(tmp_path, "o2", cls="defect", path="/m/b", name="b", commit="bbbbbbb")
    _write_obs(tmp_path, "o3", cls="friction", path="/m/a", name="a", commit="aaaaaaa")
    view = pp.portfolio_patterns(tmp_path)
    assert view["observation_count"] == 3
    by_cls = {p["observation_class"]: p for p in view["patterns"]}
    assert by_cls["defect"]["case_count"] == 2
    assert by_cls["defect"]["child_count"] == 2      # две РАЗНЫЕ дочки
    assert by_cls["friction"]["case_count"] == 1
    # Порядок: самое частое сверху.
    assert view["patterns"][0]["observation_class"] == "defect"


def test_frequency_label_reused_from_precedent_ledger(tmp_path):
    """Метка частоты берётся у precedent_ledger (2..4 → few-cases), не изобретается заново."""
    _write_obs(tmp_path, "o1", path="/m/a", name="a", commit="aaaaaaa")
    _write_obs(tmp_path, "o2", path="/m/b", name="b", commit="bbbbbbb")
    p = pp.portfolio_patterns(tmp_path)["patterns"][0]
    assert p["confidence"] == "few-cases"
    assert p["frequency_label"] == "несколько случаев"


# ── BOUNDARY: ни одной сырой идентифицирующей строки в виде ───────────────────────────────────────

def test_boundary_no_raw_identifiers_in_portfolio(tmp_path):
    """Наблюдение несёт path/commit/имя/вывод — в портфельном виде их НЕТ ни одной (точное вхождение)."""
    _write_obs(tmp_path, "o1", with_output=True)     # path/commit/name + сырой многострочный вывод
    view = pp.portfolio_patterns(tmp_path)
    blob = json.dumps(view, ensure_ascii=False)
    for raw in (_RAW_PATH, _RAW_COMMIT, _RAW_NAME, _RAW_OUTPUT, "Traceback"):
        assert raw not in blob, f"сырое идентифицирующее значение протекло в вид: {raw!r}"
    rec = view["patterns"][0]
    # Осталось только: класс + счётчики + обезличенные ключи.
    assert rec["observation_class"] == "defect"
    assert rec["case_count"] == 1
    for key in rec["children"]:
        assert pp._ANON_KEY_RE.match(key), f"ключ дочки не обезличен: {key!r}"
    # Собственный сторож на чистом виде молчит.
    assert pp.check_anonymized(view) == []
    assert pp.is_anonymized(view) is True


# ── MUTATION: сторож обязан кусаться на впрыснутой идентификации ───────────────────────────────────

def _clean_view(tmp_path):
    _write_obs(tmp_path, "o1", path="/m/a", name="a", commit="aaaaaaa")
    return pp.portfolio_patterns(tmp_path)


def test_guard_bites_on_injected_path(tmp_path):
    """Впрыснут абсолютный путь в запись → сторож краснеет (иначе граница ничего не значит)."""
    view = _clean_view(tmp_path)
    assert pp.check_anonymized(view) == []            # до мутации чисто
    view["patterns"][0]["leaked"] = "/Users/sasad/private/bnbm"
    violations = pp.check_anonymized(view)
    assert violations, "сторож НЕ заметил путь — DoD не выполнен"
    assert any("путь" in v for v in violations)
    assert pp.is_anonymized(view) is False


def test_guard_bites_on_injected_git_sha(tmp_path):
    """Впрыснут git-sha-подобный hex в НЕзапрещённое по имени поле → ловится по форме значения."""
    view = _clean_view(tmp_path)
    view["patterns"][0]["ref"] = "a5be32fcdead1234"   # 16 hex, форма коммита
    violations = pp.check_anonymized(view)
    assert any("git-sha" in v for v in violations), violations


def test_guard_bites_on_multiline_command_output(tmp_path):
    """Впрыснут многострочный текст (сырой вывод команды) → сторож краснеет."""
    view = _clean_view(tmp_path)
    view["patterns"][0]["dump"] = "line1\nline2\nline3"
    assert any("вывод" in v or "многостроч" in v for v in pp.check_anonymized(view))


def test_guard_bites_on_forbidden_key_name(tmp_path):
    """Запрещённое имя поля (`path`/`commit`/`name`) в записи ловится структурно, даже с пустым/чистым значением."""
    view = _clean_view(tmp_path)
    view["patterns"][0]["commit"] = ""                # значение чистое, но само поле недопустимо
    assert any("запрещённое" in v for v in pp.check_anonymized(view))


def test_guard_bites_on_raw_child_name_in_children(tmp_path):
    """Сырое имя дочки в `children` (форму-детекторы его не ловят) отвергается позитивной проверкой."""
    view = _clean_view(tmp_path)
    view["patterns"][0]["children"] = ["bnbm"]        # не proj-<hex>
    violations = pp.check_anonymized(view)
    assert any("не обезличенный ключ" in v for v in violations), violations


# ── УТЕЧКА ЧЕРЕЗ observation_class — свободный текст дочки в поле класса ────────────────────────────

def test_identifying_observation_class_is_normalized_at_source(tmp_path):
    """Дочка кладёт в класс СВОБОДНЫЙ ТЕКСТ (имя/почта) — он НЕ всплывает: класс схлопнут в обобщённый.

    Канал load_findings не проверяет enum, поэтому класс мог протащить идентификацию дословно. После
    нормализации у источника в виде остаётся только обобщённый класс, ни одной сырой строки, сторож молчит."""
    _write_obs(tmp_path, "o1", cls="reported-by-sasha@rox.one", path="/m/a", name="a", commit="aaaaaaa")
    _write_obs(tmp_path, "o2", cls="bnbm-prod-secret", path="/m/b", name="b", commit="bbbbbbb")
    view = pp.portfolio_patterns(tmp_path)
    blob = json.dumps(view, ensure_ascii=False)
    for raw in ("reported-by-sasha@rox.one", "bnbm-prod-secret", "sasha@rox.one"):
        assert raw not in blob, f"свободный текст класса протёк в вид: {raw!r}"
    # Оба схлопнулись в обобщённый класс.
    assert all(p["observation_class"] == pp._FALLBACK_CLASS for p in view["patterns"])
    assert pp.check_anonymized(view) == []            # сторож чист на нормализованном виде


def test_guard_bites_on_injected_identifying_class(tmp_path):
    """Впрыснут идентифицирующий класс/метка в запись (мимо нормализации) → сторож краснеет (зубы)."""
    view = _clean_view(tmp_path)
    assert pp.check_anonymized(view) == []
    view["patterns"][0]["observation_class"] = "child-bnbm@host"      # вне enum
    v1 = pp.check_anonymized(view)
    assert any("класс вне допустимого набора" in v for v in v1), v1
    view2 = _clean_view(tmp_path)
    view2["patterns"][0]["class_label"] = "проект sasha/private-repo"  # метка вне набора
    v2 = pp.check_anonymized(view2)
    assert any("метка вне допустимого набора" in v for v in v2), v2


def test_known_classes_and_labels_pass_guard(tmp_path):
    """Легальные enum-классы и их метки НЕ ложно-срабатывают (иначе сторож бесполезен)."""
    for c in ("defect", "friction", "question", "idea"):
        _write_obs(tmp_path, f"o-{c}", cls=c, path=f"/m/{c}", name=c, commit="c" * 7)
    view = pp.portfolio_patterns(tmp_path)
    assert pp.check_anonymized(view) == []
    assert {p["observation_class"] for p in view["patterns"]} == {"defect", "friction", "question", "idea"}


# ── Обезличенный ключ и его честное основание ─────────────────────────────────────────────────────

def test_anon_key_is_stable_and_one_way(tmp_path):
    """Один и тот же путь → один и тот же ключ; ключ формы proj-<16hex>, исходник по нему не виден."""
    k1, basis1 = pp.anon_key({"child": {"path": _RAW_PATH, "name": _RAW_NAME}})
    k2, _ = pp.anon_key({"child": {"path": _RAW_PATH, "name": "другое-имя"}})
    assert k1 == k2                                   # ключ от пути, стабилен
    assert pp._ANON_KEY_RE.match(k1)
    assert _RAW_PATH not in k1 and _RAW_NAME not in k1
    assert basis1 == "path"


def test_anon_key_basis_is_honest_about_non_canonical(tmp_path):
    """Нет path → ключ от имени, основание помечено как НЕ каноничный first-commit id (честность видна)."""
    key, basis = pp.anon_key({"child": {"name": _RAW_NAME}})
    assert basis == "name"
    _write_obs(tmp_path, "o1", path="", name=_RAW_NAME, commit="c")
    view = pp.portfolio_patterns(tmp_path)
    labels = " ".join(view["key_basis"].keys())
    assert "не каноничный" in labels                  # основание сведено словами, а не выдано за id


def test_ready_anon_id_passed_through(tmp_path):
    """Готовый анонимный id (форма proj-<hex>) берётся как есть, основание anon-id (ограничение снято)."""
    k, basis = pp.anon_key({"child": {"anon_id": "proj-00112233aabbccdd", "path": _RAW_PATH}})
    assert k == "proj-00112233aabbccdd" and basis == "anon-id"


# ── Честные РАЗНЫЕ пустые состояния ────────────────────────────────────────────────────────────────

def test_empty_state_no_children(tmp_path):
    """Ни наблюдений, ни отметившихся дочек → состояние `no_children` (а не «всё хорошо»)."""
    view = pp.portfolio_patterns(tmp_path)
    assert view["observation_count"] == 0
    assert view["empty_state"] == "no_children"


def test_empty_state_children_present_but_no_observations(tmp_path):
    """Дочка отметилась в охвате, но отказов нет → `no_observations` — ОТЛИЧНО от `no_children`."""
    _register_child(tmp_path)
    view = pp.portfolio_patterns(tmp_path)
    assert view["observation_count"] == 0
    assert view["registered_children"] == 1
    assert view["empty_state"] == "no_observations"
    assert view["empty_state"] != "no_children"       # два разных факта не смешиваются
