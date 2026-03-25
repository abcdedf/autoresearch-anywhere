"""Azure provider — provision and teardown GPU instances via Azure SDK.

No Azure CLI needed. Credentials are read from a service principal JSON file at runtime.
"""

import json
import os
import time

from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource import ResourceManagementClient


DEFAULT_VM_SIZE = "Standard_NV36ads_A10_v5"  # A10 GPU 24GB, 36 vCPU, 440GB RAM (Ampere)
DEFAULT_REGION = "eastus"
DEFAULT_HOURLY_RATE = 3.20  # $/hr on-demand for Standard_NV36ads_A10_v5
RESOURCE_GROUP_NAME = "autoresearch-anycloud-rg"
KEY_DIR = os.path.join(os.path.expanduser("~"), ".autoresearch-anycloud")

# NVIDIA GPU-optimized VM image (Ubuntu 22.04 with CUDA + drivers preinstalled)
IMAGE_REFERENCE = {
    "publisher": "microsoft-dsvm",
    "offer": "ubuntu-hpc",
    "sku": "2204",
    "version": "latest",
}


def _get_credential(config: dict):
    """Load Azure credentials from service principal JSON."""
    azure_config = config.get("platforms", {}).get("azure", {})
    json_path = azure_config.get("credentials_json")

    if json_path and os.path.exists(json_path):
        with open(json_path) as f:
            creds = json.load(f)
        return ClientSecretCredential(
            tenant_id=creds["tenant_id"],
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
        ), creds.get("subscription_id") or azure_config.get("subscription")

    # Check env vars
    tenant = os.environ.get("AZURE_TENANT_ID")
    client = os.environ.get("AZURE_CLIENT_ID")
    secret = os.environ.get("AZURE_CLIENT_SECRET")
    sub = os.environ.get("AZURE_SUBSCRIPTION_ID") or azure_config.get("subscription")
    if tenant and client and secret:
        return ClientSecretCredential(
            tenant_id=tenant, client_id=client, client_secret=secret,
        ), sub

    raise ValueError("No Azure credentials found. Run 'autoresearch-anycloud init azure'.")


def provision(config: dict, log=None) -> dict:
    """Launch a GPU VM on Azure. Returns instance info dict."""
    azure_config = config.get("platforms", {}).get("azure", {})
    region = azure_config.get("region", DEFAULT_REGION)
    vm_size = azure_config.get("instance_type", DEFAULT_VM_SIZE)
    use_spot = azure_config.get("use_spot", False)
    spot_max_price = float(azure_config.get("spot_max_price", -1))

    credential, subscription_id = _get_credential(config)

    resource_client = ResourceManagementClient(credential, subscription_id)
    network_client = NetworkManagementClient(credential, subscription_id)
    compute_client = ComputeManagementClient(credential, subscription_id)

    vm_name = "autoresearch-anycloud-vm"
    nsg_name = "autoresearch-anycloud-nsg"
    vnet_name = "autoresearch-anycloud-vnet"
    subnet_name = "autoresearch-anycloud-subnet"
    ip_name = "autoresearch-anycloud-ip"
    nic_name = "autoresearch-anycloud-nic"

    if log:
        log.log(f"[azure] Region: {region}, VM size: {vm_size}")

    # Step 0: Clean up orphaned resources from previous failed runs
    _cleanup_orphaned_resources(resource_client, log)

    # Step 1: Ensure SSH key pair exists
    key_path = _ensure_ssh_key(log)
    with open(key_path + ".pub") as f:
        ssh_public_key = f.read().strip()

    # Step 2: Create resource group
    if log:
        log.log(f"[azure] Creating resource group {RESOURCE_GROUP_NAME}...")
    resource_client.resource_groups.create_or_update(
        RESOURCE_GROUP_NAME,
        {"location": region},
    )

    try:
        # Step 3: Create network security group (SSH only)
        if log:
            log.log("[azure] Creating network security group...")
        nsg_poller = network_client.network_security_groups.begin_create_or_update(
            RESOURCE_GROUP_NAME,
            nsg_name,
            {
                "location": region,
                "security_rules": [{
                    "name": "AllowSSH",
                    "protocol": "Tcp",
                    "direction": "Inbound",
                    "access": "Allow",
                    "priority": 100,
                    "source_address_prefix": "*",
                    "source_port_range": "*",
                    "destination_address_prefix": "*",
                    "destination_port_range": "22",
                }],
            },
        )
        nsg = nsg_poller.result()

        # Step 4: Create virtual network and subnet
        if log:
            log.log("[azure] Creating virtual network...")
        vnet_poller = network_client.virtual_networks.begin_create_or_update(
            RESOURCE_GROUP_NAME,
            vnet_name,
            {
                "location": region,
                "address_space": {"address_prefixes": ["10.0.0.0/16"]},
                "subnets": [{
                    "name": subnet_name,
                    "address_prefix": "10.0.0.0/24",
                    "network_security_group": {"id": nsg.id},
                }],
            },
        )
        vnet = vnet_poller.result()
        subnet_id = vnet.subnets[0].id

        # Step 5: Create public IP address
        if log:
            log.log("[azure] Creating public IP address...")
        ip_poller = network_client.public_ip_addresses.begin_create_or_update(
            RESOURCE_GROUP_NAME,
            ip_name,
            {
                "location": region,
                "sku": {"name": "Standard"},
                "public_ip_allocation_method": "Static",
            },
        )
        public_ip_resource = ip_poller.result()

        # Step 6: Create network interface
        if log:
            log.log("[azure] Creating network interface...")
        nic_poller = network_client.network_interfaces.begin_create_or_update(
            RESOURCE_GROUP_NAME,
            nic_name,
            {
                "location": region,
                "ip_configurations": [{
                    "name": "autoresearch-anycloud-ipconfig",
                    "subnet": {"id": subnet_id},
                    "public_ip_address": {"id": public_ip_resource.id},
                }],
                "network_security_group": {"id": nsg.id},
            },
        )
        nic = nic_poller.result()

        # Step 7: Create VM
        pricing_mode = "spot" if use_spot else "on-demand"
        if log:
            log.log(f"[azure] Launching {vm_size} {pricing_mode} VM...")

        vm_params = {
            "location": region,
            "hardware_profile": {"vm_size": vm_size},
            "storage_profile": {
                "image_reference": IMAGE_REFERENCE,
                "os_disk": {
                    "name": f"{vm_name}-osdisk",
                    "caching": "ReadWrite",
                    "create_option": "FromImage",
                    "managed_disk": {"storage_account_type": "Premium_LRS"},
                    "disk_size_gb": 150,
                },
            },
            "os_profile": {
                "computer_name": vm_name,
                "admin_username": "azureuser",
                "linux_configuration": {
                    "disable_password_authentication": True,
                    "ssh": {
                        "public_keys": [{
                            "path": "/home/azureuser/.ssh/authorized_keys",
                            "key_data": ssh_public_key,
                        }],
                    },
                },
            },
            "network_profile": {
                "network_interfaces": [{"id": nic.id}],
            },
            "tags": {"project": "autoresearch-anycloud"},
        }

        if use_spot:
            vm_params["priority"] = "Spot"
            vm_params["eviction_policy"] = "Deallocate"
            vm_params["billing_profile"] = {"max_price": spot_max_price}

        vm_poller = compute_client.virtual_machines.begin_create_or_update(
            RESOURCE_GROUP_NAME,
            vm_name,
            vm_params,
        )
        vm = vm_poller.result()
        if log:
            log.log(f"[azure] VM created.")

        # Step 8: Wait for VM to be running
        if log:
            log.log("[azure] Waiting for VM to reach running state...")
        _wait_for_vm_running(compute_client, vm_name, log)

        # Refresh public IP
        public_ip_resource = network_client.public_ip_addresses.get(
            RESOURCE_GROUP_NAME, ip_name
        )
        public_ip = public_ip_resource.ip_address
        if log:
            log.log(f"[azure] VM running at {public_ip}")

        # Step 9: Wait for SSH
        if log:
            log.log("[azure] Waiting for SSH to become available...")
        _wait_for_ssh(public_ip, log)

        return {
            "resource_group": RESOURCE_GROUP_NAME,
            "vm_name": vm_name,
            "public_ip": public_ip,
            "region": region,
            "key_path": key_path,
            "credentials_json": azure_config.get("credentials_json"),
            "subscription": subscription_id,
        }

    except Exception as e:
        if log:
            log.log(f"[azure] Provisioning failed: {e}")
            log.log(f"[azure] Cleaning up resource group {RESOURCE_GROUP_NAME}...")
        try:
            resource_client.resource_groups.begin_delete(RESOURCE_GROUP_NAME).result()
            if log:
                log.log("[azure] Resource group deleted.")
        except Exception as cleanup_err:
            if log:
                log.log(f"[azure] Cleanup failed: {cleanup_err}")
        raise


def teardown(instance_info: dict, log=None):
    """Delete the entire resource group — cleanest way to remove all resources."""
    resource_group = instance_info["resource_group"]

    # Rebuild credentials from instance_info
    config_for_creds = {"platforms": {"azure": {
        "credentials_json": instance_info.get("credentials_json"),
        "subscription": instance_info.get("subscription"),
    }}}
    credential, subscription_id = _get_credential(config_for_creds)
    resource_client = ResourceManagementClient(credential, subscription_id)

    if log:
        log.log(f"[azure] Deleting resource group {resource_group} (all resources)...")

    try:
        poller = resource_client.resource_groups.begin_delete(resource_group)
        poller.result()
        if log:
            log.log(f"[azure] Resource group {resource_group} deleted.")
    except Exception as e:
        if log:
            log.log(f"[azure] Teardown failed: {e}")
        raise


def preflight_check(config: dict, log=None) -> list[dict]:
    """Validate credentials, VM size, image, and GPU quota. No resources created."""
    results = []
    azure_config = config.get("platforms", {}).get("azure", {})
    region = azure_config.get("region", DEFAULT_REGION)
    vm_size = azure_config.get("instance_type", DEFAULT_VM_SIZE)

    # 1. Credentials
    try:
        credential, subscription_id = _get_credential(config)
        credential.get_token("https://management.azure.com/.default")
        results.append({"check": "Credentials", "status": "pass",
                        "detail": f"subscription {subscription_id}"})
    except Exception as e:
        results.append({"check": "Credentials", "status": "fail",
                        "detail": str(e)})
        return results

    compute_client = ComputeManagementClient(credential, subscription_id)

    # 2. VM size available in region
    try:
        sizes = list(compute_client.virtual_machine_sizes.list(location=region))
        size_names = {s.name for s in sizes}
        if vm_size in size_names:
            results.append({"check": "VM size", "status": "pass",
                            "detail": f"{vm_size} available in {region}"})
        else:
            results.append({"check": "VM size", "status": "fail",
                            "detail": f"{vm_size} not available in {region}"})
    except Exception as e:
        results.append({"check": "VM size", "status": "fail",
                        "detail": str(e)})

    # 3. Image exists
    try:
        images = list(compute_client.virtual_machine_images.list(
            location=region,
            publisher_name=IMAGE_REFERENCE["publisher"],
            offer=IMAGE_REFERENCE["offer"],
            skus=IMAGE_REFERENCE["sku"],
        ))
        if images:
            results.append({"check": "Image", "status": "pass",
                            "detail": f"{IMAGE_REFERENCE['publisher']}/{IMAGE_REFERENCE['offer']}/{IMAGE_REFERENCE['sku']} ({len(images)} versions)"})
        else:
            results.append({"check": "Image", "status": "fail",
                            "detail": "No matching image found"})
    except Exception as e:
        results.append({"check": "Image", "status": "fail",
                        "detail": str(e)})

    # 4. GPU quota (the known blocker for Azure)
    try:
        usages = list(compute_client.usage.list(location=region))
        # Azure VM family names vary — search for a match
        vm_family_lower = vm_size.lower()
        found_quota = False
        for usage in usages:
            if usage.name and usage.name.localized_value and vm_family_lower[:10] in usage.name.localized_value.lower():
                found_quota = True
                available = usage.limit - usage.current_value
                if available >= 36:  # NV36ads needs 36 cores
                    results.append({"check": "vCPU quota", "status": "pass",
                                    "detail": f"{usage.name.localized_value}: {available} available (limit {usage.limit})"})
                else:
                    results.append({"check": "vCPU quota", "status": "fail",
                                    "detail": f"{usage.name.localized_value}: {available} available, need 36. Request increase at portal.azure.com → Quotas"})
                break
        if not found_quota:
            results.append({"check": "vCPU quota", "status": "warn",
                            "detail": f"Could not find quota for VM family matching {vm_size}"})
    except Exception as e:
        results.append({"check": "vCPU quota", "status": "warn",
                        "detail": f"Could not check quota: {e}"})

    return results


def estimate_cost(config: dict) -> dict:
    """Estimate cost for a run. Returns dict with hourly rate and estimated total."""
    azure_config = config.get("platforms", {}).get("azure", {})
    hourly_rate = float(azure_config.get("hourly_rate", DEFAULT_HOURLY_RATE))
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

def _ensure_ssh_key(log=None) -> str:
    """Generate an SSH key pair if it doesn't exist. Returns path to private key."""
    os.makedirs(KEY_DIR, exist_ok=True)
    key_path = os.path.join(KEY_DIR, "autoresearch-anycloud-azure")

    if os.path.exists(key_path):
        if log:
            log.log(f"[azure] Using existing SSH key '{key_path}'")
        return key_path

    if log:
        log.log("[azure] Creating SSH key pair...")
    import subprocess
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-f", key_path, "-N", "", "-C", "autoresearch-anycloud"],
        check=True, capture_output=True,
    )
    os.chmod(key_path, 0o400)
    if log:
        log.log(f"[azure] Key saved to {key_path}")

    return key_path


def _cleanup_orphaned_resources(resource_client, log=None):
    """Delete autoresearch-anycloud resource group if it exists from a previous failed run."""
    try:
        rg = resource_client.resource_groups.get(RESOURCE_GROUP_NAME)
        if rg:
            if log:
                log.log(f"[azure] Found orphaned resource group {RESOURCE_GROUP_NAME}, deleting...")
            resource_client.resource_groups.begin_delete(RESOURCE_GROUP_NAME).result()
            if log:
                log.log(f"[azure] Orphaned resource group deleted.")
    except Exception:
        pass  # Resource group doesn't exist


def _wait_for_vm_running(compute_client, vm_name: str, log=None,
                         retries: int = 30, delay: int = 10):
    """Poll until the VM instance view shows PowerState/running."""
    for attempt in range(1, retries + 1):
        instance_view = compute_client.virtual_machines.instance_view(
            RESOURCE_GROUP_NAME, vm_name
        )
        statuses = {s.code for s in (instance_view.statuses or [])}

        if "PowerState/running" in statuses:
            if log:
                log.log(f"[azure] VM running after ~{attempt * delay}s")
            return

        if log and attempt % 3 == 0:
            log.log(f"[azure] Still waiting... statuses: {statuses}")

        time.sleep(delay)

    raise TimeoutError(f"VM {vm_name} not running after {retries * delay}s. "
                       f"Last statuses: {statuses}")


def _wait_for_ssh(host: str, log=None, retries: int = 15, delay: int = 10):
    """Poll until SSH port 22 accepts connections."""
    import socket

    for attempt in range(1, retries + 1):
        try:
            sock = socket.create_connection((host, 22), timeout=5)
            sock.close()
            if log:
                log.log(f"[azure] SSH ready after {attempt * delay}s")
            return
        except (socket.timeout, ConnectionRefusedError, OSError):
            if attempt < retries:
                time.sleep(delay)

    raise TimeoutError(f"SSH not available on {host}:22 after {retries * delay}s")
