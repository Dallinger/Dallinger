"""Check a docker-ssh app's public URL, then launch it from inside the server.

A new Cloudflare tunnel can take several minutes to accept its connector,
and a new Caddy site can wait on DNS or a TLS certificate. ``/launch`` opens
recruitment, so the deploy first waits, for a bounded time, until the public
URL answers. Participants are then not sent to a Cloudflare error page. If the
wait times out, the deploy stops without launching and prints the command
that launches the app once its URL works.

The launch itself does not go through the public URL. The ``web`` container
POSTs ``/launch`` to the app's front door over the app's Docker network
with ``curl``, sending the public ``Host`` and ``X-Forwarded-Proto``. The web
image must have ``curl`` (the Dallinger and PsyNet images do), and the deploy
checks for it before waiting for the public URL. The front door trusts forwarded headers from private
networks, Caddy passes ``Host`` through, and the app runs behind ``ProxyFix``,
so the app computes its public base URL and recruitment links as if the
request had come from outside.

``/launch`` is not idempotent: it can open recruitment on MTurk or Prolific
and then fail in a later step, and a gateway error can follow a request the
app already accepted. So the launch is sent again only when curl could not
deliver it at all (the ``web`` container or front door was not up yet). Any
HTTP response, a curl timeout, or any other curl failure ends the launch:
success on 2xx with a JSON body, otherwise an error that says recruitment may
have started.
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

from dallinger.deployment import (
    BACKOFF_FACTOR,
    DEFAULT_DELAY,
    MAX_ATTEMPTS,
    handle_launch_data,
)
from dallinger.hibernation import answers_health
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
# curl's "could not resolve" / "could not connect": the request never left.
NOT_SENT_EXIT_STATUSES = frozenset({6, 7})
# ``docker compose exec`` exits 1 with one of these when web is not running.
COMPOSE_EXEC_FAILED_EXIT_STATUS = 1
WEB_NOT_RUNNING_PATTERN = re.compile(
    r"is not running|is restarting|no container|no such container", re.I
)
CURL_TIMEOUT_EXIT_STATUS = 28
CURL_CHECK = "if command -v curl >/dev/null; then echo curl-ok; else echo curl-missing; fi"
# Characters that are not literal inside a local double-quoted string.
_DOUBLE_QUOTE_UNSAFE = re.compile(r'["$`!]|\\[\\"$`\n]|\\$')


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
        return ssh_command(self.ssh_prefix, remote_command)

    def compose_exec(self, command):
        """Return a server-side command that runs ``command`` in the web container."""
        return f"docker compose -f {self.compose_file} exec -T web {command}"

    @property
    def check_command(self):
        return f"curl -sS -o /dev/null -w '%{{http_code}}\\n' {quote(self.health_url)}"

    @property
    def destroy_command(self):
        return f"dallinger docker-ssh destroy --server {self.server} --app {self.app}"


def ssh_command(ssh_prefix, remote_command):
    """Return a local shell command that runs ``remote_command`` over ssh.

    Double quotes keep single-quoted arguments readable when that is safe.
    """
    if _DOUBLE_QUOTE_UNSAFE.search(remote_command):
        return f"{ssh_prefix} {quote(remote_command)}"
    return f'{ssh_prefix} "{remote_command}"'


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
    """Return the server-side command that POSTs ``/launch`` to the front door.

    curl prints the response body, then the HTTP status on its own last line.
    """
    origin = urlsplit(target.public_origin)
    args = [
        "--silent",
        "--show-error",
        "--max-time",
        str(LAUNCH_REQUEST_TIMEOUT),
        "-X",
        "POST",
        "-H",
        f"Host: {origin.netloc}",
        "-H",
        f"X-Forwarded-Proto: {origin.scheme}",
        "-w",
        "\\n%{http_code}\\n",
        FRONT_DOOR_LAUNCH_URL,
    ]
    return target.compose_exec("curl " + " ".join(quote(arg) for arg in args))


def _split_status(stdout):
    """Return ``(body, status)`` from curl output, or ``(stdout, None)``."""
    body, _, status = stdout.rstrip().rpartition("\n")
    status = status.strip()
    if status.isdigit() and status != "000":
        return body, int(status)
    return stdout, None


def _is_json_object(text):
    try:
        return isinstance(json.loads(text), dict)
    except ValueError:
        return False


def _last_line(text):
    lines = [line for line in (text or "").splitlines() if line.strip()]
    return lines[-1].strip() if lines else ""


def require_curl(executor, target):
    """Stop the deploy early if the web image has no ``curl`` to launch with.

    Retries briefly while the web container is not up yet, like the launch.
    """
    command = target.compose_exec(f"sh -c {quote(CURL_CHECK)}")
    delay = DEFAULT_DELAY
    for attempt in range(MAX_ATTEMPTS):
        _, stdout, stderr = executor.run_with_status(command)
        if "curl-ok" in stdout:
            return
        if "curl-missing" in stdout:
            print_bold("To remove the app:")
            print(target.destroy_command)
            raise click.ClickException(
                "curl is not installed in the experiment's web image, so the "
                "deploy cannot launch the experiment. Install curl in the image "
                "(for example `apt-get install -y curl` in the Dockerfile). The "
                "app's containers are running, but the experiment was not "
                "launched and recruitment has not started."
            )
        if attempt < MAX_ATTEMPTS - 1:
            delay *= BACKOFF_FACTOR
            time.sleep(delay)
    print_bold("Check the web container logs:")
    print(target.ssh(f"docker compose -f {target.compose_file} logs web"))
    print_bold("Or remove the app:")
    print(target.destroy_command)
    raise click.ClickException(
        f"Could not run a command in {target.app}'s web container "
        f"({_last_line(stderr) or 'no output'}). The experiment was not launched "
        "and recruitment has not started."
    )


def launch_from_server(executor, target):
    """POST ``/launch`` from inside the app's network and return the launch data.

    Uses ``handle_launch_data``'s retries only while curl could not deliver
    the request. If the launch fails, prints what to check and run next and raises
    ``click.ClickException``.
    """
    command = internal_launch_command(target)

    def post():
        exit_status, stdout, stderr = executor.run_with_status(command)
        # Raising a ClickException (not a RequestException) stops
        # handle_launch_data from sending the request again.
        body, status = _split_status(stdout)
        if status is not None:
            if 200 <= status < 300 and _is_json_object(body):
                return _CommandResponse(status, body)
            raise _LaunchSent(
                f"The launch request to {target.app} returned HTTP {status}:\n{body}"
            )
        detail = _last_line(stderr) or f"exit status {exit_status}"
        if exit_status == CURL_TIMEOUT_EXIT_STATUS:
            raise _LaunchSent(
                f"The launch request to {target.app} did not answer within "
                f"{LAUNCH_REQUEST_TIMEOUT} s and may still be running."
            )
        web_not_running = (
            exit_status == COMPOSE_EXEC_FAILED_EXIT_STATUS
            and WEB_NOT_RUNNING_PATTERN.search(stderr or "")
        )
        if exit_status in NOT_SENT_EXIT_STATUSES or web_not_running:
            raise requests.exceptions.ConnectionError(detail)
        raise _LaunchSent(f"The launch request to {target.app} failed: {detail}")

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
        if _public_url_answers(status, detail):
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


def _public_url_answers(status, detail):
    """True once the app itself answers; gateway and tunnel errors keep waiting."""
    return (
        status is not None
        and answers_health(status)
        and not _tunnel_pending(status, detail)
    )


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
