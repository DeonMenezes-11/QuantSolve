"""Safe-ish execution of generated code: AST gate + restricted exec() in a child process.

Layers of defence (none of them is a hard security boundary on its own):

1. AST safety gate (parent): only allow-listed imports; no eval/exec/open/getattr...;
   no attribute names starting with "_" or leading out of the sandbox (frames, os, sys, ...).
2. Restricted builtins (child): the exec namespace only sees SAFE_BUILTINS, whose
   ``__import__`` re-checks the import allow-list at run time.
3. Separate process (multiprocessing "spawn"): a crash or hang cannot take down the app;
   secrets are scrubbed from the child's environment before any user code runs.
4. Resource limits: RLIMIT_CPU, an RSS watchdog thread, and a wall-clock timeout
   enforced by the parent (terminate, then kill).

Failure kinds: blocked, syntax, runtime, assertion, timeout, contract.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import io
import json
import multiprocessing as mp
import os
import re
import string
import sys
import threading
import time
import traceback
from dataclasses import asdict, dataclass
from typing import Any

ALLOWED_MODULES = frozenset({
    "math", "cmath", "statistics", "fractions", "decimal", "itertools", "functools",
    "collections", "datetime", "random", "heapq", "bisect", "numpy",
})

BLOCKED_NAMES = frozenset({
    "eval", "exec", "compile", "open", "__import__", "input", "breakpoint", "exit", "quit",
    "globals", "locals", "vars", "getattr", "setattr", "delattr", "memoryview",
})

# Attribute names that lead out of the sandbox without needing a dunder.
BLOCKED_ATTRS = frozenset({
    # frame / generator / traceback introspection -> caller globals
    "gi_frame", "gi_code", "gi_yieldfrom", "cr_frame", "cr_code", "cr_await",
    "ag_frame", "ag_code", "ag_await", "tb_frame", "tb_next",
    "f_back", "f_globals", "f_locals", "f_builtins", "f_code", "f_trace",
    # modules re-exported by allowed modules (statistics.sys, fractions.re.enum.bltns, ...)
    "os", "sys", "subprocess", "builtins", "bltns", "importlib", "inspect", "ctypes",
    "ctypeslib", "io", "pathlib", "shutil", "socket", "signal", "fcntl", "select",
    "selectors", "threading", "multiprocessing", "pickle", "marshal", "tempfile",
    "fileinput", "platform", "sysconfig", "posix", "posixpath", "genericpath",
    "linecache", "tokenize", "dis", "codecs", "encodings", "locale", "logging", "types",
    "gc", "weakref", "resource", "runpy", "pkgutil", "site", "code", "mmap", "asyncio",
    "glob", "contextlib", "copyreg", "monitoring", "operator",
    # numpy sub-packages with file / process access
    "f2py", "testing", "lib", "distutils", "core",
    # file I/O helpers (numpy and friends)
    "load", "save", "savez", "savez_compressed", "loadtxt", "savetxt", "genfromtxt",
    "fromfile", "tofile", "fromregex", "memmap", "DataSource", "dump", "dumps", "loads",
})

FAILURE_KINDS = ("blocked", "syntax", "runtime", "assertion", "timeout", "contract")
MIN_ASSERTS = 2
MEMORY_LIMIT_MB = 1024
STARTUP_TIMEOUT_S = 60.0          # interpreter start-up in the child (not counted as run time)
MAX_STDOUT_CHARS = 3000
MAX_RESULT_CHARS = 20_000
SAFE_ENV_VARS = frozenset({"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR"})
_MEMORY_EXIT_CODE = 86
_SIGXCPU = 24
_DUNDER_RE = re.compile(r"__[A-Za-z]\w*__")


@dataclass
class ExecutionResult:
    ok: bool
    kind: str                       # "ok" or one of FAILURE_KINDS
    message: str = ""
    traceback: str = ""
    stdout: str = ""
    result: dict | None = None
    duration_s: float = 0.0
    exc_type: str | None = None
    line: int | None = None         # last line of <solution> involved in the failure
    asserts: int = 0                # number of assert statements in the code

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- gate

def _blocked_attr(name: str) -> bool:
    return name.startswith("_") or name in BLOCKED_ATTRS


def _module_problem(dotted: str) -> str | None:
    parts = dotted.split(".")
    if parts[0] not in ALLOWED_MODULES:
        return f"import of '{dotted}' is not allowed"
    if any(_blocked_attr(p) for p in parts[1:]):
        return f"import of '{dotted}' is not allowed (blocked sub-module)"
    return None


def _string_problem(text: str) -> str | None:
    """Catch format-string tricks such as "{0.__class__}".format(x)."""
    if _DUNDER_RE.search(text):
        return "string constants may not contain dunder names"
    if "{" in text:
        try:
            fields = [f for _, f, _, _ in string.Formatter().parse(text) if f]
        except ValueError:
            return None
        for field_name in fields:
            for attr in re.findall(r"\.(\w+)", field_name):
                if _blocked_attr(attr):
                    return f"format field '{{{field_name}}}' accesses a blocked attribute"
    return None


def check_code(tree: ast.AST) -> list[str]:
    """Return a list of safety violations ("line N: why"); empty means the code may run."""
    problems: list[str] = []

    def bad(node: ast.AST, why: str) -> None:
        msg = f"line {getattr(node, 'lineno', '?')}: {why}"
        if msg not in problems:
            problems.append(msg)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if why := _module_problem(alias.name):
                    bad(node, why)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                bad(node, "relative imports are not allowed")
            elif why := _module_problem(node.module or ""):
                bad(node, why)
            for alias in node.names:
                if alias.name == "*":
                    bad(node, "'from ... import *' is not allowed")
                elif _blocked_attr(alias.name):
                    bad(node, f"importing '{alias.name}' is not allowed")
        elif isinstance(node, ast.Name):
            # `__x__` is a dunder; `_`, `__` or `___` used as throwaway loop variables are not
            is_dunder = node.id.startswith("__") and node.id.endswith("__") and node.id.strip("_")
            if node.id in BLOCKED_NAMES or (is_dunder and node.id != "__name__"):
                bad(node, f"name '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute):
            if _blocked_attr(node.attr):
                bad(node, f"attribute '.{node.attr}' is not allowed")
        elif isinstance(node, ast.MatchClass):
            for attr in node.kwd_attrs:
                if _blocked_attr(attr):
                    bad(node, f"pattern attribute '{attr}' is not allowed")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if why := _string_problem(node.value):
                bad(node, why)
    return problems


def count_asserts(tree: ast.AST) -> int:
    return sum(isinstance(node, ast.Assert) for node in ast.walk(tree))


def blocked_message(problems: list[str]) -> str:
    return (
        "Code rejected by the safety gate:\n"
        + "\n".join(f"- {p}" for p in problems)
        + "\nAllowed imports: " + ", ".join(sorted(ALLOWED_MODULES))
        + ". Forbidden: " + ", ".join(sorted(BLOCKED_NAMES))
        + ", attribute names starting with '_', and module/file/frame attributes such as "
        "os, sys, load, save, tofile, gi_frame."
    )


# ------------------------------------------------------------- restricted builtins

# Stdlib helpers that C code of allowed modules imports lazily while user code is running
# (datetime.strftime -> time, datetime.strptime -> _strptime).
RUNTIME_HELPER_MODULES = frozenset({"time", "_strptime"})


def _guarded_import(name: str, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    """Defence in depth: re-check the top-level package even if the AST gate was bypassed.

    C extensions resolve lazy imports (e.g. ndarray.mean -> numpy._core._methods) through the
    builtins of the *calling* frame, i.e. through this function, so private sub-modules of
    allowed packages must pass. Finer-grained rules live in the AST gate.
    """
    top = name.split(".")[0]
    if level or top not in ALLOWED_MODULES | RUNTIME_HELPER_MODULES:
        raise ImportError(f"import of '{name}' is not allowed in the sandbox")
    return builtins.__import__(name, globals, locals, fromlist, level)


_SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes", "callable", "chr",
    "classmethod", "complex", "dict", "divmod", "enumerate", "filter", "float", "format",
    "frozenset", "hash", "hex", "id", "int", "isinstance", "issubclass", "iter", "len",
    "list", "map", "max", "min", "next", "object", "oct", "ord", "pow", "print", "property",
    "range", "repr", "reversed", "round", "set", "slice", "sorted", "staticmethod", "str",
    "sum", "super", "tuple", "type", "zip", "NotImplemented", "Ellipsis",
    # exceptions
    "BaseException", "Exception", "ArithmeticError", "AssertionError", "AttributeError",
    "FloatingPointError", "ImportError", "IndexError", "KeyError", "LookupError",
    "MemoryError", "NameError", "NotImplementedError", "OverflowError", "RecursionError",
    "RuntimeError", "StopIteration", "TypeError", "ValueError", "ZeroDivisionError",
    "Warning", "RuntimeWarning", "UserWarning",
)
SAFE_BUILTINS: dict[str, Any] = {name: getattr(builtins, name) for name in _SAFE_BUILTIN_NAMES}
SAFE_BUILTINS["__build_class__"] = builtins.__build_class__   # needed for `class` statements
SAFE_BUILTINS["__import__"] = _guarded_import


# ------------------------------------------------------------------ child process

def _scrub_environment() -> None:
    """Drop every environment variable except a few harmless ones (API keys included)."""
    for key in list(os.environ):
        if key not in SAFE_ENV_VARS:
            del os.environ[key]


def _apply_limits(cpu_seconds: float, memory_mb: int) -> None:
    try:
        import resource
    except ImportError:  # pragma: no cover - non-POSIX platforms
        return
    limit_bytes = memory_mb * 1024 * 1024
    cpu = int(cpu_seconds) + 1  # backup for the parent's wall-clock timeout
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    with contextlib.suppress(ValueError, OSError):  # works on Linux; macOS refuses it
        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))

    def watchdog() -> None:  # portable memory cap: kill the child above the RSS limit
        scale = 1 if os.uname().sysname == "Darwin" else 1024  # ru_maxrss: bytes vs KiB
        while True:
            if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * scale > limit_bytes:
                os._exit(_MEMORY_EXIT_CODE)
            time.sleep(0.05)

    threading.Thread(target=watchdog, daemon=True).start()


def _solution_frames(exc: BaseException) -> list[traceback.FrameSummary]:
    return [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == "<solution>"]


def clean_traceback(exc: BaseException, code: str) -> str:
    """Traceback restricted to <solution> frames, with source lines pulled from `code`."""
    lines = code.splitlines()
    out = ["Traceback (solution frames only):"]
    for frame in _solution_frames(exc):
        out.append(f"  line {frame.lineno}, in {frame.name}")
        if frame.lineno and 0 < frame.lineno <= len(lines):
            out.append(f"    {lines[frame.lineno - 1].strip()}")
    try:  # from_exception keeps the "Did you mean ...?" hints of Python 3.12+
        last = "".join(traceback.TracebackException.from_exception(exc).format_exception_only())
    except Exception:  # pragma: no cover - defensive
        last = f"{type(exc).__name__}: {exc}"
    out.append(last.strip())
    return "\n".join(out)


def _check_result(namespace: dict[str, Any]) -> dict[str, Any]:
    if "RESULT" not in namespace:
        return {"ok": False, "kind": "contract", "message":
                "RESULT is not defined: assign a dict to a module-level variable named RESULT "
                "(code under `if __name__ == '__main__':` does not run here)."}
    result = namespace["RESULT"]
    if not isinstance(result, dict):
        return {"ok": False, "kind": "contract",
                "message": f"RESULT must be a dict, got {type(result).__name__}."}
    try:
        text = json.dumps(result, allow_nan=False)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "kind": "contract", "message":
                f"RESULT is not JSON-serialisable ({exc}). Convert numpy values with "
                "float()/int() and avoid NaN/inf."}
    if len(text) > MAX_RESULT_CHARS:
        return {"ok": False, "kind": "contract",
                "message": f"RESULT is too large ({len(text)} characters when serialised)."}
    return {"ok": True, "kind": "ok", "result": json.loads(text)}


def _child_main(code: str, conn, cpu_seconds: float, memory_mb: int) -> None:
    """Runs in the spawned child. Must stay a top-level function so it can be pickled."""
    _scrub_environment()
    _apply_limits(cpu_seconds, memory_mb)
    conn.send("ready")
    out = io.StringIO()
    namespace: dict[str, Any] = {"__builtins__": dict(SAFE_BUILTINS), "__name__": "__solution__"}
    try:
        compiled = compile(code, "<solution>", "exec", optimize=0)  # optimize=0 keeps asserts
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            exec(compiled, namespace)
        payload = _check_result(namespace)
    except BaseException as exc:  # noqa: BLE001 - everything is reported to the parent
        frames = _solution_frames(exc)
        payload = {
            "ok": False,
            "kind": "assertion" if isinstance(exc, AssertionError) else "runtime",
            "exc_type": type(exc).__name__,
            "message": f"{type(exc).__name__}: {exc}"[:1000],
            "traceback": clean_traceback(exc, code),
            "line": frames[-1].lineno if frames else None,
        }
    text = out.getvalue()
    payload["stdout"] = text if len(text) <= MAX_STDOUT_CHARS else text[:MAX_STDOUT_CHARS] + "\n...[truncated]"
    conn.send(payload)
    conn.close()


_MAIN_LOCK = threading.Lock()


@contextlib.contextmanager
def _main_script_hidden():
    """Stop "spawn" children from re-running the parent's __main__ script.

    multiprocessing re-executes ``__main__.__file__`` in every spawned child. Under the web
    server that is web.py (it would start a second server), under ``python3 -`` it is '<stdin>',
    which does not exist.
    The child only needs this module, so the path is hidden while the child is launched.
    """
    main = sys.modules.get("__main__")
    if main is None or not (hasattr(main, "__file__") or getattr(main, "__spec__", None)):
        yield
        return
    with _MAIN_LOCK:
        saved = main.__dict__.copy()
        main.__dict__.pop("__file__", None)
        main.__spec__ = None
        try:
            yield
        finally:
            for key in ("__file__", "__spec__"):
                if key in saved:
                    setattr(main, key, saved[key])


def _reap(proc: mp.Process) -> None:
    proc.join(2)
    if proc.is_alive():
        proc.terminate()
        proc.join(1)
    if proc.is_alive():
        proc.kill()
        proc.join(1)


# --------------------------------------------------------------------------- run

def run(code: str, timeout_s: float = 10.0, *, memory_mb: int = MEMORY_LIMIT_MB,
        gate: bool = True, min_asserts: int = MIN_ASSERTS) -> ExecutionResult:
    """Check `code`, execute it in a fresh child process and classify the outcome.

    `gate=False` skips the AST gate; it exists only so the safety evaluation can show
    that the runtime layers still contain an attack on their own.
    """
    try:
        tree = ast.parse(code, filename="<solution>")
    except SyntaxError as exc:
        src = (exc.text or "").rstrip()
        pointer = f"\n    {src}\n    {' ' * max((exc.offset or 1) - 1, 0)}^" if src else ""
        return ExecutionResult(False, "syntax", f"SyntaxError: {exc.msg} (line {exc.lineno})",
                               traceback=f"line {exc.lineno}{pointer}\nSyntaxError: {exc.msg}",
                               exc_type="SyntaxError", line=exc.lineno)
    asserts = count_asserts(tree)
    if gate and (problems := check_code(tree)):
        return ExecutionResult(False, "blocked", blocked_message(problems), asserts=asserts)
    if asserts < min_asserts:
        return ExecutionResult(False, "contract", (
            f"Found {asserts} assert statement(s); the contract requires at least {min_asserts} "
            "self-checks (`assert condition, \"message\"`) on invariants of the computation."),
            asserts=asserts)

    ctx = mp.get_context("spawn")
    recv_conn, send_conn = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child_main, args=(code, send_conn, timeout_s, memory_mb),
                       daemon=True, name="quantsolve-sandbox")
    with _main_script_hidden():
        proc.start()
    send_conn.close()  # so recv() sees EOF if the child dies
    payload: dict[str, Any] | None = None
    timed_out = False
    started = time.perf_counter()
    try:
        if recv_conn.poll(STARTUP_TIMEOUT_S) and recv_conn.recv() == "ready":
            started = time.perf_counter()  # the time limit covers user code only
            if recv_conn.poll(timeout_s):
                payload = recv_conn.recv()
            else:
                timed_out = True
    except (EOFError, OSError):
        payload = None  # child died without reporting; classified below
    finally:
        duration = time.perf_counter() - started
        recv_conn.close()
        if timed_out:
            proc.terminate()
        _reap(proc)

    if timed_out:
        return ExecutionResult(False, "timeout", (
            f"Execution exceeded the {timeout_s:g} s time limit and the process was killed "
            "(infinite loop or a very slow algorithm?)."), duration_s=round(duration, 3),
            exc_type="Timeout", asserts=asserts)
    if payload is None:
        return _classify_crash(proc.exitcode, duration, asserts, memory_mb)
    payload.setdefault("message", "")
    return ExecutionResult(
        ok=payload["ok"], kind=payload["kind"], message=payload["message"],
        traceback=payload.get("traceback", ""), stdout=payload.get("stdout", ""),
        result=payload.get("result"), duration_s=round(duration, 3),
        exc_type=payload.get("exc_type"), line=payload.get("line"), asserts=asserts)


def _classify_crash(exitcode: int | None, duration: float, asserts: int,
                    memory_mb: int) -> ExecutionResult:
    if exitcode == _MEMORY_EXIT_CODE:
        return ExecutionResult(False, "runtime", (
            f"MemoryError: the program used more than {memory_mb} MB and was killed."),
            duration_s=round(duration, 3), exc_type="MemoryError", asserts=asserts)
    if exitcode == -_SIGXCPU:
        return ExecutionResult(False, "timeout", "CPU time limit exceeded; the process was killed.",
                               duration_s=round(duration, 3), exc_type="Timeout", asserts=asserts)
    return ExecutionResult(False, "runtime", f"The sandbox process crashed (exit code {exitcode}).",
                           duration_s=round(duration, 3), exc_type="Crash", asserts=asserts)
