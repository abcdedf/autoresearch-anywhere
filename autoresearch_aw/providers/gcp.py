"""GCP provider — provision and teardown GPU instances via google-cloud-compute.

No gcloud CLI needed. Credentials are read from the service account JSON key at runtime.
"""

import os
import time

from google.cloud import compute_v1
from google.api_core.extended_operation import ExtendedOperation
from google.oauth2 import service_account


# Deep Learning VM image — comes with CUDA + PyTorch preinstalled
IMAGE_PROJECT = "deeplearning-platform-release"
IMAGE_FAMILY = "pytorch-2-7-cu128-ubuntu-2204-nvidia-570"
DEFAULT_INSTANCE_TYPE = "n1-standard-4"
DEFAULT_GPU_TYPE = "nvidia-tesla-t4"
DEFAULT_GPU_COUNT = 1
DEFAULT_REGION = "us-central1"
DEFAULT_ZONE = "us-central1-a"
DEFAULT_HOURLY_RATE = 0.35  # $/hr for n1-standard-4 + T4 on-demand
BOOT_DISK_SIZE_GB = 150
FIREWALL_RULE_NAME = "autoresearch-aw-allow-ssh"
INSTANCE_NAME = "autoresearch-aw"
NETWORK_TAG = "autoresearch-aw"
KEY_DIR = os.path.join(os.path.expanduser("~"), ".autoresearch-aw")


def _get_credentials(config: dict):
    """Load service account credentials from the JSON key file in config."""
    gcp_config = config.get("platforms", {}).get("gcp", {})
    json_path = gcp_config.get("credentials_json")

    if json_path and os.path.exists(json_path):
        return service_account.Credentials.from_service_account_file(json_path)

    # Fall back to application default credentials
    return None


def provision(config: dict, log=None) -> dict:
    """Launch a GPU instance on GCP. Returns instance info dict."""
    gcp_config = config.get("platforms", {}).get("gcp", {})
    project = gcp_config.get("project")
    zone = gcp_config.get("zone", DEFAULT_ZONE)
    instance_type = gcp_config.get("instance_type", DEFAULT_INSTANCE_TYPE)
    gpu_type = gcp_config.get("gpu_type", DEFAULT_GPU_TYPE)
    gpu_count = int(gcp_config.get("gpu_count", DEFAULT_GPU_COUNT))
    use_spot = gcp_config.get("use_spot", False)

    if not project:
        raise ValueError("GCP config requires 'project' (your GCP project ID). "
                         "Run 'autoresearch-aw init gcp' to configure.")

    credentials = _get_credentials(config)

    if log:
        log.log(f"[gcp] Project: {project}, Zone: {zone}")

    # Step 0: Clean up orphaned instances from previous failed runs
    _cleanup_orphaned_instances(project, zone, credentials, log)

    # Step 1: Ensure SSH key pair exists
    key_path, ssh_metadata = _ensure_ssh_key(log)

    # Step 2: Ensure firewall rule for SSH
    _ensure_firewall_rule(project, credentials, log)

    # Step 3: Resolve the Deep Learning VM image
    if log:
        log.log("[gcp] Resolving Deep Learning VM image...")
    image_url = _resolve_image(credentials, log)

    # Step 4: Create instance
    pricing_mode = "spot" if use_spot else "on-demand"
    if log:
        log.log(f"[gcp] Launching {instance_type} + {gpu_type} x{gpu_count} {pricing_mode} instance...")

    _create_instance(
        project=project,
        zone=zone,
        instance_type=instance_type,
        gpu_type=gpu_type,
        gpu_count=gpu_count,
        image_url=image_url,
        use_spot=use_spot,
        ssh_metadata=ssh_metadata,
        credentials=credentials,
        log=log,
    )

    # Step 5: Wait for the instance to reach RUNNING state
    if log:
        log.log(f"[gcp] Instance '{INSTANCE_NAME}' created. Waiting for RUNNING state...")
    _wait_for_running(project, zone, credentials, log)

    # Step 6: Get external IP
    public_ip = _get_external_ip(project, zone, credentials, log)
    if log:
        log.log(f"[gcp] Instance running at {public_ip}")

    # Step 7: Wait for SSH to be ready
    if log:
        log.log("[gcp] Waiting for SSH to become available...")
    _wait_for_ssh(public_ip, log)

    return {
        "instance_name": INSTANCE_NAME,
        "zone": zone,
        "project": project,
        "public_ip": public_ip,
        "key_path": key_path,
        "credentials_json": gcp_config.get("credentials_json"),
    }


def teardown(instance_info: dict, log=None):
    """Delete the instance and clean up firewall rule."""
    project = instance_info["project"]
    zone = instance_info["zone"]
    instance_name = instance_info["instance_name"]

    # Rebuild credentials from instance_info
    config_for_creds = {"platforms": {"gcp": {
        "credentials_json": instance_info.get("credentials_json"),
    }}}
    credentials = _get_credentials(config_for_creds)

    # Delete instance
    if log:
        log.log(f"[gcp] Deleting instance '{instance_name}'...")

    try:
        instances_client = compute_v1.InstancesClient(credentials=credentials)
        operation = instances_client.delete(
            project=project,
            zone=zone,
            instance=instance_name,
        )
        _wait_for_operation(operation, log, label="instance deletion")
        if log:
            log.log(f"[gcp] Instance '{instance_name}' deleted.")
    except Exception as e:
        if log:
            log.log(f"[gcp] Error deleting instance: {e}")

    # Delete firewall rule
    if log:
        log.log(f"[gcp] Deleting firewall rule '{FIREWALL_RULE_NAME}'...")

    try:
        firewalls_client = compute_v1.FirewallsClient(credentials=credentials)
        operation = firewalls_client.delete(
            project=project,
            firewall=FIREWALL_RULE_NAME,
        )
        _wait_for_operation(operation, log, label="firewall deletion")
        if log:
            log.log(f"[gcp] Firewall rule '{FIREWALL_RULE_NAME}' deleted.")
    except Exception as e:
        if log:
            log.log(f"[gcp] Could not delete firewall rule: {e}")


def estimate_cost(config: dict) -> dict:
    """Estimate cost for a run. Returns dict with hourly rate and estimated total."""
    gcp_config = config.get("platforms", {}).get("gcp", {})
    hourly_rate = float(gcp_config.get("hourly_rate", DEFAULT_HOURLY_RATE))
    max_experiments = config.get("research", {}).get("max_experiments", 1)

    # ~5 min per experiment + ~5 min for setup/prepare
    estimated_hours = (max_experiments * 5 + 5) / 60

    return {
        "hourly_rate_usd": hourly_rate,
        "estimated_hours": estimated_hours,
        "estimated_cost_usd": round(hourly_rate * estimated_hours, 2),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_ssh_key(log=None) -> tuple[str, str]:
    """Generate an SSH key pair if it doesn't exist.

    Returns (key_path, ssh_keys_metadata_value) — the metadata value is added
    to the instance (not project) so only Compute Admin is needed.
    """
    os.makedirs(KEY_DIR, exist_ok=True)
    key_path = os.path.join(KEY_DIR, "autoresearch-aw-gcp")

    if os.path.exists(key_path):
        if log:
            log.log(f"[gcp] Using existing SSH key '{key_path}'")
    else:
        # Generate ed25519 key pair
        if log:
            log.log("[gcp] Creating SSH key pair...")
        import subprocess
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-f", key_path, "-N", "", "-C", "autoresearch-aw"],
            check=True, capture_output=True,
        )
        os.chmod(key_path, 0o400)
        if log:
            log.log(f"[gcp] Key saved to {key_path}")

    # Read public key — will be injected into instance metadata at creation time
    with open(key_path + ".pub") as f:
        pub_key = f.read().strip()

    # Format: username:key-type key-data comment
    ssh_metadata = f"ubuntu:{pub_key}"

    return key_path, ssh_metadata


def _cleanup_orphaned_instances(project: str, zone: str, credentials=None, log=None):
    """Terminate any running autoresearch-aw instances from previous failed runs."""
    try:
        instances_client = compute_v1.InstancesClient(credentials=credentials)
        request = compute_v1.ListInstancesRequest(
            project=project,
            zone=zone,
            filter=f'name="{INSTANCE_NAME}" AND status="RUNNING"',
        )
        for instance in instances_client.list(request=request):
            if log:
                log.log(f"[gcp] Deleting orphaned instance '{instance.name}'...")
            operation = instances_client.delete(
                project=project,
                zone=zone,
                instance=instance.name,
            )
            _wait_for_operation(operation, log, label="orphaned instance deletion")
    except Exception:
        pass


def _resolve_image(credentials=None, log=None) -> str:
    """Resolve the latest image URL from the Deep Learning VM family."""
    images_client = compute_v1.ImagesClient(credentials=credentials)
    image = images_client.get_from_family(
        project=IMAGE_PROJECT,
        family=IMAGE_FAMILY,
    )
    if log:
        log.log(f"[gcp] Image: {image.name}")
    return image.self_link


def _create_instance(project, zone, instance_type, gpu_type, gpu_count,
                     image_url, use_spot, ssh_metadata, credentials=None, log=None):
    """Create a VM with GPU via the Compute Engine API."""
    instances_client = compute_v1.InstancesClient(credentials=credentials)

    # Accelerator config — full resource path for the GPU type
    accelerator_type = f"zones/{zone}/acceleratorTypes/{gpu_type}"

    # Scheduling: on-demand or spot
    if use_spot:
        scheduling = compute_v1.Scheduling(
            provisioning_model="SPOT",
            instance_termination_action="DELETE",
            on_host_maintenance="TERMINATE",
        )
    else:
        scheduling = compute_v1.Scheduling(
            on_host_maintenance="TERMINATE",  # required for GPU instances
        )

    # Build the instance resource
    instance_resource = compute_v1.Instance(
        name=INSTANCE_NAME,
        machine_type=f"zones/{zone}/machineTypes/{instance_type}",
        disks=[
            compute_v1.AttachedDisk(
                boot=True,
                auto_delete=True,
                initialize_params=compute_v1.AttachedDiskInitializeParams(
                    source_image=image_url,
                    disk_size_gb=BOOT_DISK_SIZE_GB,
                    disk_type=f"zones/{zone}/diskTypes/pd-ssd",
                ),
            )
        ],
        network_interfaces=[
            compute_v1.NetworkInterface(
                name="global/networks/default",
                access_configs=[
                    compute_v1.AccessConfig(
                        name="External NAT",
                        type_="ONE_TO_ONE_NAT",
                    )
                ],
            )
        ],
        guest_accelerators=[
            compute_v1.AcceleratorConfig(
                accelerator_type=accelerator_type,
                accelerator_count=gpu_count,
            )
        ],
        scheduling=scheduling,
        tags=compute_v1.Tags(items=[NETWORK_TAG]),
        metadata=compute_v1.Metadata(
            items=[
                compute_v1.Items(
                    key="install-nvidia-driver",
                    value="True",
                ),
                compute_v1.Items(
                    key="ssh-keys",
                    value=ssh_metadata,
                ),
            ]
        ),
    )

    operation = instances_client.insert(
        project=project,
        zone=zone,
        instance_resource=instance_resource,
    )
    _wait_for_operation(operation, log, label="instance creation")

    return instance_resource


def _ensure_firewall_rule(project: str, credentials=None, log=None):
    """Create or reuse a firewall rule allowing SSH (port 22) for tagged instances."""
    firewalls_client = compute_v1.FirewallsClient(credentials=credentials)

    # Check if rule already exists
    try:
        firewalls_client.get(project=project, firewall=FIREWALL_RULE_NAME)
        if log:
            log.log(f"[gcp] Reusing firewall rule '{FIREWALL_RULE_NAME}'")
        return
    except Exception:
        pass  # Rule doesn't exist, create it

    if log:
        log.log(f"[gcp] Creating firewall rule '{FIREWALL_RULE_NAME}'...")

    firewall_resource = compute_v1.Firewall(
        name=FIREWALL_RULE_NAME,
        direction="INGRESS",
        allowed=[
            compute_v1.Allowed(
                I_p_protocol="tcp",
                ports=["22"],
            )
        ],
        source_ranges=["0.0.0.0/0"],
        target_tags=[NETWORK_TAG],
        description="SSH access for autoresearch-aw",
    )

    operation = firewalls_client.insert(
        project=project,
        firewall_resource=firewall_resource,
    )
    _wait_for_operation(operation, log, label="firewall creation")

    if log:
        log.log(f"[gcp] Firewall rule '{FIREWALL_RULE_NAME}' created.")


def _wait_for_running(project: str, zone: str, credentials=None, log=None,
                      retries: int = 30, delay: int = 10):
    """Poll until instance reaches RUNNING status."""
    instances_client = compute_v1.InstancesClient(credentials=credentials)

    for attempt in range(1, retries + 1):
        instance = instances_client.get(
            project=project,
            zone=zone,
            instance=INSTANCE_NAME,
        )
        status = instance.status
        if status == "RUNNING":
            if log:
                log.log(f"[gcp] Instance is RUNNING (checked after {attempt * delay}s)")
            return
        if status in ("TERMINATED", "STOPPED", "SUSPENDED"):
            raise RuntimeError(f"Instance entered unexpected state: {status}")
        if log and attempt % 3 == 0:
            log.log(f"[gcp] Still waiting... status={status} (attempt {attempt}/{retries})")
        time.sleep(delay)

    raise TimeoutError(f"Instance not RUNNING after {retries * delay}s")


def _get_external_ip(project: str, zone: str, credentials=None, log=None) -> str:
    """Retrieve the external IP address of the running instance."""
    instances_client = compute_v1.InstancesClient(credentials=credentials)
    instance = instances_client.get(
        project=project,
        zone=zone,
        instance=INSTANCE_NAME,
    )

    for iface in instance.network_interfaces:
        for access in iface.access_configs:
            if access.nat_i_p:
                return access.nat_i_p

    raise RuntimeError("Instance has no external IP address. "
                       "Check network interface and access config.")


def _wait_for_ssh(host: str, log=None, retries: int = 15, delay: int = 10):
    """Poll until SSH port 22 accepts connections."""
    import socket

    for attempt in range(1, retries + 1):
        try:
            sock = socket.create_connection((host, 22), timeout=5)
            sock.close()
            if log:
                log.log(f"[gcp] SSH ready after {attempt * delay}s")
            return
        except (socket.timeout, ConnectionRefusedError, OSError):
            if attempt < retries:
                time.sleep(delay)

    raise TimeoutError(f"SSH not available on {host}:22 after {retries * delay}s")


def _wait_for_operation(operation: ExtendedOperation, log=None, label: str = "operation"):
    """Wait for a GCP long-running operation to complete."""
    try:
        result = operation.result()
    except Exception as e:
        raise RuntimeError(f"GCP {label} failed: {e}") from e

    if operation.error_code:
        raise RuntimeError(
            f"GCP {label} failed with error code {operation.error_code}: "
            f"{operation.error_message}"
        )

    if log:
        log.log(f"[gcp] {label.capitalize()} completed.")

    return result
