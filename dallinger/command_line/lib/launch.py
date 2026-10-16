"""Check a docker-ssh app's public URL, then launch it from inside the server.

A new Cloudflare tunnel can take several minutes to accept its connector,
and a new Caddy site can wait on DNS or a TLS certificate. ``/launch`` opens
recruitment, so the deploy first waits, for a bounded time, until the public
URL answers. Participants are then not sent to a Cloudflare error page. If the
wait times out, or the URL keeps redirecting (a login such as Cloudflare
Access, which waiting does not remove), the deploy stops without launching
and prints the command that launches the app once its URL works.

The launch itself does not go through the public URL. The ``web`` container
POSTs ``/launch`` to the app's front door over the app's Docker network
with ``curl``, sending the public ``Host`` and ``X-Forwarded-Proto``. The web
image must have ``curl`` (the Dallinger and PsyNet images do), and the deploy
checks for it, and for a 2xx from the app's own ``/health``, before waiting
for the public URL. The front door trusts forwarded headers from private
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
import paramiko
import requests

from dallinger.deployment import BACKOFF_FACTOR, DEFAULT_DELAY, MAX_ATTEMPTS
from dallinger.hibernation import STATE_HIBERNATING, STATE_WAKING
from dallinger.utils import print_bold

from .app_manifest import INGRESS_CLOUDFLARE

FRONT_DOOR_LAUNCH_URL = "http://frontdoor:5000/launch"
# /launch can be slow (database setup, recruiter API calls).
LAUNCH_REQUEST_TIMEOUT = 900
PUBLIC_CHECK_TIMEOUT = 420
PUBLIC_CHECK_INTERVAL = 10
PROGRESS_INTERVAL = 60
REQUEST_TIMEOUT = 10
CLOUDFLARE_TUNNEL_PENDING_STATUS = 530
CLOUDFLARE_TUNNEL_PENDING_PATTERN = re.compile(r"error(?: code:)? 1033\b", re.I)
# A 404 body this short is not an app's error page.
BARE_404_MAX_LENGTH = 100
# curl's "could not resolve" / "could not connect": the request never left.
NOT_SENT_EXIT_STATUSES = frozenset({6, 7})
# ``docker compose exec`` exits 1 with one of these when web is not running.
COMPOSE_EXEC_FAILED_EXIT_STATUS = 1
WEB_NOT_RUNNING_PATTERN = re.compile(
    r"is not running|is restarting|no container found|no such container", re.I
)
CURL_TIMEOUT_EXIT_STATUS = 28
FRONT_DOOR_HEALTH_URL = "http://frontdoor:5000/health"
HEALTH_STATUS_PATTERN = re.compile(r"(?m)^health=(\d{3})\s*$")
SSH_ERRORS = (paramiko.SSHException, OSError)
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
        """Return a local command that checks the public health URL."""
        insecure = "" if self.verify else "-k "
        return (
            f"curl -sS {insecure}-o /dev/null -w '%{{http_code}}\\n' "
            f"{quote(self.health_url)}"
        )

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


class _LaunchSent(Exception):
    """``/launch`` may have reached the app without clearly succeeding; never resend it."""


def _attempts():
    """Yield ``MAX_ATTEMPTS`` times, sleeping with exponential backoff in between."""
    delay = DEFAULT_DELAY
    for attempt in range(MAX_ATTEMPTS):
        if attempt:
            delay *= BACKOFF_FACTOR
            time.sleep(delay)
        yield attempt


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


def _internal_health_command(target):
    """Return a command that checks for curl, then GETs ``/health`` like the launch.

    curl prints only ``health=<status>`` on stdout, and its error, if any, on
    stderr.
    """
    origin = urlsplit(target.public_origin)
    args = [
        "--silent",
        "--show-error",
        "--max-time",
        str(REQUEST_TIMEOUT),
        "-o",
        "/dev/null",
        "-H",
        f"Host: {origin.netloc}",
        "-H",
        f"X-Forwarded-Proto: {origin.scheme}",
        "-w",
        "health=%{http_code}\\n",
        FRONT_DOOR_HEALTH_URL,
    ]
    script = (
        "command -v curl >/dev/null || { echo curl-missing; exit 0; }; exec curl "
        + " ".join(quote(arg) for arg in args)
    )
    return target.compose_exec(f"sh -c {quote(script)}")


def _stop_before_launch(target, problem, show_logs=False):
    if show_logs:
        print_bold("Check the web container logs:")
        print(target.ssh(f"docker compose -f {target.compose_file} logs web"))
    print_bold("Or remove the app:" if show_logs else "To remove the app:")
    print(target.destroy_command)
    raise click.ClickException(
        f"{problem} The app's containers are running, but the experiment was "
        "not launched and recruitment has not started."
    )


def check_internal_health(executor, target):
    """Check that the app's own ``/health`` answers 2xx from inside the server.

    Stops the deploy early if the web image has no ``curl`` to launch with,
    if the app has no ``/health`` (404), or if it does not answer below 500.
    Retries briefly while the web container or the app is still starting,
    like the launch.
    """
    command = _internal_health_command(target)
    for _ in _attempts():
        try:
            _, stdout, stderr = executor.run_with_status(command)
        except SSH_ERRORS as exc:
            _stop_before_launch(
                target,
                f"The SSH connection failed while checking the app's /health ({exc}).",
                show_logs=True,
            )
        if stdout.strip() == "curl-missing":
            _stop_before_launch(
                target,
                "curl is not installed in the experiment's web image, so the "
                "deploy cannot launch the experiment. Install curl in the image "
                "(for example `apt-get install -y curl` in the Dockerfile).",
            )
        match = HEALTH_STATUS_PATTERN.search(stdout)
        status = int(match.group(1)) if match else None
        if status and status < 500:
            break
    if status and 200 <= status < 300:
        print("The app answers /health inside the server.")
        return
    if status == 404:
        _stop_before_launch(
            target,
            "The app has no /health endpoint, so its image was built with an "
            "older Dallinger (12.4.0 or earlier). Rebuild the image with this "
            "Dallinger version (or newer) and deploy again.",
        )
    if status:
        problem = f"The app's own /health answered HTTP {status}, so it is not healthy."
    else:
        problem = (
            f"Could not read the app's own /health inside the server "
            f"({_last_line(stderr) or 'no answer'})."
        )
    _stop_before_launch(target, problem, show_logs=True)


def launch_from_server(executor, target):
    """POST ``/launch`` from inside the app's network and return the launch data.

    Sends the request again only while curl could not deliver it. If the
    launch fails, prints what to check and run next and raises
    ``click.ClickException``.
    """
    command = internal_launch_command(target)
    sent = None
    try:
        for _ in _attempts():
            data = _send_launch(executor, target, command)
            if data is not None:
                return data
    except _LaunchSent as exc:
        sent = exc
        print(exc)
    print_bold("Check the web container logs:")
    print(target.ssh(f"docker compose -f {target.compose_file} logs web"))
    if sent:
        print_bold("Only if the logs show that recruitment did not open, launch again:")
    else:
        print_bold("Retry the launch:")
    print(target.ssh(command))
    print_bold("Or remove the app:")
    print(target.destroy_command)
    if sent:
        raise click.ClickException(
            f"The launch request may have reached {target.app} but did not "
            "clearly succeed. Recruitment may have started: check the web "
            "container logs before launching again."
        ) from sent
    raise click.ClickException(
        f"The launch request could not reach {target.app} from inside the "
        f"server after {MAX_ATTEMPTS} attempts. The app's containers are "
        "running, but the experiment was not launched and recruitment has not "
        "started."
    )


def _send_launch(executor, target, command):
    """Send ``/launch`` once; return the launch data, or None if it was not delivered.

    Raises ``_LaunchSent`` if the request may have reached the app.
    """
    try:
        exit_status, stdout, stderr = executor.run_with_status(command)
    except SSH_ERRORS as exc:
        raise _LaunchSent(
            f"The SSH connection failed while launching {target.app}: {exc}"
        ) from exc
    body, status = _split_status(stdout)
    if status is not None:
        if 200 <= status < 300 and _is_json_object(body):
            return json.loads(body)
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
        and WEB_NOT_RUNNING_PATTERN.search(f"{stderr}\n{stdout}")
    )
    if exit_status in NOT_SENT_EXIT_STATUSES or web_not_running:
        print(f"The launch request did not reach {target.app} yet: {detail}")
        return None
    raise _LaunchSent(f"The launch request to {target.app} failed: {detail}")


def wait_for_public_url(executor, target, timeout=None, interval=None):
    """Wait until the public ``/health`` answers 2xx, or stop the deploy.

    Waits up to ``timeout`` seconds (default ``PUBLIC_CHECK_TIMEOUT``). Edge
    pages, gateway errors, Cloudflare's pending-tunnel 530 and the hibernation
    controller's 2xx for a sleeping or waking app keep waiting.
    A redirect, such as a Cloudflare Access login, does not go away by
    waiting, so two redirects in a row stop the wait early. If the URL does
    not answer 2xx, prints why and what to run next, and raises
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
    redirected = False
    while True:
        status, detail = _probe(target.health_url, target.verify)
        if status is not None and 200 <= status < 300 and not _is_asleep(detail):
            print(f"{target.public_origin} is reachable.")
            return
        if redirected and _is_redirect(status):
            waited = None
            break
        redirected = _is_redirect(status)
        elapsed = time.monotonic() - started
        if elapsed + interval > timeout:
            waited = limit
            break
        if elapsed >= next_report:
            print(
                f"Still waiting after {int(elapsed)} s: "
                f"{_describe(status, detail, short=True)}"
            )
            next_report += PROGRESS_INTERVAL
        time.sleep(interval)

    _abort_unreachable(executor, target, status, detail, waited)


def _duration(seconds):
    if seconds < 60:
        return f"{seconds:g} s"
    return f"{round(seconds / 60)} min"


def _probe(url, verify):
    """GET ``url`` once; return ``(status_code or None, detail)``.

    Redirects are not followed: a Cloudflare Access login page is not the app.
    If the request fails, ``detail`` is ``"<requests exception class>: <message>"``,
    with urllib3's cause added to a bare ``ConnectionError`` (for example
    ``NameResolutionError`` or ``NewConnectionError``).
    """
    try:
        response = requests.get(
            url, timeout=REQUEST_TIMEOUT, verify=verify, allow_redirects=False
        )
    except requests.exceptions.RequestException as exc:
        name = type(exc).__name__
        cause = getattr(exc.args[0], "reason", None) if exc.args else None
        if type(exc) is requests.exceptions.ConnectionError and cause is not None:
            name += f" ({type(cause).__name__})"
        return None, f"{name}: {exc}"
    if _is_redirect(response.status_code):
        return response.status_code, f"redirect to {response.headers.get('location')}"
    if "cf-mitigated" in response.headers:
        return response.status_code, f"cf-mitigated: {response.headers['cf-mitigated']}"
    return response.status_code, response.text


def _is_redirect(status):
    return status is not None and 300 <= status < 400


def _is_asleep(body):
    """True if ``body`` is the hibernation controller's answer for a stopped app.

    The controller answers ``/health`` with 200 while the app sleeps or wakes,
    so ``/launch`` would reach the controller instead of the app.
    """
    try:
        data = json.loads(body)
    except ValueError:
        return False
    return isinstance(data, dict) and data.get("status") in (
        STATE_HIBERNATING,
        STATE_WAKING,
    )


def _describe(status, detail, short=False):
    """Summarise a probe result; ``short`` gives only the class of a request error."""
    if status is None:
        if short:
            return detail.partition(":")[0] if detail else "no response"
        return detail.splitlines()[0] if detail else "no response"
    if _is_redirect(status) or detail.startswith("cf-mitigated:"):
        return f"HTTP {status}, {detail}"
    if 200 <= status < 300 and _is_asleep(detail):
        return f"HTTP {status}, app hibernating or waking up"
    return f"HTTP {status}"


def _tunnel_pending(status, detail):
    """True for Cloudflare's 530 / error 1033 answer for an unconnected tunnel."""
    return status == CLOUDFLARE_TUNNEL_PENDING_STATUS or bool(
        CLOUDFLARE_TUNNEL_PENDING_PATTERN.search(detail or "")
    )


def _connector_reports_tunnel_not_found(executor, target):
    """Search recent ``cloudflared`` logs without printing them."""
    try:
        logs = executor.run(
            f"docker compose -f {target.compose_file} logs --tail 200 cloudflared 2>&1",
            raise_=False,
        )
    except SSH_ERRORS as exc:
        print(f"Could not read the cloudflared logs over SSH: {exc}")
        return False
    return "tunnel not found" in (logs or "").lower()


def _inactive_tunnel_reason(executor, target, status, detail):
    """Return why an inactive Cloudflare tunnel explains the result, or None.

    Only no response, a 530 / error 1033 or a bare 404 can come from a tunnel
    Cloudflare has not activated. A new connector logs "Tunnel not found"
    before it starts working, so the logs are not consulted for other answers.
    """
    pending = _tunnel_pending(status, detail)
    bare_404 = status == 404 and len(detail.strip()) <= BARE_404_MAX_LENGTH
    if not (status is None or pending or bare_404):
        return None
    not_found = _connector_reports_tunnel_not_found(executor, target)
    if not (pending or not_found):
        return None
    return (
        "Cloudflare has not activated the new tunnel yet"
        + (" (cloudflared logs say 'Tunnel not found')" if not_found else "")
        + "; new tunnels usually start working within minutes."
    )


def _abort_unreachable(executor, target, status, detail, waited):
    """Print why the public URL failed and what to run next, then stop the deploy.

    ``waited`` is how long the deploy waited, or None if it stopped early.
    """
    cloudflare = target.ingress == INGRESS_CLOUDFLARE
    last = _describe(status, detail)
    if waited is None:
        print(
            f"{target.health_url} redirected twice in a row (last result: "
            f"{last}). Waiting does not remove a redirect, so the deploy "
            "stopped waiting."
        )
    else:
        print(
            f"{target.public_origin} was still not reachable after {waited} "
            f"(last result: {last})."
        )
    if _is_redirect(status):
        reason = (
            f"The public /health answered with a {detail}, so a login such as "
            "Cloudflare Access may be in front of the app. The deploy launches "
            "only once /health answers 2xx without a redirect."
        )
    elif status is not None and 200 <= status < 300:
        reason = f"The app is hibernating or waking up ({detail.strip()})."
    elif status == 403:
        mitigated = f" ({detail})" if detail.startswith("cf-mitigated:") else ""
        reason = (
            f"Cloudflare may be blocking the check{mitigated}, with a bot or "
            "WAF challenge or Cloudflare Access."
        )
    elif cloudflare:
        reason = _inactive_tunnel_reason(executor, target, status, detail) or (
            "The Cloudflare tunnel is not serving the app yet."
        )
    else:
        reason = (
            "Caddy may still be getting a TLS certificate, or DNS may not "
            "point at the server yet."
        )
    asleep = status is not None and 200 <= status < 300
    if asleep:
        print_bold("Check the public URL again (expect the app's own /health):")
    else:
        print_bold("Check the public URL again (expect 2xx):")
    print(target.check_command)
    if cloudflare and not (_is_redirect(status) or status == 403):
        print_bold("Inspect the tunnel connector logs:")
        print(target.ssh(f"docker compose -f {target.compose_file} logs cloudflared"))
    print_bold("Once the public URL works, launch the experiment:")
    print(target.ssh(internal_launch_command(target)))
    print_bold("Or remove the app:")
    print(target.destroy_command)
    answer = "answered for a stopped app" if asleep else "did not answer 2xx"
    raise click.ClickException(
        f"{target.health_url} {answer}, so the experiment was not "
        "launched. The app's containers are running, but recruitment has not "
        f"started. {reason}"
    )
