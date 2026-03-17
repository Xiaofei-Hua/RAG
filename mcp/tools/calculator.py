"""
Calculator Tool for MCP

Provides safe mathematical expression evaluation.
"""

from __future__ import annotations

import ast
import operator
from typing import Dict, Any

from utils.log_utils import log


def calculator_tool(expression: str) -> Dict[str, Any]:
    """
    Safe calculator tool.

    Evaluates mathematical expressions safely without using eval().

    Args:
        expression: Mathematical expression to evaluate

    Returns:
        Dictionary with result or error
    """
    # Define safe operators
    SAFE_OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
        ast.USub: operator.neg,
    }

    def safe_eval(node):
        """Recursively evaluate AST nodes safely."""
        if isinstance(node, ast.Num):
            return node.n
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"Unsupported constant type: {type(node.value)}")
        elif isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in SAFE_OPERATORS:
                raise ValueError(f"Unsupported operator: {op_type.__name__}")
            left = safe_eval(node.left)
            right = safe_eval(node.right)
            return SAFE_OPERATORS[op_type](left, right)
        elif isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in SAFE_OPERATORS:
                raise ValueError(f"Unsupported operator: {op_type.__name__}")
            operand = safe_eval(node.operand)
            return SAFE_OPERATORS[op_type](operand)
        else:
            raise ValueError(f"Unsupported expression type: {type(node).__name__}")

    try:
        # Parse expression into AST
        tree = ast.parse(expression, mode='eval')

        # Evaluate safely
        result = safe_eval(tree.body)

        return {
            "success": True,
            "expression": expression,
            "result": result,
        }

    except SyntaxError as e:
        return {
            "success": False,
            "error": f"Invalid expression syntax: {e}",
        }
    except ValueError as e:
        return {
            "success": False,
            "error": str(e),
        }
    except ZeroDivisionError:
        return {
            "success": False,
            "error": "Division by zero",
        }
    except Exception as e:
        log.error(f"Calculator error: {e}")
        return {
            "success": False,
            "error": f"Calculation failed: {e}",
        }


# Tool definition for MCP
CALCULATOR_TOOL_DEF = {
    "name": "calculator",
    "description": "Evaluate mathematical expressions safely. Supports +, -, *, /, **, %.",
    "input_schema": {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Mathematical expression to evaluate (e.g., '2 + 2', '10 * 5', '2 ** 8')"
            }
        },
        "required": ["expression"]
    }
}