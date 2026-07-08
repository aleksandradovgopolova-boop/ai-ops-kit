#!/usr/bin/env python3
"""Генератор runtime-файлов из общего source of truth (принцип 27).

Из registry/workflows.yaml и registry/agents.yaml генерирует в child-репозитории
`.ai/generated/<runtime>/` готовые точки входа:

  claude-code: .ai/generated/claude-code/commands/ai-<workflow>.md   (слэш-команды)
  codex:       .ai/generated/codex/prompts/ai-<workflow>.md          ($-промпты)

Плюс `.generation.json` — хэши источников, версия пакета: позволяет detect
устаревшую генерацию (adapter drift) и перегенерировать. Файлы в .ai/generated/
руками не редактируются.

Использование:
  generate_runtime.py [child_root]   — сгенерировать (по умолчанию cwd)
  generate_runtime.py --selftest     — генерация во временную папку + проверки

Требует pyyaml.
"""

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import yaml

PKG = Path(__file__).resolve().parents[1]
RUNTIMES = ("claude-code", "codex")


def sha256_file(p: Path):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_sources():
    wf = yaml.safe_load((PKG / "registry" / "workflows.yaml").read_text(encoding="utf-8"))
    ag = yaml.safe_load((PKG / "registry" / "agents.yaml").read_text(encoding="utf-8"))
    agents = {a["id"]: a for a in ag.get("agents", [])}
    return wf.get("workflows", {}), agents


def render_command(wid, w, agents, runtime):
    """Единый human-readable текст команды; фронтматтер зависит от runtime."""
    stages_lines = []
    for s in w.get("stages", []):
        owner = s.get("owner", "?")
        role = "судья (read-only)" if s.get("review_mode") == "read-only" else "исполнитель"
        purpose = (agents.get(owner) or {}).get("purpose", "")
        stages_lines.append(f"{s.get('id')} — {owner} ({role}){': ' + purpose if purpose else ''}")
    stages = "\n".join(f"{i+1}. {line}" for i, line in enumerate(stages_lines))
    gates = ", ".join(w.get("quality_gates", []))
    artifacts = "\n".join(f"- {a}" for a in w.get("required_artifacts", []))

    header = (f"---\ndescription: Workflow {wid} — {w.get('purpose','')}\n---\n"
              if runtime == "claude-code" else "")
    return f"""{header}# ai-{wid.lower()} — {w.get('purpose', wid)}

Сгенерировано из registry/workflows.yaml — НЕ редактировать вручную
(перегенерация: python3 tools/generate_runtime.py).

## Что делает
Проводит задачу по workflow **{wid}** ({w.get('preferred_execution_mode')} / минимум
{w.get('minimum_execution_mode')}). Пользователь описывает задачу обычным языком;
стадии и проверки ниже выполняются по порядку, состояние — в TaskState.

## Стадии (owner и роль)
{stages}

## Обязательные артефакты
{artifacts}

## Blocking gates
{gates}

## Правила
- Writer и judge разделены; judge read-only к проверяемому артефакту.
- Judge получает только опубликованные артефакты (handoff), не рассуждения автора.
- Состояние в TaskState — возобновление после прерывания сессии.
- Human approval: {json.dumps(w.get('approval_policy', {}), ensure_ascii=False)}.
"""


def generate(child_root: Path, verbose=True):
    workflows, agents = load_sources()
    out_files = []
    for runtime in RUNTIMES:
        sub = "commands" if runtime == "claude-code" else "prompts"
        base = child_root / ".ai" / "generated" / runtime / sub
        base.mkdir(parents=True, exist_ok=True)
        for wid, w in workflows.items():
            p = base / f"ai-{wid.lower()}.md"
            p.write_text(render_command(wid, w, agents, runtime), encoding="utf-8")
            out_files.append(p)
    meta = {
        "schema_version": 1,
        "package_version": (PKG / "VERSION").read_text(encoding="utf-8").strip(),
        "sources": {
            "registry/workflows.yaml": sha256_file(PKG / "registry" / "workflows.yaml"),
            "registry/agents.yaml": sha256_file(PKG / "registry" / "agents.yaml"),
        },
        "generated": sorted(str(p.relative_to(child_root)) for p in out_files),
        "note": "Do not edit by hand; regenerate with tools/generate_runtime.py",
    }
    (child_root / ".ai" / "generated" / ".generation.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if verbose:
        print(f"OK: сгенерировано {len(out_files)} файлов для {len(RUNTIMES)} runtime "
              f"-> {child_root / '.ai' / 'generated'}")
    return out_files


def check_drift(child_root: Path):
    """True, если генерация устарела относительно источников (adapter drift)."""
    meta_p = child_root / ".ai" / "generated" / ".generation.json"
    if not meta_p.exists():
        return True
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    for rel, digest in meta.get("sources", {}).items():
        if sha256_file(PKG / rel) != digest:
            return True
    return False


def selftest():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        files = generate(root, verbose=False)
        ok = True
        expect = {"quick", "engineering", "product", "research"}
        got = {p.stem.replace("ai-", "") for p in files}
        if not expect.issubset(got):
            ok = False; print(f"FAIL нет команд для: {expect - got}")
        else:
            print(f"PASS команды сгенерированы: {sorted(got)} x {len(RUNTIMES)} runtime")
        sample = next(p for p in files if p.stem == "ai-engineering" and "claude-code" in str(p))
        text = sample.read_text(encoding="utf-8")
        for token in ("requirements-writer", "plan-reviewer", "read-only", "implementation_verification"):
            if token not in text:
                ok = False; print(f"FAIL в ai-engineering нет '{token}'")
        else:
            print("PASS содержимое включает стадии/судей/gates")
        if check_drift(root):
            ok = False; print("FAIL свежая генерация помечена как drift")
        else:
            print("PASS drift-детект: свежая генерация актуальна")
        print("generate_runtime selftest:", "PASS" if ok else "FAIL")
        return 0 if ok else 1


def main(argv):
    if len(argv) > 1 and argv[1] == "--selftest":
        return selftest()
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path.cwd()
    generate(root)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
