"""Check a docker-ssh app's public URL, then launch it from inside the server.

A new Cloudflare tunnel can take several minutes to accept its connector,
and a new Caddy site can wait on DNS or a TLS certificate. ``/launch`` opens
recruitment, so the deploy first waits, for a bounded time, until the public
URL answers. Participants are then not sent to a Cloudflare error page. If the
wait times out, the deploy stops without launching and prints the command
that launches the app once its URL works.

The launch itself does not go through the public URL. The ``web`` container
POSTs ``/launch`` to the app's front door over the app's Docker network,
using the container's own Python, with the public ``Host`` and
``X-Forwarded-Proto``. The front door trusts forwarded headers from private
networks, Caddy passes ``Host`` through, and the app runs behind ``ProxyFix``,
so the app computes its public base URL and recruitment links as if the
request had come from outside.

``/launch`` is not idempotent: it can open recruitment on MTurk or Prolific
and then fail in a later step, and a gateway error can follow a request the
app already accepted. So the launch is sent again only when no HTTP response
came back at all (the ``web`` container or front door was not up yet). Any
HTTP response, or a request timeout, ends the launch: success on 2xx with a
JSON body, otherwise an error that says recruitment may have started.
Nothing here prints tokens or passwords.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from shlex import quote
from urllib.parse import urlsplit

import click
import requests

from dallinger.deployment import handle_launch_data
from dallinger.utils import print_bold

from .app_manifest import INGRESS_CLOUDFLARE

FRONT_DOOR_LAUNCH_URL = "http://frontdoor:5000/launch"
# /launch can be slow (database setup, recruiter API calls).
LAUNCH_REQUEST_TIMEOUT = 300
PUBLIC_CHECK_TIMEOUT = 420
PUBLIC_CHECK_INTERVAL = 10
PROGRESS_INTERVAL = 60
REQUEST_TIMEOUT = 10
CLOUDFLARE_TUNNEL_PENDING_STATUS = 530
CLOUDFLARE_TUNNEL_PENDING_PATTERN = re.compile(r"error(?: code:)? 1033\b", re.I)
# Runs inside the web container. It prints one JSON line for any HTTP
# response or a timeout, and fails with a traceback when it could not connect.
LAUNCH_SCRIPT = """\
import json, sys, urllib.error, urllib.request
url, host, proto, timeout = sys.argv[1:]
headers = {"Host": host, "X-Forwarded-Proto": proto}
request = urllib.request.Request(url, data=b"", method="POST", headers=headers)
try:
    with urllib.request.urlopen(request, timeout=float(timeout)) as response:
        status, body = response.status, response.read()
except urllib.error.HTTPError as error:
    status, body = error.code, error.read()
except TimeoutError as error:
    print(json.dumps({"timeout": str(error)}))
    sys.exit(1)
print(json.dumps({"status": status, "body": body.decode("utf-8", "replace")}))
"""
# Images without a ``python3`` command still have ``python``.
PYTHON_FALLBACK = 'if command -v python3 >/dev/null; then exec python3 "$@"; fi; exec python "$@"'


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

    @property
    def health_url(self):
        return f"{self.public_origin}/health"

    def ssh(self, remote_command):
        """Return a local shell command that runs ``remote_command`` on the server."""
        return f"{self.ssh_prefix} {quote(remote_command)}"

    @property
    def check_command(self):
        return f"curl -sS -o /dev/null -w '%{{http_code}}\\n' {self.health_url}"

    @property
    def destroy_command(self):
        return f"dallinger docker-ssh destroy --server {self.server} --app {self.app}"


class _LaunchSent(click.ClickException):
    """``/launch`` reached the app but did not clearly succeed; never resend it."""


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
    origin = urlsplit(target.public_origin)
    args = [
        FRONT_DOOR_LAUNCH_URL,
        origin.netloc,
        origin.scheme,
        str(LAUNCH_REQUEST_TIMEOUT),
    ]
    return (
        f"docker compose -f {target.compose_file} exec -T web "
        f"sh -c {quote(PYTHON_FALLBACK)} sh -c {quote(LAUNCH_SCRIPT)} "
        + " ".join(quote(arg) for arg in args)
    )


def _last_json_line(text):
    """Return the last non-empty line of ``text`` parsed as a JSON object, or None."""
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        parsed = json.loads(lines[-1])
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _is_json(text):
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def _last_line(text):
    lines = [line for line in (text or "").splitlines() if line.strip()]
    return lines[-1].strip() if lines else ""


def launch_from_server(executor, target):
    """POST ``/launch`` from inside the app's network and return the launch data.

    Uses ``handle_launch_data``'s retries only while no HTTP response comes
    back. If the launch fails, prints what to check and run next and raises
    ``click.ClickException``.
    """
    command = internal_launch_command(target)

    def post():
        exit_status, stdout, stderr = executor.run_with_status(command)
        # A reported HTTP response wins over the exit status. Raising a
        # ClickException (not a RequestException) stops handle_launch_data
        # from sending the request again.
        result = _last_json_line(stdout) or {}
        if "timeout" in result:
            raise _LaunchSent(
                f"The launch request to {target.app} did not answer within "
                f"{LAUNCH_REQUEST_TIMEOUT} s and may still be running."
            )
        if "status" in result:
            response = _CommandResponse(int(result["status"]), result.get("body", ""))
            if 200 <= response.status_code < 300 and _is_json(response.text):
                return response
            raise _LaunchSent(
                f"The launch request to {target.app} returned HTTP "
                f"{response.status_code}:\n{response.text}"
            )
        detail = _last_line(stderr) or _last_line(stdout)
        raise requests.exceptions.ConnectionError(
            detail or f"exit status {exit_status}"
        )

    try:
        return handle_launch_data(
            f"{FRONT_DOOR_LAUNCH_URL} inside {target.app}",
            print,
            context="ssh",
            post=post,
        )
    except click.ClickException as exc:
        sent = isinstance(exc, _LaunchSent)
        if sent:
            print(exc.message)
        print_bold("Check the web container logs:")
        print(target.ssh(f"docker compose -f {target.compose_file} logs web"))
        if sent:
            print_bold(
                "Only if the logs show that recruitment did not open, launch again:"
            )
        else:
            print_bold("Retry the launch:")
        print(target.ssh(command))
        print_bold("Or remove the app:")
        print(target.destroy_command)
        if sent:
            raise click.ClickException(
                f"The launch request reached {target.app} but did not succeed. "
                "Recruitment may have started: check the web container logs "
                "before launching again."
            ) from exc
        raise click.ClickException(
            f"The launch request to {target.app} failed from inside the server. "
            "The app's containers are running, but the experiment was not "
            "launched and recruitment has not started."
        ) from exc


def wait_for_public_url(executor, target, timeout=None, interval=None):
    """Wait until the app answers on its public URL, or stop the deploy.

    Waits up to ``timeout`` seconds (default ``PUBLIC_CHECK_TIMEOUT``). If the
    URL never answers, prints why and what to run next, and raises
    ``click.ClickException`` so the experiment is not launched.
    """
    timeout = PUBLIC_CHECK_TIMEOUT if timeout is None else timeout
    interval = PUBLIC_CHECK_INTERVAL if interval is None else interval
    limit = _duration(timeout)
    if target.ingress == INGRESS_CLOUDFLARE:
        print(
            "Waiting for the Cloudflare tunnel to connect before launching "
            f"(up to {limit}; a new tunnel can take several minutes)."
        )
    else:
        print(
            f"Waiting for {target.public_origin} to become reachable before "
            f"launching (up to {limit})."
        )

    started = time.monotonic()
    next_report = PROGRESS_INTERVAL
    while True:
        status, detail = _probe(target.health_url, target.verify)
        if status is not None and status < 400:
            print(f"{target.public_origin} is reachable.")
            return
        elapsed = time.monotonic() - started
        if elapsed + interval > timeout:
            break
        if elapsed >= next_report:
            print(f"Still waiting after {int(elapsed)} s: {_describe(status, detail)}")
            next_report += PROGRESS_INTERVAL
        time.sleep(interval)

    _abort_unreachable(executor, target, status, detail, limit)


def _duration(seconds):
    if seconds < 60:
        return f"{seconds:g} s"
    return f"{round(seconds / 60)} min"


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
    return status == CLOUDFLARE_TUNNEL_PENDING_STATUS or bool(
        CLOUDFLARE_TUNNEL_PENDING_PATTERN.search(detail or "")
    )


def _connector_reports_tunnel_not_found(executor, target):
    """Search recent ``cloudflared`` logs without printing them."""
    logs = executor.run(
        f"docker compose -f {target.compose_file} logs --tail 200 cloudflared 2>&1",
        raise_=False,
    )
    return "tunnel not found" in (logs or "").lower()


def _abort_unreachable(executor, target, status, detail, limit):
    cloudflare = target.ingress == INGRESS_CLOUDFLARE
    not_found = cloudflare and _connector_reports_tunnel_not_found(executor, target)
    print(
        f"{target.public_origin} was still not reachable after {limit} "
        f"(last result: {_describe(status, detail)})."
    )
    if cloudflare and (not_found or _tunnel_pending(status, detail)):
        reason = (
            "Cloudflare has not activated the new tunnel yet"
            + (" (cloudflared logs say 'Tunnel not found')" if not_found else "")
            + "; new tunnels usually start working within minutes."
        )
    elif cloudflare:
        reason = "The Cloudflare tunnel is not serving the app yet."
    else:
        reason = (
            "Caddy may still be getting a TLS certificate, or DNS may not "
            "point at the server yet."
        )
    print_bold("Check the public URL again (expect 200):")
    print(target.check_command)
    if cloudflare:
        print_bold("Inspect the tunnel connector logs:")
        print(target.ssh(f"docker compose -f {target.compose_file} logs cloudflared"))
    print_bold("Once the public URL works, launch the experiment:")
    print(target.ssh(internal_launch_command(target)))
    print_bold("Or remove the app:")
    print(target.destroy_command)
    raise click.ClickException(
        f"{target.public_origin} never answered, so the experiment was not "
        "launched. The app's containers are running, but recruitment has not "
        f"started. {reason}"
    )
