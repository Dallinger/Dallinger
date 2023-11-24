import logging
import sys
from datetime import timedelta
from functools import update_wrapper
from json import dumps

import user_agents
from flask import Response, current_app, make_response, render_template, request

from dallinger.config import get_config

logger = logging.getLogger(__name__)


def crossdomain(
    origin=None,
    methods=None,
    headers=None,
    max_age=21600,
    attach_to_all=True,
    automatic_options=True,
):
    if methods is not None:
        methods = ", ".join(sorted(x.upper() for x in methods))
    if headers is not None and not isinstance(headers, str):
        headers = ", ".join(x.upper() for x in headers)
    if not isinstance(origin, str):
        origin = ", ".join(origin)
    if isinstance(max_age, timedelta):
        max_age = max_age.total_seconds()

    def get_methods():
        if methods is not None:
            return methods

        options_resp = current_app.make_default_options_response()
        return options_resp.headers["allow"]

    def decorator(f):
        def wrapped_function(*args, **kwargs):
            if automatic_options and request.method == "OPTIONS":
                resp = current_app.make_default_options_response()
            else:
                resp = make_response(f(*args, **kwargs))
            if not attach_to_all and request.method != "OPTIONS":
                return resp

            h = resp.headers

            h["Access-Control-Allow-Origin"] = origin
            h["Access-Control-Allow-Methods"] = get_methods()
            h["Access-Control-Max-Age"] = str(max_age)
            if headers is not None:
                h["Access-Control-Allow-Headers"] = headers
            return resp

        f.provide_automatic_options = False
        return update_wrapper(wrapped_function, f)

    return decorator


def date_handler(obj):
    """Serialize dates."""
    return obj.isoformat() if hasattr(obj, "isoformat") else object


def nocache(func):
    """Stop caching for pages wrapped in nocache decorator."""

    def new_func(*args, **kwargs):
        """No cache Wrapper."""
        resp = make_response(func(*args, **kwargs))
        resp.cache_control.no_cache = True
        return resp

    return update_wrapper(new_func, func)


class ExperimentError(Exception):
    """
    Error class for experimental errors, such as subject not being found in
    the database.
    """

    def __init__(self, value):
        experiment_errors = dict(
            status_incorrectly_set=1000,
            hit_assign_worker_id_not_set_in_mturk=1001,
            hit_assign_worker_id_not_set_in_consent=1002,
            hit_assign_worker_id_not_set_in_exp=1003,
            hit_assign_appears_in_database_more_than_once=1004,
            hit_assign_worker_id_not_set_by_recruiter=1006,
            already_started_exp=1008,
            already_started_exp_mturk=1009,
            already_did_exp_hit=1010,
            tried_to_quit=1011,
            intermediate_save=1012,
            improper_inputs=1013,
            browser_type_not_allowed=1014,
            api_server_not_reachable=1015,
            ad_not_found=1016,
            error_setting_worker_complete=1017,
            hit_not_registered_with_ad_server=1018,
            template_unsafe=1019,
            insert_mode_failed=1020,
            page_not_found=404,
            in_debug=2005,
            unknown_error=9999,
        )
        self.value = value
        self.errornum = experiment_errors[self.value]
        self.template = "error.html"

    def __str__(self):
        return repr(self.value)


class ValidatesBrowser(object):
    """Checks if participant's browser has been excluded via the Configuration."""

    def __init__(self, config):
        self.config = config

    @property
    def exclusions(self):
        """Return list of browser exclusion rules defined in the Configuration."""
        exclusion_rules = [
            r.strip()
            for r in self.config.get("browser_exclude_rule", "").split(",")
            if r.strip()
        ]
        return exclusion_rules

    def is_supported(self, user_agent_string):
        """Check user agent against configured exclusions."""
        user_agent_obj = user_agents.parse(user_agent_string)
        browser_ok = True
        for rule in self.exclusions:
            if rule in ["mobile", "tablet", "touchcapable", "pc", "bot"]:
                if (
                    (rule == "mobile" and user_agent_obj.is_mobile)
                    or (rule == "tablet" and user_agent_obj.is_tablet)
                    or (rule == "touchcapable" and user_agent_obj.is_touch_capable)
                    or (rule == "pc" and user_agent_obj.is_pc)
                    or (rule == "bot" and user_agent_obj.is_bot)
                ):
                    browser_ok = False
            elif rule in user_agent_string:
                browser_ok = False

        return browser_ok


"""Define some canned response types."""


def success_response(**data):
    """Return a generic success response."""
    data_out = {}
    data_out["status"] = "success"
    data_out.update(data)
    js = dumps(data_out, default=date_handler)
    return Response(js, status=200, mimetype="application/json")


def error_response(
    error_type="Internal server error",
    error_text="",
    status=400,
    participant=None,
    simple=False,
    request_data="",
):
    """Return a generic server error response."""
    last_exception = sys.exc_info()
    if last_exception[0]:
        logger.error(
            "Failure for request: {!r}".format(dict(request.args)),
            exc_info=last_exception,
        )

    data = {"status": "error"}

    if simple:
        data["message"] = error_text
    else:
        data["html"] = (
            error_page(
                error_text=error_text,
                error_type=error_type,
                participant=participant,
                request_data=request_data,
            )
            .get_data()
            .decode("utf-8")
        )
    return Response(dumps(data), status=status, mimetype="application/json")


def error_page(
    participant=None,
    error_text=None,
    compensate=True,
    error_type="default",
    request_data="",
):
    """Render HTML for error page."""
    config = _config()

    if error_text is None:
        error_text = "There has been an error and so you are unable to continue, sorry!"

    if participant is not None:
        hit_id = participant.hit_id
        assignment_id = participant.assignment_id
        worker_id = participant.worker_id
        participant_id = participant.id
    else:
        hit_id = request.form.get("hit_id", "")
        assignment_id = request.form.get("assignment_id", "")
        worker_id = request.form.get("worker_id", "")
        participant_id = request.form.get("participant_id", None)

    if participant_id:
        try:
            participant_id = int(participant_id)
        except (ValueError, TypeError):
            participant_id = None

    return make_response(
        render_template(
            "error.html",
            error_text=error_text,
            compensate=compensate,
            contact_address=config.get("contact_email_on_error"),
            error_type=error_type,
            hit_id=hit_id,
            assignment_id=assignment_id,
            worker_id=worker_id,
            request_data=request_data,
            participant_id=participant_id,
        ),
        500,
    )


def _config():
    config = get_config()
    if not config.ready:
        config.load()

    return config
