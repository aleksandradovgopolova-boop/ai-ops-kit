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
from __future__ import annotations

import sys
from pathlib import Path

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
            Path(__file__).resolve().parents[1])
# Обязательные маркеры (что гарантирует каждый ассет).
DOCKERFILE_REQUIRED = {
    "FROM ": "базовый образ",
    "USER runner": "non-root пользователь (не root внутри контейнера)",
    "openspec": "OpenSpec CLI для гейта specification",
    "pyyaml": "зависимость движка",
    "/opt/ai-ops-kit": "кит скопирован в образ",
    "ENTRYPOINT": "энтрипоинт движка",
    # Credential-less git для PUSH, зашитый в образ (defense-in-depth — держится и без wrapper'а).
    "GIT_ASKPASS=/bin/false": "нет источника логина/пароля для git push (жёсткая недоставка средой)",
    "GIT_TERMINAL_PROMPT=0": "push по HTTPS без креды падёт быстро, не виснет в промпте",
    "GIT_CONFIG_KEY_0=credential.helper": "credential helper отключён внутри образа (нет креды push)",
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
    # v2.93 worktree-only: монтируется ОДНОРАЗОВЫЙ клон, а не основной child; доставка — host-слоем
    "git clone": "одноразовый клон child (основной репо не монтируется в контейнер)",
    "src=${CLONE}": "в /work монтируется клон, НЕ основной child-репозиторий",
    # v2.113: доставка вынесена в scoped-deliverer (только ветки прогона) — вызывается из wrapper
    "deliver-run-branches.sh": "доставка ТОЛЬКО веток прогона через scoped host-deliverer",
    # Credential-less git для PUSH (ПЕРВЫЙ рубеж недоставки — среда, не regex block_push).
    "GIT_ASKPASS=/bin/false": "нет источника логина/пароля для git push из модельной петли",
    "GIT_TERMINAL_PROMPT=0": "push по HTTPS без креды падёт быстро, не виснет в промпте",
    "GIT_CONFIG_KEY_0=credential.helper": "credential helper отключён (нет канала креды для push)",
}
# Анти-маркер: основной child НЕ должен монтироваться как writable напрямую (регресс worktree-only).
WRAPPER_FORBIDDEN = {
    "src=${CHILD_ABS},dst=/work": "основной child смонтирован в /work напрямую (нарушает worktree-only; монтируй клон)",
}


def check_dockerfile(text):
    return [f"Dockerfile: нет '{k}' ({why})" for k, why in DOCKERFILE_REQUIRED.items() if k not in text]


def check_wrapper(text):
    errs = [f"run-sandboxed.sh: нет '{k}' ({why})" for k, why in WRAPPER_REQUIRED.items() if k not in text]
    errs += [f"run-sandboxed.sh: запрещённый паттерн '{k}' ({why})"
             for k, why in WRAPPER_FORBIDDEN.items() if k in text]
    return errs


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
    # v2.113: scoped-deliverer обязателен и должен доставлять ТОЛЬКО ветки прогона (диф снимка)
    dl = root / "containers" / "deliver-run-branches.sh"
    if not dl.exists():
        errors.append("нет containers/deliver-run-branches.sh (scoped-доставка веток прогона)")
    else:
        dtext = dl.read_text(encoding="utf-8")
        for k, why in {"for-each-ref": "снимок ai-ops/* для дифа (доставить только изменённое)",
                       "fetch": "перенос веток прогона в основной репо",
                       "ai-ops/*": "область — только ai-ops/* ветки"}.items():
            if k not in dtext:
                errors.append(f"deliver-run-branches.sh: нет '{k}' ({why})")
    return errors


def main(argv):
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
