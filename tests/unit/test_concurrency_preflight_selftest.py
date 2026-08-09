"""Селфтест concurrency_preflight, вынесенный из продакшн-модуля (v3.30).

Тело перенесено дословно: цель — убрать тестовый код из модуля, который едет в child-репозиторий,
а не переписать проверки. Прежний вход `--selftest` удалён вместе с функцией.
"""
from __future__ import annotations

import pytest

from concurrency_preflight import (  # noqa: F401 — имена, которые использует тело
    Path,
    _git,
    _parse_owner_repo,
    _prs_overlap,
    open_prs_via_rest,
    os,
    preflight,
)


@pytest.mark.slow
def test_concurrency_preflight_selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _git(repo, "init", "-q")
        _git(repo, "config", "user.email", "t@t"); _git(repo, "config", "user.name", "t")
        (repo / "f.txt").write_text("v1", encoding="utf-8")
        (repo / "other.txt").write_text("x", encoding="utf-8")
        _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", "c1")
        _git(repo, "branch", "-M", "main")
        # ветка feature отделяется здесь
        _git(repo, "checkout", "-q", "-b", "feature")
        # параллельно в main меняют f.txt (как чужой смерженный PR)
        _git(repo, "checkout", "-q", "main")
        (repo / "f.txt").write_text("v2", encoding="utf-8")
        _git(repo, "add", "-A"); _git(repo, "commit", "-q", "-m", "parallel: f.txt live actions")
        _git(repo, "checkout", "-q", "feature")

        # preflight по f.txt против main -> collision (база менялась под путём)
        r = preflight(repo, "main", ["f.txt"])
        expect("collision: база менялась под целевым файлом",
               r["verdict"] == "collision" and isinstance(r["base_changes"], list)
               and any("parallel" in c["subject"] for c in r["base_changes"]))

        # preflight по нетронутому пути -> clean (gh недоступен -> не влияет на clean по base)
        r2 = preflight(repo, "main", ["other.txt"])
        # v3.0.13 (блок C): было тавтологичное `verdict in (clean, collision)` (всегда истинно). Нетронутый
        # путь без active-work и без открытых PR (gh unavailable != collision) -> детерминированно clean.
        expect("clean: нетронутый путь -> verdict=clean (не ложная collision)", r2["verdict"] == "clean")
        expect("clean: base_changes пуст для нетронутого пути", r2["base_changes"] == [])

        # active-work overlap по зонам
        aw = repo / "aw.yaml"
        aw.write_text("schema_version: 1\nkind: active-work\nactive:\n"
                      "  - {id: x, branch: feature/x, status: in-progress, "
                      "affected_areas: [materials-page], owner_session: s}\n", encoding="utf-8")
        r3 = preflight(repo, "main", ["other.txt"], areas=["materials-page"], active_work_path=str(aw))
        expect("collision: пересечение по зоне с реестром",
               r3["verdict"] == "collision" and any(a["id"] == "x" for a in r3["active_work_overlap"]))

        # v3.0.13 (блок C, тест-гэп): DONE-запись в той же зоне НЕ создаёт ложный overlap (stale-skip) —
        # именно тот ложный сигнал, который этот инструмент обязан подавлять.
        aw_done = repo / "aw_done.yaml"
        aw_done.write_text("schema_version: 1\nkind: active-work\nactive:\n"
                           "  - {id: olddone, branch: feature/old, status: done, "
                           "affected_areas: [materials-page], owner_session: s}\n", encoding="utf-8")
        r_done = preflight(repo, "main", ["other.txt"], areas=["materials-page"],
                           active_work_path=str(aw_done))
        expect("v3.0.13 stale-skip: done-запись в той же зоне НЕ даёт overlap (не ложный сигнал)",
               all(a.get("id") != "olddone" for a in r_done["active_work_overlap"]))

        # база недоступна -> base_changes 'unknown', не выдаём за clean молча
        r4 = preflight(repo, "origin/nonexistent", ["f.txt"])
        expect("нет базы -> base_changes unknown", isinstance(r4["base_changes"], str))

        # REST-фоллбэк без токена -> честный unavailable (сеть не трогаем)
        _saved = {k: os.environ.pop(k, None) for k in ("GITHUB_TOKEN", "GH_TOKEN")}
        try:
            rest = open_prs_via_rest(repo, ["f.txt"])
            expect("REST без токена -> unavailable (не clean молча)",
                   rest["status"] == "unavailable" and "GITHUB_TOKEN" in rest["note"])
        finally:
            for k, v in _saved.items():
                if v is not None:
                    os.environ[k] = v

    # разбор owner/repo из разных форм remote URL (чистая функция)
    expect("parse: https .git", _parse_owner_repo("https://github.com/acme/widget.git") == ("acme", "widget"))
    expect("parse: https без .git", _parse_owner_repo("https://github.com/acme/widget") == ("acme", "widget"))
    expect("parse: ssh scp-стиль", _parse_owner_repo("git@github.com:acme/widget.git") == ("acme", "widget"))
    expect("parse: мусор -> None", _parse_owner_repo("не-url") is None)

    # чистая логика пересечения PR (без сети)
    recs = [{"number": 7, "title": "A", "files": ["src/a.ts", "src/b.ts"]},
            {"number": 8, "title": "B", "files": ["docs/x.md"]}]
    hits = _prs_overlap(recs, ["src/b.ts"])
    expect("overlap: PR#7 трогает целевой путь", len(hits) == 1 and hits[0]["number"] == 7
           and hits[0]["shared_paths"] == ["src/b.ts"])
    expect("overlap: непересекающийся -> пусто", _prs_overlap(recs, ["src/c.ts"]) == [])

    assert ok, "перенесённый селфтест concurrency_preflight: см. строки FAIL в выводе"
