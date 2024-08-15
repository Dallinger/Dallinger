import os

import click

from .lib.ec2 import (
    _get_instance_id_from,
    _get_instance_row_from,
    get_instances,
    increase_storage,
    list_instance_types,
    list_instances,
    list_regions,
    provision,
    restart,
    start,
    stop,
    teardown,
)


def get_instance_config():
    from dallinger.config import get_config

    config = get_config()
    if not config.ready:
        config.load()
    return {
        "pem": config.get("ec2_default_pem", "dallinger"),
        "security_group_name": config.get("ec2_default_security_group", "dallinger"),
    }


# EC2 on demand provisioning
@click.group("ec2")
@click.pass_context
def ec2(ctx):
    """Sub-commands for provisioning on AWS EC2"""
    pass


@ec2.group("ssh")
@click.pass_context
def ssh(ctx):
    """Sub-commands to ssh to EC2 instances"""
    pass


@ssh.command("web")
@click.option("--app", required=True, help="App name")
@click.option("--dns", required=True, help="Server name")
def ssh__web(app, dns):
    """SSH to a web app container on an EC2 instance"""
    command = f"ssh {dns} -t 'docker exec -it {app}-web-1 bash'"
    os.system(command)


@ec2.group("list")
@click.pass_context
def list(ctx):
    """Sub-commands for listing EC2 entities"""
    pass


@list.command("instances")
@click.option("--region", default=None, help="Region name")
@click.option("--running", is_flag=True, help="List running instances")
@click.option("--stopped", is_flag=True, help="List stopped instances")
@click.option("--terminated", is_flag=True, help="List terminated instances")
@click.option("--pem", default=None, help="Name of the PEM file to use")
@click.pass_context
def list__instances(ctx, region, running, stopped, terminated, pem):
    """List your EC2 instances (with filtering)"""
    filtered_states = []
    if running:
        filtered_states.append("running")
    if stopped:
        filtered_states.append("stopped")
    if terminated:
        filtered_states.append("terminated")
    list_instances(region, filtered_states=filtered_states, pem=pem)


@list.command("regions")
@click.pass_context
def list__regions(ctx):
    """List available EC2 regions"""
    list_regions()


@list.command("instance_types")
@click.option("--region", default=None, help="Region name")
@click.pass_context
def list__instance_types(ctx, region):
    """List available EC2 instance types in your region"""
    list_instance_types(region)


@ec2.command("provision")
@click.option("--name", required=True, help="Instance name")
@click.option("--region", default=None, help="Region name")
@click.option("--type", default="m5.xlarge", help="Instance type")
@click.option("--storage", default=32, type=int, help="Storage in GB; default is 32 GB")
@click.option(
    "--pem", default="dallinger", help="PEM file name; default is dallinger.pem"
)
@click.option(
    "--image_name",
    default="ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-20230516",
    help="Image name; default is Ubuntu 22.04",
)
@click.option(
    "--security_group_name",
    default="dallinger",
    help="Security group name; default is dallinger",
)
@click.option(
    "--dns-host",
    help="DNS name to use. Must resolve all its subdomains to the IP address specified as ssh host",
    default=None,
)
@click.pass_context
def ec2__provision(
    ctx, name, region, type, storage, pem, image_name, security_group_name, dns_host
):
    """Provision an EC2 instance for running experiments"""
    config = get_instance_config()
    pem = config.get("pem", pem)
    security_group_name = config.get("security_group_name", security_group_name)

    provision(
        instance_name=name,
        region_name=region,
        instance_type=type,
        storage_in_gb=storage,
        key_name=pem,
        image_name=image_name,
        security_group_name=security_group_name,
        dns_host=dns_host,
    )


@ec2.command("increase-storage")
@click.option("--dns", default=None, help="Public DNS name")
@click.option("--name", default=None, help="Instance ID")
@click.option("--region", default=None, help="Region name")
@click.option("--storage", required=True, type=int, help="Storage in GB")
@click.pass_context
def ec2__increase_storage(ctx, dns, name, region, storage):
    """Increase the disk storage on an EC2 instance"""
    instance_row = _get_instance_row_from(
        region_name=region, instance_name=name, public_dns_name=dns
    )
    instance_id = instance_row["instance_id"]
    instance_name = instance_row["name"]
    increase_storage(instance_id, instance_name, storage, region_name=region)


@ec2.command("stop")
@click.option("--dns", default=None, help="Public DNS name")
@click.option("--name", default=None, help="Instance ID")
@click.option("--region", default=None, help="Region name")
@click.pass_context
def ec2__stop(ctx, dns, name, region):
    """Stop (pause) an existing EC2 instance"""
    instance_id = _get_instance_id_from(
        region_name=region, instance_name=name, public_dns_name=dns
    )
    stop(region, instance_id)


@ec2.command("start")
@click.option("--dns", default=None, help="Public DNS name")
@click.option("--name", default=None, help="Instance ID")
@click.option("--region", default=None, help="Region name")
@click.pass_context
def ec2__start(ctx, dns, name, region):
    """Start a stopped EC2 instance"""
    instance_id = _get_instance_id_from(
        region_name=region,
        instance_name=name,
        public_dns_name=dns,
        filter_by="state == 'stopped'",
    )
    start(region, instance_id)


@ec2.command("restart")
@click.option("--dns", default=None, help="Public DNS name")
@click.option("--name", default=None, help="Instance ID")
@click.option("--region", default=None, help="Region name")
@click.pass_context
def ec2__restart(ctx, dns, name, region):
    """Restart a running EC2 instance"""
    instance_id = _get_instance_id_from(
        region_name=region, instance_name=name, public_dns_name=dns
    )
    restart(region, instance_id)


@ec2.command("teardown")
@click.option("--dns", default=None, help="Public DNS name")
@click.option("--name", default=None, help="Instance ID")
@click.option("--region", default=None, help="Region name")
@click.option(
    "--dns-host",
    help="DNS name to use. Must resolve all its subdomains to the IP address specified as ssh host",
    default=None,
)
@click.pass_context
def ec2__teardown(ctx, dns, name, region, dns_host):
    """Teardown an EC2 instance"""
    instance_id = _get_instance_id_from(
        region_name=region, instance_name=name, public_dns_name=dns
    )
    if dns is None:
        dns = (
            get_instances(region)
            .query(f"instance_id == '{instance_id}'")
            .iloc[0]["public_dns_name"]
        )
    teardown(region, instance_id, dns, dns_host)
