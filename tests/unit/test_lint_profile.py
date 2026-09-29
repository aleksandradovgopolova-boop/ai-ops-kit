"""Профиль стиля кода дочки (#1183): сборка фрагментов по стекам, отказ от латиницы, границы слоёв.

Три теста на capability (AGENTS.md):
  * positive     — для каждого стека собирается фрагмент ПОВЕРХ конфига дочки; границы слоёв выводятся
                   из объявленных зон, запрет соседей FSD — из правила зоны самой в себя;
  * fail-closed  — ключа нет или значение незнакомое -> латиница остаётся; архитектура не объявлена ->
                   граница не угадывается, а называется необъявленной;
  * side-effect  — `apply` пишет ровно файлы профиля и не трогает конфиг дочки; повторная запись — ноль
                   изменений; устаревший профиль виден как расхождение.
"""
from __future__ import annotations

import json
import re

import pytest

from ai_ops_kit.checks import lint_profile, lint_profile_js

pytestmark = pytest.mark.unit

FSD = {
    "zones": {"app": ["src/app/**"], "pages": ["src/pages/**"], "features": ["src/features/**"],
              "shared": ["src/shared/**"]},
    "aliases": {"@/": "src/"},
    "rules": [
        {"id": "p", "forbid": {"from": "pages", "to": "app"}, "reason": "вниз"},
        {"id": "f", "forbid": {"from": "features", "to": "app"}, "reason": "вниз"},
        {"id": "s", "forbid": {"from": "shared", "to": "features"}, "reason": "shared нижний"},
        {"id": "sib", "forbid": {"from": "features", "to": "features"}, "reason": "соседи"},
    ],
}


def _js_repo(tmp_path, ts=True, base=True):
    deps = {"eslint": "10"}
    if ts:
        deps["typescript-eslint"] = "8"
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "package.json").write_text(json.dumps({"devDependencies": deps}))
    if base:
        (tmp_path / "eslint.config.js").write_text("export default [];\n")
    for f in ("src/app/router.ts", "src/pages/home/index.ts", "src/features/a/ui/view.ts",
              "src/features/b/model.ts", "src/shared/lib.ts"):
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("export {};\n")
    return tmp_path


def _profile_objects(text: str) -> list:
    body = text[text.index("export const profile = ") + len("export const profile = "):]
    return json.loads(body[: body.index("].map(") + 1])


def _objects(tmp_path, decl=None):
    prof = lint_profile.render(tmp_path, FSD if decl is None else decl)
    return prof, _profile_objects(prof["files"][lint_profile_js.OUT])


def _js_regex(pattern: str):
    """RegExp ESLint (флаг `u`) -> Python: lookahead и классы совпадают, экранирование — тоже."""
    return re.compile(pattern)


# ── Имена латиницей. ──────────────────────────────────────────────────────────────────────────
def test_latin_is_the_default_when_the_key_is_absent(tmp_path):
    assert lint_profile.identifiers_policy(tmp_path) == {
        "value": "latin", "source": "default", "note": None}


def test_explicit_opt_out_any_is_honoured(tmp_path):
    (tmp_path / ".ai-ops.yaml").write_text("standard:\n  identifiers: any\n")
    assert lint_profile.identifiers_policy(tmp_path)["value"] == "any"


def test_unknown_value_keeps_latin_and_says_so(tmp_path):
    (tmp_path / ".ai-ops.yaml").write_text("standard:\n  identifiers: cyrillic\n")
    pol = lint_profile.identifiers_policy(tmp_path)
    assert pol["value"] == "latin" and "cyrillic" in pol["note"]


def test_js_fragment_has_ascii_id_match_on_declarations(tmp_path):
    _, objs = _objects(_js_repo(tmp_path), {})
    rule = next(o for o in objs if o["name"] == "ai-ops/identifiers")["rules"]["ai-ops/id-match"]
    assert rule[1] == "^[A-Za-z_$][A-Za-z0-9_$]*$"
    assert rule[2]["properties"] is True and rule[2]["onlyDeclarations"] is True


def test_naming_convention_only_with_typescript_eslint(tmp_path):
    with_ts = lint_profile.render(_js_repo(tmp_path / "ts"), {})["files"][lint_profile_js.OUT]
    without = lint_profile.render(_js_repo(tmp_path / "js", ts=False), {})["files"][lint_profile_js.OUT]
    assert "ai-ops/naming-convention" in with_ts and 'from "typescript-eslint"' in with_ts
    assert "naming-convention" not in without and "**/*.{js,jsx,mjs,cjs}" in without


def test_opt_out_drops_identifier_rules_but_keeps_boundaries(tmp_path):
    repo = _js_repo(tmp_path)
    (repo / ".ai-ops.yaml").write_text("standard:\n  identifiers: any\n")
    prof, objs = _objects(repo)
    assert not any("id-match" in json.dumps(o) or "naming-convention" in json.dumps(o) for o in objs)
    assert any(o["name"].startswith("ai-ops/boundaries/") for o in objs)
    assert "ai-ops/id-match" not in prof["tools"][0]["rules"]


def test_opt_out_without_architecture_writes_nothing_for_js(tmp_path):
    repo = _js_repo(tmp_path)
    (repo / ".ai-ops.yaml").write_text("standard:\n  identifiers: any\n")
    prof = lint_profile.render(repo, {})
    assert lint_profile_js.OUT not in prof["files"]


def test_fragment_layers_on_top_of_the_child_config(tmp_path):
    text = lint_profile.render(_js_repo(tmp_path), {})["files"][lint_profile_js.OUT]
    assert 'import base from "./eslint.config.js";' in text
    assert "export default [...(Array.isArray(base) ? base : [base]), ...profile];" in text
    assert 'builtinRules.get("no-restricted-imports")' in text


def test_fragment_without_child_config_stands_alone(tmp_path):
    text = lint_profile.render(_js_repo(tmp_path, base=False), {})["files"][lint_profile_js.OUT]
    assert "import base" not in text and "export default [...[], ...profile];" in text


def test_undeclared_architecture_is_named_not_guessed(tmp_path):
    prof, objs = _objects(_js_repo(tmp_path), {})
    assert prof["architecture_declared"] is False
    assert any("не объявлена" in n for n in prof["notes"])
    assert not any(o["name"].startswith("ai-ops/boundaries/") for o in objs)


# ── Границы слоёв из объявления. ──────────────────────────────────────────────────────────────
def test_forbidden_expands_open_side_and_reads_self_rule_as_siblings():
    decl = {"zones": {"a": ["a/**"], "b": ["b/**"], "c": ["c/**"]},
            "rules": [{"forbid": {"to": "c"}, "reason": "r"}, {"forbid": {"from": "b", "to": "b"}}]}
    targets, siblings = lint_profile.forbidden(decl)
    assert targets == {"a": {"c": "r"}, "b": {"c": "r"}}
    assert set(siblings) == {"b"}


def test_zone_dirs_stop_at_first_glob_segment():
    assert lint_profile.zone_dirs(["src/features/**", "./lib/*.ts", "**/api/**"]) == [
        "src/features", "lib"]


def _patterns(objs, name):
    obj = next(o for o in objs if o["name"] == name)
    return obj["files"], obj["rules"]["ai-ops/no-restricted-imports"][1]["patterns"]


def test_upward_import_is_caught_by_exact_relative_prefix_and_alias(tmp_path):
    _, objs = _objects(_js_repo(tmp_path))
    files, pats = _patterns(objs, "ai-ops/boundaries/pages/1")
    assert files == ["src/pages/*/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}"]
    rx = _js_regex(pats[0]["regex"])
    assert rx.search("../../app/router") and rx.search("@/app")
    assert not rx.search("firebase/app") and not rx.search("../../shared/lib")


def test_sibling_slice_is_forbidden_but_own_slice_is_not(tmp_path):
    _, objs = _objects(_js_repo(tmp_path))
    _, pats = _patterns(objs, "ai-ops/boundaries/features/b/0")
    sib = _js_regex(next(p for p in pats if "соседний" in p["message"])["regex"])
    assert sib.search("../a/ui/view") and sib.search("@/features/a")
    assert not sib.search("../b/model") and not sib.search("@/features/b/x")
    assert not sib.search("../../shared/lib")


def test_every_depth_inside_a_slice_gets_its_own_object(tmp_path):
    _, objs = _objects(_js_repo(tmp_path))
    names = {o["name"] for o in objs}
    assert {"ai-ops/boundaries/features/a/0", "ai-ops/boundaries/features/a/1"} <= names
    _, pats = _patterns(objs, "ai-ops/boundaries/features/a/1")
    assert _js_regex(pats[0]["regex"]).search("../../../app")


def test_regex_is_valid_for_javascript_unicode_mode(tmp_path):
    """`\\-` вне класса — ошибка RegExp с флагом `u`: экранировать можно только синтаксис."""
    repo = _js_repo(tmp_path)
    (repo / "src/features/my-slice").mkdir()
    (repo / "src/features/my-slice/x.ts").write_text("")
    _, objs = _objects(repo)
    blob = json.dumps(objs)
    assert "my-slice" in blob and "\\\\-" not in blob


def test_file_exception_removes_one_edge_for_that_file_only(tmp_path):
    decl = dict(FSD, exceptions=["src/pages/home/index.ts -> app"])
    _, objs = _objects(_js_repo(tmp_path), decl)
    generic = next(o for o in objs if o["name"] == "ai-ops/boundaries/pages/1")
    assert generic["ignores"] == ["src/pages/home/index.ts"]
    assert not any(o["name"] == "ai-ops/boundaries/pages/1/exception" for o in objs)


def test_zone_of_another_language_gets_no_eslint_boundary(tmp_path):
    repo = _js_repo(tmp_path)
    (repo / "pkg/domain").mkdir(parents=True)
    (repo / "pkg/domain/__init__.py").write_text("")
    decl = dict(FSD, zones={**FSD["zones"], "domain": ["pkg/domain/**"]},
                rules=FSD["rules"] + [{"forbid": {"from": "domain", "to": "shared"}, "reason": "x"}])
    _, objs = _objects(repo, decl)
    assert not any(o["name"].startswith("ai-ops/boundaries/domain") for o in objs)


# ── Python, Go, прочие. ───────────────────────────────────────────────────────────────────────
def _py_repo(tmp_path, ruff_cfg=True):
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n" if ruff_cfg else "")
    for f in ("src/app/__init__.py", "src/app/api/__init__.py", "src/app/domain/__init__.py"):
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("")
    return tmp_path


PY_DECL = {"zones": {"api": ["src/app/api/**"], "domain": ["src/app/domain/**"]},
           "rules": [{"forbid": {"from": "domain", "to": "api"}, "reason": "домен ниже"}]}


def test_ruff_fragment_extends_the_child_config_and_only_adds_rules(tmp_path):
    prof = lint_profile.render(_py_repo(tmp_path), {})
    text = prof["files"][lint_profile.RUFF_OUT]
    assert 'extend = "../../../pyproject.toml"' in text
    assert 'extend-select = ["PLC2401", "PLC2403", "N"]' in text and 'extend-exclude = [".ai"]' in text


def test_ruff_opt_out_keeps_pep8_naming_only(tmp_path):
    repo = _py_repo(tmp_path)
    (repo / ".ai-ops.yaml").write_text("standard:\n  identifiers: any\n")
    text = lint_profile.render(repo, {})["files"][lint_profile.RUFF_OUT]
    assert 'extend-select = ["N"]' in text


def test_import_linter_layers_contract_from_declaration(tmp_path):
    text = lint_profile.render(_py_repo(tmp_path), PY_DECL)["files"][
        lint_profile.IMPORTLINTER_OUT]
    assert "type = layers" in text
    assert text.index("    app.api") < text.index("    app.domain")
    assert "root_packages =\n    app" in text


def test_import_linter_uses_forbidden_when_rules_are_not_a_full_order(tmp_path):
    decl = {"zones": {**PY_DECL["zones"], "top": ["src/app/**"]},
            "rules": [{"forbid": {"from": "domain", "to": "api"}, "reason": "x"},
                      {"forbid": {"from": "api", "to": "top"}, "reason": "x"}]}
    text = lint_profile.render(_py_repo(tmp_path), decl)["files"][lint_profile.IMPORTLINTER_OUT]
    assert "type = layers" not in text and text.count("type = forbidden") == 2


def test_layer_order_rejects_partial_orders():
    assert lint_profile._layer_order({("b", "a"), ("c", "b"), ("c", "a")}) == ["a", "b", "c"]
    assert lint_profile._layer_order({("b", "a"), ("c", "b")}) is None


def test_go_fragment_asciicheck_revive_and_depguard(tmp_path):
    (tmp_path / "go.mod").write_text("module example.com/svc\n\ngo 1.22\n")
    for f in ("internal/domain/d.go", "internal/api/a.go"):
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_text("package x\n")
    decl = {"zones": {"domain": ["internal/domain/**"], "api": ["internal/api/**"]},
            "rules": [{"forbid": {"from": "domain", "to": "api"}, "reason": "вниз"}]}
    text = lint_profile.render(tmp_path, decl)["files"][lint_profile.GOLANGCI_OUT]
    assert "default: none" in text and "- asciicheck" in text and "name: var-naming" in text
    assert 'pkg: "example.com/svc/internal/api"' in text and '"**/internal/domain/**/*.go"' in text


def test_ast_grep_fallback_only_for_languages_without_own_profile(tmp_path):
    (tmp_path / "main.rs").write_text("fn main() {}\n")
    (tmp_path / "tool.py").write_text("")
    prof = lint_profile.render(tmp_path, {})
    text = prof["files"][lint_profile.ASTGREP_OUT]
    assert "language: rust" in text and "language: python" not in text
    assert "[^\\x00-\\x7F]" in text


def test_ast_grep_fallback_is_omitted_on_opt_out(tmp_path):
    (tmp_path / "main.rs").write_text("")
    (tmp_path / ".ai-ops.yaml").write_text("standard:\n  identifiers: any\n")
    assert lint_profile.ASTGREP_OUT not in lint_profile.render(tmp_path, {})["files"]


# ── Запись и устаревание. ─────────────────────────────────────────────────────────────────────
def test_apply_writes_profile_and_leaves_child_config_untouched(tmp_path):
    repo = _js_repo(tmp_path)
    before = (repo / "eslint.config.js").read_text()
    prof = lint_profile.render(repo, FSD)
    assert lint_profile.apply(repo, prof) == [lint_profile_js.OUT]
    assert (repo / lint_profile_js.OUT).read_text() == prof["files"][lint_profile_js.OUT]
    assert (repo / "eslint.config.js").read_text() == before
    assert lint_profile.apply(repo, prof) == []


def test_new_slice_makes_the_written_profile_stale(tmp_path):
    repo = _js_repo(tmp_path)
    lint_profile.apply(repo, lint_profile.render(repo, FSD))
    assert lint_profile.drift(repo, lint_profile.render(repo, FSD)) == []
    (repo / "src/features/c").mkdir()
    (repo / "src/features/c/x.ts").write_text("")
    assert lint_profile.drift(repo, lint_profile.render(repo, FSD)) == [lint_profile_js.OUT]
