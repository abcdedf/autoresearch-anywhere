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
@click.argument("platform_name", type=click.Choice(["mac", "gcp", "aws", "azure", "oci"]))
@click.option("--credentials", "-c", default=None, help="Path to credentials file")
def init(platform_name: str, credentials: str):
    """One-time platform setup."""
    config = load_config()

    # General settings (first time only)
    if "log_dir" not in config:
        config["log_dir"] = "./logs"

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
        _init_aws(config, credentials)
    elif platform_name == "azure":
        _init_azure(config)
    elif platform_name == "oci":
        _init_oci(config)

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
    """Prompt for GCP settings. Reads service account JSON key file."""
    click.echo("Configuring GCP...\n")

    import json
    from google.oauth2 import service_account
    from google.cloud import compute_v1

    # Check for existing credentials (env var or application default)
    credentials = None
    project = None
    try:
        client = compute_v1.InstancesClient()
        click.echo("  GCP credentials: found")
    except Exception:
        # No credentials — ask for the JSON key file
        click.echo("  No GCP credentials found.")
        click.echo()

        json_path = click.prompt("  Path to GCP service account JSON key file")
        json_path = os.path.expanduser(json_path)

        if not os.path.exists(json_path):
            click.echo(f"  Error: File not found: {json_path}", err=True)
            sys.exit(1)

        # Read and verify the key file
        try:
            with open(json_path) as f:
                key_data = json.load(f)
            project = key_data.get("project_id")
            credentials = service_account.Credentials.from_service_account_file(json_path)
            client = compute_v1.InstancesClient(credentials=credentials)
            click.echo(f"  Verified (project: {project})")
        except Exception as e:
            click.echo(f"  Error: Invalid key file. {e}", err=True)
            sys.exit(1)

        # Save to standard location so google-cloud SDK finds it automatically
        gcp_cred_path = os.path.expanduser("~/.config/gcloud/application_default_credentials.json")
        os.makedirs(os.path.dirname(gcp_cred_path), exist_ok=True)
        shutil.copy2(json_path, gcp_cred_path)
        click.echo(f"  Credentials saved to {gcp_cred_path}")

    if not project:
        project = click.prompt("\nGCP project ID")
    region = click.prompt("Region", default="us-central1")
    zone = click.prompt("Zone", default=f"{region}-a")

    config["platforms"]["gcp"] = {
        "project": project,
        "region": region,
        "zone": zone,
        "instance_type": "n1-standard-4",
        "gpu_type": "nvidia-tesla-t4",
    }

    click.echo("\nGCP configured.")


def _init_aws(config: dict, credentials: str = None):
    """Configure AWS. Reads credentials CSV from ~/.aws/credentials/ or --credentials path."""
    click.echo("Configuring AWS...\n")

    import csv
    import boto3

    # Find the CSV
    default_dir = os.path.expanduser("~/.aws/credentials")
    if credentials:
        csv_path = os.path.expanduser(credentials)
    else:
        # Look for any CSV in ~/.aws/credentials/
        csv_path = None
        if os.path.isdir(default_dir):
            for name in os.listdir(default_dir):
                if name.endswith(".csv"):
                    csv_path = os.path.join(default_dir, name)
                    break

    if not csv_path or not os.path.exists(csv_path):
        click.echo(f"  Error: No credentials CSV found in {default_dir}/", err=True)
        click.echo(f"  Download your access keys CSV from the AWS IAM console", err=True)
        click.echo(f"  and move it to {default_dir}/", err=True)
        sys.exit(1)

    # Read and verify (encoding="utf-8-sig" handles BOM that AWS includes in CSV)
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        row = next(reader)
        access_key = row.get("Access key ID", "").strip()
        secret_key = row.get("Secret access key", "").strip()
    if not access_key or not secret_key:
        click.echo("  Error: Could not read keys from CSV. Expected columns: 'Access key ID', 'Secret access key'", err=True)
        sys.exit(1)

    try:
        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        click.echo(f"  Verified (account: {identity['Account']})")
    except Exception as e:
        click.echo(f"  Error: Invalid credentials. {e}", err=True)
        sys.exit(1)

    config["platforms"]["aws"] = {
        "region": "us-east-1",
        "instance_type": "g5.xlarge",
        "use_spot": False,          # Set True for spot instances (~50% cheaper, but can be interrupted)
        "spot_max_price": "0.50",   # Only used when use_spot is True
        "credentials_csv": csv_path,
    }

    click.echo("\nAWS configured.")


def _init_azure(config: dict):
    """Prompt for Azure settings. Uses service principal credentials (no CLI needed)."""
    click.echo("Configuring Azure...\n")

    from azure.identity import ClientSecretCredential, DefaultAzureCredential

    # Check for existing credentials (env vars or az login)
    try:
        credential = DefaultAzureCredential()
        credential.get_token("https://management.azure.com/.default")
        click.echo("  Azure credentials: found")
        subscription = click.prompt("\nSubscription ID")
    except Exception:
        # No credentials — ask for service principal
        click.echo("  No Azure credentials found.")
        click.echo()

        tenant_id = click.prompt("  Tenant ID (from Azure Portal → Microsoft Entra ID → Overview)")
        client_id = click.prompt("  Application (client) ID")
        client_secret = click.prompt("  Client secret value", hide_input=True)
        subscription = click.prompt("  Subscription ID")

        # Verify
        try:
            credential = ClientSecretCredential(
                tenant_id=tenant_id,
                client_id=client_id,
                client_secret=client_secret,
            )
            credential.get_token("https://management.azure.com/.default")
            click.echo("  Verified.")
        except Exception as e:
            click.echo(f"  Error: Invalid credentials. {e}", err=True)
            sys.exit(1)

        # Save as environment variables in a file the SDK can pick up
        azure_cred_dir = os.path.expanduser("~/.autoresearch-aw")
        os.makedirs(azure_cred_dir, exist_ok=True)
        env_path = os.path.join(azure_cred_dir, "azure_env")
        with open(env_path, "w") as f:
            f.write(f"AZURE_TENANT_ID={tenant_id}\n")
            f.write(f"AZURE_CLIENT_ID={client_id}\n")
            f.write(f"AZURE_CLIENT_SECRET={client_secret}\n")
            f.write(f"AZURE_SUBSCRIPTION_ID={subscription}\n")
        os.chmod(env_path, 0o600)
        click.echo(f"  Credentials saved to {env_path}")

        config["platforms"]["azure"] = {
            "subscription": subscription,
            "tenant_id": tenant_id,
            "client_id": client_id,
            "region": "eastus",
            "instance_type": "Standard_NC4as_T4_v3",
            "spot_max_price": "0.35",
        }

        region = click.prompt("\nRegion", default="eastus")
        config["platforms"]["azure"]["region"] = region
        click.echo("\nAzure configured.")
        return

    region = click.prompt("Region", default="eastus")

    config["platforms"]["azure"] = {
        "subscription": subscription,
        "region": region,
        "instance_type": "Standard_NC4as_T4_v3",
        "spot_max_price": "0.35",
    }

    click.echo("\nAzure configured.")


def _init_oci(config: dict):
    """Prompt for Oracle OCI settings. Reads API key config or creates one."""
    click.echo("Configuring Oracle OCI...\n")

    import oci

    # Check for existing credentials (~/.oci/config)
    try:
        oci_config = oci.config.from_file()
        identity_client = oci.identity.IdentityClient(oci_config)
        tenancy = identity_client.get_tenancy(oci_config["tenancy"]).data
        click.echo(f"  OCI credentials found (tenancy: {tenancy.name})")
    except Exception:
        # No credentials — guide through manual setup
        click.echo("  No OCI credentials found.")
        click.echo()
        click.echo("  You need 4 values from the OCI Console (Profile → API Keys):")
        click.echo()

        tenancy_ocid = click.prompt("  Tenancy OCID")
        user_ocid = click.prompt("  User OCID")
        region = click.prompt("  Region", default="us-ashburn-1")
        key_file = click.prompt("  Path to API private key PEM file")
        key_file = os.path.expanduser(key_file)
        fingerprint = click.prompt("  Key fingerprint")

        if not os.path.exists(key_file):
            click.echo(f"  Error: File not found: {key_file}", err=True)
            sys.exit(1)

        # Verify
        try:
            test_config = {
                "user": user_ocid,
                "key_file": key_file,
                "fingerprint": fingerprint,
                "tenancy": tenancy_ocid,
                "region": region,
            }
            identity_client = oci.identity.IdentityClient(test_config)
            tenancy = identity_client.get_tenancy(tenancy_ocid).data
            click.echo(f"  Verified (tenancy: {tenancy.name})")
        except Exception as e:
            click.echo(f"  Error: Invalid credentials. {e}", err=True)
            sys.exit(1)

        # Save to ~/.oci/config (standard OCI location)
        oci_dir = os.path.expanduser("~/.oci")
        os.makedirs(oci_dir, exist_ok=True)
        oci_config_path = os.path.join(oci_dir, "config")

        if not os.path.exists(oci_config_path):
            with open(oci_config_path, "w") as f:
                f.write("[DEFAULT]\n")
                f.write(f"user={user_ocid}\n")
                f.write(f"fingerprint={fingerprint}\n")
                f.write(f"tenancy={tenancy_ocid}\n")
                f.write(f"region={region}\n")
                f.write(f"key_file={key_file}\n")
            os.chmod(oci_config_path, 0o600)
            click.echo(f"  Credentials saved to {oci_config_path}")
        else:
            click.echo(f"  Note: {oci_config_path} already exists, not overwriting.")

    compartment_id = click.prompt("\nCompartment OCID")
    region = click.prompt("Region", default="us-ashburn-1")

    config["platforms"]["oci"] = {
        "compartment_id": compartment_id,
        "region": region,
        "instance_type": "VM.GPU.A10.1",
    }

    click.echo("\nOCI configured.")


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
        click.echo(f"  aws:    {a.get('region', '?')} / {a.get('instance_type', '?')} spot (${a.get('spot_max_price', '?')}/hr)")
    else:
        click.echo("  aws:    not configured")

    if "azure" in platforms:
        az = platforms["azure"]
        click.echo(f"  azure:  {az.get('region', '?')} / {az.get('instance_type', '?')} spot (${az.get('spot_max_price', '?')}/hr)")
    else:
        click.echo("  azure:  not configured")

    if "oci" in platforms:
        o = platforms["oci"]
        click.echo(f"  oci:    {o.get('region', '?')} / {o.get('instance_type', '?')}")
    else:
        click.echo("  oci:    not configured")

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
