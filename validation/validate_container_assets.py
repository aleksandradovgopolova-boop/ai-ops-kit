#!/usr/bin/env python3
"""Validate container isolation assets (v2.90, P0.2 runtime jail).

Брокер (tool_broker) даёт enforceable-подмножество ВНУТРИ процесса. Настоящую изоляцию ФС/
ресурсов/привилегий даёт КОНТЕЙНЕР (containers/Dockerfile + run-sandboxed.sh). Этот валидатор
стережёт, чтобы ассеты не растеряли ключевые гарантии jail'а: если кто-то уберёт `--cap-drop`,
`--read-only`, лимиты или non-root — тест упадёт (декларация проверяется, как везде в ките).

ЧЕСТНО: валидатор проверяет ПРИСУТСТВИЕ флагов изоляции в ассетах, а не поднимает контейнер.
Сборку/запуск образа выполняет Docker-хост пользователя (в CI-песочнице кита pull базового образа
может быть закрыт egress-прокси).

Использование:
  validate_container_assets.py            # проверить поставляемые containers/*
  validate_container_assets.py --selftest
Возврат 0 — ок, 1 — ошибки.
"""

import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]

# Обязательные маркеры (что гарантирует каждый ассет).
DOCKERFILE_REQUIRED = {
    "FROM ": "базовый образ",
    "USER runner": "non-root пользователь (не root внутри контейнера)",
    "openspec": "OpenSpec CLI для гейта specification",
    "pyyaml": "зависимость движка",
    "/opt/ai-ops-kit": "кит скопирован в образ",
    "ENTRYPOINT": "энтрипоинт движка",
}
WRAPPER_REQUIRED = {
    "docker run": "запуск контейнера",
    "--read-only": "root-fs только для чтения",
    "dst=/work": "writable только смонтированный worktree",
    "--tmpfs": "writable временные каталоги без записи на root-fs",
    "--memory": "лимит памяти",
    "--cpus": "лимит CPU",
    "--pids-limit": "лимит процессов",
    "--cap-drop": "сброс Linux capabilities",
    "no-new-privileges": "запрет эскалации привилегий",
}


def check_dockerfile(text):
    return [f"Dockerfile: нет '{k}' ({why})" for k, why in DOCKERFILE_REQUIRED.items() if k not in text]


def check_wrapper(text):
    return [f"run-sandboxed.sh: нет '{k}' ({why})" for k, why in WRAPPER_REQUIRED.items() if k not in text]


def check_assets(root=PKG):
    root = Path(root)
    errors = []
    df = root / "containers" / "Dockerfile"
    wr = root / "containers" / "run-sandboxed.sh"
    if not df.exists():
        errors.append("нет containers/Dockerfile")
    else:
        errors += check_dockerfile(df.read_text(encoding="utf-8"))
    if not wr.exists():
        errors.append("нет containers/run-sandboxed.sh")
    else:
        errors += check_wrapper(wr.read_text(encoding="utf-8"))
    return errors


def selftest():
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    good_df = "FROM node:22-slim\nRUN pyyaml openspec\nCOPY . /opt/ai-ops-kit\nUSER runner\nENTRYPOINT [\"x\"]\n"
    expect("dockerfile: полный набор маркеров -> без ошибок", check_dockerfile(good_df) == [])
    expect("dockerfile: без USER runner -> ошибка (root запрещён)",
           any("USER runner" in e for e in check_dockerfile(good_df.replace("USER runner", "USER root"))))
    good_wr = ("docker run --read-only --tmpfs /tmp --memory 2g --cpus 2 --pids-limit 512 "
               "--cap-drop ALL --security-opt no-new-privileges --mount type=bind,dst=/work img\n")
    expect("wrapper: полный набор jail-флагов -> без ошибок", check_wrapper(good_wr) == [])
    expect("wrapper: убрали --cap-drop -> ошибка",
           any("--cap-drop" in e for e in check_wrapper(good_wr.replace("--cap-drop ALL", ""))))
    expect("wrapper: убрали --read-only -> ошибка",
           any("--read-only" in e for e in check_wrapper(good_wr.replace("--read-only", ""))))
    # поставляемые ассеты валидны
    expect("поставляемые containers/* содержат все гарантии jail'а", check_assets() == [])
    print("validate_container_assets selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    errs = check_assets()
    if errs:
        print("CONTAINER-ASSETS: ошибки:")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("CONTAINER-ASSETS-OK: Dockerfile и run-sandboxed.sh декларируют изоляцию (P0.2 jail).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
