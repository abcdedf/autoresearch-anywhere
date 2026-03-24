"""AWS provider — provision and teardown GPU instances via boto3.

No AWS CLI needed. No manual key pair creation. Everything is automatic.
Credentials are read from the CSV in ~/.aws/credentials/ at runtime.
"""

import csv
import os
import time

import boto3
from botocore.exceptions import ClientError


# Deep Learning AMI (PyTorch, Ubuntu 22.04) — comes with CUDA + PyTorch preinstalled
AMI_FILTER = "Deep Learning OSS Nvidia Driver AMI GPU PyTorch * (Ubuntu 22.04) *"
DEFAULT_INSTANCE_TYPE = "g5.xlarge"  # A10G 24GB VRAM
DEFAULT_REGION = "us-east-1"
DEFAULT_SPOT_MAX_PRICE = "0.50"  # ~50% of on-demand ($1.006/hr)
KEY_PAIR_NAME = "autoresearch-aw"
KEY_DIR = os.path.join(os.path.expanduser("~"), ".autoresearch-aw")


def _get_session(config: dict) -> boto3.Session:
    """Create a boto3 session from the credentials CSV."""
    aws_config = config.get("platforms", {}).get("aws", {})
    region = aws_config.get("region", DEFAULT_REGION)
    csv_path = aws_config.get("credentials_csv")

    if csv_path and os.path.exists(csv_path):
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            row = next(reader)
        return boto3.Session(
            aws_access_key_id=row.get("Access key ID", "").strip(),
            aws_secret_access_key=row.get("Secret access key", "").strip(),
            region_name=region,
        )

    return boto3.Session(region_name=region)


def provision(config: dict, log=None) -> dict:
    """Launch a spot GPU instance on AWS. Returns instance info dict.

    Automatically creates an SSH key pair if one doesn't exist.
    """
    aws_config = config.get("platforms", {}).get("aws", {})
    region = aws_config.get("region", DEFAULT_REGION)
    instance_type = aws_config.get("instance_type", DEFAULT_INSTANCE_TYPE)
    use_spot = aws_config.get("use_spot", False)
    spot_max_price = str(aws_config.get("spot_max_price", DEFAULT_SPOT_MAX_PRICE))

    session = _get_session(config)
    ec2 = session.client("ec2")
    ec2_resource = session.resource("ec2")

    # Step 0: Terminate any orphaned instances from previous failed runs
    _cleanup_orphaned_instances(ec2, log)

    # Step 1: Ensure SSH key pair exists
    key_path = _ensure_key_pair(ec2, log)

    # Step 2: Find latest Deep Learning AMI
    if log:
        log.log("[aws] Finding latest Deep Learning AMI...")
    ami_id = _find_ami(ec2, log)

    # Step 3: Create security group (SSH only)
    sg_id = _ensure_security_group(ec2, log)

    # Step 4: Launch instance
    pricing_mode = "spot" if use_spot else "on-demand"
    if log:
        log.log(f"[aws] Launching {instance_type} {pricing_mode} instance...")

    launch_kwargs = dict(
        ImageId=ami_id,
        InstanceType=instance_type,
        KeyName=KEY_PAIR_NAME,
        SecurityGroupIds=[sg_id],
        MinCount=1,
        MaxCount=1,
        BlockDeviceMappings=[{
            "DeviceName": "/dev/sda1",
            "Ebs": {
                "VolumeSize": 150,  # GB — enough for data + model
                "VolumeType": "gp3",
                "Encrypted": True,
            },
        }],
        TagSpecifications=[{
            "ResourceType": "instance",
            "Tags": [{"Key": "Name", "Value": "autoresearch-aw"}],
        }],
    )

    if use_spot:
        launch_kwargs["InstanceMarketOptions"] = {
            "MarketType": "spot",
            "SpotOptions": {
                "MaxPrice": spot_max_price,
                "SpotInstanceType": "one-time",
                "InstanceInterruptionBehavior": "terminate",
            },
        }

    instances = ec2_resource.create_instances(**launch_kwargs)

    instance = instances[0]
    instance_id = instance.id
    if log:
        log.log(f"[aws] Instance {instance_id} launched. Waiting for running state...")

    # Wait for instance to be running
    instance.wait_until_running()
    instance.reload()

    public_ip = instance.public_ip_address
    if log:
        log.log(f"[aws] Instance running at {public_ip}")

    # Wait for SSH to be ready
    if log:
        log.log("[aws] Waiting for SSH to become available...")
    _wait_for_ssh(public_ip, log)

    return {
        "instance_id": instance_id,
        "public_ip": public_ip,
        "region": region,
        "key_path": key_path,
        "security_group_id": sg_id,
        "credentials_csv": aws_config.get("credentials_csv"),
    }


def teardown(instance_info: dict, log=None):
    """Terminate the instance and clean up security group."""
    region = instance_info["region"]
    instance_id = instance_info["instance_id"]
    sg_id = instance_info.get("security_group_id")

    config_for_session = {"platforms": {"aws": {
        "credentials_csv": instance_info.get("credentials_csv"),
        "region": region,
    }}}
    session = _get_session(config_for_session)
    ec2 = session.client("ec2")

    if log:
        log.log(f"[aws] Terminating instance {instance_id}...")

    ec2.terminate_instances(InstanceIds=[instance_id])
    if log:
        log.log(f"[aws] Instance {instance_id} termination initiated.")

    # Try to delete security group immediately. If it fails (instance still
    # attached), that's fine — it gets cleaned up on the next run.
    if sg_id:
        try:
            ec2.delete_security_group(GroupId=sg_id)
            if log:
                log.log(f"[aws] Security group {sg_id} deleted.")
        except ClientError:
            if log:
                log.log(f"[aws] Security group {sg_id} will be cleaned up on next run.")

    # Note: we keep the key pair for future runs (no need to recreate each time)


def estimate_cost(config: dict) -> dict:
    """Estimate cost for a run. Returns dict with hourly rate and estimated total."""
    aws_config = config.get("platforms", {}).get("aws", {})
    max_price = float(aws_config.get("spot_max_price", DEFAULT_SPOT_MAX_PRICE))
    max_experiments = config.get("research", {}).get("max_experiments", 2)

    # ~5 min per experiment + ~5 min for setup/prepare
    estimated_hours = (max_experiments * 5 + 5) / 60

    return {
        "hourly_rate_usd": max_price,
        "estimated_hours": estimated_hours,
        "estimated_cost_usd": round(max_price * estimated_hours, 2),
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure_key_pair(ec2, log=None) -> str:
    """Create an EC2 key pair if it doesn't exist. Returns path to private key."""
    os.makedirs(KEY_DIR, exist_ok=True)
    key_path = os.path.join(KEY_DIR, f"{KEY_PAIR_NAME}.pem")

    # Check if key pair already exists in AWS
    try:
        ec2.describe_key_pairs(KeyNames=[KEY_PAIR_NAME])
        if os.path.exists(key_path):
            if log:
                log.log(f"[aws] Using existing key pair '{KEY_PAIR_NAME}'")
            return key_path
        else:
            # Key exists in AWS but not locally — delete and recreate
            ec2.delete_key_pair(KeyName=KEY_PAIR_NAME)
            if log:
                log.log(f"[aws] Key pair exists in AWS but not locally. Recreating...")
    except ClientError:
        pass  # Key doesn't exist, will create

    # Create new key pair
    if log:
        log.log(f"[aws] Creating SSH key pair '{KEY_PAIR_NAME}'...")

    response = ec2.create_key_pair(KeyName=KEY_PAIR_NAME, KeyType="ed25519")
    private_key = response["KeyMaterial"]

    with open(key_path, "w") as f:
        f.write(private_key)
    os.chmod(key_path, 0o400)

    if log:
        log.log(f"[aws] Key saved to {key_path}")

    return key_path


def _find_ami(ec2, log=None) -> str:
    """Find the latest Deep Learning AMI for PyTorch on Ubuntu 22.04."""
    response = ec2.describe_images(
        Owners=["amazon"],
        Filters=[
            {"Name": "name", "Values": [AMI_FILTER]},
            {"Name": "state", "Values": ["available"]},
            {"Name": "architecture", "Values": ["x86_64"]},
        ],
    )

    images = response["Images"]
    if not images:
        raise RuntimeError("No Deep Learning AMI found. Check region and filters.")

    # Sort by creation date, pick newest
    images.sort(key=lambda x: x["CreationDate"], reverse=True)
    ami = images[0]

    if log:
        log.log(f"[aws] AMI: {ami['Name']} ({ami['ImageId']})")

    return ami["ImageId"]


def _cleanup_orphaned_instances(ec2, log=None):
    """Terminate any running autoresearch-aw instances from previous failed runs."""
    try:
        response = ec2.describe_instances(
            Filters=[
                {"Name": "tag:Name", "Values": ["autoresearch-aw"]},
                {"Name": "instance-state-name", "Values": ["running", "pending"]},
            ]
        )
        for reservation in response["Reservations"]:
            for instance in reservation["Instances"]:
                instance_id = instance["InstanceId"]
                if log:
                    log.log(f"[aws] Terminating orphaned instance {instance_id}...")
                ec2.terminate_instances(InstanceIds=[instance_id])
    except ClientError:
        pass


def _ensure_security_group(ec2, log=None) -> str:
    """Create or reuse a security group allowing SSH from anywhere."""
    sg_name = "autoresearch-aw-ssh"

    try:
        response = ec2.describe_security_groups(
            Filters=[{"Name": "group-name", "Values": [sg_name]}]
        )
        if response["SecurityGroups"]:
            sg_id = response["SecurityGroups"][0]["GroupId"]
            if log:
                log.log(f"[aws] Reusing security group {sg_id}")
            return sg_id
    except ClientError:
        pass

    response = ec2.create_security_group(
        GroupName=sg_name,
        Description="SSH access for autoresearch-aw",
    )
    sg_id = response["GroupId"]

    ec2.authorize_security_group_ingress(
        GroupId=sg_id,
        IpPermissions=[{
            "IpProtocol": "tcp",
            "FromPort": 22,
            "ToPort": 22,
            "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "SSH"}],
        }],
    )

    if log:
        log.log(f"[aws] Created security group {sg_id}")

    return sg_id


def _wait_for_ssh(host: str, log=None, retries: int = 15, delay: int = 10):
    """Poll until SSH port 22 accepts connections."""
    import socket

    for attempt in range(1, retries + 1):
        try:
            sock = socket.create_connection((host, 22), timeout=5)
            sock.close()
            if log:
                log.log(f"[aws] SSH ready after {attempt * delay}s")
            return
        except (socket.timeout, ConnectionRefusedError, OSError):
            if attempt < retries:
                time.sleep(delay)

    raise TimeoutError(f"SSH not available on {host}:22 after {retries * delay}s")
