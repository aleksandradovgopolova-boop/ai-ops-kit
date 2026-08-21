"""Селфтест security_pack, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from security_pack import (  # noqa: F401 — имена, которые использует тело
    load_domains,
    run_pack,
)


@pytest.mark.slow
def test_security_pack_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    domains, allowed = load_domains()
    expect("12 доменов загружены", len(domains) == 12)
    expect("allowed_evidence не содержит 'модель сказала нет'",
           "security_reviewer" in allowed and "human_approval" in allowed)

    # frontend-only: XSS/secrets проверяются, database/tenant audit — НЕ применим
    fe = run_pack(files_content={"src/ui/View.tsx": "el.innerHTML = userInput\n"},
                  signals={"handles_user_input": True, "user_facing_change": True})
    expect("frontend: input_validation применим", "input_validation" in fe["applicable_domains"])
    expect("frontend: data_isolation НЕ применим (нет multi_tenant/tenant-файлов)",
           "data_isolation" not in fe["applicable_domains"])
    expect("frontend: innerHTML -> input_validation fail + блок (high)",
           any(r["domain"] == "input_validation" and r["status"] == "fail" for r in fe["results"])
           and "input_validation" in fe["blocking"])

    # v3.0.19 (finding живой квалификации): 'acl' в 'dataclass' НЕ поднимает authorization_idol (word-boundary).
    _da = run_pack(files_content={"pricing.py": "from dataclasses import dataclass\n@dataclass\nclass B:\n    x: int\n"},
                   signals={})
    expect("v3.0.19: 'dataclass' НЕ триггерит authorization_idol (нет ложного needs_review)",
           "authorization_idol" not in _da["applicable_domains"])
    _auth = run_pack(files_content={"auth.py": "def can_edit(user, role):\n    return user.is_admin\n"}, signals={})
    expect("v3.0.19: реальный auth-код (can_edit/role/is_admin) -> authorization_idol применим (детект сохранён)",
           "authorization_idol" in _auth["applicable_domains"])

    # секрет -> домен secrets fail + блок (critical), всегда применим
    # v3.0.4: секрет-фикстура собрана в рантайме (без статического литерала — downstream-сканеры не флагуют)
    # Не канонический пример AWS: `AKIAIOSFODNN7EXAMPLE` — публичный образец, и
    # детектор с 19.08.2026 его не считает утечкой. Позитивной фикстуре нужен ключ,
    # похожий на настоящий.
    _aws = "AKIA" + "QRSTUVWX9012YZAB"
    sec = run_pack(files_content={"config.py": f'API_KEY = "{_aws}"\n'}, signals={})
    expect("secrets всегда применим", "secrets" in sec["applicable_domains"])
    expect("секрет -> secrets fail + overall blocked",
           any(r["domain"] == "secrets" and r["status"] == "fail" for r in sec["results"])
           and sec["overall"] == "blocked")

    # чистый secrets-домен -> авто-pass (required_evidence=[secret_scan], детерминировано)
    clean = run_pack(files_content={"a.py": "x = 1\n"}, signals={})
    sres = next(r for r in clean["results"] if r["domain"] == "secrets")
    expect("чистый secrets -> авто-pass (детерминированный evidence)", sres["status"] == "pass")

    # новая зависимость -> dependencies применим + finding
    dep = run_pack(files_content={"package.json": '{"dependencies":{"left-pad":"^1"}}'},
                   signals={}, )
    # before пуст -> left-pad считается новой
    expect("новая зависимость -> dependencies применим", "dependencies" in dep["applicable_domains"])
    # РЕГРЕССИЯ (finding аудита v2.104): medium-fail (новая зависимость) НЕ даёт overall=clear.
    # Раньше fail с severity=medium исчезал из blocking И needs_review -> ложный green.
    expect("medium-fail (новая зависимость) -> в needs_review, overall != clear (не ложный green)",
           "dependencies" in dep["needs_review"] and dep["overall"] != "clear")

    # auth-домен needs_review (required_evidence включает security_reviewer)
    auth = run_pack(files_content={"src/auth/login.py": "def login(): pass\n"}, signals={"auth_change": True})
    ares = next((r for r in auth["results"] if r["domain"] == "authentication"), None)
    expect("authentication применим по сигналу+файлу", ares is not None)
    expect("authentication чист -> needs_review (нужен судья, не авто-pass)",
           ares and ares["status"] == "needs_review" and "authentication" in auth["needs_review"])

    # ai prompt injection применим по сигналу
    ai = run_pack(files_content={"src/agent/prompt.py": "system = 'do x'\n"}, signals={"ai_component": True})
    expect("ai_prompt_injection применим по ai_component", "ai_prompt_injection" in ai["applicable_domains"])

    # v2.104 (finding самоаудита): применимость по СОДЕРЖИМОМУ, не только по пути. auth-логика в
    # файле, чей путь не матчит (src/users.py c 'password'), поднимает authentication -> не ложный green.
    hidden_auth = run_pack(files_content={"src/users.py": "def check(u, p):\n    return u.password == p\n"},
                           signals={})
    expect("самоаудит: auth-логика по содержимому (не по пути) -> authentication применим",
           "authentication" in hidden_auth["applicable_domains"])
    expect("самоаудит: скрытая auth-логика -> overall != clear (нет ложного green)",
           hidden_auth["overall"] != "clear")

    # у каждой находки есть путь/локация + remediation у домена
    expect("finding несёт path+line; домен несёт remediation",
           all("path" in f for r in fe["results"] for f in r["findings"] if f["type"] != "new_dependency")
           and all(r["remediation"] for r in fe["results"]))

    # v3.0.11 (finding аудита P1): git-энумерация файлов упала -> FAIL-CLOSED (raise), не тихий clear.
    import tempfile as _tf
    with _tf.TemporaryDirectory() as _td:            # НЕ git-репо -> git ls-files rc!=0
        try:
            run_pack(child_root=_td)
            expect("v3.0.11 A3: git-энумерация упала -> raise (fail-closed, не clear)", False)
        except RuntimeError as _e:
            expect("v3.0.11 A3: git-энумерация упала -> raise (fail-closed, не clear)",
                   "fail-closed" in str(_e))

    assert ok, "перенесённый селфтест security_pack: см. строки FAIL в выводе"
