"""Селфтест security_scan, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from security_scan import (  # noqa: F401 — имена, которые использует тело
    new_dependencies,
    scan_injection,
    scan_secrets,
    security_evidence,
)


@pytest.mark.slow
def test_security_scan_selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    # секреты. v3.0.4: фикстуры-«секреты» СОБИРАЮТСЯ в рантайме из фрагментов, чтобы в исходнике НЕ
    # было статического секрет-подобного литерала (иначе downstream секрет-сканеры (gitleaks/trufflehog)
    # ложно флагуют тесты САМОГО детектора и блокируют PR). Детектор получает полную строку -> тест валиден.
    # Не канонический пример AWS: `AKIAIOSFODNN7EXAMPLE` — публичный образец, и
    # детектор с 19.08.2026 его не считает утечкой. Позитивной фикстуре нужен ключ,
    # похожий на настоящий.
    _aws = "AKIA" + "QRSTUVWX9012YZAB"                         # канонический AWS-пример (собран, не литерал)
    _hex = "abcdef0123456789" + "ABCDEF"
    # Тело ключа обязательно: заголовок без материала — упоминание ФОРМАТА, а не утечка
    # (так он стоит в CHANGELOG и в манифесте). Секрет — байты ключа.
    _pem = "-----BEGIN RSA " + "PRIVATE KEY-----\n" + "MIIEpAIBAAKCAQEA" + "q" * 40 + "\n"
    s = scan_secrets({"a.py": f'AWS="{_aws}"\napi_key = "{_hex}"\n'})
    expect("secret: AKIA-ключ найден", any(f["id"] == "aws_access_key_id" for f in s))
    expect("secret: generic api_key в кавычках найден", any(f["id"] == "generic_secret_assignment" for f in s))
    expect("secret: чистый файл -> нет находок", scan_secrets({"b.py": "x = 1\n"}) == [])
    expect("secret: плейсхолдер/env НЕ секрет",
           scan_secrets({"c.py": 'api_key = "${API_KEY}"\ntoken = "your-token-here"\n'}) == [])
    expect("secret: private key блок найден",
           any(f["id"] == "private_key_block" for f in scan_secrets({"k": _pem})))

    # injection
    inj = scan_injection({"a.py": "eval(user_input)\nsubprocess.run(cmd, shell=True)\n"})
    expect("injection: eval флагнут", any(f["id"] == "eval_or_exec" for f in inj))
    expect("injection: shell=True флагнут", any(f["id"] == "subprocess_shell_true" for f in inj))
    expect("injection: yaml.load без Loader флагнут",
           any(f["id"] == "yaml_unsafe_load" for f in scan_injection({"a.py": "yaml.load(data)\n"})))
    expect("injection: yaml.load с SafeLoader НЕ флагнут",
           scan_injection({"a.py": "yaml.load(data, Loader=yaml.SafeLoader)\n"}) == [])
    expect("injection: чистый файл -> нет флагов", scan_injection({"b.py": "return a + b\n"}) == [])

    # новые зависимости
    before = {"package.json": '{"dependencies":{"react":"^18"}}'}
    after = {"package.json": '{"dependencies":{"react":"^18","left-pad":"^1"}}'}
    expect("deps: новая зависимость left-pad обнаружена", new_dependencies(before, after) == ["left-pad"])
    expect("deps: без новых -> пусто", new_dependencies(after, after) == [])
    expect("deps: requirements.txt новая строка",
           new_dependencies({"requirements.txt": "flask\n"}, {"requirements.txt": "flask\nrequests\n"}) == ["requests"])
    expect("deps: go.mod новый require",
           "github.com/x/y" in new_dependencies({"go.mod": "module m\n"}, {"go.mod": "module m\nrequire github.com/x/y v1.2.3\n"}))

    # evidence: закрываем no_secrets/deps_approved только когда чисто; injection -> судье
    ev = security_evidence([], [], [])
    expect("evidence: чисто -> no_secrets pass", ev["no_secrets"]["status"] == "pass")
    expect("evidence: без новых deps -> deps_approved pass", ev["deps_approved"]["status"] == "pass")
    expect("evidence: injection чисто -> needs_review (НЕ авто-pass; судья закрывает)",
           ev["no_injection_surface"]["status"] == "needs_review")
    ev2 = security_evidence([{"path": "a", "id": "x", "line": 1}], [{"path": "a", "id": "eval_or_exec", "line": 2}], ["left-pad"])
    expect("evidence: секрет -> no_secrets fail", ev2["no_secrets"]["status"] == "fail")
    expect("evidence: новые deps -> deps_approved fail", ev2["deps_approved"]["status"] == "fail")
    expect("evidence: injection-флаг -> no_injection_surface fail", ev2["no_injection_surface"]["status"] == "fail")

    assert ok, "перенесённый селфтест security_scan: см. строки FAIL в выводе"
