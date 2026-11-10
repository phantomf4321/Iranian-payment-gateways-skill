#!/usr/bin/env python3
"""Official frontmatter validation plus local resource, link, and syntax checks."""

import argparse
import ast
import re
from pathlib import Path

import yaml
from _official_quick_validate import validate_skill as official_validate

REQUIRED = [
    "SKILL.md",
    "agents/openai.yaml",
    "references/architecture.md",
    "references/zarinpal-api.md",
    "references/payment-lifecycle.md",
    "references/security.md",
    "references/django-integration.md",
    "references/troubleshooting.md",
    "scripts/validate_config.py",
    "scripts/validate_integration.py",
    "assets/templates/django/payment_adapter.py",
    "assets/templates/django/payment_service.py",
    "assets/templates/django/models.py",
    "assets/templates/django/views.py",
    "assets/templates/django/urls.py",
    "assets/templates/django/admin.py",
    "assets/templates/django/exceptions.py",
    "assets/templates/django/tests/test_service.py",
]


def validate(root: Path) -> list[str]:
    issues = []
    valid, message = official_validate(root)
    if not valid:
        issues.append(message)
    for name in REQUIRED:
        path = root / name
        if not path.is_file() or path.stat().st_size == 0:
            issues.append(f"Missing or empty resource: {name}")
    if not (root / "SKILL.md").is_file():
        return issues
    content = (root / "SKILL.md").read_text()
    try:
        frontmatter = yaml.safe_load(content.split("---", 2)[1])
        if (
            frontmatter.get("name") != "iranian-payment-gateways"
            or root.name != "iranian-payment-gateways"
        ):
            issues.append("Skill name and directory must be iranian-payment-gateways")
        if (
            not isinstance(frontmatter.get("description"), str)
            or not frontmatter["description"].strip()
        ):
            issues.append("Provide a nonempty trigger description")
    except (IndexError, AttributeError, yaml.YAMLError):
        issues.append("Cannot parse skill metadata")
    try:
        ui = yaml.safe_load((root / "agents/openai.yaml").read_text())["interface"]
        if not 25 <= len(ui["short_description"]) <= 64:
            issues.append("UI short_description must have 25–64 characters")
        if "$iranian-payment-gateways" not in ui["default_prompt"]:
            issues.append("UI prompt must explicitly invoke the skill")
    except (OSError, KeyError, TypeError, yaml.YAMLError):
        issues.append("Invalid agents/openai.yaml")
    definitions = list(root.rglob("SKILL.md"))
    if definitions != [root / "SKILL.md"]:
        issues.append("Keep exactly one authoritative SKILL.md")
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix in {".md", ".yaml"}:
            text = path.read_text()
            if re.search(r"\b(?:TODO|FIXME|TBD)\b|\[INSERT\b", text):
                issues.append(f"Unfinished content: {path.relative_to(root)}")
            if path.suffix == ".md":
                for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
                    if "://" in link or link.startswith("#"):
                        continue
                    target = (path.parent / link.split("#")[0]).resolve()
                    if not target.is_relative_to(root.resolve()) or not target.exists():
                        issues.append(
                            f"Broken or escaping link in {path.relative_to(root)}: {link}"
                        )
        if path.suffix == ".py":
            try:
                ast.parse(path.read_text())
            except SyntaxError:
                issues.append(f"Invalid Python syntax: {path.relative_to(root)}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    issues = validate(args.skill)
    for issue in issues:
        print(f"ERROR: {issue}")
    if issues:
        return 1
    print("PASS: official metadata, resources, local links, UI metadata, and Python syntax")
    print("Structural validation does not prove payment correctness.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
