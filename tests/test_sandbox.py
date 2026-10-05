import importlib
import os
import types

import pytest

from quantsolve import sandbox
from tests.conftest import program


def test_allowed_code_runs_and_returns_result():
    code = """
import math
import numpy as np
from fractions import Fraction
values = np.arange(1, 5)
total = float(values.sum())
assert total == 10, f"sum should be 10, got {total}"
assert math.isclose(Fraction(1, 3) * 3, 1), "fraction arithmetic"
print("computed", total)
RESULT = {"total": total, "mean": round(float(values.mean()), 2)}
"""
    obs = sandbox.run(code)
    assert obs.ok and obs.kind == "ok"
    assert obs.result == {"total": 10.0, "mean": 2.5}
    assert "computed 10.0" in obs.stdout
    assert obs.asserts == 2


def test_library_internals_that_import_lazily_still_work():
    """numpy / datetime C code imports helpers lazily through the guarded __import__."""
    code = program("""
import datetime
import numpy as np
a = np.array([[2.0, 1.0], [1.0, 3.0]])
x = np.linalg.solve(a, np.array([3.0, 5.0]))
stats = (float(a.mean()), float(a.std()), float(np.median(a)))
rng = np.random.default_rng(0)
sample = float(rng.normal(size=100).mean())
print(a)
day = datetime.date(2024, 3, 1)
label = day.strftime("%d %b %Y")
parsed = datetime.datetime.strptime("2024-03-01", "%Y-%m-%d").date()
""", "RESULT = {'x': [round(float(v), 6) for v in x], 'label': label, 'same': parsed == day}")
    obs = sandbox.run(code)
    assert obs.ok, obs.message
    assert obs.result == {"x": [0.8, 1.4], "label": "01 Mar 2024", "same": True}


def test_classes_and_functions_work():
    code = program("class Account:\n    def __init__(self, b):\n        self.b = b\n"
                   "def grow(a):\n    return a.b * 2\nv = grow(Account(3))",
                   "RESULT = {'v': v}")
    assert sandbox.run(code).result == {"v": 6}


BLOCKED = {
    "import os": "import os\nos.system('echo hi')",
    "from os import": "from os import system",
    "subprocess": "import subprocess",
    "open": "data = open('/etc/passwd').read()",
    "eval": "x = eval('1+1')",
    "exec": "exec('import os')",
    "__import__": "m = __import__('os')",
    "getattr builtins": "f = getattr(__builtins__, 'open')",
    "class escape": "subs = ().__class__.__base__.__subclasses__()",
    "private module attr": "import random\nrandom._os.system('id')",
    "re-exported sys": "import statistics\nstatistics.sys.modules",
    "generator frame": "g = (i for i in [1])\nf = g.gi_frame",
    "format string": "s = '{0.__class__}'.format(1)",
    "numpy file io": "import numpy as np\nnp.load('/etc/passwd')",
    "from numpy import load": "from numpy import load",
    "star import": "from math import *",
    "relative import": "from . import x",
    "globals": "g = globals()",
    "breakpoint": "breakpoint()",
    "dunder name": "b = __builtins__",
}


@pytest.mark.parametrize("snippet", BLOCKED.values(), ids=BLOCKED.keys())
def test_dangerous_patterns_are_blocked(snippet):
    obs = sandbox.run(program(snippet))
    assert obs.kind == "blocked", obs.message
    assert "Allowed imports" in obs.message


def test_underscore_throwaway_names_are_allowed():
    """Regression: the benchmark showed models writing `for __ in range(n)`."""
    code = program("total = 0\nfor __ in range(3):\n    for ___ in range(2):\n        total += 1",
                   "RESULT = {'total': total}")
    obs = sandbox.run(code)
    assert obs.ok and obs.result == {"total": 6}


def test_runtime_layer_still_contains_code_without_the_gate():
    obs = sandbox.run(program("import os"), gate=False)
    assert obs.kind == "runtime" and obs.exc_type == "ImportError"
    obs = sandbox.run(program("x = open('/etc/passwd')"), gate=False)
    assert obs.kind == "runtime" and obs.exc_type == "NameError"


def test_timeout_is_enforced():
    obs = sandbox.run(program("while True:\n    pass"), timeout_s=1.5)
    assert obs.kind == "timeout"
    assert obs.duration_s < 4


def test_memory_limit_kills_runaway_allocation():
    code = program("chunks = []\nwhile True:\n    chunks.append(b'x' * (20 * 1024 * 1024))")
    obs = sandbox.run(code, memory_mb=300)
    assert obs.kind == "runtime" and obs.exc_type == "MemoryError"


def test_failed_assert_is_classified_as_assertion():
    code = "balance = 12.5\nassert abs(balance) < 0.01, f'final balance {balance} should be 0'\n" \
           "assert True, 'x'\nRESULT = {}"
    obs = sandbox.run(code)
    assert obs.kind == "assertion"
    assert "final balance 12.5 should be 0" in obs.message
    assert obs.line == 2


def test_name_error_has_clean_traceback():
    code = "rate = 0.07\ntotal = 100\nvalue = totl * (1 + rate)\nassert 1, 'a'\nassert 1, 'b'\nRESULT = {}"
    obs = sandbox.run(code)
    assert obs.kind == "runtime" and obs.exc_type == "NameError"
    assert "line 3, in <module>" in obs.traceback
    assert "value = totl * (1 + rate)" in obs.traceback
    assert "Did you mean: 'total'" in obs.traceback
    assert "sandbox.py" not in obs.traceback and "multiprocessing" not in obs.traceback


def test_syntax_error():
    obs = sandbox.run("x = (1,\nassert True")
    assert obs.kind == "syntax" and obs.line == 1


@pytest.mark.parametrize("code, fragment", [
    ("x = 1\nassert x, 'a'\nassert x, 'b'", "RESULT is not defined"),
    ("assert 1, 'a'\nassert 1, 'b'\nRESULT = [1, 2]", "must be a dict"),
    ("assert 1, 'a'\nassert 1, 'b'\nRESULT = {'s': {1, 2}}", "not JSON-serialisable"),
    ("assert 1, 'a'\nassert 1, 'b'\nRESULT = {'v': float('nan')}", "not JSON-serialisable"),
    ("assert 1, 'only one'\nRESULT = {'v': 1}", "at least 2"),
])
def test_contract_violations(code, fragment):
    obs = sandbox.run(code)
    assert obs.kind == "contract"
    assert fragment in obs.message


def test_scrub_environment_removes_secrets(monkeypatch):
    fake_env = {"OPENAI_API_KEY": "sk-test-not-real", "AWS_SECRET": "x", "PATH": "/usr/bin"}
    monkeypatch.setattr(os, "environ", fake_env)
    sandbox._scrub_environment()
    assert fake_env == {"PATH": "/usr/bin"}


def test_child_process_does_not_see_the_api_key(monkeypatch):
    """End to end: with the gate off, walk frames to os.environ inside the child."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    code = program("def walker():\n    yield it.gi_frame.f_back.f_back\nit = walker()\n"
                   "env = next(it).f_globals['os'].environ",
                   "RESULT = {'key': 'OPENAI_API_KEY' in env, 'path': 'PATH' in env}")
    obs = sandbox.run(code, gate=False)
    assert obs.ok and obs.result == {"key": False, "path": True}


def test_no_dangerous_module_reachable_through_allowed_attributes():
    """Breadth-first walk over public, non-blocked attributes of every allowed module."""
    dangerous = {"os", "sys", "subprocess", "builtins", "importlib", "ctypes", "io", "pathlib",
                 "shutil", "socket", "pickle", "operator", "inspect", "types", "posix"}
    frontier = [importlib.import_module(m) for m in sandbox.ALLOWED_MODULES]
    seen: set[int] = set()
    for depth in range(4):
        nxt = []
        for obj in frontier:
            if id(obj) in seen:
                continue
            seen.add(id(obj))
            for name in dir(obj):
                if sandbox._blocked_attr(name):
                    continue
                try:
                    value = getattr(obj, name)
                except Exception:
                    continue
                if isinstance(value, types.ModuleType):
                    assert value.__name__ not in dangerous, f"{name} -> {value.__name__}"
                    nxt.append(value)
                elif isinstance(value, type) and depth < 2:
                    nxt.append(value)
        frontier = nxt
