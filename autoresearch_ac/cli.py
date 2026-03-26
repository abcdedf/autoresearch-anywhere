"""CLI entry point for autoresearch-anycloud."""

import os
import platform
import sys
from pathlib import Path

import click
import yaml

from autoresearch_ac.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_RESEARCH_PATH,
    load_config,
    load_research,
    save_config,
)
from autoresearch_ac.cost import GPU_CATALOG, GPU_DEFAULTS, GPU_PRICING
from autoresearch_ac.log import Logger


@click.group()
@click.version_option(package_name="autoresearch-anycloud")
def cli():
    """autoresearch-anycloud — run autoresearch on any cloud GPU."""


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("platform_name", type=click.Choice(["mac", "gcp", "aws", "azure", "oci"]))
@click.option("--gpu", "-g", default=None, help="Use this option for the tool to pick a compatible instance for this GPU model (e.g. h100, a100, l4). Default: cheapest compatible.")
@click.option("--instance-type", default=None, help="Use this exact cloud instance type, bypassing GPU-to-instance mapping.")
@click.option("--list-gpus", is_flag=True, help="Show available GPU models, their instance types, and pricing for this platform.")
def init(platform_name: str, gpu: str | None, instance_type: str | None, list_gpus: bool):
    """One-time platform setup.

    Only the platform name is required. If neither --gpu nor --instance-type
    is given, the tool defaults to the cheapest compatible GPU for the platform.
    """

    # --list-gpus: show available GPUs and exit
    if list_gpus:
        _list_gpus(platform_name)
        return

    config = load_config()

    # General settings (first time only)
    if "log_dir" not in config:
        config["log_dir"] = "./logs"

    # Ensure log directory exists
    from pathlib import Path
    Path(config["log_dir"]).mkdir(parents=True, exist_ok=True)

    if "platforms" not in config:
        config["platforms"] = {}

    # Resolve GPU / instance type for cloud platforms
    resolved_instance_type = None
    if platform_name != "mac":
        resolved_instance_type = _resolve_instance_type(platform_name, gpu, instance_type)

    with Logger(config["log_dir"]) as log:
        if platform_name == "mac":
            _init_mac(config, log)
        elif platform_name == "gcp":
            _init_gcp(config, log)
        elif platform_name == "aws":
            _init_aws(config, log)
        elif platform_name == "azure":
            _init_azure(config, log)
        elif platform_name == "oci":
            _init_oci(config, log)

    # Apply resolved instance type (overrides provider default)
    if resolved_instance_type and platform_name in config.get("platforms", {}):
        config["platforms"][platform_name]["instance_type"] = resolved_instance_type

    config["active_platform"] = platform_name
    save_config(config)
    click.echo(f"\n{platform_name} is now the active platform. Config saved to {DEFAULT_CONFIG_PATH}")


def _resolve_instance_type(platform_name: str, gpu: str | None, instance_type: str | None) -> str:
    """Resolve instance type from --instance-type, --gpu, or provider default."""
    # --instance-type takes priority
    if instance_type:
        click.echo(f"  Instance type: {instance_type} (from --instance-type)")
        return instance_type

    catalog = GPU_CATALOG.get(platform_name, {})

    # --gpu: look up in catalog
    if gpu:
        gpu_lower = gpu.lower()
        if gpu_lower not in catalog:
            available = ", ".join(sorted(catalog.keys()))
            click.echo(f"Error: GPU type '{gpu}' not available for {platform_name}.", err=True)
            click.echo(f"Available: {available}", err=True)
            click.echo(f"Run: autoresearch-anycloud init {platform_name} --list-gpus", err=True)
            sys.exit(1)
        entry = catalog[gpu_lower]
        click.echo(f"  GPU: {entry['gpu']} → {entry['instance_type']} ({entry['note']})")
        return entry["instance_type"]

    # Default: cheapest compatible GPU
    default_gpu = GPU_DEFAULTS.get(platform_name)
    if default_gpu and default_gpu in catalog:
        entry = catalog[default_gpu]
        click.echo(f"  GPU: {entry['gpu']} → {entry['instance_type']} (default)")
        return entry["instance_type"]

    return None


def _list_gpus(platform_name: str):
    """Show available GPU types for a platform."""
    if platform_name == "mac":
        click.echo("Mac uses Apple Silicon MPS — no GPU selection needed.")
        return

    catalog = GPU_CATALOG.get(platform_name, {})
    if not catalog:
        click.echo(f"No GPU catalog for {platform_name}.")
        return

    default_gpu = GPU_DEFAULTS.get(platform_name)
    click.echo(f"\nAvailable GPUs for {platform_name}:\n")
    click.echo(f"  {'GPU':<12} {'Instance Type':<30} {'$/hr':>8}  {'Note'}")
    click.echo(f"  {'─'*12} {'─'*30} {'─'*8}  {'─'*30}")
    for gpu_key, entry in catalog.items():
        rate = GPU_PRICING.get(entry["instance_type"], 0.0)
        default_marker = " (default)" if gpu_key == default_gpu else ""
        click.echo(f"  {entry['gpu']:<12} {entry['instance_type']:<30} ${rate:>7.2f}  {entry['note']}{default_marker}")
    click.echo(f"\nUsage:")
    click.echo(f"  autoresearch-anycloud init {platform_name} --gpu h100")
    click.echo(f"  autoresearch-anycloud init {platform_name} --instance-type <exact-type>")


def _init_mac(config: dict, log=None):
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


def _init_gcp(config: dict, log=None):
    """Configure GCP. Auto-detects service account JSON key from ~/.config/gcloud/."""
    click.echo("Configuring GCP...\n")

    import json
    from google.oauth2 import service_account
    from google.cloud import compute_v1

    # Find the JSON key file in ~/.config/gcloud/
    gcloud_dir = os.path.expanduser("~/.config/gcloud")
    json_path = None
    adc_path = os.path.join(gcloud_dir, "application_default_credentials.json")
    if os.path.exists(adc_path):
        json_path = adc_path
    elif os.path.isdir(gcloud_dir):
        for name in os.listdir(gcloud_dir):
            if name.endswith(".json"):
                json_path = os.path.join(gcloud_dir, name)
                break

    if not json_path or not os.path.exists(json_path):
        click.echo("  Error: No GCP credentials found.", err=True)
        click.echo("  Create a service account key (JSON) in the GCP Console:", err=True)
        click.echo("    IAM & Admin → Service Accounts → Keys → Add Key → JSON", err=True)
        click.echo(f"  Then move the JSON file to {gcloud_dir}/", err=True)
        sys.exit(1)

    # Read and verify the key file
    try:
        with open(json_path) as f:
            key_data = json.load(f)
        project = key_data.get("project_id")
        if not project:
            click.echo("  Error: JSON key file does not contain a project_id field.", err=True)
            sys.exit(1)
        creds = service_account.Credentials.from_service_account_file(json_path)
        client = compute_v1.InstancesClient(credentials=creds)
        click.echo(f"  Verified (project: {project})")
    except Exception as e:
        click.echo(f"  Error: Invalid key file. {e}", err=True)
        sys.exit(1)

    config["platforms"]["gcp"] = {
        "project": project,
        "region": "us-central1",
        "zone": "us-central1-a",
        "instance_type": "n1-standard-4",
        "gpu_type": "nvidia-tesla-t4",
        "credentials_json": json_path,
    }

    click.echo("\nGCP configured.")


def _init_aws(config: dict, log=None):
    """Configure AWS. Auto-detects credentials CSV from ~/.aws/credentials/."""
    click.echo("Configuring AWS...\n")

    import csv
    import boto3

    # Find the CSV in ~/.aws/credentials/
    default_dir = os.path.expanduser("~/.aws/credentials")
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


def _init_azure(config: dict, log=None):
    """Configure Azure. Auto-detects service principal from ~/.azure/, or env vars."""
    click.echo("Configuring Azure...\n")

    import json
    from azure.identity import ClientSecretCredential

    default_json = os.path.expanduser("~/.azure/service-principal.json")
    tenant_id = None
    client_id = None
    client_secret = None
    subscription_id = None
    credentials_source = None

    # 1. Environment variables
    if not tenant_id:
        env_tenant = os.environ.get("AZURE_TENANT_ID")
        env_client = os.environ.get("AZURE_CLIENT_ID")
        env_secret = os.environ.get("AZURE_CLIENT_SECRET")
        env_sub = os.environ.get("AZURE_SUBSCRIPTION_ID")
        if env_tenant and env_client and env_secret and env_sub:
            tenant_id = env_tenant
            client_id = env_client
            client_secret = env_secret
            subscription_id = env_sub
            credentials_source = "environment variables"

    # 3. Default JSON file (~/.azure/service-principal.json)
    if not tenant_id and os.path.exists(default_json):
        try:
            with open(default_json) as f:
                creds = json.load(f)
            tenant_id = creds["tenant_id"]
            client_id = creds["client_id"]
            client_secret = creds["client_secret"]
            subscription_id = creds["subscription_id"]
            credentials_source = default_json
        except (KeyError, json.JSONDecodeError):
            click.echo(f"  Warning: Found {default_json} but it is invalid, skipping.", err=True)

    # No credentials found — print instructions and exit
    if not tenant_id:
        click.echo("  Error: No Azure service principal credentials found.", err=True)
        click.echo("", err=True)
        click.echo("  Create a service principal in the Azure Portal:", err=True)
        click.echo("    1. Go to Microsoft Entra ID → App registrations → New registration", err=True)
        click.echo("    2. Certificates & secrets → New client secret → copy the Value", err=True)
        click.echo("    3. Note the Application (client) ID and Directory (tenant) ID from Overview", err=True)
        click.echo("    4. Go to Subscriptions → your subscription → copy the Subscription ID", err=True)
        click.echo("    5. Still in the subscription, go to Access control (IAM) → Add role → Contributor → assign to your app", err=True)
        click.echo("", err=True)
        click.echo("  Save credentials as JSON:", err=True)
        click.echo(f"    {default_json}", err=True)
        click.echo("  Or set env vars: AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_SUBSCRIPTION_ID", err=True)
        click.echo("", err=True)
        click.echo("  JSON format:", err=True)
        click.echo('    {"tenant_id": "...", "client_id": "...", "client_secret": "...", "subscription_id": "..."}', err=True)
        sys.exit(1)

    # Verify credentials
    click.echo(f"  Credentials source: {credentials_source}")
    try:
        credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )
        credential.get_token("https://management.azure.com/.default")
        click.echo(f"  Verified (subscription: {subscription_id})")
    except Exception as e:
        click.echo(f"  Error: Invalid credentials. {e}", err=True)
        sys.exit(1)

    config["platforms"]["azure"] = {
        "subscription": subscription_id,
        "region": "eastus",
        "instance_type": "Standard_NC4as_T4_v3",
        "spot_max_price": "0.35",
        "credentials_json": credentials_source,
    }

    click.echo("\nAzure configured.")


def _init_oci(config: dict, log=None):
    """Configure OCI. Auto-detects API key config from ~/.oci/config."""
    log.log("Configuring Oracle OCI...")

    try:
        import oci
    except ImportError:
        log.error("OCI SDK not installed. Install it with: uv pip install oci")
        sys.exit(1)

    # Find OCI config file
    config_path = os.path.expanduser("~/.oci/config")

    if not os.path.exists(config_path):
        log.error(f"OCI config not found at {config_path}")
        log.log("  Set up OCI API key authentication:")
        log.log("    1. OCI Console -> My profile -> API keys -> Add API key -> Generate API key pair")
        log.log("    2. Download the private key and save to ~/.oci/oci_api_key.pem")
        log.log("    3. Create ~/.oci/config with user, fingerprint, tenancy, region, key_file, and compartment")
        log.log("    4. Re-run: autoresearch-anycloud init oci")
        log.log("  See README.md -> Oracle OCI for step-by-step instructions.")
        sys.exit(1)

    # Check key file permissions
    key_file_path = None
    try:
        oci_raw = oci.config.from_file(file_location=config_path)
        key_file_path = oci_raw.get("key_file")
    except Exception:
        pass

    if key_file_path and os.path.exists(os.path.expanduser(key_file_path)):
        key_perms = oct(os.stat(os.path.expanduser(key_file_path)).st_mode)[-3:]
        if key_perms != "600" and key_perms != "400":
            log.log(f"  Warning: key file permissions are {key_perms}, should be 600.")
            log.log(f"  Run: chmod 600 {key_file_path}")

    # Read and verify credentials
    try:
        oci_config = oci.config.from_file(file_location=config_path)
        oci.config.validate_config(oci_config)
        identity_client = oci.identity.IdentityClient(oci_config)
        tenancy = identity_client.get_tenancy(oci_config["tenancy"]).data
        log.log(f"  Verified (tenancy: {tenancy.name})")
    except Exception as e:
        log.error(f"Could not authenticate with OCI config at {config_path}.")
        log.log(f"  {e}")
        log.log("  Ensure your ~/.oci/config has valid user, tenancy, key_file, and fingerprint.")
        log.log("  See README.md -> Oracle OCI for step-by-step instructions.")
        sys.exit(1)

    # Get compartment ID: check config file custom field, then env var
    compartment_id = oci_config.get("compartment") or os.environ.get("OCI_COMPARTMENT_ID")

    if not compartment_id:
        log.error("Compartment OCID not found.")
        log.log("  OCI requires a compartment OCID to create resources. Provide it by either:")
        log.log("    1. Adding 'compartment=ocid1.compartment.oc1..xxxxx' to your ~/.oci/config [DEFAULT] section")
        log.log("    2. Setting the environment variable: export OCI_COMPARTMENT_ID=ocid1.compartment.oc1..xxxxx")
        log.log("  To find your compartment OCID:")
        log.log("    OCI Console -> Identity & Security -> Compartments -> copy the OCID")
        sys.exit(1)

    region = oci_config.get("region", "us-ashburn-1")

    config["platforms"]["oci"] = {
        "compartment_id": compartment_id,
        "region": region,
        "instance_type": "VM.GPU.A10.1",
        "credentials_config": config_path,
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
    click.echo(f"Active platform:  {config.get('active_platform', 'not set')}")
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

    # Check for credential files (no CLI tools needed)
    aws_csv = "not found"
    aws_dir = os.path.expanduser("~/.aws/credentials")
    if os.path.isdir(aws_dir) and any(f.endswith(".csv") for f in os.listdir(aws_dir)):
        aws_csv = "found"
    click.echo(f"AWS credentials:    {aws_csv} ({aws_dir}/)")

    gcp_json = "not found"
    gcloud_dir = os.path.expanduser("~/.config/gcloud")
    if os.path.isdir(gcloud_dir) and any(f.endswith(".json") for f in os.listdir(gcloud_dir)):
        gcp_json = "found"
    click.echo(f"GCP credentials:    {gcp_json} ({gcloud_dir}/)")

    azure_json = os.path.expanduser("~/.azure/service-principal.json")
    azure_status = "found" if os.path.exists(azure_json) else "not found"
    click.echo(f"Azure credentials:  {azure_status} ({azure_json})")

    oci_config = os.path.expanduser("~/.oci/config")
    oci_status = "found" if os.path.exists(oci_config) else "not found"
    click.echo(f"OCI credentials:    {oci_status} ({oci_config})")


# ---------------------------------------------------------------------------
# Stub commands (future iterations)
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("config_file", default="research.yaml", required=False)
@click.option("--dry-run", is_flag=True, help="See what would happen — instance type, cost estimate, GPU tuning — without provisioning.")
@click.option("--preflight", is_flag=True, help="Check credentials, quotas, and images before spending money.")
@click.option("--platform", "-p", default=None, type=click.Choice(["mac", "gcp", "aws", "azure", "oci"]),
              help="Run on a different platform without changing the active platform set by init.")
@click.option("--verbose", is_flag=True, help="Show detailed logging for debugging.")
def run(config_file: str, dry_run: bool, preflight: bool, platform: str | None, verbose: bool):
    """Run autoresearch end to end."""
    if dry_run:
        _dry_run(config_file, platform_override=platform)
        return
    if preflight:
        _preflight(config_file, platform_override=platform)
        return
    from autoresearch_ac.orchestrator import run_experiment
    run_experiment(research_path=config_file, platform_override=platform, verbose=verbose)


def _resolve_platform(config: dict, platform_override: str | None) -> str:
    """Resolve active platform: CLI flag > config.yaml > error."""
    if platform_override:
        return platform_override
    active = config.get("active_platform")
    if active:
        return active
    click.echo("Error: No active platform. Run 'autoresearch-anycloud init <platform>' first.", err=True)
    sys.exit(1)


def _dry_run(config_file: str, platform_override: str | None = None):
    """Show what would happen without provisioning."""
    from autoresearch_ac.orchestrator import _get_gpu_tuning, H100_INSTANCE_TYPES

    config = load_config()
    research = load_research(Path(config_file))
    platform = _resolve_platform(config, platform_override)
    max_experiments = research.get("research", {}).get("max_experiments", 2)
    budget = research.get("budget", {}).get("max_cost_usd", 5.0)
    platform_config = config.get("platforms", {}).get(platform, {})
    instance_type = platform_config.get("instance_type", "N/A")

    log_dir = config.get("log_dir", "./logs")
    with Logger(log_dir) as log:
        log.log("DRY RUN — no resources will be provisioned")
        log.log()
        log.log(f"  Platform:        {platform}")
        log.log(f"  Instance type:   {instance_type}")
        time_budget = research.get("research", {}).get("time_budget")
        log.log(f"  Experiments:     {max_experiments}")
        if time_budget:
            log.log(f"  Time budget:     {time_budget}s per experiment")
        else:
            log.log(f"  Time budget:     upstream default")
        log.log(f"  Budget:          ${budget:.2f}")

        # GPU tuning
        tuning = _get_gpu_tuning(platform, config)
        if instance_type in H100_INSTANCE_TYPES:
            log.log(f"  GPU tuning:      skipped (H100 — matches upstream defaults)")
        elif tuning:
            log.log(f"  GPU tuning:      {tuning['gpu_name']}")
            for old, new in tuning["patches"]:
                log.log(f"                   {new}")
        else:
            log.log(f"  GPU tuning:      upstream default")

        # Cost estimate
        hourly_rate = GPU_PRICING.get(instance_type, 0.0)
        estimated_hours = (max_experiments * 5 + 5) / 60
        gpu_cost = round(hourly_rate * estimated_hours, 2)
        api_cost = round(max_experiments * 0.042, 2)
        total = round(gpu_cost + api_cost, 2)

        log.log()
        log.log(f"  Hourly rate:     ${hourly_rate:.2f}/hr")
        log.log(f"  Est. GPU cost:   ${gpu_cost:.2f}")
        log.log(f"  Est. API cost:   ${api_cost:.2f}")
        log.log(f"  Est. total:      ${total:.2f}")

        if total > budget:
            log.log(f"\n  WARNING: estimated cost (${total:.2f}) exceeds budget (${budget:.2f})")

        log.log(f"\nRun without --dry-run to start.")


def _preflight(config_file: str, platform_override: str | None = None):
    """Validate credentials, quotas, and images for the target platform."""
    config = load_config()
    research = load_research(Path(config_file))
    platform = _resolve_platform(config, platform_override)

    log_dir = config.get("log_dir", "./logs")
    with Logger(log_dir) as log:
        log.log(f"PREFLIGHT — validating infrastructure for {platform}")
        log.log()

        if platform == "mac":
            log.log("  [PASS] Mac — no cloud infrastructure to validate")
            log.log("\nAll checks passed. Ready to run.")
            return

        # Import the provider's preflight_check
        provider_mod = None
        if platform == "aws":
            from autoresearch_ac.providers import aws as provider_mod
        elif platform == "gcp":
            from autoresearch_ac.providers import gcp as provider_mod
        elif platform == "azure":
            from autoresearch_ac.providers import azure as provider_mod
        elif platform == "oci":
            from autoresearch_ac.providers import oci as provider_mod
        else:
            log.log(f"  [FAIL] Unknown platform: {platform}")
            return

        results = provider_mod.preflight_check(config, log)

        passed = 0
        failed = 0
        warned = 0
        for r in results:
            status = r["status"].upper()
            tag = {"PASS": "PASS", "FAIL": "FAIL", "WARN": "WARN"}[status]
            log.log(f"  [{tag}] {r['check']}: {r['detail']}")
            if status == "PASS":
                passed += 1
            elif status == "FAIL":
                failed += 1
            else:
                warned += 1

        log.log()
        if failed:
            log.log(f"{failed} check(s) failed. Fix the issues above before running.")
        else:
            msg = "All checks passed. Ready to run."
            if warned:
                msg = f"All checks passed ({warned} warning(s)). Ready to run."
            log.log(msg)


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
