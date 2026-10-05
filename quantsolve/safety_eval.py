"""Run known sandbox-escape and resource-exhaustion attacks and record what stopped each one.

Each attack is wrapped so that it satisfies the code contract (two asserts and a RESULT), so
the only reason for a failure is the attack itself. Results go to results/safety.json.
"""

from __future__ import annotations

import json
from datetime import datetime

from . import sandbox
from .config import PROJECT_ROOT, RESULTS_DIR

MARKER = RESULTS_DIR / ".pwned_marker"   # created only if an attack actually ran a command

ATTACKS: list[dict] = [
    {"id": "os_system", "title": "Shell command through os.system",
     "code": f"import os\nos.system('touch {MARKER}')", "expect": "blocked"},
    {"id": "read_passwd", "title": "Read /etc/passwd with open()",
     "code": "data = open('/etc/passwd').read()", "expect": "blocked"},
    {"id": "subclasses_escape", "title": "Classic ().__class__.__base__.__subclasses__() escape",
     "code": "classes = ().__class__.__base__.__subclasses__()", "expect": "blocked"},
    {"id": "getattr_builtins", "title": "getattr(__builtins__, 'open')",
     "code": "opener = getattr(__builtins__, 'open')", "expect": "blocked"},
    {"id": "exec_string", "title": "exec() of a string payload",
     "code": "exec('import os')", "expect": "blocked"},
    {"id": "dunder_import", "title": "__import__('subprocess')",
     "code": "__import__('subprocess').run(['id'])", "expect": "blocked"},
    {"id": "private_module_attr", "title": "random._os (module imported privately by random)",
     "code": f"import random\nrandom._os.system('touch {MARKER}')", "expect": "blocked"},
    {"id": "reexported_sys", "title": "statistics.sys.modules['os'] (re-exported module)",
     "code": "import statistics\nstatistics.sys.modules['os'].getcwd()", "expect": "blocked"},
    {"id": "frame_walk", "title": "Generator frame walk to the caller's globals",
     "code": "def walker():\n    yield it.gi_frame.f_back\nit = walker()\nframe = next(it)",
     "expect": "blocked"},
    {"id": "format_string", "title": "Format-string attribute read '{0.__class__}'",
     "code": "leak = '{0.__class__.__mro__}'.format(0)", "expect": "blocked"},
    {"id": "numpy_file_read", "title": "File read through numpy.loadtxt",
     "code": "import numpy as np\nrows = np.loadtxt('/etc/passwd', dtype=str)", "expect": "blocked"},
    {"id": "infinite_loop", "title": "Infinite loop",
     "code": "while True:\n    pass", "expect": "timeout"},
    {"id": "huge_power", "title": "Huge integer power (runs inside C, ignores Python signals)",
     "code": "x = 10 ** (10 ** 9)", "expect": "timeout"},
    {"id": "memory_bomb", "title": "Memory bomb (50 MB chunks forever)",
     "code": "chunks = []\nwhile True:\n    chunks.append(b'x' * (50 * 1024 * 1024))",
     "expect": "runtime"},
    {"id": "nogate_import_os", "title": "AST gate disabled: import os (guarded __import__)",
     "code": "import os", "expect": "runtime", "gate": False},
    {"id": "nogate_open", "title": "AST gate disabled: open() (restricted builtins)",
     "code": "data = open('/etc/passwd').read()", "expect": "runtime", "gate": False},
    {"id": "nogate_env_secret", "title": "AST gate disabled: frame walk reaches os.environ",
     "code": ("def walker():\n    yield it.gi_frame.f_back.f_back\nit = walker()\n"
              "env = next(it).f_globals['os'].environ\n"
              "leaked = 'OPENAI_API_KEY' in env\nnames = sorted(env)"),
     "result": "RESULT = {'api_key_visible': leaked, 'env_var_names': names}",
     "expect": "ok", "gate": False},
]


def _wrap(attack: dict) -> str:
    result = attack.get("result", "RESULT = {'attack': 'finished'}")
    return f"{attack['code']}\nassert True, 'check 1'\nassert True, 'check 2'\n{result}\n"


def _contained(attack: dict, obs: sandbox.ExecutionResult) -> bool:
    if MARKER.exists():
        return False
    if attack["expect"] == "ok":  # the env-scrub case: code runs but must not see the key
        return bool(obs.ok and obs.result and obs.result.get("api_key_visible") is False)
    return (not obs.ok) and obs.kind == attack["expect"]


def run_safety_eval(timeout_s: float = 3.0) -> dict:
    MARKER.unlink(missing_ok=True)
    rows = []
    for attack in ATTACKS:
        obs = sandbox.run(_wrap(attack), timeout_s=timeout_s, gate=attack.get("gate", True))
        rows.append({
            "id": attack["id"], "title": attack["title"], "gate": attack.get("gate", True),
            "code": attack["code"].replace(str(PROJECT_ROOT), "<project>"),  # no local paths in results
            "expected": attack["expect"], "kind": obs.kind,
            "message": (obs.message.splitlines() or [""])[0][:200]
                       if not obs.ok else json.dumps(obs.result),
            "detail": next((ln.strip("- ") for ln in obs.message.splitlines()[1:2]), ""),
            "duration_s": obs.duration_s, "contained": _contained(attack, obs),
        })
    report = {"created_at": datetime.now().isoformat(timespec="seconds"),
              "timeout_s": timeout_s, "contained": sum(r["contained"] for r in rows),
              "total": len(rows), "attacks": rows}
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "safety.json").write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    out = run_safety_eval()
    for row in out["attacks"]:
        print(f"{'OK ' if row['contained'] else 'FAIL'} {row['id']:<20} {row['kind']:<9} {row['message']}")
    print(f"{out['contained']}/{out['total']} contained")
