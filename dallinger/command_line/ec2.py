import os

import click

from .lib.ec2 import (
    DEFAULT_UBUNTU_24_04_AMI_SSM_PARAMETER,
    _get_instance_id_from,
    _get_instance_row_from,
    check_server_pem_matches_key_pair,
    create_dns_records,
    get_instances,
    get_pem_path,
    has_route_53_zone,
    increase_storage,
    list_instance_types,
    list_instances,
    list_regions,
    provision,
    remove_instance_dns_records,
    restart,
    route_53_dns_host,
    saved_server,
    start,
    stop,
    teardown,
    wait_for_instance_state_change,
)


def _validate_instance_selector(name, dns):
    if (name is None) == (dns is None):
        raise click.UsageError("Provide exactly one of `--name` or `--dns`.")


def get_config(strict=True):
    from dallinger.config import get_config

    config = get_config()
    config.load(strict=strict)
    return config


def get_instance_config():
    config = get_config(False)
    return {
        "pem": config.get("ec2_default_pem", "dallinger"),
        "security_group_name": config.get("ec2_default_security_group", "dallinger"),
    }


# EC2 on demand provisioning
@click.group("ec2")
@click.pass_context
def ec2(ctx):
    """Sub-commands for provisioning on AWS EC2"""
    # Load the config with strict=False so that experimenters don't encounter an error
    # if they are using custom config parameters that are not supported in Dallinger
    get_config(strict=False)


@ec2.group("ssh")
@click.pass_context
def ssh(ctx):
    """Sub-commands to ssh to EC2 instances"""
    pass


@ssh.command("web")
@click.option("--app", required=True, help="App name")
@click.option(
    "--dns",
    required=True,
    help="Public DNS of the EC2 instance (AWS hostname), e.g. ec2-...compute.amazonaws.com",
)
def ssh__web(app, dns):
    """SSH to a web app container on an EC2 instance"""
    cfg = get_instance_config()
    keyname = cfg.get("pem")
    try:
        pem_path = get_pem_path(keyname)
    except FileNotFoundError as err:
        raise click.UsageError(str(err))
    pem_opt = f"-i {pem_path}"
    command = f"ssh {pem_opt} {dns} -t 'docker exec -it {app}-web-1 bash'"
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
@click.pass_context
def list__instances(ctx, region, running, stopped, terminated):
    """List your EC2 instances (with filtering)"""
    filtered_states = []
    if running:
        filtered_states.append("running")
    if stopped:
        filtered_states.append("stopped")
    if terminated:
        filtered_states.append("terminated")
    cfg = get_instance_config()
    pem = cfg.get("pem")
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
    "--image_name",
    default=DEFAULT_UBUNTU_24_04_AMI_SSM_PARAMETER,
    help=(
        "Image name, AMI id, or SSM parameter. Default uses Canonical's "
        "Ubuntu 24.04 SSM parameter."
    ),
)
@click.option(
    "--security_group_name",
    default=None,
    help="Security group name; if not specified, defaults to the `security_group_name` config variable, whose default value is 'dallinger'.",
)
@click.option(
    "--dns-host",
    help="Custom DNS host (e.g. myexp.example.com) to create/update in Route53; distinct from --dns (instance public DNS).",
    default=None,
)
@click.pass_context
def ec2__provision(
    ctx, name, region, type, storage, image_name, security_group_name, dns_host
):
    """Provision an EC2 instance for running experiments"""
    config = get_instance_config()
    pem_key = config.get("pem")

    # Local settings that would stop provisioning are checked before an instance boots.
    try:
        check_server_pem_matches_key_pair(pem_key)
    except FileNotFoundError as err:
        raise click.UsageError(str(err))

    dallinger_config = get_config(strict=False)
    if not (
        dallinger_config.get("dashboard_user", None)
        and dallinger_config.get("dashboard_password", None)
    ):
        raise click.UsageError(
            "Set dashboard_user and dashboard_password in ~/.dallingerconfig or "
            "the environment."
        )

    from .docker_ssh import _config_contact_email, _is_email

    # The shared services set up at the end need an email for Let's Encrypt.
    email, source = _config_contact_email()
    if not _is_email(email):
        current = f"; it is {email!r} from {source}" if source else ""
        raise click.UsageError(
            "Set contact_email_on_error in ~/.dallingerconfig or the environment "
            "to a bare email address for Let's Encrypt certificates (not a "
            f"placeholder such as XXX@gmail.com{current}). `dallinger email-test` "
            "sends a test email to it."
        )

    if not security_group_name:
        security_group_name = config.get("security_group_name", security_group_name)
    from .utils import check_valid_subdomain

    check_valid_subdomain("name", name)

    provision(
        instance_name=name,
        region_name=region,
        instance_type=type,
        storage_in_gb=storage,
        key_name=pem_key,
        image_name=image_name,
        security_group_name=security_group_name,
        dns_host=dns_host,
    )


@ec2.command("increase-storage")
@click.option(
    "--dns",
    default=None,
    help="Public DNS of the EC2 instance (AWS hostname). Use this OR --name.",
)
@click.option("--name", default=None, help="Instance ID")
@click.option("--region", default=None, help="Region name")
@click.option("--storage", required=True, type=int, help="Storage in GB")
@click.pass_context
def ec2__increase_storage(ctx, dns, name, region, storage):
    """Increase the disk storage on an EC2 instance"""
    _validate_instance_selector(name, dns)
    instance_row = _get_instance_row_from(
        region_name=region, instance_name=name, public_dns_name=dns
    )
    instance_id = instance_row["instance_id"]
    instance_name = instance_row["name"]
    increase_storage(instance_id, instance_name, storage, region_name=region)


@ec2.command("stop")
@click.option(
    "--dns",
    default=None,
    help="Public DNS of the EC2 instance (AWS hostname). Use this OR --name.",
)
@click.option("--name", default=None, help="Instance ID")
@click.option("--region", default=None, help="Region name")
@click.option(
    "--dns-host",
    help="Custom DNS host (e.g. myexp.example.com) to manage in Route53; distinct from --dns (instance public DNS). Defaults to the DNS host saved when the instance was provisioned.",
    default=None,
)
@click.pass_context
def ec2__stop(ctx, dns, name, region, dns_host):
    """Stop (pause) an existing EC2 instance"""
    _validate_instance_selector(name, dns)
    instance_row = _get_instance_row_from(
        region_name=region, instance_name=name, public_dns_name=dns
    )
    instance_id = instance_row["instance_id"]
    dns_host = dns_host or route_53_dns_host(saved_server(instance_id))
    # Remove old DNS records, but keep the dallinger host
    remove_instance_dns_records(dns_host, instance_row["public_dns_name"])
    stop(region, instance_id)


@ec2.command("start")
@click.option(
    "--dns",
    default=None,
    help="Public DNS of the EC2 instance (AWS hostname). Use this OR --name.",
)
@click.option("--name", default=None, help="Instance ID")
@click.option("--region", default=None, help="Region name")
@click.option(
    "--dns-host",
    help="Custom DNS host (e.g. myexp.example.com) to manage in Route53; distinct from --dns (instance public DNS). Defaults to the DNS host saved when the instance was provisioned.",
    default=None,
)
@click.pass_context
def ec2__start(ctx, dns, name, region, dns_host):
    """Start a stopped EC2 instance"""
    _validate_instance_selector(name, dns)
    from dallinger.command_line.config import get_configured_hosts

    CONFIGURED_HOSTS = get_configured_hosts()
    instance_row = _get_instance_row_from(
        region_name=region,
        instance_name=name,
        public_dns_name=dns,
        filter_by=None,
    )
    name = instance_row["name"]
    instance_row = wait_for_instance_state_change(region, name, "stopped")
    assert instance_row["state"] == "stopped", (
        f"Instance '{name}' is not stopped, but in state '{instance_row['state']}'"
    )
    dns, instance_id, name = (
        instance_row["public_dns_name"],
        instance_row["instance_id"],
        instance_row["name"],
    )
    start(region, instance_id)

    saved = saved_server(instance_id)
    saved_dns_host = route_53_dns_host(saved)
    if not dns_host and saved_dns_host:
        if has_route_53_zone(saved_dns_host):
            dns_host = saved_dns_host
        else:
            print(
                f"Warning: No Route 53 hosted zone found for {saved_dns_host}; "
                "its DNS records were not updated."
            )
    old_dns_host = CONFIGURED_HOSTS.get(dns) or saved
    user = old_dns_host.get("user", "ubuntu")

    instance_row = wait_for_instance_state_change(region, name, "running")

    create_dns_records(dns_host, user, instance_row["public_dns_name"])


@ec2.command("restart")
@click.option(
    "--dns",
    default=None,
    help="Public DNS of the EC2 instance (AWS hostname). Use this OR --name.",
)
@click.option("--name", default=None, help="Instance ID")
@click.option("--region", default=None, help="Region name")
@click.pass_context
def ec2__restart(ctx, dns, name, region):
    """Restart a running EC2 instance"""
    _validate_instance_selector(name, dns)
    instance_id = _get_instance_id_from(
        region_name=region, instance_name=name, public_dns_name=dns
    )
    restart(region, instance_id)


@ec2.command("teardown")
@click.option(
    "--dns",
    default=None,
    help="Public DNS of the EC2 instance (AWS hostname). Use this OR --name.",
)
@click.option("--name", default=None, help="Instance ID")
@click.option("--region", default=None, help="Region name")
@click.option(
    "--dns-host",
    help="Custom DNS host (e.g. myexp.example.com) to manage in Route53; distinct from --dns (instance public DNS).",
    default=None,
)
@click.pass_context
def ec2__teardown(ctx, dns, name, region, dns_host):
    """Teardown an EC2 instance"""
    _validate_instance_selector(name, dns)
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
