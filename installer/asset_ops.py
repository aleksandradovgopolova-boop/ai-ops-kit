"""Доставка ассетов в дочку: точка входа `./ai-ops`, адаптер коммуникации, CI-workflow'ы, .gitignore/.gitattributes, зоны `.ai/`, отчёт доставки, `validate` и долг доказательства.

Под-хаб установщика (вынесен из монолита `installer/ai_ops.py`). `installer/` — НЕ пакет: модуль
грузит фасад `installer/core.py` ленивым sibling-импортом и проставляет сюда живые глобалы
работающего экземпляра установщика (`_AO_NS`). Глобалы и мелкие хелперы установщика
(`PKG`/`AI_DIR`/`REPO_ROOT`/`MANAGED`/`CHILD_CONFIG`/`CI`, `ChildConfigError`, загрузчики сателлитов
`_plan_merge_setup`/`_ci_setup`/`_child_scaffolding`) читаются через `_ao()`; хаб-функции из ДРУГИХ
под-хабов — через `_core().X` (фасад находит нужный под-хаб). Функции этого же под-хаба зовутся по
имени. Дробление на под-хабы <700 строк держит хаб ниже ратчета размера модуля — монолит не
возрождается одним core.py.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve()
_AO_NS = None


class _AoView:
    """Атрибутный доступ (чтение и запись) к namespace-словарю установщика (`ai_ops.__dict__`)."""
    __slots__ = ("_d",)

    def __init__(self, d):
        object.__setattr__(self, "_d", d)

    def __getattr__(self, name):
        try:
            return self._d[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        self._d[name] = value


def _ao():
    """Модуль установщика через живой экземпляр, хранимый на ФАСАДЕ (`core._AO_NS`) — ЕДИНЫЙ источник
    истины. Своя копия `_AO_NS` замораживалась бы, если бы ссылку на функцию под-хаба кто-то закэшировал
    в обход фасадного `__getattr__` (так делает monkeypatch на фасаде в тестах) — тогда `_load` не
    переставил бы её, и под-хаб читал бы устаревший экземпляр установщика. Фасад же переставляется на
    КАЖДОМ обращении `ai_ops.__getattr__`/`_core()`."""
    if str(_HERE.parent) not in sys.path:
        sys.path.insert(0, str(_HERE.parent))
    import core
    ns = core._AO_NS
    if ns is not None:
        return _AoView(ns)
    import ai_ops
    return ai_ops


def _core():
    """Фасад хаба (installer/core.py) — маршрутизирует к соседним под-хабам."""
    return _ao()._core()


def _delivery_source(*rel):
    """Откуда брать доставляемый шаблон: ИЗ КИТА, и только потом из managed-слоя ребёнка.

    F-032 (поле 15.08.2026, подтверждён трижды, третий раз на ЧИСТОЙ установке 17.08.2026).
    Порядок здесь был ОБРАТНЫЙ — `MANAGED` первым, `PKG` как fallback, — и это ровно та причина, по
    которой `./ai-ops` в дочке «не обновлялся». Механика: шаги доставки выполняются ДО замены
    managed-файлов (так объявлено в `deliver_assets`), поэтому чтение managed-слоя давало шаблон
    ПРЕДЫДУЩЕЙ версии. Точка входа отставала ровно на один релиз — то есть исправление, влитое в
    кит, доезжало до владельца через обновление ПОСЛЕ следующего, а до тех пор в дочке лежали обе
    версии: свежий шаблон в managed и старая обёртка в корне.
    Функция `deliver_assets` при этом ОБЪЯВЛЯЛА обратное: «читают ИСХОДНИК кита (templates/, docs/,
    registry/), а не managed-слой ребёнка». Утверждение было верным для всех шагов, кроме трёх,
    и именно эти три доставляли то, что владелец видит первым.

    Fallback на managed оставлен и не бесполезен: установщик запускают и из распакованного
    managed-слоя (`.ai/managed/installer` в старых дочках), где `PKG` указывает не туда.
    """
    for base in (_ao().PKG, _ao().MANAGED):
        cand = base.joinpath(*rel)
        if cand.is_file():
            return cand
    return _ao().PKG.joinpath(*rel)


ENTRY_NAME = "ai-ops"


def _install_entry_point(root: Path, dry=False):
    """Положить в репозиторий ЗАПУСКАЕМЫЙ `./ai-ops` из шаблона (v3.35.1).

    Все подсказки кита печатали `ai-ops …`, а такой команды не существовало: ни `console_scripts`
    (в продуктовый репозиторий кит ставится копированием, а не через pip), ни файла. Владелец
    копировал строку из первого же сообщения и получал `command not found` — обещание слоя
    коммуникации «в каждом сообщении сказано, что дальше» ломалось на первой команде.

    Обёртка, а не запись в PATH: PATH не наша зона, а `./ai-ops` работает сразу и переживает clone.
    -> {"action": created|updated|unchanged|skipped-no-template, "path": str|None}
    """
    src = _delivery_source("templates", "runtime", "ai-ops-entry.sh")
    if not src.is_file():
        return {"action": "skipped-no-template", "path": None}
    body = src.read_text(encoding="utf-8")
    dst = root / ENTRY_NAME
    old = dst.read_text(encoding="utf-8") if dst.is_file() else ""
    action = "unchanged" if old == body else ("updated" if old else "created")
    if not dry and action != "unchanged":
        dst.write_text(body, encoding="utf-8")
    if not dry:
        try:
            dst.chmod(0o755)
        except OSError:
            pass
    return {"action": action, "path": str(dst)}


COMM_MARK_BEGIN = "<!-- AI-OPS-COMMUNICATION-POLICY:BEGIN — управляется китом, не править вручную -->"
COMM_MARK_END = "<!-- AI-OPS-COMMUNICATION-POLICY:END -->"


def _install_communication_adapter(root: Path, dry=False):
    """v3.35: политика коммуникации ДОЕЗЖАЕТ до runtime — блок в `CLAUDE.md` репозитория.

    Прежде адаптер `claude-code-memory` был объявлен в `registry/communication-policy.yaml` («Claude
    Code подхватывает его автоматически») и шаблон обещал «правьте политику и перегенерируйте», но
    ни одна строка кода блок не доставляла: он лежал статическим файлом в managed-слое и в CLAUDE.md
    не попадал никогда. Объявленный адаптер без доставки — то же, что capability без реализации.

    ИДЕМПОТЕНТНО и БЕЗОПАСНО: блок ограничен маркерами, повторный запуск ЗАМЕНЯЕТ только его, текст
    пользователя вне маркеров не трогается никогда. Это и есть «перегенерация», которую обещал
    шаблон: правишь политику -> `./ai-ops update` -> блок обновлён, остальное на месте.
    -> {"action": created|updated|unchanged|skipped-no-template, "path": str}
    """
    src = _delivery_source("templates", "runtime", "claude-communication.md")
    if not src.is_file():
        return {"action": "skipped-no-template", "path": None}
    body = src.read_text(encoding="utf-8").strip()
    block = f"{COMM_MARK_BEGIN}\n{body}\n{COMM_MARK_END}\n"
    dst = root / "CLAUDE.md"
    old = dst.read_text(encoding="utf-8") if dst.is_file() else ""
    if COMM_MARK_BEGIN in old and COMM_MARK_END in old:
        head, _, rest = old.partition(COMM_MARK_BEGIN)
        _, _, tail = rest.partition(COMM_MARK_END)
        new = head + block + tail.lstrip("\n")
        action = "unchanged" if new == old else "updated"
    else:
        new = (old.rstrip("\n") + "\n\n" + block) if old.strip() else block
        action = "updated" if old.strip() else "created"
    if not dry and new != old:
        dst.write_text(new, encoding="utf-8")
    return {"action": action, "path": str(dst)}


def deliver_assets(root: Path = None, refresh_ci: bool = False) -> dict:
    """Привести ассеты ребёнка в соответствие с китом. -> отчёт по каждому шагу.

    ОДНО МЕСТО, ГДЕ ЖИВЁТ ДОСТАВКА. Шаги были размазаны по `cmd_update` и `cmd_init`, часть — за
    ранним выходом «обновление не требуется», часть только в `init`. Из-за этого исправленный
    шаблон CI не доехал ни до одного ребёнка, а зоны `.ai/` не переживали клон. Теперь и установка,
    и обновление зовут одно и то же, а значит расхождение между ними невозможно по построению.

    Все шаги идемпотентны и читают ИСХОДНИК кита (templates/, docs/, registry/), а не managed-слой
    ребёнка, — поэтому вызываются до замены managed-файлов.
    """
    root = Path(root or _ao().REPO_ROOT)
    return {
        # `root` явно: backfill обязан писать в ПЕРЕДАННЫЙ корень, а не в модульный AI_DIR
        # (= Path.cwd()). Без этого `deliver_assets(<чужой корень>)` in-process сеял контекст в
        # корень рабочего репозитория кита — единственный доставляющий шаг, писавший мимо цели.
        "context_backfilled": _ao()._child_scaffolding()._backfill_required_context(root),
        "ci_workflows": _ao()._ci_setup().sync_ci_workflows(root, refresh=refresh_ci),
        "zone_markers": ensure_zone_markers(root),
        # Здесь, а не в `cmd_init`: иначе существующие дочки — те самые, на которых находка и
        # случилась, — не получили бы правило никогда. Функция идемпотентна, повторный update
        # молчит.
        "gitignore": ensure_gitignore(root),
        # Рядом с `gitignore` и по той же причине: существующие дочки — те, на которых находка
        # и случилась, — получают правило обновлением, а не переустановкой.
        "gitattributes": ensure_gitattributes(root),
        # Атрибут merge=ai-ops-plan без записи в git config бездействует — прописываем драйвер локально.
        "plan_merge_driver": _ao()._plan_merge_setup().ensure_plan_merge_driver(root),
        "entry_point": _install_entry_point(root),
        "communication_adapter": _install_communication_adapter(root),
        # ДО посева планирования (SR-2): перенести заполненный уходящий `.ai-ops/ROADMAP.md` в
        # канонический корень, иначе посев дал бы пустой корневой поверх заполненного уходящего.
        "roadmap_migrated": _ao()._child_scaffolding()._migrate_legacy_roadmap(root),
        # ДО посева (SR-7): перенести заполненные уходящие context/system/* в ARCHITECTURE.md,
        # иначе посев дал бы пустой канонический поверх заполненного архитектурного знания.
        "architecture_migrated": _ao()._child_scaffolding()._migrate_legacy_architecture(root),
        "planning_seeded": _ao()._child_scaffolding()._seed_planning_contour(root),
        # PR-3: Product Operating Layer `.ai-ops/` (Passport из фактов, ROADMAP/DELIVERY/POLICY из
        # официальных шаблонов, templates/ — копия версий кита). Читает состав из реестра артефактов.
        "product_layer_seeded": _ao()._child_scaffolding()._seed_product_layer(root),
    }


def _assets_report_line(assets: dict) -> str:
    """Что доставлено — словами. -> кусок сообщения (пустой, если всё и так было на месте)."""
    out = ""
    created = [b["doc"] for b in (assets.get("context_backfilled") or [])
               if b.get("action") == "created-draft"]
    if created:
        out += (" Back-fill контекста (черновики status: draft): " + ", ".join(created) + ".")
    out += _ao()._ci_setup()._ci_report_line(assets.get("ci_workflows") or [])
    if assets.get("zone_markers"):
        out += ("\nПустые зоны `.ai/` получили README, чтобы раскладка пережила клон: "
                + ", ".join(assets["zone_markers"]) + ".")
    # Названо, а не сделано молча: `.gitignore` — документ владельца, и дописку в него он обязан
    # увидеть в отчёте, а не обнаружить в диффе.
    if assets.get("gitignore") in ("created", "appended"):
        out += ("\n`.gitignore` " + ("создан" if assets["gitignore"] == "created" else "дополнен")
                + ": служебное состояние кита (.ai/worktrees/, runtime-локи и active-work,"
                  " локальный учёт стоимости, кеши, байткод, записанные замечания о ките)"
                  " скрыто от git."
                  " Продуктовые артефакты кита не затронуты.")
    # Та же причина, что у `.gitignore`: дописка в документ владельца обязана быть в отчёте.
    if assets.get("gitattributes") in ("created", "appended"):
        out += ("\n`.gitattributes` " + ("создан" if assets["gitattributes"] == "created"
                                        else "дополнен")
                + ": журналы отчётов (.ai/project/report-history/*.jsonl) сводятся при слиянии"
                  " сами — они дописываются, а не переписываются. А planning/plan.yaml получил"
                  " понимающий структуру merge-driver (см. ниже).")
    out += _ao()._plan_merge_setup().plan_merge_report_line(assets.get("plan_merge_driver"))
    if (assets.get("communication_adapter") or {}).get("action") in ("created", "updated"):
        out += ("\nПолитика общения подключена к runtime (блок в CLAUDE.md между маркерами; "
                "текст вне них не тронут).")
    migrated = [x["artifact"] for x in (assets.get("roadmap_migrated") or [])
                if x.get("action") == "migrated-from-legacy"]
    if migrated:
        out += ("\nНаправление продукта перенесено в " + ", ".join(migrated)
                + ": прежний путь в `.ai-ops/` уходит, чтобы направление жило в одном месте. "
                  "Содержимое сохранено, старый файл не удалён.")
    arch_migrated = [x["artifact"] for x in (assets.get("architecture_migrated") or [])
                     if x.get("action") == "migrated-from-legacy"]
    if arch_migrated:
        out += ("\nАрхитектура собрана в ARCHITECTURE.md из прежних context/system/*: "
                "единый источник правды об архитектуре. Содержимое сохранено, старые файлы не удалены.")
    seeded = [x["artifact"] for x in (assets.get("planning_seeded") or [])
              if x.get("action") == "created-draft"]
    if seeded:
        out += ("\nBack-fill модели продукта (черновики, заполнить вам): " + ", ".join(seeded)
                + ". Дальше: `./ai-ops model` покажет, что кит понял о проекте, и спросит "
                  "недостающее одним пакетом.")
    # Реальный документ уже есть в НЕ-каноничном месте — черновик НЕ сеяли. Называем владельцу и
    # предлагаем перенос по его слову (propose, not impose): переносить и перезаписывать не вправе.
    existing = [(x["artifact"], x["action"].split("existing-at:", 1)[1])
                for x in (assets.get("planning_seeded") or [])
                if str(x.get("action", "")).startswith("existing-at:")]
    for artifact, where in existing:
        out += (f"\n{artifact}: черновик НЕ создавал — этот документ у вас уже есть в `{where}`. "
                f"Канонический стандарт кита держит его в корне (`{artifact}`); перенести в одно "
                f"место подготовлю по вашему слову — сам не переношу и не перезаписываю.")
    pl = assets.get("product_layer_seeded") or []
    made = [x["artifact"] for x in pl if x.get("action") in ("created", "generated")]
    if made:
        gen = [x["artifact"] for x in pl if x.get("action") == "generated"]
        out += ("\nProduct Operating Layer создан (`.ai-ops/`): " + ", ".join(made) + "."
                + (f" Product Passport собран из фактического состояния репозитория; проверьте "
                   f"разделы, помеченные «неизвестно» — их знает только владелец." if gen else ""))
    return out


# ── CI-workflow'ы ребёнка: доставка исправлений ───────────────────────────────────────────────
# Файлы принадлежат киту (`ai-ops-*.yml`), но живут в `.github/workflows/` ребёнка. До 3.36.2 они
# копировались ТОЛЬКО в `init` и только когда файла ещё нет: `update` их не касался вовсе. Значит
# исправление шаблона не доезжало НИ ДО ОДНОГО уже подключённого репозитория — что и обнаружилось
# на back-fill 3.36.1, где кит починил путь валидатора у себя, а у ребёнка остался сломанный CI.
#
# Молча перезаписывать файл в чужом `.github/` тоже нельзя: владелец вправе его править. Поэтому
# кит трогает только то, что САМ написал и что с тех пор никто не менял — это знание хранится
# отпечатком. Остальное он НАЗЫВАЕТ, а решение оставляет человеку.
CI_TEMPLATES = ("ai-ops-update.yml", "ai-ops-record.yml", "ai-ops-validate.yml", "ai-ops-audit.yml",
                # Набор supply-chain / OpenSSF (#608). ФОРДЖ-конфигурация дочки, не код кита: инвариант
                # «никаких новых рантайм-зависимостей у инструментов» относится к движку, а эти файлы
                # подключают GitHub-нативные механизмы. Доставляются как остальные (опт-аут = удалить
                # файл), но ADVISORY по построению — блокирующими их делает владелец, не кит. Разбор
                # границы и настроек репозитория — в `templates/ci/SUPPLY-CHAIN.md`.
                "dependabot.yml",        # Dependency-Update-Tool; кладётся в .github/, не в workflows/
                "ai-ops-codeql.yml",     # SAST
                "ai-ops-secret-scan.yml",# секрет-скан (бэкстоп к нативному push protection)
                "ai-ops-sbom.yml",       # SBOM + подписанные релизы (Sigstore attestations)
                "ai-ops-scorecard.yml",  # агрегатный сигнал OpenSSF Scorecard
                # УСЛОВНЫЙ (см. CONDITIONAL_CI_TEMPLATES): едет ТОЛЬКО UI-продукту. Превью Storybook в
                # PR как CI-артефакт статической сборки — без внешних сервисов/секретов. Бэкенд-репо
                # его не получает (нечего собирать), поэтому доставка гейтится по корню дочки.
                "ai-ops-storybook-preview.yml")

# УСЛОВНЫЕ CI-workflow: имя -> имя предиката в ci_setup (`_CONDITIONAL_CI`). Безусловные едут всем
# дочкам; условные — только тем, для кого предикат по корню истинен. storybook-preview едет лишь
# UI-продукту (есть Storybook-конфиг/зависимость/скрипт): иначе он сорил бы workflow'ом в репозиторий,
# где Storybook нет. Гейт живёт в сателлите ci_setup (там же итерация доставки), здесь — только объявление.
CONDITIONAL_CI_TEMPLATES = ("ai-ops-storybook-preview.yml",)
# Куда ложится шаблон в дочке ОТНОСИТЕЛЬНО `.github/`. По умолчанию — `workflows/<name>`; исключение —
# Dependabot, который GitHub читает ТОЛЬКО из `.github/dependabot.yml`. Источник всегда `templates/ci/<name>`.
CI_TEMPLATE_DEST = {"dependabot.yml": ("dependabot.yml",)}
# Путь отпечатков считается ОТ ПЕРЕДАННОГО КОРНЯ, а не от глобального REPO_ROOT. Первая версия
# брала глобальный — и `sync_ci_workflows(other_root)` писал отпечатки в текущий репозиторий, а не
# в тот, который обслуживал. Поймано тем, что в коммит кита попал чужой `.ai/runtime/ci-templates.json`.
CI_PRINTS_REL = ".ai/runtime/ci-templates.json"
# Клон кита в workflow ребёнка: и новая форма (`$RUNNER_TEMP`), и старая (`/tmp`) — иначе проверка
# не увидит именно те файлы, ради которых написана: у всех подключённых детей там стоит `/tmp`.
_KIT_PATH_RE = re.compile(r'(?:"?\$\{?RUNNER_TEMP\}?"?|/tmp)/ai-ops-kit/([\w./-]+)')


# Зоны `.ai/`: пустой каталог git НЕ хранит, поэтому после клона его нет — и child-валидатор
# справедливо говорит «нет зоны custom/». Локально всё выглядело целым (каталог на диске есть),
# а в CI ребёнка установка была неполной. Заметили это в первый же прогон, который наконец
# запустился: до 3.36.2 child-CI падал раньше, на несуществующем пути валидатора.
_ZONE_WHY = {
    "custom": "Оверлей: ваши правки поверх managed-слоя. Кит сюда не пишет и это не перезаписывает.",
    "project": "Факты о продукте, которые дал человек (ответы онбординга, подтверждения).",
    "generated": "Сгенерированное китом: команды runtime, промпты. Правится генератором, не руками.",
    "runtime": "Рабочее состояние прогонов: отчёты, снимки, бэкапы. В историю обычно не нужно.",
}


_GITIGNORE_MARK = "# --- AI Ops Kit: служебное состояние (не история продукта) ---"

# Правила ЗАМЕРЕНЫ, а не выписаны по вкусу. Каждая строка — то, что в поле реально пыталось уехать
# в коммит владельца (находка ии-среды 2026-08-12, F-021), либо то, что кит уже спрятал у себя
# (`.ai/repository-profile.yaml` — R-11 ревизии 2026-08-11), либо объявленная граница репозитория
# (байткод в checksummed managed-слое — tests/unit/test_installer.py).
_GITATTRIBUTES_MARK = "# --- AI Ops Kit: журналы дописываются, а не переписываются ---"

_GITATTRIBUTES_RULES = """
# ЗАМЕР ПОТРЕБИТЕЛЯ (заявка #148, ИИ-Среда, 17.08.2026): `.ai/project/report-history/<фича>.jsonl`
# правился 12 раз за неделю и давал РУЧНОЙ конфликт при слиянии — при том что файл append-only по
# построению. КОРЕНЬ УБРАН ШАРДИРОВАНИЕМ ПО ПРОГОНУ (#148, 04.09.2026): `run_report --record` больше
# не дописывает в общий файл, а пишет каждый прогон отдельным `report-history/<фича>/<run-id>.jsonl`
# (`lifecycle/run_report.py -> record_report`) — параллельные прогоны попадают в РАЗНЫЕ файлы, и их
# коммиты не конфликтуют. Правило ниже остаётся страховкой для СТАРОГО плоского `<фича>.jsonl`,
# который ещё может лежать в давно заведённых дочках: там git сведёт строки сам.
#
# ПОЧЕМУ ТОЛЬКО JSONL-ЖУРНАЛЫ ИДУТ ЧЕРЕЗ union. `union` склеивает СТРОКИ, а не структуру: на
# `decisions/registry.yaml` он дал бы синтаксически битый или удвоенный документ. Такие структурные
# файлы здесь через union не идут.
.ai/project/report-history/*.jsonl merge=union

# СТРУКТУРНЫЙ ПЛАН (#148). `planning/plan.yaml` (самый правимый файл кита) union НЕЛЬЗЯ — склеил бы
# строки в битый YAML. У него отдельный ПОНИМАЮЩИЙ СТРУКТУРУ merge-driver: непересекающиеся правки
# сводит сам, на сомнении отдаёт обычный конфликт (см. installer/plan_merge_setup.py). Драйвер
# прописывает в git config `ensure_plan_merge_driver`; без записи атрибут бездействует (built≠wired).
planning/plan.yaml merge=ai-ops-plan
"""

_GITIGNORE_RULES = """
# Кит ставится в чужой репозиторий и обязан не сорить в его истории. Ниже — только то, что
# наблюдалось уезжающим в коммит, и только служебное: рабочее состояние прогона, локальные
# кеши и байткод. Продуктовые артефакты кита (features/**, .ai/project/**, .ai/managed/**,
# .ai/custom/**) НЕ игнорируются — они и есть то, ради чего кит стоит.

# Вложенный git-репозиторий изолированного прогона: `git add -A` берёт его как gitlink,
# и в истории появляется ссылка на дерево, которого ни у кого больше нет.
.ai/worktrees/

# Координация параллельных сессий и локи — состояние ЭТОЙ машины, не факт о продукте.
.ai/runtime/active-work.yaml
.ai/runtime/*.lock
.ai/runtime/**/*.lock

# Транзакционный бэкап managed-слоя и отчёт последнего обновления. ЗАМЕР (F-022, живая проверка на
# дочке): без этих двух строк подготовленный update-PR содержал 612 файлов, из которых 609 — копия
# managed-слоя из бэкапа. Настоящих изменений было два (`.ai-ops.yaml` и `.provenance.json`).
# Дифф, который нельзя отсмотреть, — это тот же ложный green: «отревьюено» превращается в
# «пролистано».
.ai/runtime/backups/
.ai/runtime/last-update-report.json

# Локальный учёт стоимости прогонов: цифры этой машины, а не общий факт. ЕДИНСТВЕННОЕ правило
# здесь, о котором можно спорить: если команде нужна общая история стоимости — снимите эту
# строку, и ledger начнёт коммититься. Остальные строки спорными не являются.
.ai/usage/*.jsonl

# Кеш переоценки гейтов: по построению безвреден к утрате — не нашли, значит пересчитаем.
.ai/reevaluate-evidence-*.json

# Машинный кеш детекции стека (кит прячет его и у себя).
.ai/repository-profile.yaml

# Байткод внутри checksummed managed-слоя: ломает сверку и уезжает по `git add -A`.
.ai/managed/**/__pycache__/
.ai/**/*.py[co]

# Наблюдения о САМОМ КИТЕ и их состояние. ЗАМЕР (проба канала на живой дочке, 18.08.2026): первая же
# запись легла неотслеживаемой и НЕигнорируемой — то есть в худшем из состояний: git-гигиене её не
# видно, а чужой `git add -A` унёс бы её в посторонний коммит (так уже уезжал файл 12.08). Выбрано
# игнорировать, а не отслеживать: кит обязан не сорить в истории продукта, а доставленная копия
# наблюдения лежит В КИТЕ (`findings/from-children/`) и там отслеживается — знание не теряется.
# ЦЕНА НАЗВАНА: записи локальны для машины, на которой их сделали; общая для команды история
# наблюдений о ките — отдельное решение владельца, как и со строкой про ledger выше.
.ai/kit-feedback/

# СОЗНАТЕЛЬНО НЕ ВНЕСЕНО: `.ai/generated/` (манифест зовёт его isolated, но некоторым
# репозиториям сгенерированные команды runtime нужны в истории — это решение владельца) и
# `.ai/project/report-history/` (её коммитит workflow ai-ops-record: это история эффекта).
"""


def ensure_gitignore(root: Path = None):
    """Спрятать служебное состояние кита от git дочки. -> "created" | "appended" | "present".

    ПОЧЕМУ ЭТО ДЕЛАЕТ УСТАНОВЩИК (находка ии-среды 2026-08-12, F-021). Кит не писал в дочку
    `.gitignore` вовсе, и это было объявленной границей — она записана в
    `tests/unit/test_installer.py` («`.gitignore` установщик в дочку не пишет, поэтому байткод в
    managed уехал бы в коммит владельца по `git add -A`»). В поле граница обошлась дорого: за один
    прогон в коммит владельца дважды пытались уехать `.ai/worktrees/` (как вложенный репозиторий),
    `.ai/runtime/active-work.yaml` и `.lock`, `.ai/usage/product-ledger.jsonl`,
    `.ai/reevaluate-evidence-*.json`. Owner чинил это руками в своём репозитории — то есть
    становился техническим оператором кита, а это ровно та метрика, которую квалификация считает.

    Правила ДОПИСЫВАЮТСЯ отмеченным блоком и никогда не переписывают чужой файл: `.gitignore` —
    документ владельца, а не наша зона. Повторный вызов ничего не делает (маркер уже есть), поэтому
    `init` и `update` могут звать функцию свободно.
    """
    root = Path(root or _ao().REPO_ROOT)
    path = root / ".gitignore"
    block = f"{_GITIGNORE_MARK}\n{_GITIGNORE_RULES.strip()}\n"
    if not path.exists():
        path.write_text(block, encoding="utf-8")
        return "created"
    current = path.read_text(encoding="utf-8")
    if _GITIGNORE_MARK in current:
        return "present"
    sep = "" if current.endswith("\n\n") else ("\n" if current.endswith("\n") else "\n\n")
    path.write_text(current + sep + block, encoding="utf-8")
    return "appended"


def ensure_gitattributes(root: Path = None):
    """Сказать git, что журналы кита дописываются. -> "created" | "appended" | "present".

    ПОЧЕМУ ЭТО ДЕЛАЕТ УСТАНОВЩИК. Файл append-only, а конфликт при слиянии — ручной: у потребителя
    один и тот же конфликт разрешался пять раз за час, по разу на каждую задетую ветку (#148, #150).
    Кит сам создаёт эти журналы и сам знает их природу, поэтому и сказать о ней должен он, а не
    владелец, который о `merge=union` узнаёт в момент конфликта.

    Правила ДОПИСЫВАЮТСЯ отмеченным блоком и никогда не переписывают чужой файл: `.gitattributes` —
    документ владельца, как и `.gitignore`. Повторный вызов ничего не делает (маркер уже есть),
    поэтому `init` и `update` могут звать функцию свободно.

    ГРАНИЦА: `union` — ТОЛЬКО для JSONL-журналов. `planning/plan.yaml` идёт через отдельный
    merge-driver `merge=ai-ops-plan` (понимает структуру, на сомнении — обычный конфликт).
    """
    root = Path(root or _ao().REPO_ROOT)
    path = root / ".gitattributes"
    block = f"{_GITATTRIBUTES_MARK}\n{_GITATTRIBUTES_RULES.strip()}\n"
    if not path.exists():
        path.write_text(block, encoding="utf-8")
        return "created"
    current = path.read_text(encoding="utf-8")
    if _GITATTRIBUTES_MARK in current:
        return "present"
    sep = "" if current.endswith("\n\n") else ("\n" if current.endswith("\n") else "\n\n")
    path.write_text(current + sep + block, encoding="utf-8")
    return "appended"


def ensure_zone_markers(root: Path = None):
    """Положить в пустые зоны `.ai/` файл-маркер, чтобы раскладка пережила клон. -> список путей.

    Не `.gitkeep`, а README с ОБЪЯСНЕНИЕМ зоны: файл всё равно попадёт в чужой репозиторий, и
    пусть он тогда отвечает на вопрос «что это за папка», а не молчит.
    """
    root = Path(root or _ao().REPO_ROOT)
    made = []
    for zone, why in _ZONE_WHY.items():
        d = root / ".ai" / zone
        if not d.is_dir():
            continue
        if any(p.name != ".gitkeep" for p in d.iterdir()):
            continue                                    # в зоне есть содержимое — маркер не нужен
        marker = d / "README.md"
        if marker.exists():
            continue
        marker.write_text(f"# .ai/{zone}\n\n{why}\n\n"
                          f"Файл создан AI Ops, чтобы каталог пережил клон: git не хранит пустые\n"
                          f"каталоги, и без него установка после `git clone` выглядит неполной.\n",
                          encoding="utf-8")
        made.append(marker.relative_to(root).as_posix())
    return made


def _tracked_by_git(path: Path) -> bool:
    """Лежит ли файл под контролем git — тогда прежнее содержимое уже сохранено историей."""
    try:
        r = subprocess.run(["git", "-C", str(path.parent), "ls-files", "--error-unmatch",
                            path.name], capture_output=True, text=True)
    except OSError:
        return False
    return r.returncode == 0


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_git_worktree(root: Path):
    """Находится ли root внутри рабочего дерева git. False и когда git не установлен."""
    try:
        r = subprocess.run(["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
                           capture_output=True, text=True)
    except OSError:
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def cmd_validate(argv=()):
    # `ai-ops validate product-layer` (PR-5): отчёт Missing/Invalid/Outdated/Valid по `.ai-ops/`
    # ЭТОЙ дочки. Отдельная под-команда: общий `validate` проверяет установку кита, а этот —
    # продуктовые артефакты репозитория, и смешивать их вывод значило бы прятать одно за другим.
    if argv and argv[0] == "product-layer":
        for root in (_ao().AI_DIR / "managed", _ao().PKG):
            if (root / "ai_ops_kit" / "validation" / "validate_product_layer.py").is_file():
                if str(root) not in sys.path:
                    sys.path.insert(0, str(root))
                break
        from ai_ops_kit.validation import validate_product_layer as _vpl
        return _vpl.main([str(_ao().REPO_ROOT), *[a for a in argv[1:] if a.startswith("--")]])
    checks = [["validate_ai_ops_child.py"], ["validate_ai_first_registry.py"],
              ["validate_ai_first_workflows.py"], ["validate_ai_first_providers.py"],
              ["validate_openspec_change.py"]]
    results = _core().run_validators(checks)
    for r in results:
        print(f"  {'PASS' if r['status']=='pass' else 'FAIL'}  {r['check']}")
    return 0 if all(r["status"] == "pass" for r in results) else 1


# ── Долг доказательства поставки (правило 3.27.4 для исторически выпущенных функций) ──────────
DEBT_REL = ".ai/project/delivery-proof-debt.yaml"


def _released_without_proof(root: Path = None):
    """Функции со `status: released` без SHA-verified DeliveryReceipt. -> список id.

    Считаем ФАКТ по репозиторию, а не по списку в файле: иначе долг мог бы разойтись с реальностью
    в обе стороны — и закрытый остался бы висеть, и новый не появился бы.
    """
    root = Path(root or _ao().REPO_ROOT)
    out = []
    for bp in sorted((root / "features").glob("*/blueprint.yaml")):
        try:
            data = yaml.safe_load(bp.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        feat = data.get("feature") or {}
        if feat.get("status") != "released":
            continue
        fid = str(feat.get("id") or bp.parent.name)
        proven = False
        for rp in (bp.parent / "delivery-receipt.yaml",
                   root / ".ai" / "runtime" / "delivery" / fid / "receipt.yaml"):
            if not rp.is_file():
                continue
            try:
                r = yaml.safe_load(rp.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            if r.get("kind") == "DeliveryReceipt" and r.get("sha_verified") is True:
                proven = True
                break
        if not proven:
            out.append(fid)
    return out


def _debt_recorded(root: Path = None):
    """Уже признанный долг: {id: запись}. Пустой словарь, если файла нет или он не тот."""
    p = Path(root or _ao().REPO_ROOT) / DEBT_REL
    if not p.is_file():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    if data.get("kind") != "DeliveryProofDebt":
        return {}
    return {str(f.get("id")): f for f in (data.get("features") or []) if isinstance(f, dict)}
