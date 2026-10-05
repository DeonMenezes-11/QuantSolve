import pytest

from quantsolve import faults, sandbox

LOAN = """
P = 100000.0
r = 0.01
n = 12
emi = P * r * (1 + r) ** n / ((1 + r) ** n - 1)
balance = P
repaid = 0.0
for month in range(1, n + 1):
    interest = balance * r
    principal = emi - interest
    balance -= principal
    repaid += principal
assert abs(balance) < 1e-6, f"final balance should be 0, got {balance}"
assert abs(repaid - P) < 1e-6, f"principal repaid {repaid} should equal the loan {P}"
RESULT = {"emi": round(emi, 2)}
"""

WHILE_LOOP = """
balance = 100.0
months = 0
while months < 10:
    balance -= 10
    months += 1
assert months == 10, "ten months"
assert abs(balance) < 1e-9, f"balance should be 0, got {balance}"
RESULT = {"months": months}
"""


def test_original_programs_pass():
    assert sandbox.run(LOAN).ok and sandbox.run(WHILE_LOOP).ok


def test_crash_mode_renames_a_use_and_causes_name_error():
    code, description = faults.mutate(LOAN, "crash")
    assert code != LOAN and description.startswith("crash:")
    obs = sandbox.run(code)
    assert obs.kind == "runtime" and obs.exc_type == "NameError"


def test_logic_mode_off_by_one_is_caught_by_asserts():
    code, description = faults.mutate(LOAN, "logic")
    assert "range(1, n)" in code and "off-by-one" in description
    assert sandbox.run(code).kind == "assertion"


def test_logic_mode_flips_sign_inside_loop_without_range():
    code, description = faults.mutate(WHILE_LOOP, "logic")
    assert "balance += 10" in code and "flipped" in description
    assert sandbox.run(code).kind == "assertion"


def test_mutation_is_deterministic():
    assert faults.mutate(LOAN, "logic") == faults.mutate(LOAN, "logic")
    assert faults.mutate(LOAN, "crash") == faults.mutate(LOAN, "crash")


def test_no_applicable_mutation_returns_original():
    code = "x = 1\nRESULT = {'x': x}\n"
    mutated, description = faults.mutate(code, "logic")
    assert mutated == code and "no logic fault" in description


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        faults.mutate(LOAN, "chaos")
