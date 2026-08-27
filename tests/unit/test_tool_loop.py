"""Unit tests for tools/tool_loop.py — action parsing and loop mechanics."""
from __future__ import annotations

import pytest

import tool_loop


@pytest.mark.unit
@pytest.mark.critical_path
class TestParseAction:
    """Tests for parse_action(): extracting JSON action proposals from model output."""

    def test_parse_action_valid_json(self):
        """Valid JSON embedded in text must be extracted."""
        result = tool_loop.parse_action('blah {"op":"read","path":"a.py"} blah')
        assert result["op"] == "read"
        assert result["path"] == "a.py"

    def test_parse_action_no_json(self):
        """Text with no JSON must return error."""
        result = tool_loop.parse_action("no json here at all")
        assert result.get("error") == "no-json"

    def test_parse_action_bad_json(self):
        """Malformed JSON (has braces but invalid content) must return bad-json error."""
        result = tool_loop.parse_action('{broken json "no colon"}')
        assert result.get("error") == "bad-json"

    def test_parse_action_dict_passthrough(self):
        """Dict input must be returned as-is (no parsing needed)."""
        action = {"op": "write", "path": "x.py", "content": "hello"}
        result = tool_loop.parse_action(action)
        assert result is action

    def test_parse_action_done(self):
        """Done action must be parsed correctly."""
        result = tool_loop.parse_action('{"done": true, "summary": "all done"}')
        assert result["done"] is True
        assert result["summary"] == "all done"

    def test_parse_action_empty_string(self):
        """Empty string must return no-json error."""
        result = tool_loop.parse_action("")
        assert result.get("error") == "no-json"

    def test_parse_action_none(self):
        """None input must return no-json error."""
        result = tool_loop.parse_action(None)
        assert result.get("error") == "no-json"


@pytest.mark.unit
@pytest.mark.critical_path
class TestRunLoop:
    """Tests for run_loop(): tool-calling loop mechanics with mock proposers."""

    @pytest.fixture
    def loop_deps(self, tmp_path):
        """Minimal setup: import tool_broker, create a policy and a temp root."""
        import tool_broker
        import budget as budget_mod

        root = tmp_path / "loop-root"
        root.mkdir()
        (root / "src").mkdir()
        (root / "f.txt").write_text("content", encoding="utf-8")
        policy = tool_broker.Policy(level="execution", write_scope=["src/"])
        return policy, root, budget_mod

    def test_run_loop_done_immediate(self, loop_deps):
        """Proposer returns done on first step -> loop stops immediately."""
        policy, root, budget_mod = loop_deps
        proposer = lambda ctx: {"done": True, "summary": "instant done"}
        report = tool_loop.run_loop(proposer, root, policy, budget={"max_model_calls": 5})
        assert report["stopped"] == "done"
        assert report["steps"] == 1
        assert report["model_calls"] == 1

    def test_run_loop_budget_exceeded(self, loop_deps):
        """Budget limit stops the loop."""
        policy, root, budget_mod = loop_deps
        # Proposer always returns a read action (never done)
        proposer = lambda ctx: {"op": "read", "path": "f.txt"}
        report = tool_loop.run_loop(proposer, root, policy, budget={"max_model_calls": 2})
        assert report["stopped"].startswith("budget")
        assert report["model_calls"] == 2

    def test_run_loop_max_steps(self, loop_deps):
        """max_steps acts as a safety limit."""
        policy, root, budget_mod = loop_deps
        proposer = lambda ctx: {"op": "read", "path": "f.txt"}
        report = tool_loop.run_loop(proposer, root, policy,
                                    budget={"max_model_calls": 100}, max_steps=3)
        assert report["stopped"] == "max_steps"
        assert report["steps"] == 3

    def test_run_loop_bad_proposals_stop(self, loop_deps):
        """N consecutive bad proposals stop the loop."""
        policy, root, budget_mod = loop_deps
        proposer = lambda ctx: {"error": "bad-json"}
        report = tool_loop.run_loop(proposer, root, policy,
                                    budget={"max_model_calls": 10},
                                    max_bad_proposals=3)
        assert report["stopped"].startswith("bad-proposal")

    def test_run_loop_write_outside_scope_denied(self, loop_deps):
        """Write outside write_scope must be denied by policy."""
        policy, root, budget_mod = loop_deps
        steps = iter([
            {"op": "write", "path": "outside/a.py", "content": "x"},
            {"done": True, "summary": "done"},
        ])
        proposer = lambda ctx: next(steps)
        report = tool_loop.run_loop(proposer, root, policy, budget={"max_model_calls": 5})
        assert report["stopped"] == "done"
        assert any(e["op"] == "write" for e in report["denied"])

    # ── Перенос из test_tool_loop_selftest.py: поведения, которых не было в гранулярном файле ──

    def test_run_loop_write_in_scope_creates_file(self, loop_deps):
        """Write внутри write_scope РЕАЛЬНО создаёт файл + в executed есть write ok=True."""
        policy, root, budget_mod = loop_deps
        steps = iter([
            {"op": "write", "path": "src/a.ts", "content": "hello"},
            {"done": True, "summary": "готово"},
        ])
        report = tool_loop.run_loop(lambda ctx: next(steps), root, policy,
                                    budget={"max_model_calls": 10})
        assert (root / "src" / "a.ts").exists()
        assert any(e["op"] == "write" and e["ok"] for e in report["executed"])

    def test_run_loop_write_outside_scope_not_created(self, loop_deps):
        """Write вне scope не только denied, но и физически НЕ создан на диске."""
        policy, root, budget_mod = loop_deps
        steps = iter([
            {"op": "write", "path": "config/x.yaml", "content": "y"},
            {"done": True, "summary": "готово"},
        ])
        report = tool_loop.run_loop(lambda ctx: next(steps), root, policy,
                                    budget={"max_model_calls": 10})
        assert not (root / "config" / "x.yaml").exists()
        assert any(e["op"] == "write" for e in report["denied"])

    def test_run_loop_shell_executed_as_evidence(self, loop_deps):
        """Shell-операция исполняется под execution-политикой как evidence (ok=True)."""
        policy, root, budget_mod = loop_deps
        steps = iter([
            {"op": "shell", "command": "echo ok"},
            {"done": True, "summary": "готово"},
        ])
        report = tool_loop.run_loop(lambda ctx: next(steps), root, policy,
                                    budget={"max_model_calls": 10})
        assert any(e["op"] == "shell" and e["ok"] for e in report["executed"])

    def test_run_loop_read_content_visible_in_context(self, loop_deps):
        """finding аудита: модель ВИДИТ содержимое прочитанного файла в контексте."""
        policy, root, budget_mod = loop_deps
        (root / "readme.txt").write_text("SENTINEL_CONTENT_42", encoding="utf-8")
        seen = {}

        def prop_read(ctx):
            seen["ctx"] = ctx
            if not seen.get("did_read"):
                seen["did_read"] = True
                return {"op": "read", "path": "readme.txt"}
            return {"done": True, "summary": "прочитал"}

        tool_loop.run_loop(prop_read, root, policy, budget={"max_model_calls": 5})
        assert "SENTINEL_CONTENT_42" in seen.get("ctx", "")

    def test_run_loop_recovers_after_bad_json(self, loop_deps):
        """Битый JSON дважды не убивает прогон: далее валидный write + done -> файл создан."""
        policy, root, budget_mod = loop_deps
        seq = iter([
            {"error": "bad-json"}, {"error": "bad-json"},
            {"op": "write", "path": "src/rec.ts", "content": "ok"}, {"done": True},
        ])
        report = tool_loop.run_loop(lambda c: next(seq), root, policy,
                                    budget={"max_model_calls": 10})
        assert report["stopped"] == "done"
        assert (root / "src" / "rec.ts").exists()

    def test_run_loop_bad_json_correction_hint_in_context(self, loop_deps):
        """Корректирующая подсказка про JSON («ОШИБКА РАЗБОРА») попадает в контекст переспроса."""
        policy, root, budget_mod = loop_deps
        cap = {}
        seq = iter([{"error": "bad-json"}, {"done": True}])

        def prop_corr(ctx):
            cap["ctx"] = ctx
            return next(seq)

        tool_loop.run_loop(prop_corr, root, policy, budget={"max_model_calls": 5})
        assert "ОШИБКА РАЗБОРА" in cap.get("ctx", "")

    def test_run_loop_read_cap_rejects_excess_reads(self, loop_deps):
        """Анти-флейл: чтение по кругу отклоняется после max_consecutive_reads (allowed=False, read-cap)."""
        policy, root, budget_mod = loop_deps
        report = tool_loop.run_loop(lambda c: {"op": "read", "path": "f.txt"}, root, policy,
                                    budget={"max_model_calls": 30}, max_steps=12,
                                    max_consecutive_reads=5)
        capped = [t for t in report["transcript"]
                  if not t.get("allowed") and "read-cap" in (t.get("reason") or "")]
        assert len(capped) > 0

    def test_run_loop_read_cap_does_not_affect_normal_flow(self, loop_deps):
        """Нормальный поток (2 read -> write -> done) не задет read-cap'ом."""
        policy, root, budget_mod = loop_deps
        norm = iter([{"op": "read", "path": "f.txt"}, {"op": "read", "path": "f.txt"},
                     {"op": "write", "path": "src/z.ts", "content": "z"}, {"done": True}])
        report = tool_loop.run_loop(lambda c: next(norm), root, policy,
                                    budget={"max_model_calls": 10}, max_consecutive_reads=5)
        assert report["stopped"] == "done"
        assert (root / "src" / "z.ts").exists()


@pytest.mark.unit
@pytest.mark.critical_path
class TestRunReview:
    """Tests for run_review(): независимый read-only ревьюер (writer ≠ judge)."""

    @pytest.fixture
    def review_deps(self, tmp_path):
        """Read-only политика + temp root с файлом для чтения."""
        import tool_broker

        root = tmp_path / "review-root"
        root.mkdir()
        (root / "src").mkdir()
        (root / "f.txt").write_text("content", encoding="utf-8")
        policy = tool_broker.Policy(level="read-only")
        return policy, root

    def test_run_review_terminal_pass(self, review_deps):
        """Терминальный вердикт pass возвращается (status=pass, gate=code_review)."""
        policy, root = review_deps
        rev = tool_loop.run_review(
            lambda c: {"kind": "reviewer-result", "gate": "code_review", "status": "pass",
                       "checks": [{"id": "logic", "status": "pass"}]},
            root, policy, "code_review", budget={"max_model_calls": 5})
        assert rev["result"] and rev["result"]["status"] == "pass"
        assert rev["result"]["gate"] == "code_review"

    def test_run_review_write_denied_readonly(self, review_deps):
        """Ревьюер под read-only не может писать: write отклонён, файл не создан, denied непуст."""
        policy, root = review_deps
        rev_seq = iter([{"op": "write", "path": "src/evil.ts", "content": "x"},
                        {"kind": "reviewer-result", "gate": "code_review", "status": "fail",
                         "checks": [{"id": "logic", "status": "fail"}], "blockers": ["баг в ветке"]}])
        rev = tool_loop.run_review(lambda c: next(rev_seq), root, policy, "code_review",
                                   budget={"max_model_calls": 5})
        assert rev["denied"]
        assert not (root / "src" / "evil.ts").exists()

    def test_run_review_fail_with_blockers(self, review_deps):
        """Вердикт fail несёт непустой blockers."""
        policy, root = review_deps
        rev_seq = iter([{"op": "write", "path": "src/evil.ts", "content": "x"},
                        {"kind": "reviewer-result", "gate": "code_review", "status": "fail",
                         "checks": [{"id": "logic", "status": "fail"}], "blockers": ["баг в ветке"]}])
        rev = tool_loop.run_review(lambda c: next(rev_seq), root, policy, "code_review",
                                   budget={"max_model_calls": 5})
        assert rev["result"]["status"] == "fail"
        assert rev["result"]["blockers"]

    def test_run_review_reviewer_sees_content(self, review_deps):
        """Ревьюер, прочитав файл, видит его содержимое в контексте вердикта (SENTINEL)."""
        policy, root = review_deps
        (root / "reviewme.txt").write_text("REVIEW_SENTINEL_7", encoding="utf-8")
        cap_r = {}
        rseq = iter([{"op": "read", "path": "reviewme.txt"},
                     {"kind": "reviewer-result", "gate": "code_review", "status": "pass",
                      "checks": [{"id": "x", "status": "pass"}]}])

        def rprop(ctx):
            cap_r["ctx"] = ctx
            return next(rseq)

        tool_loop.run_review(rprop, root, policy, "code_review", budget={"max_model_calls": 5})
        assert "REVIEW_SENTINEL_7" in cap_r.get("ctx", "")

    def test_run_review_no_verdict_returns_none(self, review_deps):
        """Ревьюер не вынес вердикт за лимит чтений -> result=None (честный не-pass)."""
        policy, root = review_deps
        rev = tool_loop.run_review(lambda c: {"op": "read", "path": "f.txt"}, root, policy,
                                   "code_review", budget={"max_model_calls": 20}, max_reads=3)
        assert rev["result"] is None

    def test_run_review_provider_refusal_is_named_not_crash(self, review_deps):
        """Провайдер судьи отказал (пусто/обрезано) -> run_review несёт названную причину, не падает.

        Прежде подъём ProviderRefusal из провайдера был бы неперехваченным (движок его не ловил);
        теперь run_review возвращает честный no-verdict с refusal-словарём для gate_executor."""
        from ai_ops_kit.providers.response_contract import ProviderRefusal
        policy, root = review_deps

        def refuses(_ctx):
            raise ProviderRefusal("empty_answer", "claude -p вернул пустой result",
                                  "claude-cli", "claude-code-local")

        rev = tool_loop.run_review(refuses, root, policy, "code_review",
                                   budget={"max_model_calls": 5})
        assert rev["result"] is None
        assert rev["stopped"].startswith("refusal")
        assert rev["refusal"]["reason"] == "empty_answer"
        assert rev["refusal"]["provider"] == "claude-cli"

    def test_run_review_force_verdict_after_reads(self, review_deps):
        """rc10: жадное чтение до лимита, затем на ФОРС-ХОДЕ выносится вердикт (не тихий no-verdict)."""
        policy, root = review_deps

        def greedy_then_verdict(c):
            if "ЛИМИТ ЧТЕНИЙ ИСЧЕРПАН" in c:
                return {"kind": "reviewer-result", "gate": "code_review", "status": "pass",
                        "checks": [{"id": "ok", "status": "pass"}]}
            return {"op": "read", "path": "f.txt"}

        rev = tool_loop.run_review(greedy_then_verdict, root, policy, "code_review",
                                   budget={"max_model_calls": 20}, max_reads=3)
        assert rev["result"] is not None
        assert rev["stopped"] == "verdict"
        assert len(rev["reads"]) == 3
