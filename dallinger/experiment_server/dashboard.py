import logging
import os
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


class DashboardTabs(object):
    tabs = ()

    def __init__(self, tabs):
        self.tabs = tabs or []

    def insert(self, title, route_name, position=None):
        if not route_name.startswith("dashboard."):
            route_name = "dashboard." + route_name
        if position is None:
            self.tabs.append((title, route_name))
        else:
            self.tabs.insert(position, (title, route_name))

    def insert_before_route(self, title, route_name, before_route):
        before_check = frozenset((before_route, "dashboard." + before_route))
        for i, (t, r) in enumerate(self.tabs):
            if r in before_check:
                position = i
                break
        else:
            raise ValueError("Route {} not found".format(before_route))
        self.insert(title, route_name, position)

    def insert_after_route(self, title, route_name, after_route):
        after_check = frozenset((after_route, "dashboard." + after_route))
        for i, (t, r) in enumerate(self.tabs):
            if r in after_check:
                position = i + 1
                break
        else:
            raise ValueError("Route {} not found".format(after_route))
        self.insert(title, route_name, position)

    def remove(self, route_name):
        route_check = frozenset((route_name, "dashboard." + route_name))
        self.tabs = [t for t in self.tabs if t[1] not in route_check]

    def __iter__(self):
        for title, route_name in self.tabs:
            yield (title, route_name)


dashboard_tabs = DashboardTabs([("Home", "dashboard.index")])


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
    return render_template("dashboard_home.html", title="Home")
