import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents/skills/iranian-payment-gateways"
SCRIPTS = SKILL / "scripts"


def run(script, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), *map(str, args)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_real_skill_passes_official_and_extended_validation():
    result = run("validate_skill.py")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture
def skill_copy(tmp_path):
    target = tmp_path / "iranian-payment-gateways"
    shutil.copytree(SKILL, target, ignore=shutil.ignore_patterns("__pycache__"))
    return target


def test_skill_validator_rejects_missing_file(skill_copy):
    (skill_copy / "references/security.md").unlink()
    result = run("validate_skill.py", skill_copy)
    assert result.returncode == 1 and "security.md" in result.stdout


def test_skill_validator_rejects_broken_link_and_unfinished_content(skill_copy):
    with (skill_copy / "SKILL.md").open("a") as handle:
        handle.write("\nTODO: [missing](references/missing.md)\n")
    result = run("validate_skill.py", skill_copy)
    assert result.returncode == 1
    assert "Unfinished" in result.stdout and "Broken" in result.stdout


@pytest.mark.parametrize(
    "frontmatter",
    [
        "name: other\ndescription: Wrong name",
        "name: [invalid]\ndescription: x",
        "not: [valid",
        "- list",
    ],
)
def test_skill_validator_rejects_bad_metadata(skill_copy, frontmatter):
    (skill_copy / "SKILL.md").write_text(f"---\n{frontmatter}\n---\nBody\n")
    result = run("validate_skill.py", skill_copy)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


def test_example_config_is_valid_but_not_live_authorization():
    result = run("validate_config.py", "--env-file", SKILL / "assets/templates/django/.env.example")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "not verified" in result.stdout


@pytest.mark.parametrize(
    "extra",
    [
        "ZARINPAL_MERCHANT_ID=private-invalid-value",
        "ZARINPAL_SANDBOX=yes",
        "PAYMENT_CALLBACK_URL=http://insecure.example/",
        "PAYMENT_CURRENCY=IRT",
        "PAYMENT_MIN_AMOUNT_IRR=not-integer",
        "PAYMENT_MAX_AMOUNT_IRR=-1",
        "unexpected shell syntax",
    ],
)
def test_config_validator_rejects_bad_settings_without_values(tmp_path, extra):
    config = tmp_path / ".env"
    config.write_text(
        (SKILL / "assets/templates/django/.env.example").read_text() + "\n" + extra + "\n"
    )
    result = run("validate_config.py", "--env-file", config)
    assert result.returncode == 1
    assert "private-invalid-value" not in result.stdout + result.stderr
    assert "http://insecure.example" not in result.stdout + result.stderr
    assert "Traceback" not in result.stderr


def test_integration_validator_accepts_reference_assets():
    result = run("validate_integration.py", SKILL / "assets/templates/django")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Heuristic" in result.stdout


def test_integration_validator_rejects_empty_project(tmp_path):
    result = run("validate_integration.py", tmp_path)
    assert result.returncode == 1 and "server verification" in result.stdout


def test_integration_validator_flags_credentials_and_no_tests(tmp_path):
    (tmp_path / "settings.py").write_text(
        'ZARINPAL_MERCHANT_ID = "00000000-1111-2222-3333-444444444444"\n'
    )
    (tmp_path / "page.tsx").write_text(
        "const merchant = process.env.NEXT_PUBLIC_ZARINPAL_MERCHANT_ID;\n"
    )
    result = run("validate_integration.py", tmp_path)
    assert result.returncode == 1
    assert "Hardcoded merchant" in result.stdout and "frontend credential" in result.stdout
    assert "00000000-1111" not in result.stdout


def test_integration_validator_reports_syntax_errors(tmp_path):
    (tmp_path / "service.py").write_text("invalid Python $$$\n")
    result = run("validate_integration.py", tmp_path)
    assert result.returncode == 1 and "syntax" in result.stdout


def test_invalid_cli_usage_has_nonzero_exit():
    assert run("validate_config.py", "--unknown-flag").returncode == 2
