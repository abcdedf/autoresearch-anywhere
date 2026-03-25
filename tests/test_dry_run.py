"""Integration test: dry-run all platforms and verify output via log files.

Run with: uv run python tests/test_dry_run.py
"""

import os
import subprocess
import sys
import tempfile
import textwrap

PLATFORMS = ["mac", "aws", "gcp", "azure", "oci"]

EXPECTED = {
    "mac": {
        "instance_type": "N/A",
        "gpu_tuning": "upstream default",
        "hourly_rate": "$0.00/hr",
        "batch_size": None,         # no tuning for mac
    },
    "aws": {
        "instance_type": "g5.xlarge",
        "gpu_tuning": "A10G 24GB",
        "hourly_rate": "$1.01/hr",
        "batch_size": "DEVICE_BATCH_SIZE = 32",
    },
    "gcp": {
        "instance_type": "g2-standard-4",
        "gpu_tuning": "L4 24GB",
        "hourly_rate": "$0.72/hr",
        "batch_size": "DEVICE_BATCH_SIZE = 32",
    },
    "azure": {
        "instance_type": "Standard_NV36ads_A10_v5",
        "gpu_tuning": "A10 24GB",
        "hourly_rate": "$3.20/hr",
        "batch_size": "DEVICE_BATCH_SIZE = 32",
    },
    "oci": {
        "instance_type": "VM.GPU.A10.1",
        "gpu_tuning": "A10 24GB",
        "hourly_rate": "$0.50/hr",
        "batch_size": "DEVICE_BATCH_SIZE = 32",
    },
}

LOG_LATEST = os.path.join("logs", "run_latest.log")


def run_dry_run(platform: str) -> tuple[str, str]:
    """Run dry-run for a platform. Returns (console_output, log_content)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(textwrap.dedent(f"""\
            research:
              topic: "test"
              program: "program.md"
              max_experiments: 1
            platform: {platform}
            budget:
              max_cost_usd: 5.00
        """))
        f.flush()
        result = subprocess.run(
            ["uv", "run", "autoresearch-anycloud", "run", "--dry-run", f.name],
            capture_output=True, text=True,
        )
        console = result.stdout + result.stderr

        log_content = ""
        if os.path.exists(LOG_LATEST):
            with open(LOG_LATEST) as lf:
                log_content = lf.read()

        return console, log_content


def check(console: str, log: str, platform: str) -> list[str]:
    """Check dry-run output against expected values. Returns list of errors."""
    errors = []
    expected = EXPECTED[platform]

    # Verify both console and log have the same content
    for source_name, output in [("console", console), ("log", log)]:
        if "DRY RUN" not in output:
            errors.append(f"{source_name}: missing DRY RUN header")

        if f"Platform:        {platform}" not in output:
            errors.append(f"{source_name}: wrong platform")

        if f"Instance type:   {expected['instance_type']}" not in output:
            errors.append(f"{source_name}: wrong instance_type (expected {expected['instance_type']})")

        if f"GPU tuning:      {expected['gpu_tuning']}" not in output:
            errors.append(f"{source_name}: wrong gpu_tuning (expected {expected['gpu_tuning']})")

        if f"Hourly rate:     {expected['hourly_rate']}" not in output:
            errors.append(f"{source_name}: wrong hourly_rate (expected {expected['hourly_rate']})")

        if expected["batch_size"] and expected["batch_size"] not in output:
            errors.append(f"{source_name}: wrong batch_size (expected {expected['batch_size']})")

        # time_budget: if set in config, verify value is picked up; otherwise upstream default
        expected_tb = expected.get("time_budget")
        if expected_tb:
            if f"Time budget:     {expected_tb}" not in output:
                errors.append(f"{source_name}: wrong time_budget (expected {expected_tb})")
        else:
            if "Time budget:     upstream default" not in output:
                errors.append(f"{source_name}: missing time_budget upstream default")

        if "Est. total:" not in output:
            errors.append(f"{source_name}: missing cost estimate")

    return errors


def main():
    passed = 0
    failed = 0

    for platform in PLATFORMS:
        console, log = run_dry_run(platform)
        errors = check(console, log, platform)

        if errors:
            print(f"  FAIL  {platform}:")
            for e in errors:
                print(f"         - {e}")
            failed += 1
        else:
            print(f"  PASS  {platform}")
            passed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
