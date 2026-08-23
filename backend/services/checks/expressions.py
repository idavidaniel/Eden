"""A deliberately small expression evaluator for assertion checks.

`eval()` would let a pack — or a model that wrote one — run anything. This walks
the AST and refuses everything that is not arithmetic, comparison, or a call to
one of a handful of named functions. No attribute access, no subscripting into
callables, no imports, no names except the ones bound by the caller.
"""

import ast
import operator

MAX_LENGTH = 500

_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: operator.not_}
_COMPARE = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}
FUNCTIONS = {
    "abs": abs,
    "all": all,
    "any": any,
    "float": float,
    "int": int,
    "len": len,
    "max": max,
    "min": min,
    "round": round,
    "sum": sum,
    "sorted": sorted,
}


class ExpressionError(ValueError):
    pass


def evaluate(expression: str, values: dict):
    if not expression or len(expression) > MAX_LENGTH:
        raise ExpressionError(f"Expression must be 1–{MAX_LENGTH} characters.")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"Could not parse the expression: {exc.msg}") from exc
    return _eval(tree.body, values)


def _eval(node, values):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in values:
            return values[node.id]
        raise ExpressionError(f"Unknown name '{node.id}'.")
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        return _BINARY[type(node.op)](_eval(node.left, values), _eval(node.right, values))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand, values))
    if isinstance(node, ast.BoolOp):
        results = [_eval(value, values) for value in node.values]
        return all(results) if isinstance(node.op, ast.And) else any(results)
    if isinstance(node, ast.Compare):
        left = _eval(node.left, values)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            if type(op) not in _COMPARE:
                raise ExpressionError(f"Comparison {type(op).__name__} is not allowed.")
            right = _eval(comparator, values)
            if not _COMPARE[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            allowed = ", ".join(sorted(FUNCTIONS))
            raise ExpressionError(f"Only these functions are available: {allowed}")
        if node.keywords:
            raise ExpressionError("Keyword arguments are not allowed.")
        return FUNCTIONS[node.func.id](*[_eval(arg, values) for arg in node.args])
    if isinstance(node, ast.List | ast.Tuple):
        return [_eval(item, values) for item in node.elts]
    if isinstance(node, ast.Subscript):
        container = _eval(node.value, values)
        if not isinstance(container, list | tuple | dict | str):
            raise ExpressionError("Only lists, strings and plain objects can be indexed.")
        return container[_eval(node.slice, values)]
    raise ExpressionError(f"{type(node).__name__} is not allowed in an assertion.")
