"""G-code templates: the 'script' behind every custom G-code box.

A template is plain G-code with tags in braces, filled from a dictionary of
variables (see :mod:`gcodeproducer.core.gcode_vars`):

=================================  ===================================================
``{nozzle_temp}``                  value of a variable
``{nozzle_temp:.1f}``              with a Python format spec
``{nozzle_temp + 5}``              an expression (arithmetic, comparisons, ``and`` /
                                   ``or`` / ``not``, ``x if c else y``, and the
                                   functions ``round int float min max abs str``)
``{if chamber_temp > 0}`` ...      conditional block; ``{elif ...}`` and ``{else}``
``{endif}``                        are optional; blocks may be nested and may span
                                   lines
``{{`` / ``}}``                    literal ``{`` / ``}``
``; comments``                     left untouched (tags inside them are filled too)
=================================  ===================================================

Numbers print without a trailing ``.0`` (``S205``, ``Z0.2``); booleans print as
``1`` / ``0``.  Expressions are evaluated safely: only the constructs above are
allowed, nothing can be imported or called otherwise.  Problems (unknown
variables, syntax errors, unbalanced ``{if}``) are collected, not raised:
:func:`render` returns them with the text so the GUI / log can show them.
"""
from __future__ import annotations

import ast
import operator
import re
from typing import Iterable

_TAG = re.compile(r"\{\{|\}\}|\{([^{}]*)\}")

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_CMP = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
        ast.Gt: operator.gt, ast.GtE: operator.ge}
_FUNCS = {"round": round, "int": int, "float": float, "min": min, "max": max, "abs": abs, "str": str}


class TemplateError(ValueError):
    pass


def _eval(node, variables: dict):
    if isinstance(node, ast.Expression):
        return _eval(node.body, variables)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str, bool)):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in variables:
            return variables[node.id]
        if node.id in ("True", "False"):
            return node.id == "True"
        raise TemplateError(f"unknown variable '{node.id}'")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return _BIN[type(node.op)](_eval(node.left, variables), _eval(node.right, variables))
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, variables)
        if isinstance(node.op, ast.Not):
            return not v
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return +v
    if isinstance(node, ast.BoolOp):
        vals = [_eval(v, variables) for v in node.values]
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, variables)
        for op, comp in zip(node.ops, node.comparators):
            if type(op) not in _CMP:
                raise TemplateError("unsupported comparison")
            right = _eval(comp, variables)
            if not _CMP[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _eval(node.body if _eval(node.test, variables) else node.orelse, variables)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS \
            and not node.keywords:
        return _FUNCS[node.func.id](*[_eval(a, variables) for a in node.args])
    raise TemplateError(f"not allowed in a template: {ast.dump(node)[:40]}")


def evaluate(expr: str, variables: dict):
    """Safely evaluate one template expression."""
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise TemplateError(f"syntax error in '{expr.strip()}'") from exc
    return _eval(tree, variables)


def format_value(value, spec: str = "") -> str:
    if spec:
        return format(value, spec)
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _split_spec(body: str):
    """'expr:spec' -> (expr, spec); a ':' inside brackets / quotes is part of the expression."""
    depth, quote = 0, None
    for i, ch in enumerate(body):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == ":" and depth == 0:
            return body[:i], body[i + 1:]
    return body, ""


def _tokens(text: str):
    """Yield ('text', s) and ('tag', kind, arg, line) items."""
    pos = 0
    for m in _TAG.finditer(text):
        if m.start() > pos:
            yield ("text", text[pos:m.start()])
        line = text.count("\n", 0, m.start()) + 1
        tok = m.group(0)
        if tok == "{{":
            yield ("text", "{")
        elif tok == "}}":
            yield ("text", "}")
        else:
            body = m.group(1).strip()
            word = body.split(None, 1)[0] if body else ""
            if word in ("if", "elif"):
                yield ("tag", word, body[len(word):].strip(), line)
            elif body in ("else", "endif"):
                yield ("tag", body, "", line)
            else:
                yield ("tag", "expr", m.group(1), line)
        pos = m.end()
    if pos < len(text):
        yield ("text", text[pos:])


def render(text: str, variables: dict) -> tuple:
    """Fill a template. Returns ``(text, problems)``; problems is a list of messages."""
    out, problems = [], []
    # stack frames: [parent_active, branch_taken, active, line]
    stack: list = []
    active = True

    def cond(arg, line):
        try:
            return bool(evaluate(arg, variables))
        except TemplateError as exc:
            problems.append(f"line {line}: {exc}")
            return False

    for tok in _tokens(text or ""):
        if tok[0] == "text":
            if active:
                out.append(tok[1])
            continue
        _t, kind, arg, line = tok
        if kind == "if":
            took = active and cond(arg, line)
            stack.append([active, took, took, line])
            active = took
        elif kind in ("elif", "else"):
            if not stack:
                problems.append(f"line {line}: '{{{kind}}}' without '{{if}}'")
                continue
            frame = stack[-1]
            if frame[1] or not frame[0]:
                frame[2] = False
            else:
                frame[2] = True if kind == "else" else cond(arg, line)
                frame[1] = frame[2]
            active = frame[2]
        elif kind == "endif":
            if not stack:
                problems.append(f"line {line}: '{{endif}}' without '{{if}}'")
                continue
            active = stack.pop()[0]
        else:
            if not active:
                continue
            expr, spec = _split_spec(arg)
            try:
                out.append(format_value(evaluate(expr, variables), spec.strip()))
            except (TemplateError, ValueError, TypeError, ZeroDivisionError) as exc:
                problems.append(f"line {line}: {exc}")
                out.append("{" + arg + "}")          # keep it visible in the output
    for frame in stack:
        problems.append(f"line {frame[3]}: '{{if}}' without '{{endif}}'")
    return "".join(out), problems


def check(text: str, names: Iterable[str]) -> list:
    """Problems in a template, checked against the variable *names* (values not needed).

    Every branch is checked, not only the ones that would be taken."""
    names = set(names)
    problems = []
    depth_lines = []
    for tok in _tokens(text or ""):
        if tok[0] == "text":
            continue
        _t, kind, arg, line = tok
        if kind == "if":
            depth_lines.append(line)
        elif kind == "endif":
            if not depth_lines:
                problems.append(f"line {line}: '{{endif}}' without '{{if}}'")
            else:
                depth_lines.pop()
        elif kind in ("elif", "else") and not depth_lines:
            problems.append(f"line {line}: '{{{kind}}}' without '{{if}}'")
        if kind in ("if", "elif", "expr"):
            expr = _split_spec(arg)[0] if kind == "expr" else arg
            try:
                tree = ast.parse(expr.strip(), mode="eval")
            except SyntaxError:
                problems.append(f"line {line}: syntax error in '{expr.strip()}'")
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id not in names and node.id not in _FUNCS \
                        and node.id not in ("True", "False"):
                    problems.append(f"line {line}: unknown variable '{node.id}'")
    for line in depth_lines:
        problems.append(f"line {line}: '{{if}}' without '{{endif}}'")
    return problems
