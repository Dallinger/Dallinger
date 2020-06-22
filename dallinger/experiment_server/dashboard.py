import json
import logging
import os
import six
from datetime import datetime
from six.moves.urllib.parse import urlencode
from faker import Faker
from flask import Blueprint
from flask import abort, flash, redirect, render_template, request, url_for
from flask.wrappers import Response
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField, HiddenField
from wtforms.validators import DataRequired, ValidationError
from flask_login import current_user, login_required, login_user, logout_user
from flask_login import UserMixin
from flask_login.utils import login_url as make_login_url
from dallinger import recruiters
from dallinger.config import get_config


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
        self.title = title
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
        self.tabs = tabs or []

    def insert(self, title, route_name, position=None):
        """Insert a new dashboard tab (optionally at a specific position)

        :param title: Title string to appear in the dashboard HTML
        :type title: str
        :param route_name: The registered route name (optionally prefixed with ``dashboard.``)
        :type route_name: str
        :param position: The 0-based index where the tab should be inserted. By default tabs will be appended to the end.
        :type position: int, optional

        """
        if not route_name.startswith("dashboard."):
            route_name = "dashboard." + route_name
        if position is None:
            self.tabs.append(DashboardTab(title, route_name))
        else:
            self.tabs.insert(position, DashboardTab(title, route_name))

    def insert_before_route(self, title, route_name, before_route):
        """Insert a new dashboard tab before an existing tab by route name

        :param title: Title string to appear in the dashboard HTML
        :type title: str
        :param route_name: The registered route name (optionally prefixed with ``dashboard.``)
        :type route_name: str
        :param before_route: The route name to insert this tab before.
        :type before_route: str
        :raises ValueError: When ``before_route`` is not found in registered tabs

        """
        before_check = frozenset((before_route, "dashboard." + before_route))
        for i, tab in enumerate(self.tabs):
            if tab.route_name in before_check:
                position = i
                break
        else:
            raise ValueError("Route {} not found".format(before_route))
        self.insert(title, route_name, position)

    def insert_after_route(self, title, route_name, after_route):
        """Insert a new dashboard tab after an existing tab by route name

        :param title: Title string to appear in the dashboard HTML
        :type title: str
        :param route_name: The registered route name (optionally prefixed with ``dashboard.``)
        :type route_name: str
        :param after_route: The route name to insert this tab after.
        :type after_route: str
        :raises ValueError: When ``after_route`` is not found in registered tabs

        """
        after_check = frozenset((after_route, "dashboard." + after_route))
        for i, tab in enumerate(self.tabs):
            if tab.route_name in after_check:
                position = i + 1
                break
        else:
            raise ValueError("Route {} not found".format(after_route))
        self.insert(title, route_name, position)

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


class NotUsingMTurkRecruiter(Exception):
    """The experiment does not use the MTurk Recruiter"""


class MTurkDataSource(object):
    def __init__(self, recruiter):
        self._recruiter = recruiter
        try:
            self._mturk = recruiter.mturkservice
        except AttributeError:
            raise NotUsingMTurkRecruiter()

    def account_balance(self):
        return self._mturk.account_balance()

    def current_hit(self):
        hit_id = self._recruiter.current_hit_id()
        if hit_id is not None:
            return self._mturk.get_hit(hit_id)


_fake_hit_data = {
    "annotation": None,
    "assignments_available": 1,
    "assignments_completed": 0,
    "assignments_pending": 0,
    "created": datetime(2018, 1, 1, 1, 26, 52, 54000),
    "description": "Fake HIT Description",
    "expiration": datetime(2018, 1, 1, 1, 27, 26, 54000),
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
    def __init__(self):
        self._hit = _fake_hit_data.copy()

    def account_balance(self):
        return 1234.5

    def current_hit(self):
        return self._hit


class MTurkDashboardInformation(object):
    def __init__(self, data_source):
        self._source = data_source

    @property
    def hit_info(self):
        hit = self._source.current_hit()
        if hit is not None:
            return {
                "HIT title": hit["title"],
                "HIT keywords": ", ".join(hit["keywords"]),
                "HIT base payment": "${:.2f}".format(hit["reward"]),
                "HIT description": hit["description"],
                "HIT creation time": hit["created"],
                "HIT expiration time": hit["expiration"],
                "HIT max assignments": hit["max_assignments"],
                "HIT assignments available": hit["assignments_available"],
                "HIT assignments completed": hit["assignments_completed"],
                "HIT assignments pending": hit["assignments_pending"],
            }

    @property
    def account_balance(self):
        return "${:.2f}".format(self._source.account_balance())


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

    helper = MTurkDashboardInformation(data_source)

    data = {
        "account_balance": helper.account_balance,
        "hit_info": helper.hit_info,
    }

    return render_template("dashboard_mturk.html", title="MTurk Dashboard", data=data)
