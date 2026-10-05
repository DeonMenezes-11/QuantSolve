"""Deterministic, AST-based bug injection ("inject a bug" demo switch).

Applied to attempt 1 only, so the benchmark can measure whether the loop notices and
repairs a bug it did not write itself.

- ``crash``: rename one *use* of a variable to a misspelled name -> NameError.
- ``logic``: off-by-one in the stop argument of a ``range()`` loop, or flip the first
  ``+``/``-`` inside a loop -> silently wrong numbers that the self-check asserts should catch.

Note: the mutated program is regenerated with ``ast.unparse``, so comments are dropped.
"""

from __future__ import annotations

import ast
import builtins
import copy
import re

MODES = ("crash", "logic")


class _ReplaceNode(ast.NodeTransformer):
    """Swap exactly one node (matched by identity) for a replacement."""

    def __init__(self, target: ast.AST, replacement: ast.AST) -> None:
        self.target, self.replacement = target, replacement

    def generic_visit(self, node: ast.AST) -> ast.AST:
        if node is self.target:
            return ast.copy_location(self.replacement, node)
        return super().generic_visit(node)


def _in_source_order(nodes) -> list:
    return sorted(nodes, key=lambda n: (getattr(n, "lineno", 0), getattr(n, "col_offset", 0)))


def _line_of(code: str, snippet: str, *, word: bool = False) -> int | None:
    pattern = rf"\b{re.escape(snippet)}\b" if word else re.escape(snippet)
    return next((i for i, line in enumerate(code.splitlines(), 1) if re.search(pattern, line)), None)


# ------------------------------------------------------------------------ crash

def _misspell(name: str, taken: set[str]) -> str | None:
    candidates = []
    if len(name) >= 4 and name[-1] != name[-2]:
        candidates.append(name[:-2] + name[-1] + name[-2])      # balance -> balanec
    if len(name) >= 3:
        candidates.append(name[0] + name[2:])                    # rate -> rte
    candidates.append(name + "1")
    return next((c for c in candidates if c not in taken and c.isidentifier()), None)


def _inject_crash(tree: ast.Module) -> tuple[ast.Module, str, str] | None:
    names = [n for n in ast.walk(tree) if isinstance(n, ast.Name)]
    first_store: dict[str, int] = {}
    for n in _in_source_order(names):
        if isinstance(n.ctx, ast.Store):
            first_store.setdefault(n.id, n.lineno)
    taken = {n.id for n in names} | set(dir(builtins))
    taken |= {a.arg for a in ast.walk(tree) if isinstance(a, ast.arg)}
    taken |= {d.name for d in ast.walk(tree)
              if isinstance(d, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))}
    for node in _in_source_order(names):
        if (isinstance(node.ctx, ast.Load) and node.id != "RESULT"
                and node.id in first_store and node.lineno > first_store[node.id]):
            new_name = _misspell(node.id, taken)
            if new_name:
                new_tree = _ReplaceNode(node, ast.Name(id=new_name, ctx=ast.Load())).visit(tree)
                return new_tree, node.id, new_name
    return None


# ------------------------------------------------------------------------ logic

def _is_range_call(node: ast.AST) -> bool:
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "range" and 1 <= len(node.args) <= 3 and not node.keywords)


def _off_by_one(call: ast.Call) -> ast.Call:
    idx = 0 if len(call.args) == 1 else 1
    stop = call.args[idx]
    if (isinstance(stop, ast.BinOp) and isinstance(stop.op, ast.Add)
            and isinstance(stop.right, ast.Constant) and stop.right.value == 1):
        new_stop = stop.left                                      # range(1, n + 1) -> range(1, n)
    elif isinstance(stop, ast.Constant) and isinstance(stop.value, int):
        new_stop = ast.Constant(stop.value - 1)                   # range(12) -> range(11)
    else:
        new_stop = ast.BinOp(stop, ast.Sub(), ast.Constant(1))    # range(n) -> range(n - 1)
    args = list(call.args)
    args[idx] = new_stop
    return ast.Call(func=call.func, args=args, keywords=[])


def _is_text(node: ast.AST) -> bool:
    return isinstance(node, ast.JoinedStr) or (isinstance(node, ast.Constant)
                                               and isinstance(node.value, str))


def _flip_candidates(tree: ast.Module) -> list[ast.AST]:
    found = []
    for loop in ast.walk(tree):
        if isinstance(loop, (ast.For, ast.While)):
            for stmt in loop.body:
                for node in ast.walk(stmt):
                    if isinstance(node, ast.AugAssign) and isinstance(node.op, (ast.Add, ast.Sub)):
                        found.append(node)
                    elif (isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub))
                          and not (_is_text(node.left) or _is_text(node.right))):
                        found.append(node)
    return _in_source_order(found)


def _flipped(node: ast.AST) -> ast.AST:
    new = copy.copy(node)
    new.op = ast.Sub() if isinstance(node.op, ast.Add) else ast.Add()
    return new


def _inject_logic(tree: ast.Module) -> tuple[ast.Module, str, str] | None:
    loops = [n for n in _in_source_order(ast.walk(tree))
             if isinstance(n, ast.For) and _is_range_call(n.iter)]
    if loops:                                   # 1) off-by-one in the first `for ... in range()`
        target, replacement = loops[0].iter, _off_by_one(loops[0].iter)
    elif flips := _flip_candidates(tree):       # 2) flip the first +/- inside a loop
        target, replacement = flips[0], _flipped(flips[0])
    else:                                       # 3) any other range() call
        calls = [n for n in _in_source_order(ast.walk(tree)) if _is_range_call(n)]
        if not calls:
            return None
        target, replacement = calls[0], _off_by_one(calls[0])
    before, after = ast.unparse(target), ast.unparse(replacement)
    return _ReplaceNode(target, replacement).visit(tree), before, after


# ------------------------------------------------------------------------ public

def mutate(code: str, mode: str) -> tuple[str, str]:
    """Return (mutated_code, description). Unchanged code is returned if nothing applies."""
    if mode not in MODES:
        raise ValueError(f"unknown inject mode {mode!r}; expected one of {MODES}")
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code, f"no {mode} fault injected: the code does not parse"
    mutated = (_inject_crash if mode == "crash" else _inject_logic)(copy.deepcopy(tree))
    if mutated is None:
        return code, f"no {mode} fault injected: no suitable place found; code left unchanged"
    new_tree, before, after = mutated
    new_code = ast.unparse(ast.fix_missing_locations(new_tree)) + "\n"
    line = _line_of(new_code, after, word=(mode == "crash"))
    where = f" on line {line}" if line else ""
    if mode == "crash":
        return new_code, f"crash: renamed a use of `{before}` to `{after}`{where} (expect NameError)"
    kind = "off-by-one in range()" if "range" in before else "flipped +/- inside a loop"
    return new_code, f"logic: {kind}{where}: `{before}` -> `{after}`"
