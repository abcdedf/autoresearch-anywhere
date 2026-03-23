"""CLI entry point for autoresearch-aw."""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import click
import yaml

from autoresearch_aw.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_RESEARCH_PATH,
    load_config,
    load_research,
    save_config,
)


@click.group()
@click.version_option(package_name="autoresearch-aw")
def cli():
    """autoresearch-aw — run autoresearch from anywhere."""


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("platform_name", type=click.Choice(["mac", "gcp", "aws", "azure"]))
def init(platform_name: str):
    """One-time platform setup."""
    config = load_config()

    # General settings (first time only)
    if "log_dir" not in config:
        log_dir = click.prompt("Log directory", default="./logs")
        config["log_dir"] = log_dir

    # Ensure log directory exists
    from pathlib import Path
    Path(config["log_dir"]).mkdir(parents=True, exist_ok=True)

    if "platforms" not in config:
        config["platforms"] = {}

    if platform_name == "mac":
        _init_mac(config)
    elif platform_name == "gcp":
        _init_gcp(config)
    elif platform_name == "aws":
        _init_aws(config)
    elif platform_name == "azure":
        _init_azure(config)

    save_config(config)
    click.echo(f"\nConfig saved to {DEFAULT_CONFIG_PATH}")


def _init_mac(config: dict):
    """Detect Apple Silicon and verify PyTorch MPS support."""
    click.echo("Detecting Mac environment...")

    # Check Apple Silicon
    machine = platform.machine()
    is_apple_silicon = machine == "arm64"

    if is_apple_silicon:
        click.echo(f"  Apple Silicon detected ({machine})")
    else:
        click.echo(f"  Intel Mac detected ({machine}) — MPS not available, will use CPU")

    # Check Python version
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    click.echo(f"  Python {py_version}")

    if sys.version_info < (3, 10):
        click.echo("  Error: Python 3.10+ required", err=True)
        sys.exit(1)

    # Check PyTorch MPS
    mps_available = False
    try:
        import torch
        mps_available = torch.backends.mps.is_available()
        if mps_available:
            click.echo("  PyTorch MPS: available")
        else:
            click.echo("  PyTorch MPS: not available (will use CPU)")
    except ImportError:
        click.echo("  PyTorch: not installed (will be installed by autoresearch)")

    config["platforms"]["mac"] = {
        "enabled": True,
        "apple_silicon": is_apple_silicon,
        "mps_available": mps_available,
    }

    click.echo("\nMac platform configured.")


def _init_gcp(config: dict):
    """Prompt for GCP settings."""
    click.echo("Configuring GCP...")

    # Check gcloud CLI
    if not shutil.which("gcloud"):
        click.echo("Error: gcloud CLI not found. Install with: brew install google-cloud-sdk", err=True)
        sys.exit(1)

    # Check authentication
    result = subprocess.run(
        ["gcloud", "auth", "application-default", "print-access-token"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        click.echo("Error: Not authenticated. Run: gcloud auth application-default login", err=True)
        sys.exit(1)

    project = click.prompt("GCP project")
    region = click.prompt("Region", default="us-central1")
    zone = click.prompt("Zone", default=f"{region}-a")
    use_spot = click.confirm("Use spot instances?", default=True)

    config["platforms"]["gcp"] = {
        "project": project,
        "region": region,
        "zone": zone,
        "instance_type": "n1-standard-4",
        "gpu_type": "nvidia-tesla-t4",
        "use_spot": use_spot,
    }

    click.echo("\nGCP platform configured.")


def _init_aws(config: dict):
    """Prompt for AWS settings."""
    click.echo("Configuring AWS...")

    if not shutil.which("aws"):
        click.echo("Error: AWS CLI not found. Install with: brew install awscli", err=True)
        sys.exit(1)

    # Check credentials
    result = subprocess.run(
        ["aws", "sts", "get-caller-identity"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        click.echo("Error: AWS credentials not configured. Run: aws configure", err=True)
        sys.exit(1)

    profile = click.prompt("AWS profile", default="default")
    region = click.prompt("Region", default="us-east-1")
    use_spot = click.confirm("Use spot instances?", default=True)

    config["platforms"]["aws"] = {
        "profile": profile,
        "region": region,
        "instance_type": "g5.xlarge",
        "use_spot": use_spot,
    }

    click.echo("\nAWS platform configured.")


def _init_azure(config: dict):
    """Prompt for Azure settings."""
    click.echo("Configuring Azure...")

    if not shutil.which("az"):
        click.echo("Error: Azure CLI not found. Install with: brew install azure-cli", err=True)
        sys.exit(1)

    # Check login
    result = subprocess.run(
        ["az", "account", "show"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        click.echo("Error: Not logged in. Run: az login", err=True)
        sys.exit(1)

    subscription = click.prompt("Subscription ID")
    region = click.prompt("Region", default="eastus")
    use_spot = click.confirm("Use spot instances?", default=True)

    config["platforms"]["azure"] = {
        "subscription": subscription,
        "region": region,
        "instance_type": "Standard_NC4as_T4_v3",
        "use_spot": use_spot,
    }

    click.echo("\nAzure platform configured.")


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

@cli.command("config")
def show_config():
    """Show current configuration."""
    config = load_config()
    research = load_research()

    # Init settings
    click.echo("── Init Settings ──────────────────────────")
    click.echo(f"Log directory:    {config.get('log_dir', 'not set')}")
    click.echo()

    click.echo("Platforms configured:")
    platforms = config.get("platforms", {})

    if "mac" in platforms:
        mac = platforms["mac"]
        device = "Apple Silicon MPS" if mac.get("mps_available") else "CPU"
        click.echo(f"  mac:    enabled ({device})")
    else:
        click.echo("  mac:    not configured")

    if "gcp" in platforms:
        g = platforms["gcp"]
        spot = "spot" if g.get("use_spot") else "on-demand"
        click.echo(f"  gcp:    {g['project']} / {g['zone']} / T4 {spot}")
    else:
        click.echo("  gcp:    not configured")

    if "aws" in platforms:
        a = platforms["aws"]
        spot = "spot" if a.get("use_spot") else "on-demand"
        click.echo(f"  aws:    {a['profile']} profile / {a['region']} / {a['instance_type']} {spot}")
    else:
        click.echo("  aws:    not configured")

    if "azure" in platforms:
        az = platforms["azure"]
        spot = "spot" if az.get("use_spot") else "on-demand"
        click.echo(f"  azure:  {az['region']} / {az['instance_type']} {spot}")
    else:
        click.echo("  azure:  not configured")

    # Research file
    click.echo()
    if research:
        click.echo(f"── Research File ({DEFAULT_RESEARCH_PATH}) ──────────")
        r = research.get("research", {})
        click.echo(f"Topic:            {r.get('topic', 'not set')}")
        click.echo(f"Program:          {r.get('program', 'not set')}")
        click.echo(f"Max experiments:  {r.get('max_experiments', 'not set')}")
        click.echo(f"Platform:         {research.get('platform', 'not set')}")
        b = research.get("budget", {})
        click.echo(f"Budget:           ${b.get('max_cost_usd', 'not set')}")
    else:
        click.echo(f"── Research File ({DEFAULT_RESEARCH_PATH}) ──────────")
        click.echo("  No research.yaml found")

    # Credentials
    click.echo()
    click.echo("── Credentials ────────────────────────────")

    anthropic_key = "set" if os.environ.get("ANTHROPIC_API_KEY") else "not set"
    click.echo(f"ANTHROPIC_API_KEY:  {anthropic_key}")

    openai_key = "set" if os.environ.get("OPENAI_API_KEY") else "not set"
    click.echo(f"OPENAI_API_KEY:     {openai_key}")

    gcp_auth = "authenticated" if shutil.which("gcloud") and subprocess.run(
        ["gcloud", "auth", "application-default", "print-access-token"],
        capture_output=True, text=True,
    ).returncode == 0 else "not authenticated"
    click.echo(f"GCP (gcloud):       {gcp_auth}")

    aws_auth = "configured" if shutil.which("aws") and subprocess.run(
        ["aws", "sts", "get-caller-identity"],
        capture_output=True, text=True,
    ).returncode == 0 else "not configured"
    click.echo(f"AWS (aws cli):      {aws_auth}")

    az_auth = "logged in" if shutil.which("az") and subprocess.run(
        ["az", "account", "show"],
        capture_output=True, text=True,
    ).returncode == 0 else "not logged in"
    click.echo(f"Azure (az cli):     {az_auth}")


# ---------------------------------------------------------------------------
# Stub commands (future iterations)
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("config_file", default="research.yaml", required=False)
@click.option("--dry-run", is_flag=True, help="Terraform plan only, no provisioning")
@click.option("--verbose", is_flag=True, help="Detailed logging")
def run(config_file: str, dry_run: bool, verbose: bool):
    """Run autoresearch end to end."""
    if dry_run:
        click.echo("Dry run not yet implemented for Mac.")
        return
    from autoresearch_aw.orchestrator import run_experiment
    run_experiment(research_path=config_file, verbose=verbose)


@cli.command()
@click.argument("config_file", default="research.yaml", required=False)
def estimate(config_file: str):
    """Show cost estimate without running."""
    click.echo("Not yet implemented. Coming in iteration 2.")


@cli.command()
def status():
    """Show status of a running session."""
    click.echo("Not yet implemented. Coming in iteration 3.")


@cli.command()
def stop():
    """Gracefully stop, collect results, tear down."""
    click.echo("Not yet implemented. Coming in iteration 3.")


@cli.command()
def teardown():
    """Force destroy cloud resources."""
    click.echo("Not yet implemented. Coming in iteration 3.")
