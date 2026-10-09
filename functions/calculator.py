"""式を読み取り計算結果を返す関数群で、数値質問を即時に処理します。"""

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

_EXPR_PATTERN = re.compile(r"[0-9+\-*/().]+")
_PAIR_EXPR_PATTERNS = (
    (re.compile(r"([-+]?\d+)\s*と\s*([-+]?\d+)\s*(?:を)?\s*(?:足して|たして)"), "+"),
    (re.compile(r"([-+]?\d+)\s*と\s*([-+]?\d+)\s*(?:を)?\s*(?:引いて|ひいて)"), "-"),
    (re.compile(r"([-+]?\d+)\s*と\s*([-+]?\d+)\s*(?:を)?\s*(?:かけて|掛けて)"), "*"),
    (re.compile(r"([-+]?\d+)\s*と\s*([-+]?\d+)\s*(?:を)?\s*(?:割って|わって)"), "/"),
)


def _extract_expression(text: str) -> str | None:
    original = (text or "")
    for pattern, operator in _PAIR_EXPR_PATTERNS:
        match = pattern.search(original)
        if match:
            return f"{match.group(1)}{operator}{match.group(2)}"

    normalized = original
    for src, dst in _OP_WORDS.items():
        normalized = normalized.replace(src, dst)

    normalized = normalized.translate(_TRANSLATE_TABLE)
    normalized = re.sub(r"\s+", "", normalized)

    candidates = _EXPR_PATTERN.findall(normalized)
    for candidate in candidates:
        if not candidate:
            continue
        if not re.search(r"\d", candidate):
            continue
        if not re.search(r"[+\-*/]", candidate):
            continue

        trimmed = candidate
        while trimmed and trimmed[0] in "+*/.":
            trimmed = trimmed[1:]
        while trimmed and trimmed[-1] in "+-*/.(":
            trimmed = trimmed[:-1]

        if not trimmed:
            continue
        if not re.search(r"\d", trimmed):
            continue
        if not re.search(r"[+\-*/]", trimmed):
            continue
        return trimmed

    return None


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