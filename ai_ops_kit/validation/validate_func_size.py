#!/usr/bin/env python3
"""Ратчет максимального размера функции в ai_ops_kit/ и installer/ (F-06).

AST-обход всех .py файлов в каждом объявленном каталоге, для каждой function/async function
считает end_lineno - lineno + 1. У каждого каталога (scope) свой потолок; проверка сверяет
максимум каталога с его потолком и возвращает 0, если ни один scope не превышен, 1 — если
хотя бы один превышен.

Scopes перечислены в packages/func-size-baseline.yaml (ключ `scopes`). Раньше ратчет стерёг
только engine/, а god-функции ВНЕ него росли свободно; теперь потолок есть у каждого
объявленного каталога.

ЧТО КРАСНЕЕТ, А ЧТО ПРЕДУПРЕЖДАЕТ (#1128). Отказ — только РОСТ максимума сверх потолка: это новая
god-функция. Снижение максимума ниже потолка — ПРЕДУПРЕЖДЕНИЕ с подсказкой опустить потолок, а не
отказ: сокращение функции в постороннем PR — хорошая новость, и ронять за неё чужой PR значило бы
наказывать ровно то поведение, ради которого ратчет заведён (тот же выбор, что у module-size:
«усыхание не краснит прогон»). Устаревший-вниз потолок безвреден — он лишь даёт запас, который
следующий `--baseline` снимет. Расхождение КООРДИНАТ (имя/файл/строка максимума) — тоже
предупреждение: координаты справочные, их обновляет `--baseline`, а краснеть за сдвиг строки от
правки выше по файлу — шум.

`--baseline` ПРАВИТ ЧИСЛА ТЕКСТОМ (#1128, подход #1071 — приёмка кандидатов в plan.yaml). Прежде
файл переписывался через `yaml.dump`, и после одного прогона исчезали все пояснения — история
опусканий и обоснования потолков. Теперь меняются только значения четырёх полей scope'а, каждый
прочий байт (комментарии, порядок, пустые строки) остаётся на месте; итоговый текст сначала
разбирается в памяти и сверяется с задуманным, и лишь потом пишется. По умолчанию `--baseline`
только ОПУСКАЕТ потолки: подъём — отказ целиком (файл не тронут), пока не дан явный
`--allow-raise "<обоснование>"`; тогда подъём записывается в ленту `raises` с этим обоснованием.
Контракт в тестах сверяет baseline с origin/main (`unrecorded_raises`): выросший потолок без
непрерывной цепочки записей в `raises` краснеет; новый каталог заводится только по факту.
Концы строк файла (LF/CRLF) `--baseline` сохраняет.

Использование:
  validate_func_size.py                                    # проверить все scope против baseline
  validate_func_size.py --report                           # топ-10 по каждому scope без проверки
  validate_func_size.py --baseline                         # опустить потолки, обновить координаты
  validate_func_size.py --baseline --allow-raise "почему"  # то же, с разрешённым подъёмом

Возврат 0 — все scope в пределах потолка (или baseline обновлён), 1 — хотя бы один превышен
(или `--baseline` отказал: подъём без обоснования, правка не сошлась).
"""
from __future__ import annotations

import ast
import datetime as _dt
import json
import posixpath
import re
import sys
from pathlib import Path

import yaml

PKG = next((_p for _p in Path(__file__).resolve().parents if (_p / "VERSION").is_file()),
           Path(__file__).resolve().parents[1])
ENGINE_DIR = PKG / "ai_ops_kit" / "engine"
BASELINE_FILE = PKG / "packages" / "func-size-baseline.yaml"


def measure_functions(directory: Path = ENGINE_DIR) -> list[dict]:
    """AST-обход: для каждой function/async function возвращает имя, файл, строки, размер.

    Обход РЕКУРСИВНЫЙ (#1119). Прежде мерился только верхний уровень каталога, и подпакет-сателлит
    оказывался зоной свободного роста: `checks/surface_extractors/` — 18 файлов и 102 функции — не
    стерёг никто, хотя сам `checks/` объявлен. Репозиторий активно плодит сателлиты, так что дыра
    росла бы сама. Переход на рекурсию не сдвинул ни один потолок: у всех двадцати каталогов
    максимум остался прежним — значит это чистое расширение охвата, а не ослабление ратчета.
    """
    results = []
    for f in sorted(directory.rglob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                size = node.end_lineno - node.lineno + 1
                results.append({
                    "name": node.name,
                    "file": f.name if f.parent == directory else str(f.relative_to(directory)),
                    "lineno": node.lineno,
                    "size": size,
                })
    return results


def top_n(funcs: list[dict], n: int = 10) -> list[dict]:
    """Топ-N крупнейших функций, по убыванию размера."""
    return sorted(funcs, key=lambda f: f["size"], reverse=True)[:n]


def load_baseline(path: Path = BASELINE_FILE) -> dict:
    """Загрузить baseline из YAML. Возвращает dict с 'max_function_lines'."""
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _ceiling(spec: dict):
    """Потолок scope'а или None, если числа нет (bool числом не считается)."""
    ceiling = spec.get("max_function_lines")
    if not isinstance(ceiling, int) or isinstance(ceiling, bool):
        return None
    return ceiling


def check(funcs: list[dict], baseline: dict) -> list[str]:
    """Сверить текущий максимум с потолком. Возвращает список ОШИБОК (пустой = ОК).

    Ошибка — только рост сверх потолка (и отсутствие самого потолка). Снижение ниже потолка —
    не ошибка, а предупреждение (`advise`): сокращение функции не роняет посторонний PR (#1128).
    """
    ceiling = _ceiling(baseline)
    if ceiling is None:
        return ["ратчет func-size: в baseline нет числа max_function_lines — потолка не существует"]
    actual_max = max((f["size"] for f in funcs), default=0)
    if actual_max > ceiling:
        worst = max(funcs, key=lambda f: f["size"])
        return [
            f"ратчет func-size: max {actual_max} строк ({worst['file']}:{worst['lineno']} "
            f"{worst['name']}) превышает потолок {ceiling} — новая god-функция или "
            f"рефакторинг не завершён; опустить потолок после разбиения"
        ]
    return []


def advise(funcs: list[dict], baseline: dict) -> list[str]:
    """ПРЕДУПРЕЖДЕНИЯ scope'а: потолок выше факта и устаревшие координаты максимума.

    Ни одно из них не роняет прогон (#1128): потолок выше факта безвреден, а координаты —
    справочные. Оба лечатся одной командой `--baseline`, которую предупреждение и называет.
    """
    ceiling = _ceiling(baseline)
    if ceiling is None or not funcs:
        return []
    actual_max = max(f["size"] for f in funcs)
    if actual_max > ceiling:
        return []        # рост — уже ошибка `check`; координаты при нём сверять бессмысленно
    notes = []
    if actual_max < ceiling:
        notes.append(
            f"ратчет func-size: max {actual_max} строк при потолке {ceiling} — функцию сократили; "
            f"опустить потолок: validate_func_size.py --baseline (ратчет ходит только вниз)")
    recorded = (baseline.get("max_function"), baseline.get("max_function_file"),
                baseline.get("max_function_lineno"))
    if recorded == (None, None, None):
        return notes     # координаты не записаны вовсе — сверять нечего
    leaders = [f for f in funcs if f["size"] == actual_max]
    if not any((f["name"], f["file"], f["lineno"]) == recorded for f in leaders):
        now = leaders[0]
        notes.append(
            f"ратчет func-size: координаты максимума устарели — записано "
            f"{recorded[1]}:{recorded[2]} {recorded[0]}, факт {now['file']}:{now['lineno']} "
            f"{now['name']}; обновить: validate_func_size.py --baseline")
    return notes


def iter_scopes(baseline: dict, pkg_root: Path = PKG) -> list[dict]:
    """Список scope'ов из baseline с разрешённым каталогом.

    Каждый элемент: {'path': относительный путь, 'dir': абсолютный Path, 'spec': dict scope}.
    Порядок сохраняется как в baseline.
    """
    scopes = []
    for spec in baseline.get("scopes", []) or []:
        rel = spec.get("path", "")
        scopes.append({"path": rel, "dir": pkg_root / rel, "spec": spec})
    return scopes


def check_all(baseline: dict, pkg_root: Path = PKG) -> list[str]:
    """Сверить максимум каждого scope с его потолком. Возвращает список ошибок (пустой = ОК).

    Ошибки каждого scope префиксуются его путём. Отсутствие секции `scopes` — сама ошибка:
    без неё ратчет ничего не стережёт.
    """
    scopes = iter_scopes(baseline, pkg_root)
    if not scopes:
        return ["ратчет func-size: в baseline нет секции scopes — стеречь нечего"]
    errors = []
    for scope in scopes:
        funcs = measure_functions(scope["dir"])
        for err in check(funcs, scope["spec"]):
            errors.append(f"[{scope['path']}] {err}")
    return errors


def advise_all(baseline: dict, pkg_root: Path = PKG) -> list[str]:
    """Предупреждения всех scope'ов (с префиксом пути). На код возврата не влияют."""
    notes = []
    for scope in iter_scopes(baseline, pkg_root):
        for note in advise(measure_functions(scope["dir"]), scope["spec"]):
            notes.append(f"[{scope['path']}] {note}")
    return notes


def render_report(funcs: list[dict], n: int = 10) -> str:
    """Человекочитаемый отчёт: топ-N крупнейших функций."""
    lines = [f"Всего функций: {len(funcs)}"]
    for f in top_n(funcs, n):
        lines.append(f"  {f['size']:5d}  {f['file']}:{f['lineno']}  {f['name']}")
    return "\n".join(lines)


# ── --baseline: правка чисел ТЕКСТОМ (комментарии сохраняются; #1128 по образцу #1071) ──────────

def _yaml_scalar(value) -> str:
    """Значение поля → YAML-скаляр. Число и простое имя/путь пишутся как есть, прочее —
    JSON-строкой (валидный YAML-скаляр в двойных кавычках с корректным экранированием)."""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    s = str(value)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_./-]*", s):
        return s
    return json.dumps(s, ensure_ascii=False)


def _unquote(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1]
    return raw


_PATH_LINE = re.compile(r"^(?P<indent>\s*)-\s+path\s*:\s*(?P<value>[^#\n]*?)\s*(#.*)?$")


def _scope_block(lines: list[str], path: str) -> tuple[int, int]:
    """Границы блока scope'а `path` в строках файла: [начало, конец). ValueError, если блока нет
    или он встречается дважды — угадывать, какой из них править, нельзя."""
    starts = [i for i, ln in enumerate(lines)
              if (m := _PATH_LINE.match(ln.rstrip("\n"))) and _unquote(m.group("value")) == path]
    if len(starts) != 1:
        raise ValueError(f"scope {path!r} найден в baseline {len(starts)} раз(а) — "
                         f"правка вслепую невозможна")
    start = starts[0]
    indent = len(_PATH_LINE.match(lines[start].rstrip("\n")).group("indent"))
    end = len(lines)
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        body = ln.strip()
        if not body or body.startswith("#"):
            continue
        cur = len(ln) - len(ln.lstrip())
        if cur == 0 or cur < indent or (cur == indent and body.startswith("-")):
            end = i
            break
    return start, end


def rewrite_scope_text(text: str, path: str, values: dict) -> str:
    """Заменить значения полей `values` в блоке scope'а `path`, не трогая ни одного другого байта.

    Меняется только значение после `поле:` — отступ, ключ и хвостовой комментарий строки
    остаются. Поле, которого в блоке нет (или оно дважды), — ValueError: вставлять вслепую
    не угадываем.
    """
    lines = text.splitlines(keepends=True)
    start, end = _scope_block(lines, path)
    for field, value in values.items():
        pat = re.compile(rf"^(\s+{re.escape(field)}\s*:[ \t]*)([^#\n]*?)([ \t]*#[^\n]*)?(\n?)$")
        hits = [i for i in range(start + 1, end) if pat.match(lines[i])]
        if len(hits) != 1:
            raise ValueError(f"в scope {path!r} поле {field} встречается {len(hits)} раз(а) — "
                             f"правка вслепую невозможна")
        m = pat.match(lines[hits[0]])
        lines[hits[0]] = f"{m.group(1)}{_yaml_scalar(value)}{m.group(3) or ''}{m.group(4)}"
    return "".join(lines)


_RAISES_HEADER = (
    "\n# Лента ОСОЗНАННЫХ подъёмов потолка (#1128). Пишет её только `--baseline --allow-raise`;\n"
    "# потолок, выросший относительно origin/main без записи здесь, краснит контракт в тестах.\n"
    "raises:\n")


def append_raises_text(text: str, entries: list[dict]) -> str:
    """Дописать записи подъёма в ленту `raises` ТЕКСТОМ. Ленты нет — она заводится в конце файла.

    Лента обязана быть ПОСЛЕДНИМ верхнеуровневым ключом (так её заводит эта же функция):
    дописывание в середину файла вслепую дало бы битый YAML — ValueError.
    """
    lines = text.splitlines(keepends=True)
    top = [i for i, ln in enumerate(lines) if ln[:1] not in ("", " ", "\t", "#", "\n")]
    raises_idx = [i for i in top if re.match(r"^raises\s*:", lines[i])]
    rendered = "".join(
        f"  - at: '{e['at']}'\n    path: {_yaml_scalar(e['path'])}\n    from: {e['from']}\n"
        f"    to: {e['to']}\n    why: {json.dumps(e['why'], ensure_ascii=False)}\n"
        for e in entries)
    if text and not text.endswith("\n"):
        text += "\n"
    if not raises_idx:
        return text + _RAISES_HEADER + rendered
    if raises_idx[0] != top[-1]:
        raise ValueError("лента raises — не последний верхнеуровневый ключ baseline: "
                         "дописывать вслепую нельзя")
    if lines[raises_idx[0]].split(":", 1)[1].split("#", 1)[0].strip():
        raise ValueError("лента raises не блок-список (значение в той же строке) — "
                         "дописывать вслепую нельзя")
    return text + rendered


def plan_baseline(baseline: dict, pkg_root: Path = PKG) -> list[dict]:
    """Что `--baseline` запишет по каждому scope: {'path', 'old': потолок, 'values': поля}."""
    plans = []
    for scope in iter_scopes(baseline, pkg_root):
        funcs = measure_functions(scope["dir"])
        worst = max(funcs, key=lambda f: f["size"]) if funcs else {}
        values = {"max_function_lines": worst.get("size", 0),
                  "max_function": worst.get("name", ""),
                  "max_function_file": worst.get("file", ""),
                  "max_function_lineno": worst.get("lineno", 0)}
        plans.append({"path": scope["path"], "old": _ceiling(scope["spec"]), "values": values})
    return plans


def rebaseline(path: Path = BASELINE_FILE, pkg_root: Path = PKG,
               allow_raise: str | None = None, today: str | None = None) -> tuple[int, list[str]]:
    """Обновить baseline ТЕКСТОМ. -> (код возврата, сообщения). На диск пишет только при коде 0.

    Подъём потолка без непустого `allow_raise` — отказ ЦЕЛИКОМ: не переписывается ни один scope,
    даже те, что опустились бы. Половинчатый baseline хуже непереписанного: подъём в нём спрятался
    бы среди честных опусканий. Итоговый текст разбирается в памяти и сверяется с задуманным до
    записи (страховка F4 из #1071) — не сошлось, ничего не пишем.
    """
    if not path.is_file():
        return 1, [f"отказ: baseline-файла нет ({path}) — обновлять нечего; потолки заводятся "
                   f"записью scope'ов вручную"]
    # Концы строк сохраняются: файл читается байтами, правится в LF и пишется обратно тем концом
    # строки, что был в нём (CRLF-файл остаётся CRLF). Смешанные концы сводятся к CRLF.
    raw = path.read_bytes().decode("utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    plans = plan_baseline(yaml.safe_load(text) or {}, pkg_root)
    if not plans:
        return 1, ["отказ: в baseline нет секции scopes — обновлять нечего"]
    raised = [p for p in plans
              if p["old"] is not None and p["values"]["max_function_lines"] > p["old"]]
    reason = (allow_raise or "").strip()
    if raised and not reason:
        return 1, [f"отказ: {p['path']} потолок {p['old']} -> {p['values']['max_function_lines']} "
                   f"ПОДНЯЛСЯ бы, а ратчет ходит только вниз. Разбейте функцию или повторите с "
                   f"--allow-raise \"<обоснование>\" (оно ляжет в ленту raises). Файл не тронут"
                   for p in raised]
    try:
        new_text = text
        for p in plans:
            new_text = rewrite_scope_text(new_text, p["path"], p["values"])
        if raised:
            day = today or _dt.date.today().isoformat()
            new_text = append_raises_text(new_text, [
                {"at": day, "path": p["path"], "from": p["old"],
                 "to": p["values"]["max_function_lines"], "why": reason} for p in raised])
        parsed = yaml.safe_load(new_text) or {}
    except (ValueError, yaml.YAMLError) as e:
        return 1, [f"отказ: {e} — файл не тронут"]
    got = {sc.get("path"): sc for sc in parsed.get("scopes", []) or []}
    for p in plans:
        if any(got.get(p["path"], {}).get(k) != v for k, v in p["values"].items()):
            return 1, [f"отказ: после правки scope {p['path']} разобрался не так, как задумано — "
                       f"файл не тронут"]
    if new_text != text:
        path.write_bytes(new_text.replace("\n", nl).encode("utf-8"))
    msgs = [f"  {p['path']}: max={p['values']['max_function_lines']} "
            f"({p['values']['max_function_file']}:{p['values']['max_function_lineno']} "
            f"{p['values']['max_function']})" for p in plans]
    return 0, msgs + ["Baseline обновлён (комментарии сохранены)."]


def _norm_path(p) -> str:
    """Путь scope'а для сравнения версий: `kernel/`, `kernel` и `./kernel` — один каталог.
    Иначе переименование записи сделало бы каталог «новым» и спрятало подъём его потолка."""
    s = posixpath.normpath(str(p or "").strip().replace("\\", "/"))
    return "" if s == "." else s


def _chain_recorded(ledger: list[tuple[int, int]], was: int, now: int) -> bool:
    """Есть ли в записях подъёма (from, to) непрерывная цепочка was -> … -> now.

    Два `--allow-raise` подряд пишут 4->11 и 11->21; против origin/main (4) это подъём 4->21,
    записанный целиком, хотя пары (4, 21) в ленте нет.
    """
    reached, frontier = {was}, [was]
    while frontier:
        cur = frontier.pop()
        for frm, to in ledger:
            if frm == cur and to not in reached:
                if to == now:
                    return True
                reached.add(to)
                frontier.append(to)
    return False


def unrecorded_raises(old: dict, new: dict, measured: dict | None = None) -> list[str]:
    """Потолки, выросшие от `old` к `new` без записи в ленте `raises` нового baseline.

    Подъём записан, если в ленте есть непрерывная цепочка записей того же каталога (пути
    нормализованы) от прежнего потолка к новому, у каждой — непустое why.

    НОВЫЙ каталог (его нет в `old`) — решение #1128: подъёмом он не считается, но заводится ПО
    ФАКТУ. Если передан `measured` ({путь: текущий максимум}), потолок нового каталога выше факта —
    нарушение: иначе завести «новый» каталог с запасом было бы обходом ратчета. Без `measured`
    (сверка только двух файлов) новый каталог не проверяется.
    """
    before = {_norm_path(sc.get("path")): _ceiling(sc) for sc in old.get("scopes", []) or []}
    ledger: dict[str, list[tuple[int, int]]] = {}
    for r in new.get("raises", []) or []:
        if isinstance(r, dict) and str(r.get("why") or "").strip():
            ledger.setdefault(_norm_path(r.get("path")), []).append((r.get("from"), r.get("to")))
    facts = {_norm_path(k): v for k, v in (measured or {}).items()}
    problems = []
    for sc in new.get("scopes", []) or []:
        key, now = _norm_path(sc.get("path")), _ceiling(sc)
        if now is None:
            continue
        if key not in before:
            fact = facts.get(key)
            if measured is not None and fact is not None and now > fact:
                problems.append(f"{sc.get('path')}: новый каталог заведён с потолком {now} выше "
                                f"факта {fact} — новый потолок = текущий максимум")
            continue
        was = before[key]
        if was is None or now <= was or _chain_recorded(ledger.get(key, []), was, now):
            continue
        problems.append(f"{sc.get('path')}: потолок {was} -> {now} вырос без записи в raises "
                        f"(подъём — только через --baseline --allow-raise \"<обоснование>\")")
    return problems


def _allow_raise_arg(argv: list[str]) -> str | None:
    """Значение `--allow-raise <why>` / `--allow-raise=<why>`; флаг без значения -> ''."""
    for i, a in enumerate(argv):
        if a.startswith("--allow-raise="):
            return a.split("=", 1)[1]
        if a == "--allow-raise":
            nxt = argv[i + 1] if i + 1 < len(argv) else ""
            return "" if nxt.startswith("--") else nxt
    return None


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    baseline = load_baseline()
    scopes = iter_scopes(baseline)

    if "--report" in argv:
        for scope in scopes:
            funcs = measure_functions(scope["dir"])
            print(f"== {scope['path']} ==")
            print(render_report(funcs))
        return 0

    if "--baseline" in argv:
        code, msgs = rebaseline(allow_raise=_allow_raise_arg(argv))
        for m in msgs:
            print(m)
        return code

    errors = check_all(baseline)
    for e in errors:
        print(f"  [FAIL] {e}")
    for note in advise_all(baseline):
        print(f"  [WARN] {note}")
    if errors:
        print(f"FUNC-SIZE-FAIL: {len(errors)} нарушение(ий)")
        return 1
    for scope in scopes:
        funcs = measure_functions(scope["dir"])
        actual_max = max((f["size"] for f in funcs), default=0)
        print(f"FUNC-SIZE-OK: {scope['path']} max {actual_max} строк, в пределах потолка "
              f"({scope['spec'].get('max_function_lines')})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
