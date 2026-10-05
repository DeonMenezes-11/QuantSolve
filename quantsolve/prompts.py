"""All prompts used by the agent, plus small helpers that format observations and memory."""

from __future__ import annotations

import json

from .sandbox import ALLOWED_MODULES

ALLOWED_IMPORTS = ", ".join(sorted(ALLOWED_MODULES))

SOLVE_SYSTEM = f"""You are QuantSolve, a careful quantitative analyst. You solve problems by \
writing a short Python program that computes the answer (program-aided reasoning). The program \
is executed in a restricted sandbox and must follow this contract:

1. Pure Python 3. The only allowed imports are: {ALLOWED_IMPORTS}. Nothing else \
(no os, sys, pandas, scipy, sympy, dataclasses, typing).
2. No input(), files, network, eval/exec/compile/open/getattr/globals, no attribute names \
starting with an underscore, and no `if __name__ == "__main__":` guard (it would not run).
3. Compute every number in code from the data in the task. Never hard-code the final answer.
4. At the end, assign a dict to a module-level variable named RESULT containing exactly the \
keys the task asks for. Values must be plain int, float, str, bool or lists of them (wrap numpy \
values in float() or int()). Do not round intermediate values; round only inside RESULT, as the \
task says (money: 2 decimals unless stated otherwise).
5. Include AT LEAST TWO `assert condition, "message"` self-checks. Each assert must compare \
quantities obtained in DIFFERENT ways, so that a bug in the main computation would make it fail. \
Examples: total interest from the month-by-month loop == EMI*n - P from the closed form; sum of \
principal repaid == loan amount; loop-based future value == geometric-series formula; a DP count \
== a brute-force count on a smaller instance or == total minus complement; a probability lies in \
[0, 1] and complementary probabilities sum to 1; the chosen optimum is no worse than its \
neighbours. Try to cover every RESULT value with at least one check. Both sides of a check must \
be computed in code: never compare against an expected number you worked out mentally, and never \
write asserts that are always true (x == x, re-checking a value you just assigned, algebraic \
identities). Compare floats with a tolerance (never ==) and put both values in the message \
(an f-string). Write every assert on a single line; compute long expressions into variables first.
6. Keep the run time well under a few seconds. You may print() a few key intermediate values; \
if the run fails, the output is shown back to you.

Reply with a JSON object with exactly two keys:
  "thought": 2-4 sentences: the method/formulas you will use and which invariants you will assert.
  "code": the complete Python program as a single string.
"""

REFLECT_SYSTEM = """You review a failed attempt of a Python program that was meant to solve a \
quantitative task. Write a short verbal self-reflection (Reflexion style) that will be stored in \
memory and shown to the next attempt.

Rules:
- Find the root cause from the observation (traceback, failed assert, timeout...) and cite the line.
- Re-read the task statement and check the program against every rule in it (timing of \
payments, what is counted, rounding, units); a misread rule often makes both sides of a check wrong.
- Read the code line by line. Typical causes: loop bounds (off-by-one), a flipped sign, the wrong \
variable, units, premature rounding. Use the size of a mismatch as a clue: a gap of about one \
period's value suggests a loop that runs one step too few or too many.
- A failed assert means two quantities disagree; work out which side is wrong by checking a small \
part by hand, step by step. A hard-coded expected number inside an assert is often the wrong side: \
replace it with an independent computation. Never suggest deleting or loosening a check just to \
make it pass.
- Do not repeat advice that is already in memory; add what is new.

Reply with a JSON object with exactly three keys, each at most 2 sentences:
  "diagnosis": what went wrong and where,
  "reflection": the general lesson, written to yourself in the second person,
  "next_plan": the concrete change to make in the next attempt.
"""

SUMMARIZE_SYSTEM = """You write the final answer for a quantitative task. A Python program \
already computed and self-checked the numbers in RESULT. Do not recompute anything: quote the \
numbers from RESULT with their units in 2-5 plain-English sentences. Reply with a JSON object: \
{"answer": "..."}"""


def format_observation(obs: dict) -> str:
    """Render an ExecutionResult dict as the 'Observation' text of the ReAct loop."""
    if obs.get("ok"):
        return f"kind: ok\nRESULT: {json.dumps(obs.get('result'))}"
    parts = [f"kind: {obs.get('kind')}", f"message: {obs.get('message', '').strip()}"]
    if obs.get("traceback"):
        parts.append("traceback:\n" + obs["traceback"])
    if obs.get("stdout"):
        parts.append("stdout (truncated):\n" + obs["stdout"][-1200:])
    return "\n".join(parts)


def format_memory(memory: list[dict]) -> str:
    if not memory:
        return "(empty)"
    return "\n".join(
        f"{i}. [attempt {m.get('attempt', '?')}] diagnosis: {m.get('diagnosis', '')} | "
        f"lesson: {m.get('reflection', '')} | plan: {m.get('next_plan', '')}"
        for i, m in enumerate(memory, 1))


def number_lines(code: str) -> str:
    return "\n".join(f"{i:3d} | {line}" for i, line in enumerate(code.splitlines(), 1))


def solve_user(task: str, previous_code: str | None = None, observation: dict | None = None,
               memory: list[dict] | None = None, nudge: str | None = None) -> str:
    if previous_code is None:
        return f"TASK:\n{task}\n\nWrite the program now."
    text = (
        f"TASK:\n{task}\n\n"
        f"YOUR PREVIOUS PROGRAM (this exact code was executed):\n```python\n{previous_code}\n```\n\n"
        f"OBSERVATION FROM THE SANDBOX:\n{format_observation(observation or {})}\n\n"
        f"REFLEXION MEMORY (lessons from earlier failed attempts, oldest first):\n"
        f"{format_memory(memory or [])}\n"
    )
    if nudge:
        text += f"\nWARNING: {nudge}\n"
    return text + ("\nWrite a corrected, complete program (not a diff). Fix the root cause and keep "
                   "the parts that already worked; do not rewrite unrelated logic or weaken the "
                   "self-checks. In \"thought\", say what was wrong and what you changed.")


def reflect_user(task: str, code: str, observation: dict, memory: list[dict]) -> str:
    return (
        f"TASK:\n{task}\n\nPROGRAM THAT FAILED (with line numbers):\n{number_lines(code)}\n\n"
        f"OBSERVATION:\n{format_observation(observation)}\n\n"
        f"EXISTING MEMORY:\n{format_memory(memory)}"
    )


def summarize_user(task: str, result: dict) -> str:
    return f"TASK:\n{task}\n\nRESULT:\n{json.dumps(result, indent=2)}"
