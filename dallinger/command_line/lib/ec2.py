import errno
import logging
import os.path
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import boto3
import click
import pandas as pd
import paramiko
import requests
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from botocore.exceptions import ConnectionError as BotoConnectionError
from paramiko import ssh_exception as pse
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_fixed,
)
from yaspin import yaspin

from ..config import get_configured_hosts
from ..config import remove_host as dallinger_remove_host
from ..config import store_host as dallinger_store_host
from ..docker_ssh import Executor
from ..docker_ssh import prepare_server as dallinger_prepare_server
from ..docker_ssh import register_server as dallinger_register_server
from ..utils import get_server_pem_path

logger = logging.getLogger(__name__)

DEFAULT_AWS_REGION = "us-east-1"

DEFAULT_UBUNTU_24_04_AMI_SSM_PARAMETER = (
    "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
)


def _resolve_default_region_name():
    """Resolve the region boto uses when no region is given, for user-facing messages."""
    return get_keys()["region_name"]


def get_keys(region_name=None):
    """Return boto client arguments: Dallinger's AWS keys, if set, and a region.

    If the keys are unset or still the placeholder defaults, boto finds
    credentials itself (``~/.aws``, SSO, a role). If the key ID is a
    temporary one (``ASIA...``) and is the one in ``AWS_ACCESS_KEY_ID``,
    ``AWS_SESSION_TOKEN`` is passed along with the keys, so exported temporary
    credentials work; a leftover token never reaches long-lived keys. The
    region is ``region_name``, else boto's default region
    (``AWS_DEFAULT_REGION`` or the AWS profile's region) when Dallinger's keys
    aren't used, else Dallinger's ``aws_region``.
    """
    from dallinger.config import get_config
    from dallinger.data import aws_access_keys_present

    config = get_config(load=True)
    default_region = config.get("aws_region", DEFAULT_AWS_REGION) or DEFAULT_AWS_REGION
    if aws_access_keys_present(config):
        keys = {
            "aws_access_key_id": config.get("aws_access_key_id"),
            "aws_secret_access_key": config.get("aws_secret_access_key"),
            "region_name": region_name or default_region,
        }
        session_token = os.environ.get("AWS_SESSION_TOKEN")
        key_id = keys["aws_access_key_id"]
        if (
            session_token
            and key_id.startswith("ASIA")
            and key_id == os.environ.get("AWS_ACCESS_KEY_ID")
        ):
            keys["aws_session_token"] = session_token
        return keys
    return {"region_name": region_name or boto3.Session().region_name or default_region}


def url_to_country_city(url):
    # Lookup the country and city of an IP address
    # https://stackoverflow.com/questions/38099968/how-to-get-country-name-from-ip-address-in-python
    import json

    import requests

    response = requests.get(f"http://ip-api.com/json/{url}")
    js = json.loads(response.text)
    return {
        "country": js["country"],
        "city": js["city"],
    }


_AUTH_FAILURE_MSG = (
    "AWS authentication failed. "
    "Please check that (1) your AWS credentials are correct and not expired, "
    "and (2) your system clock is in sync (e.g. run 'timedatectl' on Linux "
    "or 'w32tm /query /status' on Windows)."
)

_AUTH_FAILURE_CODES = {"AuthFailure", "InvalidClientTokenId", "RequestExpired"}

_REGION_UNAVAILABLE_CODES = {"AuthFailure", "OptInRequired", "UnauthorizedOperation"}
# Fail fast on unreachable regions in the all-regions scan; boto's defaults
# retry for about five minutes per region.
_REGION_SCAN_CONFIG = Config(connect_timeout=10, retries={"max_attempts": 2})


class _BotoClientProxy:
    """Wraps a boto3 client to add a helpful hint to auth-related errors."""

    def __init__(self, client):
        self._client = client

    def __getattr__(self, name):
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr

        def wrapper(*args, **kwargs):
            try:
                return attr(*args, **kwargs)
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") in _AUTH_FAILURE_CODES:
                    raise click.ClickException(_AUTH_FAILURE_MSG) from e
                raise

        return wrapper


def get_ec2_client(region_name=None, config=None):
    return _BotoClientProxy(
        boto3.client("ec2", config=config, **get_keys(region_name))
    )


def get_ssm_client(region_name=None):
    return _BotoClientProxy(boto3.client("ssm", **get_keys(region_name)))


def get_53_client():
    return _BotoClientProxy(boto3.client("route53", **get_keys()))


def list_regions():
    logger.info("Getting regions...")
    regions = get_ec2_client().describe_regions()["Regions"]
    region_metadata = []
    for region in regions:
        region_metadata.append(
            {
                "region_name": region["RegionName"],
                "endpoint": region["Endpoint"],
                **url_to_country_city(region["Endpoint"]),
            }
        )

    print(pd.DataFrame(region_metadata).to_markdown())


def get_instance_details(instance_types, region_name=None):
    try:
        response = requests.get(
            "https://ec2.shop",
            params={
                "filter": ",".join(instance_types),
                "region": region_name,
            },
            headers={
                "accept": "json",
            },
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning(
            f"Could not fetch instance details from ec2.shop (offline or unreachable): {e}"
        )
        return None
    if response.status_code != 200:
        print(f"Failed to get details for {instance_types} in {region_name}")
        return None

    price_df = pd.DataFrame(response.json()["Prices"])

    if len(price_df) != len(instance_types):
        print(f"Failed to get all details for {instance_types} in {region_name}")
    return price_df


def get_instances(region_name, show_spinner=True, boto_config=None):
    display_region = region_name or _resolve_default_region_name()
    if show_spinner:
        with yaspin(
            text=f"Retrieving instances in {display_region}...", color="green"
        ) as sp:
            reservations = get_ec2_client(
                region_name, boto_config
            ).describe_instances()["Reservations"]
            sp.ok("✔")
    else:
        reservations = get_ec2_client(region_name, boto_config).describe_instances()[
            "Reservations"
        ]
    instances = []
    for reservation in reservations:
        for instance in reservation["Instances"]:
            try:
                name = instance["Tags"][0]["Value"]
            except KeyError:
                name = "Unnamed"
            instance_time_zone = instance["LaunchTime"].tzinfo
            now_in_instance_time_zone = datetime.now(instance_time_zone)

            instances.append(
                {
                    "name": name,
                    "instance_id": instance["InstanceId"],
                    "instance_type": instance["InstanceType"],
                    "region": region_name,
                    "state": instance["State"]["Name"],
                    "public_dns_name": instance["PublicDnsName"],
                    # 'public_ip_address': instance['PublicIpAddress'],
                    "pem": instance["KeyName"],
                    # Duration since instance was started
                    "uptime": (
                        now_in_instance_time_zone - instance["LaunchTime"]
                    ).seconds,
                }
            )

    columns = [
        "name",
        "instance_id",
        "instance_type",
        "region",
        "state",
        "public_dns_name",
        "pem",
        "uptime",
    ]
    return pd.DataFrame(instances, columns=columns)


def get_all_instances(region_name=None):
    if region_name is None:
        logger.info("Listing instances in all regions...")
        instance_dfs = []
        all_regions = get_ec2_client(config=_REGION_SCAN_CONFIG).describe_regions()[
            "Regions"
        ]
        with Progress(
            SpinnerColumn(style="green"),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            transient=True,
        ) as progress:
            task = progress.add_task(
                "Retrieving instances in all regions...", total=len(all_regions)
            )
            skipped = {}
            for region in all_regions:
                progress.update(
                    task,
                    description=f"Retrieving instances in {region['RegionName']}...",
                )
                try:
                    instance_dfs.append(
                        get_instances(
                            region["RegionName"],
                            show_spinner=False,
                            boto_config=_REGION_SCAN_CONFIG,
                        )
                    )
                except BotoConnectionError:
                    skipped[region["RegionName"]] = "unreachable"
                except (ClientError, click.ClickException) as e:
                    # _BotoClientProxy turns AuthFailure into a ClickException.
                    error = e if isinstance(e, ClientError) else e.__cause__
                    if not isinstance(error, ClientError):
                        raise
                    code = error.response.get("Error", {}).get("Code")
                    if code not in _REGION_UNAVAILABLE_CODES:
                        raise
                    skipped[region["RegionName"]] = code
                progress.advance(task)
        if not instance_dfs:
            message = "Could not list instances in any region: " + ", ".join(
                f"{r} ({c})" for r, c in skipped.items()
            )
            if skipped and set(skipped.values()) <= _AUTH_FAILURE_CODES:
                message += f". {_AUTH_FAILURE_MSG}"
            raise click.ClickException(message)
        for skipped_region, code in skipped.items():
            click.echo(
                click.style(
                    f"Warning: skipped region {skipped_region} ({code}); "
                    "its instances are not listed or checked.",
                    fg="yellow",
                ),
                err=True,
            )
        scanned = (
            f"{len(instance_dfs)} of {len(all_regions)} regions"
            if skipped
            else "all regions"
        )
        click.echo(
            click.style(f"✔ Finished retrieving instances in {scanned}.", fg="green")
        )
        instance_df = pd.concat(instance_dfs)
    else:
        instance_df = get_instances(region_name)
    if len(instance_df) == 0:
        return instance_df
    with yaspin(text="Getting instance details..."):
        details_frames = []
        for (instance_type, region), group in instance_df.groupby(
            ["instance_type", "region"]
        ):
            details_df = get_instance_details([instance_type], region)
            if details_df is not None:
                details_df = details_df.copy()
                details_df["instance_type"] = instance_type
                details_df["region"] = region
                details_frames.append(details_df)
        instance_details = (
            pd.concat(details_frames, ignore_index=True) if details_frames else None
        )
        if instance_details is not None:
            selected_cols = ["instance_type", "region"]
            for col in ["Memory", "VCPUS", "Cost"]:
                if col in instance_details.columns:
                    selected_cols.append(col)
            instance_details = instance_details[selected_cols]
            instance_df = instance_df.merge(
                instance_details, on=["instance_type", "region"], how="left"
            )
            if "Cost" in instance_df.columns:
                instance_df["Cost"] = pd.to_numeric(
                    instance_df["Cost"], errors="coerce"
                )
                instance_df["Cost"] = (
                    instance_df["Cost"] * instance_df["uptime"] / (60**2)
                )
                instance_df = instance_df.sort_values("Cost")
                instance_df["Cost"] = instance_df["Cost"].apply(
                    lambda x: f"${int(x)}" if pd.notna(x) else "N/A"
                )
    instance_df["uptime"] = instance_df["uptime"].apply(
        lambda x: str(int(x / 60**2)) + "h"
    )
    return instance_df


def list_instances(region_name=None, filtered_states=[], pem=None):
    logger.info("Getting instances...")
    # Get all instances for the specified region
    instance_df = get_all_instances(region_name)
    # Filter instances based on state and pem
    if len(filtered_states) > 0:
        instance_df = instance_df.query("state in @filtered_states")
    if pem is not None:
        instance_df = instance_df.query("pem.str.endswith(@pem)")
    print(instance_df.to_markdown())


def get_instance_types(region_name=None):
    ec2 = get_ec2_client(region_name)
    with Progress(
        SpinnerColumn(style="green"),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        task = progress.add_task("Retrieving instance types...", total=None)
        response = ec2.describe_instance_types()
        instance_types = response["InstanceTypes"]
        progress.update(
            task, description=f"Retrieving instance types... ({len(instance_types)})"
        )
        while "NextToken" in response:
            response = ec2.describe_instance_types(NextToken=response["NextToken"])
            instance_types += response["InstanceTypes"]
            progress.update(
                task,
                description=f"Retrieving instance types... ({len(instance_types)})",
            )

    instance_type_metadata = []
    for instance_type in instance_types:
        memory_in_gb = instance_type["MemoryInfo"]["SizeInMiB"] / 1024
        if instance_type["InstanceStorageSupported"]:
            storage_in_gb = instance_type["InstanceStorageInfo"]["TotalSizeInGB"]
        else:
            storage_in_gb = 0
        instance_type_metadata.append(
            {
                "instance_type": instance_type["InstanceType"],
                "vcpu": instance_type["VCpuInfo"]["DefaultVCpus"],
                "memory": f"{memory_in_gb} GB",
                "storage": f"{storage_in_gb} GB",
                "network_performance": instance_type["NetworkInfo"][
                    "NetworkPerformance"
                ],
            }
        )
    return pd.DataFrame(instance_type_metadata)


def list_instance_types(region_name=None):
    print("Getting all instance types...")
    instance_type_df = get_instance_types(region_name)
    print(instance_type_df.to_markdown())


def list_recent_ubuntu_images(region_name=None):
    logger.info("Getting recent Ubuntu images...")
    response = get_ec2_client(region_name).describe_images(
        IncludeDeprecated=False,
    )
    image_ids = []
    for image in response["Images"]:
        image_ids.append(
            {
                "image_id": image["ImageId"],
                "name": image["Name"],
                "creation_date": image["CreationDate"],
            }
        )
    print(pd.DataFrame(image_ids).to_markdown())


def get_security_group_id(security_group_name, region_name=None):
    try:
        response = get_ec2_client(region_name).describe_security_groups(
            GroupNames=[security_group_name]
        )
        return response["SecurityGroups"][0]["GroupId"]
    except Exception:
        print(
            f"Security group {security_group_name} not found in region {region_name}. Creating..."
        )
        response = get_ec2_client(region_name).create_security_group(
            Description="Default security group for dallinger docker to EC2",
            GroupName=security_group_name,
        )
        group_id = response["GroupId"]

        IpPermissions = [
            {
                "FromPort": port,
                "IpProtocol": "tcp",
                "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                "Ipv6Ranges": [],
                "PrefixListIds": [],
                "ToPort": port,
                "UserIdGroupPairs": [],
            }
            for port in [80, 22, 443, 5000]
        ]

        # Add inbound rules
        get_ec2_client(region_name).authorize_security_group_ingress(
            GroupId=group_id,
            IpPermissions=IpPermissions,
        )
        return group_id


def get_pem_path(key_name) -> Path:
    """Return a Path to the PEM file for the given key name.

    Looks for the key in ~/.ssh/ first (best practice), then falls back to ~/
    for backwards compatibility.
    """
    # Try ~/.ssh/ first (best practice)
    ssh_pem_path = Path.home() / ".ssh" / f"{key_name}.pem"
    if ssh_pem_path.exists():
        return ssh_pem_path

    # Fall back to home directory for backwards compatibility
    home_pem_path = Path.home() / f"{key_name}.pem"
    if home_pem_path.exists():
        logger.warning(
            f"PEM file found at legacy location: {home_pem_path}\n"
            f"    Recommended: Move to {ssh_pem_path} for better security\n"
            f"    Command: mkdir -p ~/.ssh && mv '{home_pem_path}' '{ssh_pem_path}' && chmod 400 '{ssh_pem_path}'"
        )
        return home_pem_path

    # Neither location found - provide helpful error message
    raise FileNotFoundError(
        f"Private key file for EC2 keypair '{key_name}' not found.\n"
        "Looked in the following locations:\n"
        f"  - {ssh_pem_path} (recommended)\n"
        f"  - {home_pem_path} (legacy)\n\n"
        "Best practice: Store your PEM file in ~/.ssh/ directory.\n"
        "Make sure you have the private key locally and that the path is correct.\n"
        "Set the EC2 key name in your config with: ec2_default_pem = <keyname>"
    )


def register_key_pair(ec2, key_name):
    """Import a local SSH key into EC2.

    Supports RSA, Ed25519, and ECDSA key types.
    """
    pem_path: Path = get_pem_path(key_name)

    # Try each supported key type
    key = None
    for key_class in [paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey]:
        try:
            key = key_class.from_private_key_file(str(pem_path))
            break
        except Exception:
            continue

    if key is None:
        raise ValueError(
            f"Unable to load key from {pem_path}. "
            "Supported key types: RSA, Ed25519, ECDSA (DSS/DSA keys are not supported)"
        )

    # Get public key in SSH format (works for all types!)
    public_key = f"{key.get_name()} {key.get_base64()}\n".encode()
    ec2.import_key_pair(KeyName=key_name, PublicKeyMaterial=public_key)


def _is_retryable(exc: BaseException) -> bool:
    """Avoid retrying when there's no hope."""
    _RETRY_ERRNOS = {
        getattr(errno, "ECONNREFUSED", None),
        getattr(errno, "EHOSTUNREACH", None),
        getattr(errno, "ENETUNREACH", None),
        getattr(errno, "ETIMEDOUT", None),
        getattr(errno, "ECONNRESET", None),
    }

    # Common transient cases
    if isinstance(
        exc,
        (
            socket.timeout,
            ConnectionRefusedError,
            ConnectionResetError,
            pse.NoValidConnectionsError,
        ),
    ):
        return True

    # temporary DNS failure
    if isinstance(exc, socket.gaierror):
        return exc.errno == getattr(socket, "EAI_AGAIN", -3)

    # Raw OSErrors: host/net unreachable, timeouts, refused/reset, etc.
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in _RETRY_ERRNOS:
        return True

    # SSH handshake timing issues while sshd is coming up
    if isinstance(exc, pse.SSHException):
        # (SSHException is very broad, unfortunately)
        msg = str(exc)
        return any(
            s in msg
            for s in (
                "Error reading SSH protocol banner",
                "kex timeout",
                "Connection reset by peer",
            )
        )

    return False


def wait_for_instance(host, user="ubuntu", n_tries=10):
    @retry(
        stop=stop_after_attempt(n_tries),
        wait=wait_fixed(5),
        retry=retry_if_exception(_is_retryable),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _wait_for_instance():
        return Executor(host, user)

    return _wait_for_instance()


def check_server_pem_matches_key_pair(key_name):
    """Raise a ``UsageError`` unless ``server_pem`` is the private key of EC2 key pair ``key_name``.

    New instances accept only the key pair they boot with, and docker-ssh
    logs in to every server with ``server_pem``, which can't have a passphrase.
    """
    pair_path, server_pem = get_pem_path(key_name), get_server_pem_path()
    same_file = pair_path.resolve() == server_pem.resolve()
    keys = []
    for path in [server_pem] if same_file else [server_pem, pair_path]:
        try:
            keys.append(paramiko.PKey.from_path(path))
        except Exception as exc:
            raise click.UsageError(
                f"Could not read the SSH key {path}: {exc}. server_pem and the "
                "ec2_default_pem key file must be unencrypted RSA, ECDSA or "
                "Ed25519 private keys (to replace a DSA key, see "
                "https://dallinger.readthedocs.io/en/latest/docker_support.html"
                "#replacing-a-dsa-key)."
            ) from exc
    if not same_file and keys[0].get_base64() != keys[1].get_base64():
        raise click.UsageError(
            f"server_pem ({server_pem}) is not the private key of the EC2 key pair "
            f"ec2_default_pem = {key_name} ({pair_path}). New instances accept only "
            "that key pair, and Dallinger logs in to every server with server_pem. "
            f"Set server_pem = {pair_path} in ~/.dallingerconfig or the "
            "environment, or set "
            "ec2_default_pem to the key pair whose private key server_pem is."
        )


def _get_latest_ubuntu_image_id(ec2):
    """Fallback: find the latest Ubuntu 24.04 AMI via ec2.describe_images."""
    response = ec2.describe_images(
        IncludeDeprecated=False,
        Owners=["099720109477"],  # Canonical
        Filters=[
            {
                "Name": "name",
                "Values": [
                    "ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"
                ],
            },
            {"Name": "state", "Values": ["available"]},
        ],
    )
    images = response["Images"]
    if not images:
        raise Exception(
            f"No Ubuntu 24.04 AMI found in region '{ec2.meta.region_name}'."
        )
    # Sort by name descending — the date suffix (YYYYMMDD) makes this work
    images.sort(key=lambda img: img["Name"], reverse=True)
    latest = images[0]
    print(f"Resolved latest Ubuntu 24.04 AMI: {latest['ImageId']} ({latest['Name']})")
    return latest["ImageId"]


def get_image_id(ec2, image_name):
    if image_name.startswith("ami-"):
        return image_name

    if image_name.startswith("/aws/service/"):
        region_name = ec2.meta.region_name
        ssm = get_ssm_client(region_name)
        try:
            response = ssm.get_parameter(Name=image_name)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("AccessDeniedException", "ParameterNotFound"):
                print(
                    f"Warning: SSM lookup failed ({error_code}). "
                    f"Falling back to describe_images for the latest Ubuntu 24.04 AMI."
                )
                return _get_latest_ubuntu_image_id(ec2)
            raise Exception(
                f"SSM parameter '{image_name}' not found in region '{region_name}'."
            ) from exc
        ami_id = response["Parameter"]["Value"]
        if not ami_id.startswith("ami-"):
            raise Exception(
                f"SSM parameter '{image_name}' returned unexpected value '{ami_id}'."
            )
        return ami_id

    response = ec2.describe_images(
        IncludeDeprecated=False,
        Filters=[
            {
                "Name": "name",
                "Values": [image_name],
            },
        ],
    )
    images = response["Images"]
    if len(images) != 1:
        region_name = ec2.meta.region_name
        if len(images) == 0:
            raise Exception(
                f"No AMI found for name '{image_name}' in region '{region_name}'."
            )
        raise Exception(
            f"Multiple AMIs found for name '{image_name}' in region '{region_name}'. "
            "Provide a unique AMI name, an AMI id, or an SSM parameter."
        )
    return images[0]["ImageId"]


def setup_ssh_keys(ec2, key_name, region_name=None):
    try:
        ec2.describe_key_pairs(KeyNames=[key_name])
    except ClientError:
        print(f"Key pair {key_name} not found in region {region_name}. Creating...")
        register_key_pair(ec2, key_name)


def boot_instance(ec2, image_id, instance_type, key_name, instance_name, region_name):
    response = ec2.run_instances(
        ImageId=image_id,
        InstanceType=instance_type,
        KeyName=key_name,
        MaxCount=1,
        MinCount=1,
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [
                    {
                        "Key": "Name",
                        "Value": instance_name,
                    },
                ],
            },
        ],
    )
    instance = response["Instances"][0]
    instance_id = instance["InstanceId"]

    try:
        with yaspin(
            text=f"Waiting for {instance_name} to be ready...", color="green"
        ) as sp:
            waiter = get_ec2_client(region_name).get_waiter("instance_running")
            waiter.wait(InstanceIds=[instance_id])
            sp.ok("✔")
    except BaseException:
        _print_teardown_hint(instance_name, instance_id, region_name, starting=True)
        raise
    return instance_id


def _print_teardown_hint(instance_name, instance_id, region_name, starting=False):
    """Say how to remove an instance that booted but was not set up.

    ``ec2 teardown --name`` finds only running instances, so an instance that
    may still be ``pending`` gets that caveat.
    """
    region = f" --region {region_name}" if region_name else ""
    teardown = f"`dallinger ec2 teardown --name {instance_name}{region}`"
    if starting:
        print(
            f"{instance_name} ({instance_id}) was launched but may still be "
            f"starting. Terminate {instance_id} in the EC2 console now, or run "
            f"{teardown} once `dallinger ec2 list instances --running{region}` "
            "shows it; then provision it again."
        )
    else:
        print(
            f"{instance_name} ({instance_id}) is running but was not set up. Fix "
            f"the problem above, then remove it with {teardown} and provision it "
            "again."
        )


def set_security_group(
    ec2, instance_id, instance_name, security_group_id, security_group_name
):
    print(f"Associating security group {security_group_name} with {instance_name}...")
    ec2.modify_instance_attribute(
        Groups=[security_group_id],
        InstanceId=instance_id,
    )


def get_volume_size(ec2, volume_id):
    response = ec2.describe_volumes(VolumeIds=[volume_id])
    return response["Volumes"][0]["Size"]


def increase_storage(
    instance_id, instance_name, storage_in_gb, ec2=None, region_name=None
):
    if ec2 is None:
        assert region_name is not None
        ec2 = get_ec2_client(region_name)
    # get volume id
    response = ec2.describe_instances(InstanceIds=[instance_id])
    instance = response["Reservations"][0]["Instances"][0]
    volume_id = instance["BlockDeviceMappings"][0]["Ebs"]["VolumeId"]

    # Get volume size
    volume_size = get_volume_size(ec2, volume_id)

    assert (
        volume_size < storage_in_gb
    ), f"Volume size {volume_size} GB is already greater than {storage_in_gb} GB"

    with yaspin(
        text=f"Increasing storage of {instance_name} to {storage_in_gb} GB...",
        color="green",
    ) as sp:
        ec2.modify_volume(
            VolumeId=volume_id,
            Size=storage_in_gb,
        )

        sp.text = "Waiting for volume to be ready..."
        waiter = ec2.get_waiter("volume_in_use")
        waiter.wait(VolumeIds=[volume_id])
        sp.ok("✔")

    # Extend partition
    host, user, ip_address = (
        instance["PublicDnsName"],
        "ubuntu",
        instance["PublicIpAddress"],
    )
    executor = wait_for_instance(host, user)

    volume_partition_list = [
        line for line in executor.run("lsblk -o name -n").split("\n") if line != ""
    ]
    volume_to_partitions = {}
    for volume_or_partition in volume_partition_list:
        if not any([volume_or_partition.__contains__(arrow) for arrow in ["└─", "├─"]]):
            volume_to_partitions[volume_or_partition] = []
        else:
            partition = volume_or_partition
            for volume in volume_to_partitions.keys():
                if volume_or_partition.__contains__(volume):
                    partition = volume + partition.split(volume)[1]
                    volume_to_partitions[volume].append(partition)
                    break
    selected_volumes = [
        volume
        for volume, partitions in volume_to_partitions.items()
        if len(partitions) > 0
    ]
    assert len(selected_volumes) == 1
    selected_volume = selected_volumes[0]
    selected_partition = volume_to_partitions[selected_volume][0]

    print("Disk usage before resize:")
    print(executor.run("df -h"))

    with yaspin(
        text=f"Resizing partition /dev/{selected_volume}...", color="green"
    ) as sp:
        time.sleep(20)
        executor.run(f"sudo growpart /dev/{selected_volume} 1")

        sp.text = f"Resizing filesystem on /dev/{selected_partition}..."
        time.sleep(10)
        executor.run(f"sudo resize2fs /dev/{selected_partition}")
        sp.ok("✔")

    print("Disk usage after resize:")
    print(executor.run("df -h"))
    return host, user, ip_address, executor


def filter_zone_ids(zone_name, route_53=None):
    if route_53 is None:
        route_53 = get_53_client()
    return [
        item.get("Id")
        for item in route_53.list_hosted_zones_by_name()["HostedZones"]
        if zone_name in item.get("Name", "")
    ]


def get_domain(dns_host):
    return ".".join(dns_host.split(".")[-2:])


def get_subdomain(dns_host):
    return dns_host.split(".")[0]


def _managed_record_names(dns_host):
    """Return the Route 53 record names that Dallinger manages for dns_host.

    ``create_dns_records`` creates both ``dns_host`` and ``*.dns_host``, and
    Route 53 reports fully qualified names with the wildcard octet escaped as
    ``\\052``, so every spelling of the pair is included.
    """
    base = dns_host.rstrip(".").lower()
    if base.startswith("*."):
        base = base[2:]
    return {f"{base}.", f"*.{base}.", f"\\052.{base}."}


def _find_dns_records(route_53, zone_id, dns_host):
    """Return the records in zone_id that Dallinger manages for dns_host.

    Records of any type are returned, because ``create_dns_record`` has to
    replace whatever is at that name (a hand-made ``A`` record, say) with its
    ``CNAME``. A name holding ``SOA`` or ``NS`` records is a zone apex or a
    delegated subdomain: a ``CNAME`` cannot live there, and deleting its other
    records would break mail or the delegated zone, so it is refused outright.
    """
    managed_names = _managed_record_names(dns_host)
    paginator = route_53.get_paginator("list_resource_record_sets")
    records = [
        record
        for page in paginator.paginate(HostedZoneId=zone_id)
        for record in page["ResourceRecordSets"]
        if record["Name"].lower() in managed_names
    ]
    record_types = {record["Type"] for record in records}
    if "SOA" in record_types:
        raise click.ClickException(
            f"DNS host {dns_host} is the apex of a hosted zone, so Dallinger cannot "
            f"point it at a server. Use a subdomain instead, for example exp.{dns_host}."
        )
    if "NS" in record_types:
        raise click.ClickException(
            f"DNS host {dns_host} is delegated to another hosted zone, so Dallinger "
            "cannot point it at a server. Use a name that is neither delegated nor "
            "inside a delegated subdomain."
        )
    return records


def _record_targets(record):
    """Return the hostnames a Route 53 record (or alias record) points at."""
    values = [r["Value"] for r in record.get("ResourceRecords", [])]
    values.append(record.get("AliasTarget", {}).get("DNSName", ""))
    return sorted({value.rstrip(".").lower() for value in values if value})


def remove_dns_records(zone_id, dns_host, route_53=None, confirm=False, target=None):
    """Delete the records for dns_host and its wildcard, optionally confirming first.

    With ``target``, only records pointing at that hostname are deleted; the
    others are kept with a warning.
    """
    if route_53 is None:
        route_53 = get_53_client()
    filtered_records = _find_dns_records(route_53, zone_id, dns_host)
    if target is not None:
        target = target.rstrip(".").lower()
        kept = [r for r in filtered_records if _record_targets(r) != [target]]
        for record in kept:
            targets = _record_targets(record)
            stale = (
                " It may be stale (for example after `ec2 stop`/`start`); "
                "check it and delete it by hand if so."
                if any(t.startswith("ec2-") for t in targets)
                else ""
            )
            print(
                f"Warning: Kept DNS record {record['Name']}, which points at "
                f"{', '.join(targets) or 'an unknown target'}, not {target}.{stale}"
            )
        filtered_records = [r for r in filtered_records if r not in kept]

    if len(filtered_records) > 0:
        targets = sorted(
            {
                resource["Value"]
                for record in filtered_records
                for resource in record.get("ResourceRecords", [])
            }
        )
        used_host = ", ".join(targets) if targets else "an unknown target"
        msg = f"""
                DNS host {dns_host} is already used by instance {used_host}. Make sure no experiments are running under this
                domain, OTHERWISE THIS WILL BREAK THEM. Are you sure you want to overwrite the DNS record and use it for
                this server?
                """
        if confirm and not click.confirm(msg):
            print("Aborting...")
            sys.exit(1)

        # delete the existing records
        for record in filtered_records:
            route_53.change_resource_record_sets(
                HostedZoneId=zone_id,
                ChangeBatch={
                    "Changes": [{"Action": "DELETE", "ResourceRecordSet": record}]
                },
            )
        print(f"Removed DNS record {dns_host}")


def create_dns_record(dns_host, user, host, route_53=None):
    """Point ``dns_host`` at ``host`` with a Route 53 CNAME and wait until it is in sync.

    Nothing connects through the new name, as the local resolver may still
    cache an older answer (or a negative one) for it.
    """
    if route_53 is None:
        route_53 = get_53_client()

    filtered_hosts = filter_zone_ids(get_domain(dns_host), route_53)
    hosted_zone_id = filtered_hosts[0]
    response = route_53.change_resource_record_sets(
        HostedZoneId=hosted_zone_id,
        ChangeBatch={
            "Changes": [
                {
                    "Action": "UPSERT",
                    "ResourceRecordSet": {
                        "Type": "CNAME",
                        "Name": dns_host,
                        "TTL": 300,
                        "ResourceRecords": [{"Value": host}],
                    },
                }
            ]
        },
    )

    assert (
        response["ResponseMetadata"]["HTTPStatusCode"] == 200
    ), "Failed to set up DNS record"

    print(f"Waiting for the DNS record {dns_host} (can take up to two minutes)...")
    change_id = response["ChangeInfo"]["Id"]
    n_tries, wait = 24, 5
    for _ in range(n_tries):
        if route_53.get_change(Id=change_id)["ChangeInfo"]["Status"] == "INSYNC":
            print(f"DNS record {dns_host} is in sync.")
            return
        time.sleep(wait)
    print(
        f"Route 53 had not synced the DNS record {dns_host} after {n_tries * wait} "
        "seconds; it usually finishes within a few more minutes."
    )


def prepare_instance(
    instance_name: str,
    region_name: str,
    instance_type: str,
    storage_in_gb: int,
    key_name: str,
    image_name: str,
    security_group_name: str,
    dns_host: str = None,
    callback: Callable[
        [str, str, str, Executor, Optional[str], str, str], None
    ] = None,
):
    instance_df = get_all_instances(region_name)
    assert (
        len(instance_df) == 0
        or len(instance_df.query(f"name == '{instance_name}' and state=='running'"))
        == 0
    ), f"Instance {instance_name} already exists!"

    if dns_host is not None:
        route_53 = get_53_client()
        domain = get_domain(dns_host)

        msg = f"""
        Hosted zone {domain} not found in Route 53.
        To set it up, you need a DNS record for your experiment server.
        On the AWS online console, navigate to the Route 53 service.
        On the Dashboard you can register a domain name. Note that different domain names
        come with different costs, and that registering a domain name can take from a few minutes to several hours.
        Before proceeding with the next steps, please wait until the AWS console tells you that the registration
        is complete.
        """
        filtered_ids = filter_zone_ids(domain, route_53)
        assert len(filtered_ids) == 1, msg

        remove_dns_records(filtered_ids[0], dns_host, route_53, confirm=True)

        with open(os.path.expanduser("~/.ssh/known_hosts"), "r") as f:
            known_hosts = f.readlines()
            known_hosts = [
                line for line in known_hosts if not line.startswith(dns_host)
            ]

        with open(os.path.expanduser("~/.ssh/known_hosts"), "w") as f:
            f.writelines(known_hosts)

    start = time.time()
    ec2 = get_ec2_client(region_name)
    # Without --region, get_keys picks boto's default region or aws_region.
    region_name = ec2.meta.region_name
    security_group_id = get_security_group_id(security_group_name, region_name)
    print(f"Provisioning {instance_name} on {region_name}...")
    image_id = get_image_id(ec2, image_name)

    setup_ssh_keys(ec2, key_name, region_name)
    instance_id = boot_instance(
        ec2, image_id, instance_type, key_name, instance_name, region_name
    )

    try:
        set_security_group(
            ec2, instance_id, instance_name, security_group_id, security_group_name
        )
        host, user, ip_address, executor = increase_storage(
            instance_id, instance_name, storage_in_gb, ec2
        )
    except BaseException as exc:
        # With a key that loads, paramiko reports a rejection as "Invalid key"
        # after also trying the file as other key types.
        if isinstance(exc, pse.AuthenticationException) or (
            isinstance(exc, pse.SSHException) and "Invalid key" in str(exc)
        ):
            print(
                f"The instance rejected server_pem. It accepts only the EC2 key pair "
                f"{key_name} it booted with. If that key pair in AWS was imported "
                f"from a different key than your local {key_name}.pem, delete it in "
                "the EC2 console so that provisioning imports the local key."
            )
        _print_teardown_hint(instance_name, instance_id, region_name)
        raise
    if callback is not None:
        try:
            callback(
                host, user, ip_address, executor, dns_host, instance_name, instance_id
            )
        except BaseException:
            region = f" --region {region_name}" if region_name else ""
            dns = f" --dns-host {dns_host}" if dns_host else ""
            print(
                "To remove the instance and its DNS records instead, run "
                f"`dallinger ec2 teardown --name {instance_name}{region}{dns}`."
                if dns_host
                else "To remove the instance instead, run "
                f"`dallinger ec2 teardown --name {instance_name}{region}`."
            )
            raise

    duration = round(time.time() - start)
    print(
        f"Provisioning complete in {duration} seconds. {instance_name} is ready at {host}"
    )


def create_dns_records(dns_host, user, host):
    if dns_host is not None:
        create_dns_record(dns_host, user, host)
        create_dns_record("*." + dns_host, user, host)


def remove_dns_record(dns_host, remove_dallinger_host=True, target=None):
    """Delete the Route 53 records for ``dns_host``, warning if it has no hosted zone.

    ``target`` is passed to :func:`remove_dns_records`.
    """
    if dns_host is None:
        return
    route_53 = get_53_client()
    zone_ids = filter_zone_ids(get_domain(dns_host), route_53)
    if zone_ids:
        remove_dns_records(zone_ids[0], dns_host, route_53, target=target)
    else:
        print(
            f"Warning: No Route 53 hosted zone found for {dns_host}; "
            "no DNS records were removed."
        )
    if remove_dallinger_host:
        dallinger_remove_host(dns_host)


def prepare_docker_experiment_setup(
    host, user, ip_address, executor, dns_host=None, instance_name=None, instance_id=None
):
    """Install Docker on a new instance, create its DNS records and register it.

    Everything connects over the AWS hostname ``host``: a resolver may still
    cache an old or negative answer for the new DNS host. Without a DNS host,
    a nip.io name for the public IP gives the server's sites a name that
    Let's Encrypt certifies, unlike the AWS hostname, which can resolve to a
    private IP inside AWS. A server record is saved under the AWS hostname
    and, with a DNS host, under that name too, both with the instance id so
    that ``ec2 teardown``, ``stop`` and ``start`` find them. A failure prints
    the commands that finish the setup (``prepare_instance`` adds the teardown
    command).
    """
    server_dns_host = dns_host or f"{ip_address}.nip.io"
    try:
        if dns_host:
            try:
                create_dns_records(dns_host, user, host)
            except Exception as exc:
                print(
                    f"Warning: Could not create the DNS records {dns_host} and "
                    f"*.{dns_host} ({exc}). Create them in Route 53 as CNAME "
                    f"records pointing to {host}."
                )
        dallinger_prepare_server(host, user)
        print("Registering the server and starting its shared services.")
        server_info = dallinger_register_server(
            host, user, dns_host=server_dns_host, network_advice=False
        )
        server_info = {**server_info, "ec2_instance_id": instance_id}
        dallinger_store_host(server_info)
        if dns_host:
            dallinger_store_host({**server_info, "host": dns_host})
    except BaseException:
        commands = [
            f"dallinger docker-ssh servers add --host {host} --user {user} "
            f"--dns-host {server_dns_host}"
        ]
        if dns_host:
            commands.append(
                f"dallinger docker-ssh servers add --host {dns_host} --user {user} "
                f"--dns-host {dns_host}"
            )
        print(
            f"{host} is running but is not set up. Fix the problem above, then run:\n"
            + "".join(f"  {command}\n" for command in commands)
            + (f"Run the second command once {dns_host} resolves. " if dns_host else "")
            + "If `servers add` says the shared files were left unchanged, also "
            f"run `dallinger docker-ssh servers upgrade --host {host} --yes`."
        )
        raise


def provision(
    instance_name: str,
    region_name: str,
    instance_type: str,
    storage_in_gb: int,
    key_name: str,
    image_name: str,
    security_group_name: str,
    dns_host: str = None,
):
    prepare_instance(
        instance_name,
        region_name,
        instance_type,
        storage_in_gb,
        key_name,
        image_name,
        security_group_name,
        dns_host,
        callback=prepare_docker_experiment_setup,
    )


def _get_instance_row_from(
    region_name,
    instance_name=None,
    public_dns_name=None,
    filter_by="state == 'running'",
):
    if (instance_name is None) == (public_dns_name is None):
        raise click.ClickException("Provide exactly one of `--name` or `--dns`.")

    instances_df = get_instances(region_name)
    if filter_by is not None:
        instances_df = instances_df.query(filter_by)
    if instance_name is not None:
        selected_instances = instances_df.query(f"name == '{instance_name}'")
    else:
        selected_instances = instances_df.query(
            f"public_dns_name == '{public_dns_name}'"
        )
    if len(selected_instances) == 0:
        lookup = (
            f"name '{instance_name}'"
            if instance_name is not None
            else f"public DNS '{public_dns_name}'"
        )
        if region_name is not None:
            region_hint = f"region '{region_name}'"
        else:
            default_region = _resolve_default_region_name()
            region_hint = (
                f"default AWS region '{default_region}' " "(no `--region` was provided)"
            )
        error_prefix = click.style("✖", fg="red")
        raise click.ClickException(
            f"{error_prefix} No EC2 instance found for {lookup} in {region_hint}.\n"
            "Tip: Check the instance name/DNS and region. You can list instances with "
            "`dallinger ec2 list instances --region <region>`."
        )
    elif len(selected_instances) > 1:
        raise Exception("Multiple running instances found")
    else:
        return selected_instances.iloc[0]


def _get_instance_id_from(
    region_name,
    instance_name=None,
    public_dns_name=None,
    filter_by="state == 'running'",
):
    return _get_instance_row_from(
        region_name, instance_name, public_dns_name, filter_by
    )["instance_id"]


def wait_for_instance_state_change(region, name, state, n_tries=12, wait=10):
    with yaspin(
        text=f"Waiting for the instance to change to state '{state}': ", color="yellow"
    ) as sp:
        for _ in range(n_tries):
            instance_row = _get_instance_row_from(
                region_name=region,
                instance_name=name,
                filter_by=None,
            )
            if instance_row["state"] == state:
                break
            time.sleep(wait)
        if instance_row["state"] != state:
            sp.fail("❌")
            raise Exception(
                f"Instance '{name}' did not change to state '{state}' after {n_tries * wait} seconds"
            )
        else:
            sp.text = f"Instance '{name}' changed to state '{state}'"
            sp.ok("✅")
        return instance_row


def get_instance_id_from_url(region_name, public_dns_name):
    return _get_instance_id_from(region_name, public_dns_name=public_dns_name)


def get_instance_id_from_name(region_name, instance_name):
    return _get_instance_id_from(region_name, instance_name=instance_name)


def restart(region_name, instance_id):
    logger.info(f"Restarting {instance_id}...")
    get_ec2_client(region_name).reboot_instances(InstanceIds=[instance_id])
    logger.info(f"Restarting of {instance_id} complete!")


def start(region_name, instance_id):
    logger.info(f"Starting {instance_id}...")
    get_ec2_client(region_name).start_instances(InstanceIds=[instance_id])
    logger.info(f"Starting of {instance_id} complete!")


def stop(region_name, instance_id):
    logger.warning(
        f"Instance {instance_id} will be stopped. You will still be charged for the storage."
    )
    logger.info(f"Stopping {instance_id}...")
    get_ec2_client(region_name).stop_instances(InstanceIds=[instance_id])
    logger.info(f"Stopping of {instance_id} complete!")


def saved_server(instance_id):
    """Return a server entry that provisioning saved for ``instance_id``, or ``{}``."""
    return next(
        (
            info
            for info in get_configured_hosts().values()
            if instance_id and info.get("ec2_instance_id") == instance_id
        ),
        {},
    )


def route_53_dns_host(server_info):
    """Return the saved DNS host of a server entry, unless it is a nip.io name.

    Provisioning without ``--dns-host`` saves ``<ip>.nip.io``, which has no
    Route 53 records to manage.
    """
    dns_host = server_info.get("dns_host")
    if dns_host and not dns_host.lower().endswith(".nip.io"):
        return dns_host
    return None


def has_route_53_zone(dns_host):
    """Whether ``dns_host`` is in a Route 53 hosted zone of this account."""
    return bool(filter_zone_ids(get_domain(dns_host), get_53_client()))


def teardown(region_name, instance_id, public_dns_name, dns_host):
    """Delete an instance's DNS records, terminate it, and remove its server entries.

    An entry belongs to the instance if it has the instance id saved at
    provisioning or, for entries without one (older versions), if it is named
    after ``public_dns_name`` or ``dns_host``. Without ``dns_host``, the DNS
    host saved in an entry with this instance id is used. Only DNS records
    pointing at ``public_dns_name`` are deleted. A Route 53 failure is reported
    as a warning so that the instance is still terminated.
    """
    hosts = get_configured_hosts()
    owned = [
        host
        for host, info in hosts.items()
        if (
            info["ec2_instance_id"] == instance_id
            if info.get("ec2_instance_id")
            else host in (public_dns_name, dns_host)
        )
    ]
    saved = [
        route_53_dns_host(hosts[h]) for h in owned if hosts[h].get("ec2_instance_id")
    ]
    dns_host = dns_host or next(filter(None, saved), None)
    try:
        remove_dns_record(dns_host, remove_dallinger_host=False, target=public_dns_name)
    except (BotoCoreError, ClientError, click.ClickException) as e:
        logger.warning(
            f"Could not delete the Route 53 records for {dns_host} ({e}). Delete "
            f"{dns_host} and *.{dns_host} by hand if they point at {public_dns_name}."
        )
    logger.info(f"Terminating {instance_id} ({public_dns_name})...")
    get_ec2_client(region_name).terminate_instances(InstanceIds=[instance_id])
    for host in owned:
        dallinger_remove_host(host)
    logger.info(f"Termination of {instance_id} complete!")
