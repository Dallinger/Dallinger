import json
import logging
from copy import deepcopy
from datetime import datetime, timedelta
from xml.sax.saxutils import escape

import six
import timeago
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask.wrappers import Response
from flask_login import UserMixin, current_user, login_required, login_user, logout_user
from flask_login.utils import login_url as make_login_url
from flask_wtf import FlaskForm
from six.moves.urllib.parse import urlencode
from tzlocal import get_localzone
from wtforms import BooleanField, HiddenField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, ValidationError

import dallinger.db
from dallinger import recruiters
from dallinger.config import get_config
from dallinger.db import get_all_mapped_classes
from dallinger.heroku.tools import HerokuApp
from dallinger.utils import deferred_route_decorator

from .utils import date_handler, error_response, success_response

logger = logging.getLogger(__name__)


class User(UserMixin):
    def __init__(self, userid, password):
        self.id = userid
        self.password = password


class DashboardTab(object):
    def __init__(self, title, route_name, children_function=None, params=None):
        """Creates a new dashboard tab

        :param title: Title string to appear in the dashboard HTML
        :type title: str
        :param route_name: The registered route name (optionally prefixed with ``dashboard.``)
        :type route_name: str
        :param children_function: A callable that returns an iterable of ``DashboardTab`` to be displayed as children of this tab
        :type position: function, optional
        :param params: A mapping of url query string parameters used when generating the route url.
        :type position: dict, optional

        """
        self.title = title
        if not route_name.startswith("dashboard."):
            route_name = "dashboard." + route_name
        self.route_name = route_name
        self.children_function = children_function
        self.params = params

    def url(self):
        url = url_for(self.route_name)
        if self.params is not None:
            url += "?" + urlencode(self.params)
        return url

    @property
    def has_children(self):
        return self.children_function is not None

    def __eq__(self, other):
        return self.__class__ == other.__class__ and all(
            getattr(self, attr) == getattr(other, attr) for attr in self.__dict__
        )

    def __iter__(self):
        if self.has_children:
            children = self.children_function()
            for child in children:
                yield child


class DashboardTabs(object):
    tabs = ()

    def __init__(self, tabs):
        self.tabs = list(tabs) or []

    def insert(self, title, route_name, position=None):
        """Creates a new dashboard tab and inserts it (optionally at a specific position)

        :param title: Title string to appear in the dashboard HTML
        :type title: str
        :param route_name: The registered route name (optionally prefixed with ``dashboard.``)
        :type route_name: str
        :param position: The 0-based index where the tab should be inserted. By default tabs will be appended to the end.
        :type position: int, optional

        """
        tab = DashboardTab(title, route_name)
        self.insert_tab(tab, position)

    def insert_tab(self, tab, position=None):
        """Insert a new dashboard tab (optionally at a specific position)

        :param tab: DashboardTab instance
        :type tab: DashboardTab
        :param position: The 0-based index where the tab should be inserted. By default tabs will be appended to the end.
        :type position: int, optional

        """
        if position is None:
            self.tabs.append(tab)
        else:
            self.tabs.insert(position, tab)

    def insert_before_route(self, title, route_name, before_route):
        """Creates a new dashboard tab and inserts it before an existing tab by route name

        :param title: Title string to appear in the dashboard HTML
        :type title: str
        :param route_name: The registered route name (optionally prefixed with ``dashboard.``)
        :type route_name: str
        :param before_route: The route name to insert this tab before.
        :type before_route: str
        :raises ValueError: When ``before_route`` is not found in registered tabs

        """
        tab = DashboardTab(title, route_name)
        self.insert_tab_before_route(tab, before_route)

    def insert_tab_before_route(self, tab, before_route):
        """Insert a new dashboard tab before an existing tab by route name

        :param tab: DashboardTab instance
        :type tab: DashboardTab
        :param before_route: The route name to insert this tab before.
        :type before_route: str
        :raises ValueError: When ``before_route`` is not found in registered tabs

        """
        before_check = frozenset((before_route, "dashboard." + before_route))
        for i, cur_tab in enumerate(self.tabs):
            if cur_tab.route_name in before_check:
                position = i
                break
        else:
            raise ValueError("Route {} not found".format(before_route))
        self.insert_tab(tab, position)

    def insert_after_route(self, title, route_name, after_route):
        """Creates a new dashboard tab and inserts it after an existing tab by route name

        :param title: Title string to appear in the dashboard HTML
        :type title: str
        :param route_name: The registered route name (optionally prefixed with ``dashboard.``)
        :type route_name: str
        :param after_route: The route name to insert this tab after.
        :type after_route: str
        :raises ValueError: When ``after_route`` is not found in registered tabs

        """
        tab = DashboardTab(title, route_name)
        self.insert_tab_after_route(tab, after_route)

    def insert_tab_after_route(self, tab, after_route):
        """Insert a new dashboard tab after an existing tab by route name

        :param tab: DashboardTab instance
        :type tab: DashboardTab
        :param after_route: The route name to insert this tab after.
        :type after_route: str
        :raises ValueError: When ``after_route`` is not found in registered tabs

        """
        after_check = frozenset((after_route, "dashboard." + after_route))
        for i, cur_tab in enumerate(self.tabs):
            if cur_tab.route_name in after_check:
                position = i + 1
                break
        else:
            raise ValueError("Route {} not found".format(after_route))
        self.insert_tab(tab, position)

    def remove(self, route_name):
        """Remove a tab by route name

        :param route_name: The registered route name (optionally prefixed with ``dashboard.``)
        :type route_name: str

        """
        route_check = frozenset((route_name, "dashboard." + route_name))
        self.tabs = [t for t in self.tabs if t.route_name not in route_check]

    def __iter__(self):
        return iter(self.tabs)


def database_children():
    mapped_classes = list(get_all_mapped_classes().items())
    mapped_classes.sort(key=lambda x: x[0])
    for cls_name, cls_info in mapped_classes:
        yield DashboardTab(
            cls_name,
            "dashboard.database",
            None,
            {
                "table": cls_info["table"],
                "polymorphic_identity": cls_info["polymorphic_identity"],
            },
        )


dashboard_tabs = DashboardTabs(
    [
        DashboardTab("Config", "dashboard.index"),
        DashboardTab("Heroku", "dashboard.heroku"),
        DashboardTab("MTurk", "dashboard.mturk"),
        DashboardTab("Monitoring", "dashboard.monitoring"),
        DashboardTab("Lifecycle", "dashboard.lifecycle"),
        DashboardTab("Database", "dashboard.database", database_children),
        DashboardTab("Development", "dashboard.develop"),
    ]
)


def load_user(userid):
    admin_user = current_app.config.get("ADMIN_USER")
    if userid != admin_user.id:
        return
    return admin_user


def load_user_from_request(request):
    admin_user = current_app.config.get("ADMIN_USER")
    auth = request.authorization
    if auth:
        if auth["username"] != admin_user.id:
            return
        if auth["password"] == admin_user.password:
            return admin_user
    return


def unauthorized():
    config = get_config()
    if config.get("mode") == "debug":
        abort(401)

    redirect_url = make_login_url("dashboard.login", next_url=request.url)
    return redirect(redirect_url)


dashboard = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@dashboard.errorhandler(401)
def custom_401(error):
    return Response(
        "Unauthorized", 401, {"WWW-Authenticate": 'Basic realm="Login Required"'}
    )


def validate_username(form, field):
    admin_user = current_app.config.get("ADMIN_USER")
    if field.data != admin_user.id:
        raise ValidationError("Unknown user")


def next_default():
    return request.args.get("next")


class LoginForm(FlaskForm):
    next = HiddenField("next", default=next_default)
    username = StringField("Username", validators=[DataRequired(), validate_username])
    password = PasswordField("Password", validators=[DataRequired()])
    remember_me = BooleanField("Remember Me")
    submit = SubmitField("Sign In")


def is_safe_url(url):
    base = url_for("index")
    if url.startswith("/") or url.startswith(base):
        return True
    return False


@dashboard.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.form.get("next", request.args.get("next"))
    next_url = (
        next_url if next_url and is_safe_url(next_url) else url_for("dashboard.index")
    )
    if current_user.is_authenticated:
        return redirect(next_url)
    form = LoginForm()
    if not form.is_submitted():
        return render_template("login.html", title="Sign In", form=form)

    if form.validate_on_submit():
        admin_user = current_app.config.get("ADMIN_USER")
        if not admin_user.password == form.password.data:
            flash("Invalid username or password", "danger")
            return redirect(url_for("dashboard.login"))

        login_user(admin_user, remember=form.remember_me.data)
        flash("You are now logged in!", "success")
        return redirect(next_url)
    flash("There was a problem with your submission", "danger")
    return render_template("login.html", title="Sign In", form=form)


@dashboard.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("dashboard.index"))


@dashboard.route("/")
@dashboard.route("/index")
@login_required
def index():
    """Displays active experiment configuation"""
    config = get_config()
    config.load()
    config_dict = config.as_dict()
    config_list = sorted(config_dict.items())
    return render_template(
        "dashboard_home.html",
        title="Config",
        configuration=config_list,
        configuration_dictionary=config_dict,
        changeable_params=config.changeable_params,
    )


@dashboard.route("/heroku")
@login_required
def heroku():
    """Assemble links from Heroku add-on info, stored in config, plus some
    standard dashboard links.
    """
    config = get_config()
    if config.get("mode") == "debug":
        flash(
            "This experiment is running in debug mode and is not deployed to Heroku",
            "warning",
        )
        return render_template("dashboard_heroku.html", links=[])

    heroku_app = HerokuApp(config.get("heroku_app_id_root"))
    links = [
        {"url": heroku_app.dashboard_url, "title": "Heroku dashboard"},
        {"url": heroku_app.dashboard_metrics_url, "title": "Heroku metrics"},
    ]
    details = json.loads(
        config.get("infrastructure_debug_details", six.text_type("{}"))
    )
    links.extend(
        [{"title": v["title"].title(), "url": v["url"]} for v in details.values()]
    )

    return render_template("dashboard_heroku.html", links=links)


tz = get_localzone()


def when_with_relative_time(dt):
    now = datetime.now().replace(tzinfo=tz)
    formatted = dt.strftime("%a %b %-d")
    return "{} ({})".format(formatted, timeago.format(dt, now))


class NotUsingMTurkRecruiter(Exception):
    """The experiment does not use the MTurk Recruiter"""


class MTurkDataSource(object):
    def __init__(self, recruiter):
        self._recruiter = recruiter
        try:
            self._mturk = recruiter.mturkservice
        except AttributeError:
            raise NotUsingMTurkRecruiter()

    @property
    def is_sandbox(self):
        return self._recruiter.is_sandbox

    @property
    def _mturk_root(self):
        if self.is_sandbox:
            return "https://requestersandbox.mturk.com"
        return "https://requester.mturk.com"

    @property
    def account_balance(self):
        return self._mturk.account_balance()

    @property
    def ad_url(self):
        hit_id = self._recruiter.current_hit_id()
        template = "{}&assignmentId=ASSIGNMENT_ID_NOT_AVAILABLE&hitId={}"
        if hit_id is not None:
            return template.format(self._recruiter.ad_url, hit_id)

    @property
    def current_hit(self):
        hit_id = self._recruiter.current_hit_id()
        logger.info("HIT is: {}".format(hit_id))
        if hit_id is not None:
            return self._mturk.get_hit(hit_id)

    @property
    def requester_url(self):
        return "{}/manage".format(self._mturk_root)

    @property
    def qualification_types_url(self):
        return "{}/qualification_types".format(self._mturk_root)


_fake_hit_data = {
    "annotation": None,
    "assignments_available": 1,
    "assignments_completed": 0,
    "assignments_pending": 0,
    "created": (datetime.now() - timedelta(minutes=10)).replace(tzinfo=tz),
    "description": "Fake HIT Description",
    "expiration": (datetime.now() + timedelta(hours=6)).replace(tzinfo=tz),
    "id": "3X7837UUADRXYCA1K7JAJLKC66DJ60",
    "keywords": ["testkw1", "testkw2"],
    "max_assignments": 1,
    "qualification_type_ids": ["000000000000000000L0", "00000000000000000071"],
    "review_status": "NotReviewed",
    "reward": 0.01,
    "status": "Assignable",
    "title": "Fake HIT Title",
    "type_id": "3V76OXST9SAE3THKN85FUPK7730050",
    "worker_url": "https://workersandbox.mturk.com/projects/3V76OXST9SAE3THKN85FUPK7730050/tasks",
}


class FakeMTurkDataSource(object):
    account_balance = 1234.5
    ad_url = "http://unicodesnowmanforyou.com/"
    requester_url = "https://fakerequesterurl.com"
    qualification_types_url = "https://fakequalificationtypes.com"
    is_sandbox = True

    def __init__(self):
        self.current_hit = _fake_hit_data.copy()


class MTurkDashboardInformation(object):
    def __init__(self, config, data_source):
        self._config = config
        self._source = data_source

    @property
    def hit(self):
        return self._source.current_hit

    @property
    def hit_info(self):
        hit = self.hit
        if hit is not None:
            return {
                "HIT Id": hit["id"],
                "Title": hit["title"],
                "Keywords": ", ".join(hit["keywords"]),
                "Base payment": "${:.2f}".format(hit["reward"]),
                "Description": hit["description"],
                "Creation time": when_with_relative_time(hit["created"]),
                "Expiration time": when_with_relative_time(hit["expiration"]),
                "Assignments requested": hit["max_assignments"],
                "Assignments available": hit["assignments_available"],
                "Assignments completed": hit["assignments_completed"],
                "Assignments pending": hit["assignments_pending"],
            }

    @property
    def hit_expiration_isoformat(self):
        hit = self.hit
        if hit is not None:
            return self.hit["expiration"].strftime("%Y-%m-%dT%H:%M")

    @property
    def is_sandbox(self):
        return self._source.is_sandbox

    @property
    def account_balance(self):
        return "${:.2f}".format(self._source.account_balance)

    @property
    def last_updated(self):
        return datetime.now().strftime("%X")

    @property
    def ad_url(self):
        return self._source.ad_url

    @property
    def requester_url(self):
        return self._source.requester_url

    @property
    def qualification_types_url(self):
        return self._source.qualification_types_url

    @property
    def expire_command(self):
        app_id = self._config.get("id")
        sandbox_option = " --sandbox " if self._source.is_sandbox else " "
        return "dallinger expire{}--app {}".format(sandbox_option, app_id)


def mturk_data_source(config):
    recruiter = recruiters.from_config(config)
    try:
        return MTurkDataSource(recruiter)
    except NotUsingMTurkRecruiter:
        if config.get("mode") == "debug":
            flash(
                "Debug mode: Fake MTurk information provided for testing only.",
                "warning",
            )
            return FakeMTurkDataSource()
        else:
            raise


@dashboard.route("/mturk")
@login_required
def mturk():
    config = get_config()
    try:
        data_source = mturk_data_source(config)
    except NotUsingMTurkRecruiter:
        flash("This experiment does not use the MTurk Recruiter.", "danger")
        return render_template(
            "dashboard_mturk.html", title="MTurk Dashboard", data=None
        )

    helper = MTurkDashboardInformation(config, data_source)

    data = {
        "account_balance": helper.account_balance,
        "ad_url": helper.ad_url,
        "hit_info": helper.hit_info,
        "hit_expiration": helper.hit_expiration_isoformat,
        "last_updated": helper.last_updated,
        "requester_url": helper.requester_url,
        "is_sandbox": helper.is_sandbox,
        "qualification_types_url": helper.qualification_types_url,
        "expire_command": helper.expire_command,
    }

    return render_template("dashboard_mturk.html", title="MTurk Dashboard", data=data)


@dashboard.route("/auto_recruit/<bool_val>", methods=["POST"])
@login_required
def auto_recruit(bool_val):
    from dallinger.db import redis_conn

    num_val = int(bool_val)
    assert num_val in [0, 1]
    redis_conn.set("auto_recruit", num_val)
    return success_response()


@dashboard.route("/monitoring")
@login_required
def monitoring():
    from sqlalchemy import distinct, func

    from dallinger.experiment_server.experiment_server import Experiment, session
    from dallinger.models import Network

    exp = Experiment(session)
    panes = exp.monitoring_panels(**request.args.to_dict(flat=False))
    network_structure = exp.network_structure(**request.args.to_dict(flat=False))
    vis_options = exp.node_visualization_options()
    net_roles = (
        session.query(Network.role, func.count(Network.role))
        .group_by(Network.role)
        .order_by(Network.role)
        .all()
    )
    net_ids = [
        i[0] for i in session.query(distinct(Network.id)).order_by(Network.id).all()
    ]
    return render_template(
        "dashboard_monitor.html",
        title="Experiment Monitoring",
        panes=panes,
        network_structure=json.dumps(network_structure, default=date_handler),
        net_roles=net_roles,
        net_ids=net_ids,
        vis_options=json.dumps(vis_options),
    )


@dashboard.route("/node_details/<object_type>/<obj_id>")
@login_required
def node_details(object_type, obj_id):
    from dallinger.experiment_server.experiment_server import Experiment, session

    exp = Experiment(session)
    html_data = exp.node_visualization_html(object_type, obj_id)
    return Response(html_data, status=200, mimetype="text/html")


@dashboard.route("/init_db", methods=["POST"])
@login_required
def init_db():
    dallinger.db.init_db(drop_all=True)
    return success_response()


@dashboard.route("/lifecycle")
@login_required
def lifecycle():
    config = get_config()

    try:
        mturk = MTurkDashboardInformation(config, mturk_data_source(config))
    except NotUsingMTurkRecruiter:
        mturk = None

    sandbox_option = " --sandbox " if config.get("mode") == "sandbox" else " "
    data = {
        "heroku_app_id": config.get("heroku_app_id_root"),
        "expire_command": mturk.expire_command if mturk else None,
        "sandbox_option": sandbox_option,
    }

    return render_template(
        "dashboard_lifecycle.html", title="Experiment lifecycle Dashboard", **data
    )


TABLE_DEFAULTS = {
    "dom": "frtilBpP",
    "ordering": True,
    "searching": True,
    "select": True,
    "paging": True,
    "lengthChange": True,
    "searchPanes": {"threshold": 0.99},
    "buttons": [
        {
            "extend": "collection",
            "text": "Export",
            "buttons": ["export_json", "csvHtml5", "print"],
        },
    ],
}


def prep_datatables_options(table_data):
    """Attempts to generate a reasonable a DataTables config"""
    datatables_options = deepcopy(TABLE_DEFAULTS)
    datatables_options.update(deepcopy(table_data))
    # Display objects and arrays in useful ways
    for row in datatables_options.get("data", []):
        for col in datatables_options.get("columns", []):
            data = col["data"]
            if isinstance(data, dict):
                key = data.get("_")
            else:
                key = data

            display_key = key + "_display"
            value = row[key]
            if not isinstance(value, (six.text_type, six.binary_type)):
                row[display_key] = "<code>{}</code>".format(
                    escape(json.dumps(value, default=date_handler))
                )
            else:
                row[display_key] = escape(value)
            col["data"] = {
                "_": key,
                "filter": key,
                "display": display_key,
            }

            if isinstance(row[key], (list, dict)):
                col["searchPanes"] = {
                    "orthogonal": {
                        "display": "filter",
                        "sort": "filter",
                        "search": "filter",
                        "type": "type",
                    }
                }
                if "render" in col:
                    del col["render"]

            if isinstance(row[key], dict):
                # Make sure SearchPanes can show dict values reasonably
                row[key] = json.dumps(value, default=date_handler)
                # Add indentation to dicts
                row[display_key] = "<code>{}</code>".format(
                    escape(json.dumps(value, default=date_handler, indent=True))
                )
            elif isinstance(row[key], list):
                # Make sure SearchPanes can show list values reasonably
                row[key] = json.dumps(value, default=date_handler)

    return datatables_options


@dashboard.route("/database")
@login_required
def database():
    from dallinger.db import get_polymorphic_mapping
    from dallinger.experiment_server.experiment_server import Experiment, session

    exp = Experiment(session)

    table = request.args.get("table", None)
    polymorphic_identity = request.args.get("polymorphic_identity", None)

    if polymorphic_identity == "None":
        polymorphic_identity = None

    if table is None and polymorphic_identity is None:
        table = "participant"

    if polymorphic_identity is not None:
        assert table is not None
        cls = get_polymorphic_mapping(table)[polymorphic_identity]
        label = cls.__name__
    else:
        label = table.capitalize()

    title = "Database View: {}".format(label)
    datatables_options = prep_datatables_options(
        exp.table_data(**request.args.to_dict())
    )
    columns = [
        c.get("name") or c["data"]
        for c in datatables_options.get("columns", [])
        if c.get("data")
    ]

    # Extend with custom actions
    actions = {
        "extend": "collection",
        "text": "Actions",
        "buttons": [],
    }
    buttons = actions["buttons"]

    exp_actions = exp.dashboard_database_actions()
    for action in exp_actions:
        buttons.append(
            {
                "extend": "route_action",
                "text": action["title"],
                "route_name": action["name"],
            }
        )

    is_sandbox = getattr(recruiters.from_config(get_config()), "is_sandbox", None)
    if is_sandbox is True or is_sandbox is False:
        buttons.append("compensate")
    else:
        is_sandbox = None

    if len(buttons):
        datatables_options["buttons"].append(actions)

    return render_template(
        "dashboard_database.html",
        title=title,
        columns=columns,
        is_sandbox=is_sandbox,
        datatables_options=json.dumps(
            datatables_options, default=date_handler, indent=True
        ),
    )


@dashboard.route("/develop", methods=["GET", "POST"])
@login_required
def develop():
    """Dashboard for working with ``dallinger develop`` Flask server."""
    return render_template(
        "dashboard_develop.html",
        mode=get_config().get("mode"),
        recruiter=recruiters.from_config(get_config()).nickname,
    )


@dashboard.route("/database/action/<route_name>", methods=["POST"])
@login_required
def database_action(route_name):
    from dallinger.experiment_server.experiment_server import Experiment, session

    data = request.json
    exp = Experiment(session)
    if route_name not in {a["name"] for a in exp.dashboard_database_actions()}:
        return error_response(
            error_text="Access to {} not allowed".format(route_name), status=403
        )
    route_func = getattr(exp, route_name, None)
    if route_func is None:
        return error_response(
            error_text="Method {} not found".format(route_name), status=404
        )
    result = route_func(data)
    session.commit()
    if result.get("message"):
        flash(result["message"], "success")
    return success_response(**result)


DASHBOARD_ROUTE_REGISTRATIONS = []


def dashboard_tab(title, **kwargs):
    """Creates a decorator to register experiment functions or classmethods as
    dashboard tabs. Adds a tab with a ``title`` at the path
    ``/dashboard/function_name`` and accepts any other flask ``route`` keyword
    arguments. Registers the decorated method as a route on the
    :attr:`dallinger.experiment_server.dashboard.dashboard` Blueprint. The
    registration is deferred until experiment server setup to allow routes to be
    overridden. Optionally accepts ``after_route`` and ``before_route``
    arguments to specify tab ordering relative to other named routes.

    :param title: The dashboard tab title
    :type title: str
    :param after_route: Optional name of a tab after which to insert
                        this tab
    :type after_route: str
    :param before_route: Optional name of a tab before which to insert
                         this tab
    :type before_route: str
    :param tab: Optional
                :attr:`~dallinger.experiment_server.dashboard.DashboardTab`
                instance if you need to provide nested dashboard menus,
                or other tab features.
    :type tab: :attr:`~dallinger.experiment_server.dashboard.DashboardTab`

    :returns: Returns a decorator to register methods from a class as dashboard
              routes.
    """
    registered_routes = DASHBOARD_ROUTE_REGISTRATIONS
    after_route = kwargs.pop("after_route", None)
    before_route = kwargs.pop("before_route", None)
    full_tab = kwargs.pop("tab", None)
    route = {
        "kwargs": tuple(kwargs.items()),
        "title": title,
        "after_route": after_route,
        "before_route": before_route,
        "tab": full_tab,
    }

    return deferred_route_decorator(route, registered_routes)
