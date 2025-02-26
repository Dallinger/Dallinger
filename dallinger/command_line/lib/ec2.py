import base64
import logging
import os.path
import struct
import subprocess
import sys
import time
from datetime import datetime
from typing import Callable

import boto3
import click
import pandas as pd
import paramiko
import requests
from botocore.exceptions import ClientError
from paramiko.util import deflate_long
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_fixed
from tqdm import tqdm
from yaspin import yaspin

from ..config import remove_host as dallinger_remove_host
from ..config import store_host as dallinger_store_host
from ..docker_ssh import Executor
from ..docker_ssh import prepare_server as dallinger_prepare_server

logger = logging.getLogger(__name__)


def get_keys(region_name=None):
    from dallinger.config import get_config

    config = get_config()
    if not config.ready:
        config.load(strict=False)
    keys = {}
    # If keys are not set let boto get them from ~/.aws/config or other standard places
    if config.get("aws_access_key_id"):
        keys = {
            "aws_access_key_id": config.get("aws_access_key_id"),
            "aws_secret_access_key": config.get("aws_secret_access_key"),
            "region_name": region_name or config.get("aws_region", "us-east-1"),
        }
    return keys


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


def get_ec2_client(region_name=None):
    return boto3.client("ec2", **get_keys(region_name))


def get_53_client():
    return boto3.client("route53", **get_keys())


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
    response = requests.get(
        "https://ec2.shop",
        params={
            "filter": ",".join(instance_types),
            "region": region_name,
        },
        headers={
            "accept": "json",
        },
    )
    if response.status_code != 200:
        print(f"Failed to get details for {instance_types} in {region_name}")
        return None

    price_df = pd.DataFrame(response.json()["Prices"])

    if len(price_df) != len(instance_types):
        print(f"Failed to get all details for {instance_types} in {region_name}")
    return price_df


def get_instances(region_name):
    reservations = get_ec2_client(region_name).describe_instances()["Reservations"]
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

    return pd.DataFrame(instances)


def get_all_instances(region_name=None):
    if region_name is None:
        logger.warning("Listing instances in all regions...")
        instance_dfs = []
        all_regions = get_ec2_client().describe_regions()["Regions"]
        pb = tqdm(all_regions, total=len(all_regions))
        for region in pb:
            pb.set_description("Retrieving instances in " + region["RegionName"])
            instance_dfs.append(get_instances(region["RegionName"]))
        instance_df = pd.concat(instance_dfs)
    else:
        instance_df = get_instances(region_name)
    if len(instance_df) == 0:
        return instance_df
    with yaspin(text="Getting instance details..."):
        instance_details = instance_df.groupby(["instance_type", "region"]).apply(
            lambda x: get_instance_details(
                x["instance_type"].unique(), x["region"].unique()
            )
        )
        instance_details = instance_details.reset_index()
        instance_details = instance_details[
            ["instance_type", "region", "Memory", "VCPUS", "Cost"]
        ]
    instance_df = instance_df.merge(
        instance_details, on=["instance_type", "region"], how="left"
    )
    instance_df["Cost"] = instance_df["Cost"] * instance_df["uptime"] / (60**2)
    instance_df.sort_values("Cost", inplace=True)
    instance_df["Cost"] = instance_df["Cost"].apply(lambda x: f"${int(x)}")
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
    pb = tqdm()
    response = ec2.describe_instance_types()
    instance_types = response["InstanceTypes"]
    pb.update(len(instance_types))
    while "NextToken" in response:
        response = ec2.describe_instance_types(NextToken=response["NextToken"])
        instance_types += response["InstanceTypes"]
        pb.update(len(instance_types))

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


def get_pem_path(key_name):
    return os.path.join(os.path.expanduser("~"), f"{key_name}.pem")


def register_key_pair(ec2, key_name):
    pem_loc = get_pem_path(key_name)
    key = paramiko.RSAKey.from_private_key_file(pem_loc)

    output = b""
    parts = [
        b"ssh-rsa",
        deflate_long(key.public_numbers.e),
        deflate_long(key.public_numbers.n),
    ]
    for part in parts:
        output += struct.pack(">I", len(part)) + part
    public_key = b"ssh-rsa " + base64.b64encode(output) + b"\n"
    ec2.import_key_pair(KeyName=key_name, PublicKeyMaterial=public_key)


def add_key_to_ssh_agent(key_name):
    pem_loc = get_pem_path(key_name)
    subprocess.run(["ssh-add", pem_loc])


def wait_for_instance(host, user="ubuntu", n_tries=10):
    @retry(
        stop=stop_after_attempt(n_tries),
        wait=wait_fixed(5),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _wait_for_instance():
        return Executor(host, user)

    return _wait_for_instance()


def get_image_id(ec2, image_name):
    response = ec2.describe_images(
        IncludeDeprecated=False,
        Filters=[
            {
                "Name": "name",
                "Values": [image_name],
            },
        ],
    )
    assert len(response["Images"]) == 1
    return response["Images"][0]["ImageId"]


def setup_ssh_keys(ec2, key_name, region_name=None):
    try:
        ec2.describe_key_pairs(KeyNames=[key_name])
    except ClientError:
        print(f"Key pair {key_name} not found in region {region_name}. Creating...")
        register_key_pair(ec2, key_name)

    add_key_to_ssh_agent(key_name)


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

    print(f"Waiting for {instance_name} to be ready...")
    waiter = get_ec2_client(region_name).get_waiter("instance_running")
    waiter.wait(InstanceIds=[instance_id])
    print(f"{instance_name} is ready!")
    return instance_id


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
    # Set sufficient storage
    print(f"Increasing storage of {instance_name} to {storage_in_gb} GB...")

    # get volume id
    response = ec2.describe_instances(InstanceIds=[instance_id])
    instance = response["Reservations"][0]["Instances"][0]
    volume_id = instance["BlockDeviceMappings"][0]["Ebs"]["VolumeId"]

    # Get volume size
    volume_size = get_volume_size(ec2, volume_id)

    assert (
        volume_size < storage_in_gb
    ), f"Volume size {volume_size} GB is already greater than {storage_in_gb} GB"

    # increase volume size
    ec2.modify_volume(
        VolumeId=volume_id,
        Size=storage_in_gb,
    )

    print(f"Waiting for {instance_name} to be ready...")
    waiter = ec2.get_waiter("volume_in_use")
    waiter.wait(VolumeIds=[volume_id])
    print(f"{instance_name} is ready!")

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

    print(executor.run("df -h"))
    print(executor.run("lsblk"))
    time.sleep(20)
    executor.run(f"sudo growpart /dev/{selected_volume} 1")

    time.sleep(10)
    executor.run(f"sudo resize2fs /dev/{selected_partition}")

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


def remove_dns_records(zone_id, dns_host, route_53=None, confirm=False):
    if route_53 is None:
        route_53 = get_53_client()
    records = route_53.list_resource_record_sets(HostedZoneId=zone_id)
    filtered_records = [
        record for record in records["ResourceRecordSets"] if dns_host in record["Name"]
    ]

    if len(filtered_records) > 0:
        used_host = filtered_records[0]["ResourceRecords"][0]["Value"]
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
    if route_53 is None:
        route_53 = get_53_client()

    filtered_hosts = filter_zone_ids(get_domain(dns_host), route_53)
    hosted_zone_id = filtered_hosts[0]
    response = route_53.change_resource_record_sets(
        HostedZoneId=hosted_zone_id,
        ChangeBatch={
            "Changes": [
                {
                    "Action": "CREATE",
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

    with yaspin(
        text="Waiting for DNS record to be set up (can take up to two minutes)..."
    ):
        change_id = response["ChangeInfo"]["Id"]
        n_tries = 24
        wait = 5
        timeout = n_tries * wait
        for _ in range(n_tries):
            response = route_53.get_change(Id=change_id)
            if response["ChangeInfo"]["Status"] == "INSYNC":
                break
            time.sleep(wait)
        else:
            raise Exception(f"DNS record setup timed out after {timeout} seconds.")

    is_wild_card = dns_host.startswith("*.")
    full_domain = dns_host.replace("*.", "")
    test_host = f"test.{full_domain}" if is_wild_card else dns_host

    dns_executor = Executor(test_host, user)
    print("DNS record set up!")
    return dns_executor


def prepare_instance(
    instance_name: str,
    region_name: str,
    instance_type: str,
    storage_in_gb: int,
    key_name: str,
    image_name: str,
    security_group_name: str,
    dns_host: str = None,
    callback: Callable[[str, str, str, Executor], None] = None,
):
    instance_df = get_all_instances(region_name)
    assert (
        len(instance_df) == 0
        or len(instance_df.query(f"name == '{instance_name}' and state=='running'"))
        == 0
    ), f"Instance {instance_name} already exists!"

    if dns_host is not None:
        route_53 = get_53_client()
        assert (
            len(dns_host.split(".")) == 3
        ), "DNS host must be in the format subdomain.domain.tld"
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
    security_group_id = get_security_group_id(security_group_name, region_name)
    print(f"Provisioning {instance_name} on {region_name}...")
    image_id = get_image_id(ec2, image_name)

    setup_ssh_keys(ec2, key_name, region_name)
    instance_id = boot_instance(
        ec2, image_id, instance_type, key_name, instance_name, region_name
    )

    set_security_group(
        ec2, instance_id, instance_name, security_group_id, security_group_name
    )

    host, user, ip_address, executor = increase_storage(
        instance_id, instance_name, storage_in_gb, ec2
    )
    if callback is not None:
        callback(host, user, ip_address, executor, dns_host, instance_name)

    duration = time.time() - start
    print(
        f"Provisioning complete! Time taken: {duration}. {instance_name} is ready at {host}"
    )


def create_dns_records(dns_host, user, host):
    if dns_host is not None:
        create_dns_record(dns_host, user, host)
        create_dns_record("*." + dns_host, user, host)


def remove_dns_record(dns_host, remove_dallinger_host=True):
    if dns_host is not None:
        route_53 = get_53_client()
        filtered_ids = filter_zone_ids(get_domain(dns_host), route_53)
        remove_dns_records(filtered_ids[0], dns_host, route_53)
        if remove_dallinger_host:
            dallinger_remove_host(dns_host)


def prepare_docker_experiment_setup(
    host, user, ip_address, executor, dns_host=None, instance_name=None
):
    from dallinger.config import get_config

    config = get_config()
    if not config.ready:
        config.load()
    assert config.get("dashboard_user") and config.get(
        "dashboard_password"
    ), "dashboard_user and dashboard_password must be set in ~/.dallingerconfig"

    dallinger_prepare_server(host, user)

    create_dns_records(dns_host, user, host)

    dallinger_store_host(dict(host=host, user=user))
    dallinger_store_host(dict(host=dns_host, user=user))
    print("Host registered in dallinger")


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
    instances_df = get_instances(region_name)
    if filter_by is not None:
        instances_df = instances_df.query(filter_by)

    assert (
        sum([var is None for var in [instance_name, public_dns_name]]) == 1
    ), "Provide either instance_name or public_dns"
    if instance_name is not None:
        selected_instances = instances_df.query(f"name == '{instance_name}'")
    else:
        selected_instances = instances_df.query(
            f"public_dns_name == '{public_dns_name}'"
        )
    if len(selected_instances) == 0:
        raise Exception("No instances found")
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


def teardown(region_name, instance_id, public_dns_name, dns_host):
    logger.info(f"Terminating {instance_id} ({public_dns_name})...")
    get_ec2_client(region_name).terminate_instances(InstanceIds=[instance_id])
    dallinger_remove_host(public_dns_name)
    remove_dns_record(dns_host, remove_dallinger_host=True)
    logger.info(f"Termination of {instance_id} complete!")
