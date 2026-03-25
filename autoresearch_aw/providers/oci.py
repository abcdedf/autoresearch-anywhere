"""OCI provider — provision and teardown GPU instances via the oci Python SDK."""

import os
import time

import oci
from oci.exceptions import ServiceError


DEFAULT_SHAPE = "VM.GPU.A10.1"          # NVIDIA A10 24GB VRAM
DEFAULT_REGION = "us-ashburn-1"
DEFAULT_HOURLY_RATE = 0.50              # estimated $/hr for GPU shapes
DEFAULT_BOOT_VOLUME_GB = 150
VCN_CIDR = "10.0.0.0/16"
SUBNET_CIDR = "10.0.0.0/24"
DISPLAY_PREFIX = "autoresearch-anywhere"
KEY_DIR = os.path.join(os.path.expanduser("~"), ".autoresearch-anywhere")


# ---------------------------------------------------------------------------
# Public interface (matches aws.py)
# ---------------------------------------------------------------------------

def provision(config: dict, log=None) -> dict:
    """Launch a GPU instance on OCI. Returns instance info dict."""
    oci_config = config.get("platforms", {}).get("oci", {})
    region = oci_config.get("region", DEFAULT_REGION)
    shape = oci_config.get("shape", DEFAULT_SHAPE)
    compartment_id = oci_config.get("compartment_id")

    if not compartment_id:
        raise ValueError("OCI config requires 'compartment_id'. "
                         "Run 'autoresearch-anywhere init oci' to configure.")

    # Generate SSH key pair (like GCP provider)
    key_path, ssh_public_key = _ensure_ssh_key(log)

    # Authenticate using the default config file (~/.oci/config)
    sdk_config = oci.config.from_file()
    sdk_config["region"] = region

    compute = oci.core.ComputeClient(sdk_config)
    network = oci.core.VirtualNetworkClient(sdk_config)

    # Track created resources for cleanup on failure
    created = {}

    try:
        # Step 1: Create VCN
        if log:
            log.log("[oci] Creating VCN...")
        created["vcn_id"] = _create_vcn(network, compartment_id, log)

        # Step 2: Create internet gateway and route table
        if log:
            log.log("[oci] Creating internet gateway and route table...")
        created["internet_gateway_id"] = _create_internet_gateway(network, compartment_id, created["vcn_id"], log)
        created["route_table_id"] = _create_route_table(network, compartment_id, created["vcn_id"], created["internet_gateway_id"], log)

        # Step 3: Create security list (SSH)
        if log:
            log.log("[oci] Creating security list (SSH port 22)...")
        created["security_list_id"] = _create_security_list(network, compartment_id, created["vcn_id"], log)

        # Step 4: Create subnet
        if log:
            log.log("[oci] Creating subnet...")
        created["subnet_id"] = _create_subnet(network, compartment_id, created["vcn_id"], created["route_table_id"], created["security_list_id"], log)

        # Step 5: Find a GPU image
        if log:
            log.log(f"[oci] Finding GPU image for shape {shape}...")
        image_id = _find_image(compute, compartment_id, shape, log)

        # Step 6: Launch instance
        if log:
            log.log(f"[oci] Launching {shape} instance...")

        launch_details = oci.core.models.LaunchInstanceDetails(
            compartment_id=compartment_id,
            availability_domain=_get_availability_domain(sdk_config, compartment_id),
            display_name=f"{DISPLAY_PREFIX}-gpu",
            shape=shape,
            source_details=oci.core.models.InstanceSourceViaImageDetails(
                source_type="image",
                image_id=image_id,
                boot_volume_size_in_gbs=DEFAULT_BOOT_VOLUME_GB,
            ),
            create_vnic_details=oci.core.models.CreateVnicDetails(
                subnet_id=created["subnet_id"],
                assign_public_ip=True,
            ),
            metadata={
                "ssh_authorized_keys": ssh_public_key,
            },
        )

        launch_response = compute.launch_instance(launch_details)
        instance_id = launch_response.data.id
        created["instance_id"] = instance_id

        if log:
            log.log(f"[oci] Instance {instance_id} launched. Waiting for RUNNING state...")

        # Step 7: Wait for instance to reach RUNNING
        instance = _wait_for_running(compute, instance_id, log)

        # Step 8: Get public IP
        public_ip = _get_public_ip(compute, network, compartment_id, instance_id, log)
        if log:
            log.log(f"[oci] Instance running at {public_ip}")

        # Step 9: Wait for SSH
        if log:
            log.log("[oci] Waiting for SSH to become available...")
        _wait_for_ssh(public_ip, key_path, log)

    except Exception:
        # Clean up any resources created before the failure
        if log:
            log.log("[oci] Provision failed. Cleaning up created resources...")
        _cleanup_created_resources(compute, network, created, log)
        raise

    return {
        "instance_id": instance_id,
        "compartment_id": compartment_id,
        "public_ip": public_ip,
        "region": region,
        "key_path": key_path,
        "vcn_id": created["vcn_id"],
        "subnet_id": created["subnet_id"],
        "security_list_id": created["security_list_id"],
        "internet_gateway_id": created["internet_gateway_id"],
        "route_table_id": created["route_table_id"],
    }


def teardown(instance_info: dict, log=None):
    """Terminate the instance and clean up all networking resources."""
    sdk_config = oci.config.from_file()
    sdk_config["region"] = instance_info.get("region", DEFAULT_REGION)

    compute = oci.core.ComputeClient(sdk_config)
    network = oci.core.VirtualNetworkClient(sdk_config)

    instance_id = instance_info["instance_id"]
    compartment_id = instance_info["compartment_id"]

    # Terminate instance
    if log:
        log.log(f"[oci] Terminating instance {instance_id}...")
    try:
        compute.terminate_instance(instance_id, preserve_boot_volume=False)
    except ServiceError as e:
        if e.status == 404:
            if log:
                log.log(f"[oci] Instance {instance_id} already terminated.")
        else:
            raise

    # Wait for termination
    _wait_for_terminated(compute, instance_id, log)
    if log:
        log.log(f"[oci] Instance {instance_id} terminated.")

    # Delete subnet
    subnet_id = instance_info.get("subnet_id")
    if subnet_id:
        _safe_delete(network.delete_subnet, subnet_id, "subnet", log)

    # Delete route table (non-default)
    rt_id = instance_info.get("route_table_id")
    if rt_id:
        _safe_delete(network.delete_route_table, rt_id, "route table", log)

    # Delete internet gateway
    ig_id = instance_info.get("internet_gateway_id")
    if ig_id:
        _safe_delete(network.delete_internet_gateway, ig_id, "internet gateway", log)

    # Delete security list (non-default)
    sl_id = instance_info.get("security_list_id")
    if sl_id:
        _safe_delete(network.delete_security_list, sl_id, "security list", log)

    # Delete VCN
    vcn_id = instance_info.get("vcn_id")
    if vcn_id:
        _safe_delete(network.delete_vcn, vcn_id, "VCN", log)


def estimate_cost(config: dict) -> dict:
    """Estimate cost for a run. Returns dict with hourly rate and estimated total."""
    oci_config = config.get("platforms", {}).get("oci", {})
    hourly_rate = float(oci_config.get("hourly_rate", DEFAULT_HOURLY_RATE))
    max_experiments = config.get("research", {}).get("max_experiments", 2)

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

def _cleanup_created_resources(compute, network, created: dict, log=None):
    """Clean up any OCI resources tracked in the created dict. Called on provision failure."""
    # Terminate instance first (if it was created)
    instance_id = created.get("instance_id")
    if instance_id:
        try:
            compute.terminate_instance(instance_id, preserve_boot_volume=False)
            if log:
                log.log(f"[oci] Terminated instance {instance_id}")
            _wait_for_terminated(compute, instance_id, log)
        except Exception:
            pass

    # Delete in reverse creation order: subnet → route table → security list → gateway → VCN
    for key, name, delete_fn in [
        ("subnet_id", "subnet", network.delete_subnet),
        ("route_table_id", "route table", network.delete_route_table),
        ("security_list_id", "security list", network.delete_security_list),
        ("internet_gateway_id", "internet gateway", network.delete_internet_gateway),
        ("vcn_id", "VCN", network.delete_vcn),
    ]:
        resource_id = created.get(key)
        if resource_id:
            _safe_delete(delete_fn, resource_id, name, log)


def _ensure_ssh_key(log=None) -> tuple[str, str]:
    """Generate an SSH key pair if it doesn't exist.

    Returns (private_key_path, public_key_content).
    """
    os.makedirs(KEY_DIR, exist_ok=True)
    key_path = os.path.join(KEY_DIR, "autoresearch-anywhere-oci")

    if os.path.exists(key_path):
        if log:
            log.log(f"[oci] Using existing SSH key '{key_path}'")
    else:
        if log:
            log.log("[oci] Creating SSH key pair...")
        import subprocess
        subprocess.run(
            ["ssh-keygen", "-t", "ed25519", "-f", key_path, "-N", "", "-C", "autoresearch-anywhere"],
            check=True, capture_output=True,
        )
        os.chmod(key_path, 0o400)
        if log:
            log.log(f"[oci] Key saved to {key_path}")

    with open(key_path + ".pub") as f:
        pub_key = f.read().strip()

    return key_path, pub_key


def _get_availability_domain(sdk_config: dict, compartment_id: str) -> str:
    """Return the first availability domain in the tenancy."""
    identity = oci.identity.IdentityClient(sdk_config)
    ads = identity.list_availability_domains(compartment_id).data
    if not ads:
        raise RuntimeError("No availability domains found in compartment.")
    return ads[0].name


def _create_vcn(network, compartment_id: str, log=None) -> str:
    """Create a VCN and return its OCID."""
    vcn_details = oci.core.models.CreateVcnDetails(
        compartment_id=compartment_id,
        cidr_block=VCN_CIDR,
        display_name=f"{DISPLAY_PREFIX}-vcn",
    )
    vcn = network.create_vcn(vcn_details).data
    if log:
        log.log(f"[oci] VCN created: {vcn.id}")
    return vcn.id


def _create_internet_gateway(network, compartment_id: str, vcn_id: str, log=None) -> str:
    """Create an internet gateway attached to the VCN."""
    ig_details = oci.core.models.CreateInternetGatewayDetails(
        compartment_id=compartment_id,
        vcn_id=vcn_id,
        display_name=f"{DISPLAY_PREFIX}-ig",
        is_enabled=True,
    )
    ig = network.create_internet_gateway(ig_details).data
    if log:
        log.log(f"[oci] Internet gateway created: {ig.id}")
    return ig.id


def _create_route_table(network, compartment_id: str, vcn_id: str, ig_id: str, log=None) -> str:
    """Create a route table with a default route through the internet gateway."""
    rt_details = oci.core.models.CreateRouteTableDetails(
        compartment_id=compartment_id,
        vcn_id=vcn_id,
        display_name=f"{DISPLAY_PREFIX}-rt",
        route_rules=[
            oci.core.models.RouteRule(
                destination="0.0.0.0/0",
                destination_type="CIDR_BLOCK",
                network_entity_id=ig_id,
            ),
        ],
    )
    rt = network.create_route_table(rt_details).data
    if log:
        log.log(f"[oci] Route table created: {rt.id}")
    return rt.id


def _create_security_list(network, compartment_id: str, vcn_id: str, log=None) -> str:
    """Create a security list allowing SSH ingress and all egress."""
    sl_details = oci.core.models.CreateSecurityListDetails(
        compartment_id=compartment_id,
        vcn_id=vcn_id,
        display_name=f"{DISPLAY_PREFIX}-sl",
        ingress_security_rules=[
            oci.core.models.IngressSecurityRule(
                protocol="6",  # TCP
                source="0.0.0.0/0",
                source_type="CIDR_BLOCK",
                tcp_options=oci.core.models.TcpOptions(
                    destination_port_range=oci.core.models.PortRange(min=22, max=22),
                ),
            ),
        ],
        egress_security_rules=[
            oci.core.models.EgressSecurityRule(
                protocol="all",
                destination="0.0.0.0/0",
                destination_type="CIDR_BLOCK",
            ),
        ],
    )
    sl = network.create_security_list(sl_details).data
    if log:
        log.log(f"[oci] Security list created: {sl.id}")
    return sl.id


def _create_subnet(network, compartment_id: str, vcn_id: str, rt_id: str, sl_id: str, log=None) -> str:
    """Create a public subnet in the VCN."""
    subnet_details = oci.core.models.CreateSubnetDetails(
        compartment_id=compartment_id,
        vcn_id=vcn_id,
        cidr_block=SUBNET_CIDR,
        display_name=f"{DISPLAY_PREFIX}-subnet",
        route_table_id=rt_id,
        security_list_ids=[sl_id],
        prohibit_public_ip_on_vnic=False,  # allow public IPs
    )
    subnet = network.create_subnet(subnet_details).data
    if log:
        log.log(f"[oci] Subnet created: {subnet.id}")
    return subnet.id


def _find_image(compute, compartment_id: str, shape: str, log=None) -> str:
    """Find a suitable GPU-compatible image (Ubuntu preferred, then Oracle Linux)."""
    # Try Ubuntu GPU images first, then fall back to Oracle Linux
    for os_name in ("Canonical Ubuntu", "Oracle Linux"):
        images = compute.list_images(
            compartment_id=compartment_id,
            operating_system=os_name,
            shape=shape,
            sort_by="TIMECREATED",
            sort_order="DESC",
            lifecycle_state="AVAILABLE",
        ).data

        if images:
            image = images[0]
            if log:
                log.log(f"[oci] Image: {image.display_name} ({image.id})")
            return image.id

    raise RuntimeError(
        f"No GPU-compatible image found for shape {shape}. "
        "Check compartment permissions and region availability."
    )


def _wait_for_running(compute, instance_id: str, log=None, timeout: int = 600, poll: int = 10):
    """Poll until instance reaches RUNNING state."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        instance = compute.get_instance(instance_id).data
        state = instance.lifecycle_state
        if state == "RUNNING":
            return instance
        if state in ("TERMINATED", "TERMINATING"):
            raise RuntimeError(f"Instance {instance_id} entered {state} state instead of RUNNING. "
                               "This can happen when preemptible capacity is unavailable.")
        time.sleep(poll)

    raise TimeoutError(f"Instance {instance_id} did not reach RUNNING state within {timeout}s")


def _wait_for_terminated(compute, instance_id: str, log=None, timeout: int = 300, poll: int = 10):
    """Poll until instance is terminated."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            instance = compute.get_instance(instance_id).data
            if instance.lifecycle_state == "TERMINATED":
                return
        except ServiceError as e:
            if e.status == 404:
                return  # already gone
            raise
        time.sleep(poll)

    if log:
        log.log(f"[oci] Warning: timed out waiting for instance {instance_id} to terminate.")


def _get_public_ip(compute, network, compartment_id: str, instance_id: str, log=None) -> str:
    """Retrieve the public IP of the instance's primary VNIC."""
    vnic_attachments = compute.list_vnic_attachments(
        compartment_id=compartment_id,
        instance_id=instance_id,
    ).data

    if not vnic_attachments:
        raise RuntimeError(f"No VNIC attachments found for instance {instance_id}")

    vnic_id = vnic_attachments[0].vnic_id
    vnic = network.get_vnic(vnic_id).data

    if not vnic.public_ip:
        raise RuntimeError(f"Instance {instance_id} has no public IP. "
                           "Check subnet configuration.")

    return vnic.public_ip


def _wait_for_ssh(host: str, key_path: str, log=None, retries: int = 15, delay: int = 10):
    """Poll until SSH port 22 accepts connections."""
    import socket

    for attempt in range(1, retries + 1):
        try:
            sock = socket.create_connection((host, 22), timeout=5)
            sock.close()
            if log:
                log.log(f"[oci] SSH ready after {attempt * delay}s")
            return
        except (socket.timeout, ConnectionRefusedError, OSError):
            if attempt < retries:
                time.sleep(delay)

    raise TimeoutError(f"SSH not available on {host}:22 after {retries * delay}s")


def _safe_delete(delete_fn, resource_id: str, resource_name: str, log=None):
    """Call a delete function, handling 404 (already deleted) gracefully."""
    try:
        delete_fn(resource_id)
        if log:
            log.log(f"[oci] Deleted {resource_name} {resource_id}")
    except ServiceError as e:
        if e.status == 404:
            if log:
                log.log(f"[oci] {resource_name} {resource_id} already deleted.")
        else:
            if log:
                log.log(f"[oci] Could not delete {resource_name} {resource_id}: {e.message}")
