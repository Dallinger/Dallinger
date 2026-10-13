"""Launch docker-ssh apps from inside the server, then check the public URL.

A new Cloudflare tunnel can take several minutes to accept its connector,
and a new Caddy site can wait on DNS or a TLS certificate. When ``/launch``
went through the public URL, a slow tunnel left a running app that was never
launched. Here the ``web`` container POSTs ``/launch`` to the app's front door
over the app's Docker network, so the launch only waits for the app itself.

The request carries the public ``Host`` and ``X-Forwarded-Proto``. The front
door trusts forwarded headers from private networks, Caddy passes ``Host``
through, and the app runs behind ``ProxyFix``, so the app computes its public
base URL and recruitment links as if the request had come from outside.

Public reachability is checked after the launch and only warns, because the
app is already launched by then. Nothing here prints tokens or passwords.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from shlex import quote
from urllib.parse import urlsplit

import click
import requests

from dallinger.deployment import handle_launch_data
from dallinger.utils import END, RED, print_bold

from .app_manifest import INGRESS_CLOUDFLARE

FRONT_DOOR_LAUNCH_URL = "http://frontdoor:5000/launch"
PUBLIC_CHECK_TIMEOUT = 420
PUBLIC_CHECK_INTERVAL = 10
PROGRESS_INTERVAL = 60
REQUEST_TIMEOUT = 10
CLOUDFLARE_TUNNEL_PENDING_STATUS = 530


@dataclass(frozen=True)
class LaunchTarget:
    """A deployed docker-ssh app, and how an operator reaches it."""

    app: str
    server: str
    public_origin: str
    ingress: str
    ssh_prefix: str
    verify: bool = True

    @property
    def compose_file(self):
        return f"~/dallinger/{self.app}/docker-compose.yml"

    def ssh(self, remote_command):
        """Return a local shell command that runs ``remote_command`` on the server."""
        return f"{self.ssh_prefix} {quote(remote_command)}"

    @property
    def check_command(self):
        return (
            f"curl -sS -o /dev/null -w '%{{http_code}}\\n' {self.public_origin}/health"
        )

    @property
    def destroy_command(self):
        return f"dallinger docker-ssh destroy --server {self.server} --app {self.app}"


class _CommandResponse:
    """The parts of ``requests.Response`` that ``handle_launch_data`` reads."""

    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text
        self.ok = status_code < 400

    def json(self):
        return json.loads(self.text)


def internal_launch_command(target):
    """Return the server-side command that POSTs ``/launch`` to the front door."""
    # Double quotes keep the printed retry command readable once it is
    # single-quoted for ssh. App names and hostnames are DNS-safe.
    origin = urlsplit(target.public_origin)
    return (
        f"docker compose -f {target.compose_file} exec -T web "
        "curl -sS -X POST "
        f'-H "Host: {origin.netloc}" '
        f'-H "X-Forwarded-Proto: {origin.scheme}" '
        f'-w "\\n%{{http_code}}" {FRONT_DOOR_LAUNCH_URL}'
    )


def launch_from_server(executor, target):
    """POST ``/launch`` from inside the app's network and return the launch data.

    Keeps ``handle_launch_data``'s retries while the ``web`` container starts.
    If the launch fails, prints how to retry or remove the app and raises
    ``click.ClickException``.
    """
    command = internal_launch_command(target)

    def post():
        status, stdout, stderr = executor.run_with_status(command)
        body, _, code = stdout.rpartition("\n")
        # curl writes 000 when it got no HTTP response at all.
        if status or not code.isdigit() or code == "000":
            detail = (stderr or stdout).strip() or f"exit status {status}"
            raise requests.exceptions.ConnectionError(detail)
        return _CommandResponse(int(code), body)

    try:
        return handle_launch_data(
            f"{FRONT_DOOR_LAUNCH_URL} inside {target.app}",
            print,
            context="ssh",
            post=post,
        )
    except click.ClickException as exc:
        print_bold("Check the web container logs:")
        print(target.ssh(f"docker compose -f {target.compose_file} logs web"))
        print_bold("Retry the launch:")
        print(target.ssh(command))
        print_bold("Or remove the app:")
        print(target.destroy_command)
        raise click.ClickException(
            f"The launch request to {target.app} failed from inside the server. "
            "The app's containers are running, but the experiment was not "
            "launched and recruitment has not started."
        ) from exc


def wait_for_public_url(
    executor,
    target,
    timeout=PUBLIC_CHECK_TIMEOUT,
    interval=PUBLIC_CHECK_INTERVAL,
):
    """Wait until the app answers on its public URL; warn if it never does.

    Returns True when the public health check succeeds, and False after
    printing a warning when it is still failing after ``timeout`` seconds.
    """
    url = f"{target.public_origin}/health"
    minutes = max(1, round(timeout / 60))
    if target.ingress == INGRESS_CLOUDFLARE:
        print(
            "Waiting for the Cloudflare tunnel to connect "
            f"(up to {minutes} min; a new tunnel can take several minutes)."
        )
    else:
        print(f"Waiting for {target.public_origin} to become reachable (up to {minutes} min).")

    started = time.monotonic()
    next_report = PROGRESS_INTERVAL
    while True:
        status, detail = _probe(url, target.verify)
        if status is not None and status < 400:
            print(f"{target.public_origin} is reachable.")
            return True
        elapsed = time.monotonic() - started
        if elapsed + interval > timeout:
            break
        if elapsed >= next_report:
            print(f"Still waiting after {int(elapsed)} s: {_describe(status, detail)}")
            next_report += PROGRESS_INTERVAL
        time.sleep(interval)

    _warn_unreachable(executor, target, status, detail, minutes)
    return False


def _probe(url, verify):
    """GET ``url`` once; return ``(status_code or None, detail)``."""
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT, verify=verify)
    except requests.exceptions.RequestException as exc:
        return None, str(exc)
    return response.status_code, response.text


def _describe(status, detail):
    if status is None:
        return detail.splitlines()[0] if detail else "no response"
    return f"HTTP {status}"


def _tunnel_pending(status, detail):
    """True for Cloudflare's 530 / error 1033 answer for an unconnected tunnel."""
    return status == CLOUDFLARE_TUNNEL_PENDING_STATUS or "1033" in (detail or "")


def _connector_reports_tunnel_not_found(executor, target):
    """Search recent ``cloudflared`` logs without printing them."""
    logs = executor.run(
        f"docker compose -f {target.compose_file} logs --tail 200 cloudflared 2>&1",
        raise_=False,
    )
    return "tunnel not found" in (logs or "").lower()


def _warn_unreachable(executor, target, status, detail, minutes):
    cloudflare = target.ingress == INGRESS_CLOUDFLARE
    not_found = cloudflare and _connector_reports_tunnel_not_found(executor, target)
    print(
        f"{RED}Warning:{END} {target.public_origin} was still not reachable after "
        f"{minutes} min (last result: {_describe(status, detail)})."
    )
    if cloudflare and (not_found or _tunnel_pending(status, detail)):
        print(
            "Cloudflare has not activated the new tunnel yet"
            + (" (cloudflared logs say 'Tunnel not found')" if not_found else "")
            + ". The app is running and launched, and participants can reach "
            "it once the tunnel connects."
        )
    elif cloudflare:
        print(
            "The app is running and launched, but the Cloudflare tunnel is "
            "not serving it yet."
        )
    else:
        print(
            "The app is running and launched. Caddy may still be getting a "
            "TLS certificate, or DNS may not point at the server yet."
        )
    print_bold("Check again later (expect 200):")
    print(target.check_command)
    if cloudflare:
        print_bold("Inspect the tunnel connector logs:")
        print(target.ssh(f"docker compose -f {target.compose_file} logs cloudflared"))
    print_bold("To remove the app:")
    print(target.destroy_command)
