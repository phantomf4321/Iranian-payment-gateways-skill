#!/usr/bin/env python3
"""Heuristic Django integration audit. Does not execute project code or prove security."""

import argparse
import ast
import re
from pathlib import Path

EXCLUDED = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".ruff_cache"}
UUID = re.compile(r"[a-fA-F0-9]{8}-(?:[a-fA-F0-9]{4}-){3}[a-fA-F0-9]{12}\Z")


def audit(root: Path) -> list[str]:
    issues = []
    calls, definitions, literals = set(), set(), set()
    tests = 0
    if not root.is_dir():
        return ["Provide an existing Django application directory"]
    try:
        paths = sorted(root.rglob("*"))
        for path in paths:
            if not path.is_file() or EXCLUDED.intersection(path.relative_to(root).parts):
                continue
            if path.suffix not in {".py", ".ts", ".tsx", ".js", ".jsx", ".env"}:
                continue
            relative = path.relative_to(root)
            text = path.read_text()
            if re.search(r"(?:NEXT_PUBLIC_|VITE_)(?:ZARINPAL_)?(?:MERCHANT_ID|ACCESS_TOKEN)", text):
                issues.append(f"Potential frontend credential exposure: {relative}")
            if path.suffix != ".py":
                continue
            try:
                tree = ast.parse(text)
            except SyntaxError:
                issues.append(f"Invalid Python syntax: {relative}")
                continue
            is_test = path.name.startswith("test_") or "tests" in relative.parts
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    definitions.add(node.name)
                    tests += int(is_test and node.name.startswith("test_"))
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute):
                        calls.add(node.func.attr)
                    elif isinstance(node.func, ast.Name):
                        calls.add(node.func.id)
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    literals.add(node.value)
                if not is_test and isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    value = node.value
                    if any(
                        isinstance(t, ast.Name) and t.id == "ZARINPAL_MERCHANT_ID" for t in targets
                    ):
                        if isinstance(value, ast.Constant) and value.value:
                            issues.append(f"Hardcoded merchant setting: {relative}:{node.lineno}")
                if not is_test and isinstance(node, ast.keyword) and node.arg == "merchant_id":
                    if (
                        isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)
                        and UUID.fullmatch(node.value.value)
                    ):
                        issues.append(f"Literal merchant argument: {relative}:{node.lineno}")
    except (OSError, UnicodeError):
        return ["Could not read all candidate files; audit is incomplete"]
    required = {
        "payment persistence": "Payment" in definitions,
        "attempt persistence": "PaymentAttempt" in definitions,
        "server verification call": "verify_payment" in calls,
        "database row locking": "select_for_update" in calls,
        "durable fulfillment handoff": "FulfillmentEvent" in definitions,
        "automated payment tests": tests > 0,
        "callback configuration": "PAYMENT_CALLBACK_URL" in literals,
        "merchant configuration": "ZARINPAL_MERCHANT_ID" in literals,
    }
    issues.extend(
        f"Review missing evidence: {label}" for label, present in required.items() if not present
    )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    issues = audit(args.project)
    for issue in issues:
        print(f"REVIEW: {issue}")
    print("Heuristic checks only; review money flow, auth and locks. Run PostgreSQL tests.")
    if issues:
        return 1
    print(
        "PASS: expected Django integration evidence found; no matched credential exposure patterns"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
