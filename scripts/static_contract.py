"""Business objective: retain a mandatory local static baseline even when a sandbox cannot install Ruff/mypy.

Technical description: parses every production Python module and rejects untyped function signatures, wildcard imports, bare except clauses, dynamic exec/eval, and syntax-invalid modules; CI still requires real Ruff and mypy.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/invoice_canonicalizer"


def main() -> int:
    failures: list[str] = []
    checked = 0
    for path in sorted(SOURCE.rglob("*.py")):
        checked += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                missing = [
                    argument.arg
                    for argument in arguments
                    if argument.arg not in {"self", "cls"} and argument.annotation is None
                ]
                if node.args.vararg and node.args.vararg.annotation is None:
                    missing.append("*" + node.args.vararg.arg)
                if node.args.kwarg and node.args.kwarg.annotation is None:
                    missing.append("**" + node.args.kwarg.arg)
                if missing or node.returns is None:
                    failures.append(
                        f"{path.relative_to(ROOT)}:{node.lineno} untyped signature {node.name}: "
                        f"args={missing}, return_missing={node.returns is None}"
                    )
            elif isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names):
                failures.append(f"{path.relative_to(ROOT)}:{node.lineno} wildcard import")
            elif isinstance(node, ast.ExceptHandler) and node.type is None:
                failures.append(f"{path.relative_to(ROOT)}:{node.lineno} bare except")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
                failures.append(f"{path.relative_to(ROOT)}:{node.lineno} dynamic {node.func.id}() is forbidden")
    if failures:
        print("\n".join(failures))
        return 1
    print(f"Static contract passed for {checked} production Python modules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
