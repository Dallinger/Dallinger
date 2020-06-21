# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import codecs
import mock
import pytest

from dallinger.experiment_server.dashboard import DashboardTab


class TestDashboardTabs(object):
    @pytest.fixture
    def dashboard_tabs(self):
        from dallinger.experiment_server.dashboard import DashboardTabs

        return DashboardTabs([DashboardTab("Home", "dashboard.index")])

    def test_dashboard_iter(self):
        from dallinger.experiment_server.dashboard import DashboardTabs

        dashboard_tabs = DashboardTabs(
            [("Home", "dashboard.index"), ("Second", "dashboard.second")]
        )

        assert list(dashboard_tabs) == [
            ("Home", "dashboard.index"),
            ("Second", "dashboard.second"),
        ]

    def test_dashboard_insert(self, dashboard_tabs):
        dashboard_tabs.insert("Next", "next")
        assert list(dashboard_tabs) == [
            DashboardTab("Home", "dashboard.index"),
            DashboardTab("Next", "dashboard.next"),
        ]

        dashboard_tabs.insert("Previous", "dashboard.previous", 1)
        assert list(dashboard_tabs) == [
            DashboardTab("Home", "dashboard.index"),
            DashboardTab("Previous", "dashboard.previous"),
            DashboardTab("Next", "dashboard.next"),
        ]

    def test_dashboard_insert_before(self, dashboard_tabs):
        dashboard_tabs.insert_before_route("First", "first", "index")
        assert list(dashboard_tabs) == [
            DashboardTab("First", "dashboard.first"),
            DashboardTab("Home", "dashboard.index"),
        ]

        dashboard_tabs.insert_before_route(
            "Second", "dashboard.second", "dashboard.index"
        )
        assert list(dashboard_tabs) == [
            DashboardTab("First", "dashboard.first"),
            DashboardTab("Second", "dashboard.second"),
            DashboardTab("Home", "dashboard.index"),
        ]

    def test_dashboard_insert_after(self, dashboard_tabs):
        dashboard_tabs.insert_after_route("Last", "last", "index")
        assert list(dashboard_tabs) == [
            DashboardTab("Home", "dashboard.index"),
            DashboardTab("Last", "dashboard.last"),
        ]

        dashboard_tabs.insert_after_route(
            "Second", "dashboard.second", "dashboard.index"
        )
        assert list(dashboard_tabs) == [
            DashboardTab("Home", "dashboard.index"),
            DashboardTab("Second", "dashboard.second"),
            DashboardTab("Last", "dashboard.last"),
        ]

    def test_dashboard_remove(self, dashboard_tabs):
        dashboard_tabs.insert("Last", "last")
        assert len(list(dashboard_tabs)) == 2

        dashboard_tabs.remove("last")
        assert list(dashboard_tabs) == [DashboardTab("Home", "dashboard.index")]

        dashboard_tabs.insert("Last", "last")
        assert len(list(dashboard_tabs)) == 2

        dashboard_tabs.remove("dashboard.last")
        assert list(dashboard_tabs) == [DashboardTab("Home", "dashboard.index")]

        dashboard_tabs.remove("index")
        assert len(list(dashboard_tabs)) == 0


class TestDashboard(object):
    def test_load_user(self):
        from dallinger.experiment_server.dashboard import admin_user, load_user

        assert admin_user.id == "admin"
        assert load_user("admin") is admin_user
        assert load_user("user") is None

    @staticmethod
    def create_request(*args, **kw):
        from werkzeug.test import create_environ
        from werkzeug.wrappers import Request

        environ = create_environ(*args, **kw)
        request = Request(environ)
        return request

    def test_load_user_from_empty_request(self):
        from dallinger.experiment_server.dashboard import load_user_from_request

        assert (
            load_user_from_request(
                self.create_request("/dashboard", "http://localhost/")
            )
            is None
        )

    def test_load_user_with_wrong_user(self):
        from dallinger.experiment_server.dashboard import load_user_from_request
        from dallinger.experiment_server.dashboard import admin_user

        bad_credentials = (
            codecs.encode(
                "user:{}".format(admin_user.password).encode("ascii"), "base64"
            )
            .strip()
            .decode("ascii")
        )
        assert (
            load_user_from_request(
                self.create_request(
                    "/dashboard",
                    "http://localhost/",
                    headers={"Authorization": "Basic {}".format(bad_credentials)},
                )
            )
            is None
        )

    def test_load_user_with_bad_password(self):
        from dallinger.experiment_server.dashboard import load_user_from_request
        from dallinger.experiment_server.dashboard import admin_user

        bad_password = (
            codecs.encode("{}:password".format(admin_user.id).encode("ascii"), "base64")
            .strip()
            .decode("ascii")
        )
        assert (
            load_user_from_request(
                self.create_request(
                    "/dashboard",
                    "http://localhost/",
                    headers={"Authorization": "Basic {}".format(bad_password)},
                )
            )
            is None
        )

    def test_load_user_from_request(self):
        from dallinger.experiment_server.dashboard import load_user_from_request
        from dallinger.experiment_server.dashboard import admin_user

        good_credentials = (
            codecs.encode(
                "{}:{}".format(admin_user.id, admin_user.password).encode("ascii"),
                "base64",
            )
            .strip()
            .decode("ascii")
        )
        assert (
            load_user_from_request(
                self.create_request(
                    "/dashboard",
                    "http://localhost/",
                    headers={"Authorization": "Basic {}".format(good_credentials)},
                )
            )
            is admin_user
        )

    def test_unauthorized_debug_mode(self, active_config):
        from werkzeug.exceptions import Unauthorized
        from dallinger.experiment_server.dashboard import unauthorized

        active_config.set("mode", "debug")

        with pytest.raises(Unauthorized):
            unauthorized()

    def test_unauthorized_redirects(self, active_config):
        from dallinger.experiment_server.dashboard import unauthorized

        active_config.set("mode", "sandbox")
        with mock.patch("dallinger.experiment_server.dashboard.request"):
            with mock.patch(
                "dallinger.experiment_server.dashboard.make_login_url"
            ) as make_login_url:
                response = unauthorized()
                assert response.status_code == 302
                assert "<MagicMock name='make_login_url()'" in response.location
                make_login_url.assert_called_once_with(
                    "dashboard.login", next_url=mock.ANY
                )

    def test_safe_url(self):
        from dallinger.experiment_server.dashboard import is_safe_url

        with mock.patch("dallinger.experiment_server.dashboard.url_for") as url_for:
            url_for.side_effect = lambda x: "http://localhost"
            assert is_safe_url("https://evil.org") is False
            assert is_safe_url("http://localhost/") is True
            assert is_safe_url("/") is True


@pytest.fixture
def csrf_token(webapp, active_config):
    # active_config.set("mode", "sandbox")
    # Make a writeable session and copy the csrf token into it
    from flask_wtf.csrf import generate_csrf

    with webapp.application.test_request_context() as request:
        with webapp.session_transaction() as sess:
            token = generate_csrf()
            sess.update(request.session)
    yield token


@pytest.fixture
def logged_in(webapp, csrf_token):
    from dallinger.experiment_server.dashboard import admin_user

    webapp.post(
        "/dashboard/login",
        data={
            "username": admin_user.id,
            "password": admin_user.password,
            "next": "/dashboard/something",
            "submit": "Sign In",
            "csrf_token": csrf_token,
        },
    )
    yield webapp


@pytest.mark.usefixtures("experiment_dir_merged")
class TestDashboardCoreRoutes(object):
    def test_debug_dashboad_unauthorized(self, webapp, active_config):
        resp = webapp.get("/dashboard/")
        assert resp.status_code == 401

    def test_nondebug_dashboad_redirects_to_login(self, webapp, active_config):
        active_config.set("mode", "sandbox")
        resp = webapp.get("/dashboard/")
        assert resp.status_code == 302
        assert resp.location.endswith("/login?next=%2Fdashboard%2F")

    def test_login_bad_password(self, webapp, csrf_token):
        from dallinger.experiment_server.dashboard import admin_user

        resp = webapp.post(
            "/dashboard/login",
            data={
                "username": admin_user.id,
                "password": "badpass",
                "next": "/dashboard/",
                "submit": "Sign In",
                "csrf_token": csrf_token,
            },
        )
        # Redirects to login form
        assert resp.status_code == 302
        assert resp.location.endswith("/dashboard/login")
        login_resp = webapp.get("/dashboard/login")
        assert "Invalid username or password" in login_resp.data.decode("utf8")

    def test_login_redirects_to_next(self, webapp, csrf_token):
        from dallinger.experiment_server.dashboard import admin_user

        login_resp = webapp.get("/dashboard/login?next=%2Fdashboard%2F")
        assert login_resp.status_code == 200

        resp = webapp.post(
            "/dashboard/login",
            data={
                "username": admin_user.id,
                "password": admin_user.password,
                "next": "/dashboard/something",
                "submit": "Sign In",
                "csrf_token": csrf_token,
            },
        )
        assert resp.status_code == 302
        assert resp.location.endswith("/dashboard/something")

    def test_login_rejects_malicious_urls(self, webapp, csrf_token):
        from dallinger.experiment_server.dashboard import admin_user

        resp = webapp.post(
            "/dashboard/login",
            data={
                "username": admin_user.id,
                "password": admin_user.password,
                "next": "https://evil.org/",
                "submit": "Sign In",
                "csrf_token": csrf_token,
            },
        )
        assert resp.status_code == 302
        assert resp.location.endswith("/dashboard/index")

    def test_login_session_retained(self, logged_in):
        from dallinger.experiment_server.dashboard import admin_user

        resp = logged_in.get("/dashboard/")
        assert resp.status_code == 200
        assert "Welcome User: {}".format(admin_user.id) in resp.data.decode("utf8")

    def test_logout(self, active_config, logged_in):
        active_config.set("mode", "sandbox")
        resp = logged_in.get("/dashboard/")
        assert resp.status_code == 200

        logout_resp = logged_in.get("/dashboard/logout")
        assert logout_resp.status_code == 302

        loggedout_resp = logged_in.get("/dashboard/")
        assert loggedout_resp.status_code == 302
        assert loggedout_resp.location.endswith("/dashboard/login?next=%2Fdashboard%2F")


@pytest.mark.usefixtures("experiment_dir_merged")
class TestDashboardMTurkRoutes(object):
    def test_requires_login(self, webapp):
        assert webapp.get("/dashboard/mturk").status_code == 401

    def test_loads_with_fake_data_in_debug_mode(self, logged_in):
        resp = logged_in.get("/dashboard/mturk")

        assert resp.status_code == 200
        assert "<h1>MTurk Dashboard</h1>" in resp.data.decode("utf8")
