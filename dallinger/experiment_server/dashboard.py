import json
import logging
import os
import six
import timeago
from datetime import datetime
from datetime import timedelta
from six.moves.urllib.parse import urlencode
from faker import Faker
from flask import Blueprint
from flask import abort, flash, redirect, render_template, request, url_for
from flask.wrappers import Response
from flask_wtf import FlaskForm
from tzlocal import get_localzone
from wtforms import StringField, PasswordField, BooleanField, SubmitField, HiddenField
from wtforms.validators import DataRequired, ValidationError
from flask_login import current_user, login_required, login_user, logout_user
from flask_login import UserMixin
from flask_login.utils import login_url as make_login_url
from dallinger import recruiters
from dallinger.config import get_config
from .utils import date_handler


logger = logging.getLogger(__name__)


class User(UserMixin):
    def __init__(self, userid, password):
        self.id = userid
        self.password = password


admin_user = User(
    userid=os.environ.get("DASHBOARD_USER", "admin"),
    password=os.environ.get("DASHBOARD_PASSWORD") or Faker().password(),
)


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


def heroku_children():
    config = get_config()
    details = config.get("infrastructure_debug_details", six.text_type("{}"))
    details = json.loads(details)

    dlgr_id = "dlgr-" + config.get("id")[:8]
    details["HEROKU"] = {
        "url": "https://dashboard.heroku.com/apps/" + dlgr_id,
        "title": "Heroku dashboard",
        "link": True,
    }

    for pane_id, pane in details.items():
        yield DashboardTab(pane["title"], "dashboard.heroku", None, {"type": pane_id})


dashboard_tabs = DashboardTabs(
    [
        DashboardTab("Home", "dashboard.index"),
        DashboardTab("Heroku", "dashboard.heroku", heroku_children),
        DashboardTab("MTurk", "dashboard.mturk"),
        DashboardTab("Monitoring", "dashboard.monitoring"),
        DashboardTab("Lifecycle", "dashboard.lifecycle"),
    ]
)


def load_user(userid):
    if userid != admin_user.id:
        return
    return admin_user


def load_user_from_request(request):
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
    config = sorted(get_config().as_dict().items())
    return render_template(
        "dashboard_home.html", title="Dashboard Home", configuration=config
    )


@dashboard.route("/heroku")
@login_required
def heroku():
    config = get_config()
    details = config.get("infrastructure_debug_details", six.text_type("{}"))
    details = json.loads(details)

    dlgr_id = "dlgr-" + config.get("id")[:8]
    details["HEROKU"] = {
        "url": "https://dashboard.heroku.com/apps/" + dlgr_id,
        "title": "Heroku dashboard",
        "link": True,
    }

    addon_type = request.args.get("type")
    if addon_type is None:
        addon_type = "HEROKU"
    pane = details.get(addon_type)
    return render_template(
        "dashboard_wrapper.html",
        panes=details,
        title=pane["title"],
        url=pane["url"],
        link=pane.get("link", False),
    )


tz = get_localzone()


def when_with_relative_time(dt):
    now = tz.localize(datetime.now())
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
    "created": tz.localize(datetime.now() - timedelta(minutes=10)),
    "description": "Fake HIT Description",
    "expiration": tz.localize(datetime.now() + timedelta(hours=6)),
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
        sandbox_option = " --sandbox " if self._source.is_sandbox else ""
        return "dallinger expire{}--app {}".format(sandbox_option, app_id)


def mturk_data_source(config):
    recruiter = recruiters.from_config(config)
    try:
        return MTurkDataSource(recruiter)
    except NotUsingMTurkRecruiter:
        if config.get("mode") == "debug":
            flash(
                "Since you're in debug mode, you're seeing fake data for testing.",
                "danger",
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


@dashboard.route("/monitoring")
@login_required
def monitoring():
    from sqlalchemy import distinct, func
    from dallinger.experiment_server.experiment_server import Experiment, session
    from dallinger.models import Network

    exp = Experiment(session)
    panes = exp.monitoring_panels(**request.args.to_dict(flat=False))
    network_structure = exp.network_structure(**request.args.to_dict(flat=False))
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
    )


@dashboard.route("/node_details/<object_type>/<obj_id>")
@login_required
def node_details(object_type, obj_id):
    from dallinger.experiment_server.experiment_server import Experiment, session

    exp = Experiment(session)
    html_data = exp.node_visualization_html(object_type, obj_id)
    return Response(html_data, status=200, mimetype="text/html")


@dashboard.route("/lifecycle")
@login_required
def lifecycle():
    config = get_config()

    data = {
        "id": config.get("id"),
    }

    return render_template(
        "dashboard_cli.html", title="Experiment lifecycle Dashboard", **data
    )
