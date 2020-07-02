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
            [DashboardTab("Home", "index"), DashboardTab("Second", "dashboard.second")]
        )
        tab_list = list(dashboard_tabs)
        assert len(tab_list) == 2
        assert tab_list[0].title == "Home"
        assert tab_list[0].route_name == "dashboard.index"
        assert tab_list[1].title == "Second"
        assert tab_list[1].route_name == "dashboard.second"

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
                make_login_url.return_value = "http://www.example.net/login"
                response = unauthorized()
                assert response.status_code == 302
                assert response.location == "http://www.example.net/login"
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
        assert 'Welcome User: "{}"'.format(admin_user.id) in resp.data.decode("utf8")

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
    @pytest.fixture
    def fake_mturk_data(self):
        from dallinger.experiment_server.dashboard import FakeMTurkDataSource

        with mock.patch(
            "dallinger.experiment_server.dashboard.mturk_data_source"
        ) as factory:
            fake = FakeMTurkDataSource()
            factory.return_value = fake
            yield fake

    def test_requires_login(self, webapp):
        assert webapp.get("/dashboard/mturk").status_code == 401

    def test_loads_hit_data(self, fake_mturk_data, logged_in):
        resp = logged_in.get("/dashboard/mturk")

        assert resp.status_code == 200
        assert "<td>Fake HIT Title</td>" in resp.data.decode("utf8")

    def test_explains_if_hit_data_not_yet_available(self, fake_mturk_data, logged_in):
        fake_mturk_data._hit = None
        resp = logged_in.get("/dashboard/mturk")

        assert resp.status_code == 200
        assert (
            "HIT data not available until first participant joins."
            in resp.data.decode("utf8")
        )

    def test_shows_error_if_not_using_mturk_recruiter(self, active_config, logged_in):
        active_config.extend({"mode": "live", "recruiter": "cli"})
        resp = logged_in.get("/dashboard/mturk")

        assert resp.status_code == 200
        assert "This experiment does not use the MTurk Recruiter." in resp.data.decode(
            "utf8"
        )


@pytest.mark.usefixtures("experiment_dir_merged")
class TestDashboardMonitorRoute(object):
    def test_requires_login(self, webapp):
        assert webapp.get("/dashboard/monitoring").status_code == 401

    def test_has_statistics(self, logged_in):
        resp = logged_in.get("/dashboard/monitoring")

        assert resp.status_code == 200
        resp_text = resp.data.decode("utf8")
        assert "<h3>Participants</h3>" in resp_text
        assert "<li>working: 0</li>" in resp_text
        assert "<li>active: 0</li>" in resp_text

    def test_statistics_show_working(self, logged_in, db_session):
        from dallinger.models import Participant

        participant = Participant(
            recruiter_id="hotair",
            worker_id="1",
            hit_id="1",
            assignment_id="1",
            mode="test",
        )
        db_session.add(participant)

        resp = logged_in.get("/dashboard/monitoring")

        assert resp.status_code == 200
        resp_text = resp.data.decode("utf8")
        assert "<h3>Participants</h3>" in resp_text
        assert "<li>working: 1</li>" in resp_text


@pytest.mark.usefixtures("experiment_dir_merged", "webapp")
class TestDashboardNetworkStructure(object):
    @pytest.fixture
    def multinetwork_experiment(self, a, db_session):
        from dallinger.experiment_server.experiment_server import Experiment
        from dallinger.models import Network

        exp = Experiment(db_session)

        network = Network.query.all()[0]
        network2 = a.network(role="test")
        a.participant(
            recruiter_id="hotair",
            worker_id="1",
            hit_id="1",
            assignment_id="1",
            mode="test",
        )
        source = a.source(network=network)
        source2 = a.source(network=network2)
        info1 = a.info(origin=source, contents="contents1")
        info2 = a.info(origin=source, contents="contents2")
        info3 = a.info(origin=source2, contents="contents3")
        info4 = a.info(origin=source2, contents="contents3")
        a.transformation(info_in=info1, info_out=info2)
        a.transformation(info_in=info3, info_out=info4)
        yield exp

    def test_network_structure(self, a, db_session):
        from dallinger.experiment_server.experiment_server import Experiment
        from dallinger.models import Network

        exp = Experiment(db_session)

        network = Network.query.all()[0]

        network_structure = exp.network_structure()
        assert len(network_structure["networks"]) == 1
        assert network_structure["networks"][0]["id"] == network.id
        assert network_structure["networks"][0]["role"] == network.role
        assert len(network_structure["nodes"]) == 0
        assert len(network_structure["vectors"]) == 0
        assert len(network_structure["infos"]) == 0
        assert len(network_structure["participants"]) == 0
        assert len(network_structure["trans"]) == 0

        source = a.source(network=network)

        network_structure = exp.network_structure()
        assert len(network_structure["nodes"]) == 1
        assert network_structure["nodes"][0]["type"] == source.type

        # Transformations are not included by default
        info1 = a.info(origin=source, contents="contents1")
        info2 = a.info(origin=source, contents="contents2")
        a.transformation(info_in=info1, info_out=info2)

        network_structure = exp.network_structure()
        assert len(network_structure["nodes"]) == 1
        assert len(network_structure["infos"]) == 2
        assert len(network_structure["trans"]) == 0

        network_structure = exp.network_structure(transformations="on")
        assert len(network_structure["trans"]) == 1

    def test_network_structure_multinetwork(self, multinetwork_experiment):
        network_structure = multinetwork_experiment.network_structure(
            transformations="on"
        )
        assert len(network_structure["networks"]) == 2
        assert len(network_structure["nodes"]) == 2
        assert len(network_structure["infos"]) == 4
        assert len(network_structure["participants"]) == 1
        assert len(network_structure["trans"]) == 2

    def test_network_structure_collapsed(self, multinetwork_experiment):
        network_structure = multinetwork_experiment.network_structure(
            transformations="on", collapsed="on"
        )
        assert len(network_structure["networks"]) == 2
        assert len(network_structure["nodes"]) == 2
        assert len(network_structure["trans"]) == 0
        assert len(network_structure["infos"]) == 0
        assert len(network_structure["participants"]) == 0

    def test_network_structure_filter_roles(self, multinetwork_experiment):
        network_structure = multinetwork_experiment.network_structure(
            transformations="on", network_roles=["test"]
        )
        assert len(network_structure["networks"]) == 1
        assert network_structure["networks"][0]["id"] == 2
        assert len(network_structure["nodes"]) == 1
        assert network_structure["nodes"][0]["id"] == 2
        assert len(network_structure["infos"]) == 2
        assert {i["id"] for i in network_structure["infos"]} == {3, 4}
        assert len(network_structure["participants"]) == 1
        assert len(network_structure["trans"]) == 1
        assert network_structure["trans"][0]["id"] == 2

    def test_network_structure_filter_ids(self, multinetwork_experiment):
        network_structure = multinetwork_experiment.network_structure(
            transformations="on", network_ids=["1"]
        )
        assert len(network_structure["networks"]) == 1
        assert network_structure["networks"][0]["id"] == 1
        assert len(network_structure["nodes"]) == 1
        assert network_structure["nodes"][0]["id"] == 1
        assert len(network_structure["infos"]) == 2
        assert {i["id"] for i in network_structure["infos"]} == {1, 2}
        assert len(network_structure["participants"]) == 1
        assert len(network_structure["trans"]) == 1
        assert network_structure["trans"][0]["id"] == 1

    def test_network_structure_filter_multiple(self, multinetwork_experiment):
        network_structure = multinetwork_experiment.network_structure(
            transformations="on", network_ids=[2], network_roles=["test"]
        )
        assert len(network_structure["networks"]) == 1
        assert network_structure["networks"][0]["id"] == 2
        assert len(network_structure["nodes"]) == 1
        assert network_structure["nodes"][0]["id"] == 2
        assert len(network_structure["infos"]) == 2
        assert {i["id"] for i in network_structure["infos"]} == {3, 4}
        assert len(network_structure["participants"]) == 1
        assert len(network_structure["trans"]) == 1
        assert network_structure["trans"][0]["id"] == 2

        # Parameters may yield no results
        network_structure = multinetwork_experiment.network_structure(
            transformations="on", network_ids=[1], network_roles=["test"]
        )
        assert len(network_structure["networks"]) == 0
        assert len(network_structure["nodes"]) == 0
        assert len(network_structure["infos"]) == 0
        assert len(network_structure["participants"]) == 1
        assert len(network_structure["trans"]) == 0
