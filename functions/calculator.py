import ast
import re


_OP_WORDS = {
    "かける": "*",
    "掛ける": "*",
    "たす": "+",
    "足す": "+",
    "ひく": "-",
    "引く": "-",
    "わる": "/",
    "割る": "/",
}

_TRANSLATE_TABLE = str.maketrans({
    "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
    "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
    "＋": "+", "－": "-", "×": "*", "＊": "*", "÷": "/", "／": "/",
})

_EXPR_PATTERN = re.compile(r"[-+]?\d+(?:\s*[+\-*/]\s*[-+]?\d+)+")


def _extract_expression(text: str) -> str | None:
    normalized = (text or "")
    for src, dst in _OP_WORDS.items():
        normalized = normalized.replace(src, dst)

    normalized = normalized.translate(_TRANSLATE_TABLE)
    normalized = re.sub(r"\s+", "", normalized)

    match = _EXPR_PATTERN.search(normalized)
    if not match:
        return None

    return match.group(0)


def _safe_eval(expr: str) -> float:
    node = ast.parse(expr, mode="eval")

    def _eval(n):
        if isinstance(n, ast.Expression):
            return _eval(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            value = _eval(n.operand)
            return value if isinstance(n.op, ast.UAdd) else -value
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left = _eval(n.left)
            right = _eval(n.right)
            if isinstance(n.op, ast.Add):
                return left + right
            if isinstance(n.op, ast.Sub):
                return left - right
            if isinstance(n.op, ast.Mult):
                return left * right
            return left / right

        raise ValueError("unsupported expression")

    return _eval(node)


def calculate(text):
    expr = _extract_expression(text)
    if not expr:
        return "答えを計算できませんでした。"

    try:
        result = _safe_eval(expr)
    except Exception:
        return "答えを計算できませんでした。"

    if isinstance(result, float) and result.is_integer():
        result = int(result)

    return f"答えは{result}です。"