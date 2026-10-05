"""Agent loop tests with a scripted fake LLM (no network)."""

import json

import pytest

from quantsolve import agent, prompts
from quantsolve.config import Settings

GOOD = """
total = sum(range(1, 11))
assert total == 55, f"sum 1..10 should be 55, got {total}"
assert total == 10 * 11 // 2, "matches the closed form"
RESULT = {"total": total}
"""
CRASHING = GOOD.replace("assert total == 55", "assert totl == 55")
LOOPED = """
total = 0
for i in range(1, 11):
    total += i
assert total == 55, f"sum 1..10 should be 55, got {total}"
assert total == 10 * 11 // 2, "matches the closed form"
RESULT = {"total": total}
"""


class FakeLLM:
    """Returns scripted programs for SOLVE calls and canned replies for the rest."""

    def __init__(self, programs):
        self.programs = list(programs)
        self.solve_prompts: list[str] = []
        self.calls = 0

    def __call__(self, system, user, settings, usage, temperature=None):
        self.calls += 1
        usage.add(settings.model, 100, 50)
        if system == prompts.SOLVE_SYSTEM:
            self.solve_prompts.append(user)
            code = self.programs.pop(0) if len(self.programs) > 1 else self.programs[0]
            return {"thought": "Sum the integers and check with the closed form.", "code": code}
        if system == prompts.REFLECT_SYSTEM:
            return {"diagnosis": "A typo `totl` on line 3 caused a NameError.",
                    "reflection": "You should double-check variable names.",
                    "next_plan": "Use `total` consistently."}
        return {"answer": "The total is 55."}


@pytest.fixture
def settings():
    return Settings(max_attempts=3, timeout_s=5)


def run(monkeypatch, tmp_path, settings, programs, **kwargs):
    fake = FakeLLM(programs)
    monkeypatch.setattr(agent.llm, "chat_json", fake)
    events = []
    trace = agent.solve("Add the numbers 1..10.", settings=settings, runs_dir=tmp_path,
                        on_event=lambda kind, payload: events.append(kind), **kwargs)
    return trace, fake, events


def test_loop_heals_on_second_attempt_and_records_reflection(monkeypatch, tmp_path, settings):
    trace, fake, events = run(monkeypatch, tmp_path, settings, [CRASHING, GOOD])
    assert trace.success and len(trace.attempts) == 2
    first, second = trace.attempts
    assert first.observation["kind"] == "runtime" and first.observation["exc_type"] == "NameError"
    assert first.reflection and "NameError" in first.reflection["diagnosis"]
    assert second.observation["ok"] and trace.result == {"total": 55}
    # Reflexion memory and the observation are fed into the second SOLVE prompt
    assert "double-check variable names" in fake.solve_prompts[1]
    assert "NameError" in fake.solve_prompts[1]
    assert trace.final_answer == "The total is 55."
    assert trace.usage["calls"] == 4 and trace.usage["cost_usd"] > 0
    assert events[:4] == ["attempt_start", "action", "observation", "reflection"]
    assert events[-1] == "final"
    saved = json.loads((tmp_path / f"{trace.run_id}.json").read_text())
    assert saved["attempts"][0]["reflection"]["next_plan"] == "Use `total` consistently."


def test_loop_guard_nudges_after_identical_code(monkeypatch, tmp_path, settings):
    trace, fake, _ = run(monkeypatch, tmp_path, settings, [CRASHING])
    assert not trace.success and len(trace.attempts) == 3
    assert trace.attempts[1].nudge == agent.NUDGE_SAME_CODE
    assert "identical to an earlier attempt" in fake.solve_prompts[2]
    assert "No verified answer after 3 attempt(s)" in trace.final_answer
    assert trace.attempts[-1].reflection is None  # no reflection after the last attempt


def test_injected_logic_bug_is_caught_and_repaired(monkeypatch, tmp_path, settings):
    trace, _, _ = run(monkeypatch, tmp_path, settings, [LOOPED], inject="logic")
    first = trace.attempts[0]
    assert first.injected and "off-by-one" in first.injected
    assert first.llm_code == LOOPED.lstrip() and first.code != first.llm_code
    assert first.observation["kind"] == "assertion"
    assert trace.success and len(trace.attempts) == 2


def test_code_fingerprint_ignores_comments_and_whitespace():
    assert agent.code_fingerprint("x = 1  # one\n") == agent.code_fingerprint("x=1\n\n")
    assert agent.code_fingerprint("x = 1") != agent.code_fingerprint("x = 2")


def test_strip_fences():
    assert agent._strip_fences("```python\nx = 1\n```") == "x = 1\n"
    assert agent._strip_fences("x = 1") == "x = 1\n"


def test_error_signature_ignores_line_shifts():
    from quantsolve.sandbox import ExecutionResult
    a = ExecutionResult(False, "assertion", "x", exc_type="AssertionError", line=2)
    b = ExecutionResult(False, "assertion", "x", exc_type="AssertionError", line=3)
    code_a = "x = 1\nassert x == 2, 'x'\n"
    code_b = "# moved down\nx = 1\nassert x == 2, 'x'\n"
    assert agent.error_signature(a, code_a) == agent.error_signature(b, code_b)


def test_load_trace_finds_runs_in_archive_folders(tmp_path):
    (tmp_path / "archive_old").mkdir()
    (tmp_path / "archive_old" / "20260101-000000_demo.json").write_text('{"run_id": "x"}')
    assert agent.load_trace("20260101-000000_demo", tmp_path) == {"run_id": "x"}
    assert len(agent.list_runs(tmp_path)) == 0
    assert len(agent.list_runs(tmp_path, include_subdirs=True)) == 1


def test_usage_cost_uses_model_prices():
    from quantsolve.llm import Usage
    u = Usage()
    u.add("gpt-4.1-mini", 1_000_000, 1_000_000)
    u.add("gpt-4o-mini", 1_000_000, 1_000_000)
    assert abs(u.cost_usd - (0.40 + 1.60 + 0.15 + 0.60)) < 1e-9
