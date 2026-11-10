#!/usr/bin/env python3
"""Validate configuration locally; never contact the provider or print input values."""

import argparse
import importlib.util
import os
import shlex
import sys
from pathlib import Path


def load_config_class():
    root = Path(__file__).resolve().parents[1] / "assets/templates/django"
    name = "_payment_config_template"
    spec = importlib.util.spec_from_file_location(
        name, root / "__init__.py", submodule_search_locations=[str(root)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    adapter = importlib.import_module(f"{name}.payment_adapter")
    return adapter.GatewayConfig, importlib.import_module(f"{name}.exceptions").ConfigurationError


def read_env_file(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip().isidentifier():
            raise ValueError("Invalid env-file assignment; no shell syntax is executed")
        tokens = shlex.split(value, comments=True)
        if len(tokens) > 1:
            raise ValueError("Quote env-file values containing spaces")
        values[key.strip()] = tokens[0] if tokens else ""
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file", type=Path, help="Optional simple KEY=value file; never sourced as shell"
    )
    args = parser.parse_args()
    config_class, config_error = load_config_class()
    try:
        values = dict(os.environ) if args.env_file is None else read_env_file(args.env_file)
        for name in ("PAYMENT_MIN_AMOUNT_IRR", "PAYMENT_MAX_AMOUNT_IRR"):
            if name in values:
                try:
                    values[name] = int(values[name])
                except ValueError:
                    raise ValueError("Amount limits must be integer IRR") from None
        config_class.from_mapping(values)
    except (config_error, OSError, ValueError) as error:
        # OSError and parser errors may contain secrets or paths; keep those diagnostics fixed.
        print(
            f"ERROR: {error}"
            if isinstance(error, config_error)
            else "ERROR: Cannot read configuration or parse integer limits/env-file syntax"
        )
        return 1
    print(
        "PASS: merchant format, explicit environment, callback safety, IRR, and local amount limits"
    )
    print("No values displayed. Merchant authorization and connectivity are not verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
