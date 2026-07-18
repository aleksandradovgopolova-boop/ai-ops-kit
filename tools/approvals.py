#!/usr/bin/env python3
"""ApprovalRecord + доменные human_approval_conditions (v2.115 Preflight Truth).

Аудит: human-approval был обычным boolean (`signals.human_approved`), который технически мог передать
любой вызывающий код, без автора/времени/scope/revision, и доменные `human_approval_conditions`
security-доменов НЕ исполнялись. Здесь — настоящая запись одобрения и её проверка.

ApprovalRecord (features/<wid>/approvals/*.yaml):
  kind: ApprovalRecord
  approval: <domain_id>          # secrets | dependencies | authentication | ...
  approved_by: user@example.com  # автор (не пусто)
  scope: package.json            # что именно одобрено
  revision: <sha|->              # к какой ревизии относится
  created_at: 2026-07-18T..
  reason: <зачем>                # обоснование (не пусто)

Проверка (детерминированно, по сигналам — до правок): для каждого security-домена, чей триггер-сигнал
взведён, требуется валидный ApprovalRecord для этого домена. Нет записи -> preflight блокирует
(человек не пройден). boolean `human_approved` больше НЕ достаточен для доменных условий.

Использование:
  approvals.py require --signals '{...}'                 # какие одобрения нужны
  approvals.py check <child_root> <wid> --signals '{...}'# что есть/чего не хватает
  approvals.py record <child_root> <wid> --approval secrets --by u@x --scope f --reason r [--revision sha]
  approvals.py --selftest
"""

import argparse
import json
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]

# Домен -> сигналы-триггеры, которые ДЕТЕРМИНИРОВАННО (по сигналам, до диффа) делают домен применимым
# и требующим человеко-одобрения. Для secrets/dependencies applicability.signals в доменах пуст (они
# ловятся по содержимому диффа), поэтому им заданы явные сигналы намерения.
_EXPLICIT_TRIGGERS = {
    "secrets": ["secret_boundary"],
    "dependencies": ["dependency_addition", "dependency_added", "new_dependency"],
}


def load_domains():
    import yaml
    d = yaml.safe_load((PKG / "security" / "security-domains.yaml").read_text(encoding="utf-8"))
    doms = d.get("domains") if isinstance(d, dict) else d
    return doms or []


def _domain_triggers(dom):
    """Сигналы, взводящие требование одобрения для домена: applicability.signals + явные триггеры."""
    sigs = list(((dom.get("applicability") or {}).get("signals")) or [])
    sigs += _EXPLICIT_TRIGGERS.get(dom["id"], [])
    return sigs


def required_approvals(signals, domains=None):
    """-> [{domain, condition, trigger}] для доменов с human_approval_conditions, чей триггер взведён."""
    signals = dict(signals or {})
    domains = domains if domains is not None else load_domains()
    out = []
    for dom in domains:
        ha = dom.get("human_approval_conditions")
        if not ha:
            continue
        trigger = next((s for s in _domain_triggers(dom) if signals.get(s)), None)
        if trigger:
            out.append({"domain": dom["id"], "condition": ha[0], "trigger": trigger})
    return out


def _approvals_dir(child_root, wid):
    return Path(child_root) / "features" / str(wid) / "approvals"


def load_approvals(child_root, wid):
    """Прочитать все ApprovalRecord из features/<wid>/approvals/*.yaml. -> [record]."""
    import yaml
    d = _approvals_dir(child_root, wid)
    recs = []
    if d.is_dir():
        for p in sorted(d.glob("*.yaml")):
            try:
                r = yaml.safe_load(p.read_text(encoding="utf-8"))
                if isinstance(r, dict) and r.get("kind") == "ApprovalRecord":
                    recs.append(r)
            except Exception:  # noqa: BLE001 — битую запись игнорируем (не считаем одобрением)
                pass
    return recs


def _record_valid(rec):
    """ApprovalRecord валиден, если несёт автора, scope и причину (не пустые). Иначе не одобрение."""
    return bool(rec.get("approval")) and bool(rec.get("approved_by")) \
        and bool(rec.get("scope")) and bool(rec.get("reason"))


def check(signals, child_root, wid, domains=None):
    """-> {ok, required[], satisfied[], missing[], records_seen}. missing непуст -> человек не пройден."""
    req = required_approvals(signals, domains=domains)
    recs = load_approvals(child_root, wid)
    valid_by_domain = {r["approval"] for r in recs if _record_valid(r)}
    satisfied, missing = [], []
    for r in req:
        if r["domain"] in valid_by_domain:
            satisfied.append(r)
        else:
            has_invalid = any(rc.get("approval") == r["domain"] for rc in recs)
            missing.append({**r, "reason": ("ApprovalRecord есть, но невалиден (нужны approved_by/scope/reason)"
                                            if has_invalid else "нет валидного ApprovalRecord")})
    return {"ok": not missing, "required": req, "satisfied": satisfied,
            "missing": missing, "records_seen": len(recs)}


def write_record(child_root, wid, approval, approved_by, scope, reason, revision="-", created_at=None):
    """Создать ApprovalRecord на диске (features/<wid>/approvals/<approval>.yaml). created_at обязателен
    в проде (передаётся вызывающим — детерминированность/отсутствие скрытого времени)."""
    import yaml
    d = _approvals_dir(child_root, wid)
    d.mkdir(parents=True, exist_ok=True)
    rec = {"schema_version": 1, "kind": "ApprovalRecord", "approval": approval,
           "approved_by": approved_by, "scope": scope, "revision": revision,
           "created_at": created_at or "unspecified", "reason": reason}
    p = d / f"{approval}.yaml"
    p.write_text(yaml.safe_dump(rec, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def selftest():
    import tempfile
    ok = True

    def expect(name, cond):
        nonlocal ok
        ok = ok and cond
        print(f"{'PASS' if cond else 'FAIL'} {name}")

    doms = load_domains()
    expect("домены загружены с human_approval_conditions",
           any(d.get("human_approval_conditions") for d in doms))

    # required: secret_boundary -> secrets; dependency_addition -> dependencies; auth_change -> auth+authz
    req_s = {r["domain"] for r in required_approvals({"secret_boundary": True})}
    expect("required: secret_boundary -> домен secrets", "secrets" in req_s)
    req_d = {r["domain"] for r in required_approvals({"dependency_addition": True})}
    expect("required: dependency_addition -> домен dependencies", "dependencies" in req_d)
    req_a = {r["domain"] for r in required_approvals({"auth_change": True})}
    expect("required: auth_change -> authentication + authorization", "authentication" in req_a and "authorization_idol" in req_a)
    expect("required: чистые сигналы -> одобрений не требуется", required_approvals({"task_type": "QUICK"}) == [])

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        sig = {"secret_boundary": True}
        # нет записи -> missing -> not ok
        c0 = check(sig, root, "wi")
        expect("check: требуется secrets, записи нет -> missing + ok=False",
               c0["ok"] is False and any(m["domain"] == "secrets" for m in c0["missing"]))
        # невалидная запись (без reason) -> всё ещё missing
        write_record(root, "wi", "secrets", approved_by="u@x", scope="config", reason="")
        c1 = check(sig, root, "wi")
        expect("check: невалидный ApprovalRecord (пустой reason) НЕ засчитан",
               c1["ok"] is False and "невалиден" in c1["missing"][0]["reason"])
        # валидная запись -> ok
        write_record(root, "wi", "secrets", approved_by="u@x", scope="config/secrets.py",
                     reason="ротация ключа согласована", created_at="2026-07-18T10:00:00Z")
        c2 = check(sig, root, "wi")
        expect("check: валидный ApprovalRecord -> ok=True", c2["ok"] is True and not c2["missing"])
        # запись не того домена не закрывает нужный
        c3 = check({"auth_change": True}, root, "wi")
        expect("check: запись secrets НЕ закрывает authentication",
               c3["ok"] is False and any(m["domain"] == "authentication" for m in c3["missing"]))

    print("approvals selftest:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    ap = argparse.ArgumentParser(prog="approvals.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rq = sub.add_parser("require"); rq.add_argument("--signals", default="{}"); rq.add_argument("--json", action="store_true")
    ck = sub.add_parser("check"); ck.add_argument("child_root"); ck.add_argument("wid")
    ck.add_argument("--signals", default="{}"); ck.add_argument("--json", action="store_true")
    rc = sub.add_parser("record"); rc.add_argument("child_root"); rc.add_argument("wid")
    rc.add_argument("--approval", required=True); rc.add_argument("--by", required=True)
    rc.add_argument("--scope", required=True); rc.add_argument("--reason", required=True)
    rc.add_argument("--revision", default="-"); rc.add_argument("--created-at")
    a = ap.parse_args(argv)
    if a.cmd == "require":
        req = required_approvals(json.loads(a.signals))
        print(json.dumps(req, ensure_ascii=False, indent=2) if a.json
              else ("нужны одобрения: " + (", ".join(r["domain"] for r in req) or "нет")))
        return 0
    if a.cmd == "check":
        res = check(json.loads(a.signals), Path(a.child_root), a.wid)
        if a.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print(f"APPROVALS: ok={res['ok']} · требуется {len(res['required'])} · не хватает {len(res['missing'])}")
            for m in res["missing"]:
                print(f"  ✗ {m['domain']}: {m['reason']} (условие: {m['condition']})")
        return 0 if res["ok"] else 1
    if a.cmd == "record":
        p = write_record(Path(a.child_root), a.wid, a.approval, a.by, a.scope, a.reason,
                         revision=a.revision, created_at=a.created_at)
        print(f"APPROVAL-RECORD: записан {p}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
