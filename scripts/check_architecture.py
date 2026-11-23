"""Static import rules for the initial modular monolith (not a security sandbox)."""

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAYERS = {
    "domain": {"domain"},
    "application": {"domain", "application"},
    "adapters": {"domain", "adapters"},
    "interfaces": {"domain", "application", "adapters", "interfaces"},
}
PURE_STDLIB = {
    "__future__",
    "dataclasses",
    "enum",
    "hashlib",
    "json",
    "math",
    "typing",
    "collections",
    "datetime",
    "decimal",
    "uuid",
    "abc",
    "re",
    "functools",
}


def violations(source: str, layer: str) -> list[str]:
    errors = []
    for node in ast.walk(ast.parse(source)):
        modules = []
        if isinstance(node, ast.Import):
            modules = [item.name for item in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                errors.append(f"line {node.lineno}: use absolute imports so boundaries are visible")
                continue
            modules = [node.module or ""]
        elif isinstance(node, ast.Call) and (
            (isinstance(node.func, ast.Name) and node.func.id in {"__import__", "eval", "exec"})
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module")
        ):
            errors.append(f"line {node.lineno}: dynamic code/import bypasses static boundaries")
        for module in modules:
            assert isinstance(node, (ast.Import, ast.ImportFrom))
            parts = module.split(".")
            if parts[0] == "eval_orchestrator":
                if len(parts) < 2 or parts[1] not in LAYERS[layer]:
                    errors.append(f"line {node.lineno}: {layer} cannot import {module}")
            elif layer in {"domain", "application"} and parts[0] not in PURE_STDLIB:
                errors.append(f"line {node.lineno}: {module} belongs behind an adapter")
    return errors


def main() -> int:
    errors = []
    package = ROOT / "src/eval_orchestrator"
    for path in sorted(package.rglob("*.py")):
        relative = path.relative_to(package)
        if str(relative) == "__init__.py":
            if any(
                not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Constant)
                for node in ast.parse(path.read_text()).body
            ):
                errors.append("Package root must only contain its docstring")
            continue
        layer = relative.parts[0]
        if layer not in LAYERS:
            errors.append(f"{relative}: assign this module to an explicit layer")
            continue
        errors.extend(f"{relative}: {error}" for error in violations(path.read_text(), layer))
    print("\n".join(errors) if errors else "Architecture boundaries passed")
    return bool(errors)


if __name__ == "__main__":
    sys.exit(main())
