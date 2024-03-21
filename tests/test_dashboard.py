# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import codecs
from unittest import mock

import pytest

from dallinger.experiment_server.dashboard import DashboardTab


class TestDashboardTabs(object):
    @pytest.fixture
    def cleared_tab_routes(self):
        from dallinger.experiment_server import dashboard

        routes = dashboard.DASHBOARD_ROUTE_REGISTRATIONS
        orig_routes = routes[:]
        routes.clear()
        yield routes
        routes[:] = orig_routes

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

    def test_deferred_tab_decorator(self, cleared_tab_routes):
        from dallinger.experiment_server.dashboard import dashboard_tab

        decorator = dashboard_tab(
            "My Dashboard",
            before_route="network",
            methods=["POST", "GET"],
        )
        assert len(cleared_tab_routes) == 0

        def fake_route():
            pass

        # Decorator does not modify or wrap the function
        assert decorator(fake_route) is fake_route
        assert len(cleared_tab_routes) == 1
        assert cleared_tab_routes[0] == {
            "title": "My Dashboard",
            "before_route": "network",
            "after_route": None,
            "tab": None,
            "kwargs": (("methods", ["POST", "GET"]),),
            "func_name": "fake_route",
        }


class TestDashboard(object):
    @pytest.fixture
    def admin_user(self):
        from dallinger.experiment_server import experiment_server
        from dallinger.experiment_server.dashboard import User

        with experiment_server.app.app_context():
            with mock.patch("dallinger.experiment_server.dashboard.current_app") as app:
                admin_user = User("admin", "DUMBPASSWORD")
                app.config = {
                    "ADMIN_USER": admin_user,
                    "SECRET_KEY": "FLASK_SECRET",
                }
                yield admin_user

    def test_load_user(self, admin_user):
        from dallinger.experiment_server.dashboard import load_user

        assert load_user("admin") is admin_user
        assert load_user("user") is None

    @staticmethod
    def create_request(*args, **kw):
        from werkzeug.test import create_environ
        from werkzeug.wrappers import Request

        environ = create_environ(*args, **kw)
        request = Request(environ)
        return request

    def test_load_user_from_empty_request(self, admin_user):
        from dallinger.experiment_server.dashboard import load_user_from_request

        assert (
            load_user_from_request(
                self.create_request("/dashboard", "http://localhost/")
            )
            is None
        )

    def test_load_user_with_wrong_user(self, admin_user):
        from dallinger.experiment_server.dashboard import load_user_from_request

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

    def test_load_user_with_bad_password(self, admin_user):
        from dallinger.experiment_server.dashboard import load_user_from_request

        bad_password = (
            codecs.encode(b"admin:password", "base64").strip().decode("ascii")
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

    def test_load_user_from_request(self, env, admin_user):
        from dallinger.experiment_server.dashboard import load_user_from_request

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

    def test_unauthorized_debug_mode(self, active_config, env):
        from werkzeug.exceptions import Unauthorized

        from dallinger.experiment_server.dashboard import unauthorized

        active_config.set("mode", "debug")

        with pytest.raises(Unauthorized):
            unauthorized()

    def test_unauthorized_redirects(self, active_config, env):
        from dallinger.experiment_server import experiment_server
        from dallinger.experiment_server.dashboard import unauthorized

        active_config.set("mode", "sandbox")
        with experiment_server.app.test_request_context():
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
def mock_renderer(webapp_admin):
    with mock.patch(
        "dallinger.experiment_server.dashboard.render_template"
    ) as renderer:
        renderer.return_value = ""
        yield webapp_admin, renderer


@pytest.mark.usefixtures("experiment_dir_merged")
class TestDashboardCoreRoutes(object):
    def test_debug_dashboad_unauthorized(self, webapp):
        resp = webapp.get("/dashboard/")
        assert resp.status_code == 401

    def test_nondebug_dashboad_redirects_to_login(self, webapp, active_config):
        active_config.set("mode", "sandbox")
        resp = webapp.get("/dashboard/")
        assert resp.status_code == 302
        assert resp.location.endswith("/login?next=%2Fdashboard%2F")

    def test_login_bad_password(self, csrf_token, webapp):
        resp = webapp.post(
            "/dashboard/login",
            data={
                "username": "admin",
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

    def test_login_redirects_to_next(self, csrf_token, webapp):
        admin_user = webapp.application.config["ADMIN_USER"]
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

    def test_login_rejects_malicious_urls(self, csrf_token, webapp):
        admin_user = webapp.application.config["ADMIN_USER"]

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

    def test_login_session_retained(self, webapp_admin):
        resp = webapp_admin.get("/dashboard/")
        assert resp.status_code == 200
        assert 'Welcome User: "admin"' in resp.data.decode("utf8")

    def test_logout(self, active_config, webapp_admin):
        active_config.set("mode", "sandbox")
        resp = webapp_admin.get("/dashboard/")
        assert resp.status_code == 200

        logout_resp = webapp_admin.get("/dashboard/logout")
        assert logout_resp.status_code == 302

        loggedout_resp = webapp_admin.get("/dashboard/")
        assert loggedout_resp.status_code == 302
        assert loggedout_resp.location.endswith("/dashboard/login?next=%2Fdashboard%2F")

    # Cannot be isolated because route registration happens at import time
    @pytest.mark.xfail
    def test_custom_route(self, webapp_admin):
        resp = webapp_admin.get("/dashboard/custom_dashboard")
        assert resp.status_code == 200
        assert "A custom dashboard for TestExperiment." in resp.data.decode("utf8")

    # Cannot be isolated because route registration happens at import time
    @pytest.mark.xfail
    def test_custom_route_requires_login(self, webapp):
        resp = webapp.get("/dashboard/custom_dashboard")
        assert resp.status_code == 401

    # Cannot be isolated because route registration happens at import time
    @pytest.mark.xfail
    def test_custom_route_tabs(self, webapp_admin):
        tabs = webapp_admin.application.config["dashboard_tabs"]
        tab_titles = [t.title for t in tabs]
        # Inserted after "monitoring"
        assert "Custom Tab" in tab_titles
        index = tab_titles.index("Custom Tab")
        assert tab_titles[index - 1] == "Monitoring"


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

    def test_loads_hit_data(self, fake_mturk_data, webapp_admin):
        resp = webapp_admin.get("/dashboard/mturk")

        assert resp.status_code == 200
        assert "<td>Fake HIT Title</td>" in resp.data.decode("utf8")

    def test_explains_if_hit_data_not_yet_available(
        self, fake_mturk_data, webapp_admin
    ):
        fake_mturk_data.current_hit = None
        resp = webapp_admin.get("/dashboard/mturk")

        assert resp.status_code == 200
        assert (
            "HIT data not available until first participant joins."
            in resp.data.decode("utf8")
        )

    def test_shows_error_if_not_using_mturk_recruiter(
        self, active_config, webapp_admin
    ):
        active_config.extend({"mode": "live", "recruiter": "cli"})
        resp = webapp_admin.get("/dashboard/mturk")

        assert resp.status_code == 200
        assert "This experiment does not use the MTurk Recruiter." in resp.data.decode(
            "utf8"
        )

    def test_includes_expire_command_info(self, fake_mturk_data, webapp_admin):
        page = webapp_admin.get("/dashboard/mturk").data.decode("utf8")
        assert (
            'data-content="dallinger expire --sandbox --app TEST_EXPERIMENT_UID"'
            in page
        )


@pytest.mark.usefixtures("experiment_dir_merged", "db_session")
class TestDashboardMonitorRoute(object):
    def test_requires_login(self, webapp):
        assert webapp.get("/dashboard/monitoring").status_code == 401

    def test_has_statistics(self, webapp_admin):
        resp = webapp_admin.get("/dashboard/monitoring")

        assert resp.status_code == 200
        resp_text = resp.data.decode("utf8")
        assert '<h5 class="card-title">Participants</h5>' in resp_text
        assert "<li>working: 0</li>" in resp_text

    def test_statistics_show_working(self, webapp_admin, db_session):
        from dallinger.models import Participant

        participant = Participant(
            recruiter_id="hotair",
            worker_id="1",
            hit_id="1",
            assignment_id="1",
            mode="test",
        )
        db_session.add(participant)

        resp = webapp_admin.get("/dashboard/monitoring")

        assert resp.status_code == 200
        resp_text = resp.data.decode("utf8")
        assert '<h5 class="card-title">Participants</h5>' in resp_text
        assert "<li>working: 1</li>" in resp_text

    def test_custom_vis_options(self, webapp_admin):
        # The HTML is customized using a property on the model class
        with mock.patch(
            "dallinger.experiment.Experiment.node_visualization_options"
        ) as vis_options:
            vis_options.return_value = {"custom_vis_option": 3}
            resp = webapp_admin.get("/dashboard/monitoring")
            assert resp.status_code == 200
            resp_text = resp.data.decode("utf8")
            assert '"custom_vis_option": 3' in resp_text


@pytest.mark.usefixtures("experiment_dir_merged", "webapp")
class TestDashboardNetworkInfo(object):
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
        db_session.commit()
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

    def test_custom_node_html(self, multinetwork_experiment):
        custom_html = multinetwork_experiment.node_visualization_html("Info", 1)
        assert custom_html == ""
        bogus_content = multinetwork_experiment.node_visualization_html("Bogus", 1)
        assert bogus_content == ""
        # The HTML is customized using a property on the model class
        with mock.patch("dallinger.nodes.Source.visualization_html") as node_html:
            custom_html = multinetwork_experiment.node_visualization_html("Node", 1)
            assert custom_html is node_html


@pytest.mark.usefixtures("experiment_dir_merged")
class TestDashboardLifeCycleRoutes(object):
    def test_requires_login(self, webapp):
        assert webapp.get("/dashboard/lifecycle").status_code == 401

    def test_includes_destroy_command(self, active_config, webapp_admin):
        resp = webapp_admin.get("/dashboard/lifecycle")

        app_id = active_config.get("heroku_app_id_root")

        assert resp.status_code == 200
        assert "dallinger destroy --app {}".format(app_id) in resp.data.decode("utf8")

    def test_add_sandbox_option_to_destroy_command(self, active_config, webapp_admin):
        active_config.set("mode", "sandbox")
        resp = webapp_admin.get("/dashboard/lifecycle")

        app_id = active_config.get("heroku_app_id_root")

        assert resp.status_code == 200
        assert "dallinger destroy --sandbox --app {}".format(
            app_id
        ) in resp.data.decode("utf8")


@pytest.mark.usefixtures("experiment_dir_merged")
class TestDashboardHerokuRoutes(object):
    def test_requires_login(self, webapp):
        assert webapp.get("/dashboard/heroku").status_code == 401

    def test_renders_links_for_heroku_services(self, active_config, webapp_admin):
        from dallinger.heroku.tools import HerokuApp

        details = '{"REDIS": {"url": "https://redis-url", "title": "REDIS"}}'
        active_config.set("infrastructure_debug_details", details)
        active_config.set("mode", "sandbox")
        heroku_app = HerokuApp(active_config.get("heroku_app_id_root"))

        resp = webapp_admin.get("/dashboard/heroku")

        assert '<a href="https://redis-url"' in resp.data.decode("utf8")
        assert '<a href="{}"'.format(
            heroku_app.dashboard_metrics_url
        ) in resp.data.decode("utf8")

    def test_shows_no_links_when_not_deployed_to_heroku(
        self, active_config, webapp_admin
    ):
        resp = webapp_admin.get("/dashboard/heroku")
        assert '<a href="https://redis-url"' not in resp.data.decode("utf8")


@pytest.mark.usefixtures("experiment_dir_merged")
class TestDashboardDatabase(object):
    def test_requires_login(self, webapp):
        assert webapp.get("/dashboard/database").status_code == 401

    def test_render(self, active_config, webapp_admin):
        resp = webapp_admin.get("/dashboard/database?table=network")

        assert resp.status_code == 200
        assert "<h1>Database View: Network</h1>" in resp.data.decode("utf8")

    def test_table_data(self, a, db_session):
        from dallinger.experiment_server.experiment_server import Experiment
        from dallinger.models import Network

        exp = Experiment(db_session)

        network = Network.query.all()[0]

        table = exp.table_data(table="network")
        assert len(table["data"]) == 1
        assert table["data"][0]["id"] == network.id
        assert table["data"][0]["role"] == network.role
        assert len(table["columns"]) > 2
        for col in table["columns"]:
            if col["data"] == "role":
                assert col == {"data": "role", "name": "role"}
                break
        else:
            raise KeyError("'role' not in Network columns")

        source = a.source(network=network)

        table = exp.table_data(table="node")
        assert len(table["data"]) == 1
        assert table["data"][0]["id"] == source.id
        assert table["data"][0]["type"] == source.type
        assert len(table["columns"]) > 2
        for col in table["columns"]:
            if col["data"] == "id":
                assert col == {"data": "id", "name": "id"}
                break
        else:
            raise KeyError("'id' not in Node columns")

        p = a.participant()
        table = exp.table_data(table="participant")
        assert len(table["data"]) == 1
        assert table["data"][0]["id"] == p.id
        assert table["data"][0]["type"] == p.type
        assert table["data"][0]["worker_id"] == p.worker_id
        assert table["data"][0]["recruiter"] == p.recruiter_id
        assert len(table["columns"]) == len(table["data"][0])

    def test_prep_datatables_options_renders_dicts(self):
        from dallinger.experiment_server.dashboard import prep_datatables_options

        table_data = {
            "data": [{"col1": {"something": "else"}}],
            "columns": [{"data": "col1", "name": "col1"}],
        }
        datatables_options = prep_datatables_options(table_data)
        row0 = datatables_options["data"][0]
        assert len(row0) == 2
        assert row0["col1"] == '{"something": "else"}'
        assert row0["col1_display"] == '<code>{\n "something": "else"\n}</code>'

        col_info = datatables_options["columns"][0]
        assert col_info["name"] == "col1"
        assert col_info["data"] == {
            "_": "col1",
            "filter": "col1",
            "display": "col1_display",
        }
        assert col_info["searchPanes"]["orthogonal"] == {
            "display": "filter",
            "sort": "filter",
            "search": "filter",
            "type": "type",
        }

    def test_prep_datatables_options_renders_lists(self):
        from dallinger.experiment_server.dashboard import prep_datatables_options

        table_data = {
            "data": [{"col1": [1, 2, "three"]}],
            "columns": [{"data": "col1", "name": "col1"}],
        }
        datatables_options = prep_datatables_options(table_data)
        row0 = datatables_options["data"][0]
        assert len(row0) == 2
        assert row0["col1"] == '[1, 2, "three"]'
        assert row0["col1_display"] == '<code>[1, 2, "three"]</code>'

        col_info = datatables_options["columns"][0]
        assert col_info["name"] == "col1"
        assert col_info["data"] == {
            "_": "col1",
            "filter": "col1",
            "display": "col1_display",
        }
        assert col_info["searchPanes"]["orthogonal"] == {
            "display": "filter",
            "sort": "filter",
            "search": "filter",
            "type": "type",
        }

    def test_prep_datatables_options_renders_mixed(self):
        from dallinger.experiment_server.dashboard import prep_datatables_options

        # Mixed data all gets treated as JSON
        table_data = {
            "data": [
                {"col1": [1, 2, "three"]},
                {"col1": {"a": "b"}},
                {"col1": "String 3"},
            ],
            "columns": [{"data": "col1", "name": "col1"}],
        }
        datatables_options = prep_datatables_options(table_data)

        col_info = datatables_options["columns"][0]
        assert col_info["name"] == "col1"
        assert col_info.get("render") is None
        assert col_info["data"] == {
            "_": "col1",
            "filter": "col1",
            "display": "col1_display",
        }
        assert col_info["searchPanes"]["orthogonal"] == {
            "display": "filter",
            "sort": "filter",
            "search": "filter",
            "type": "type",
        }

        row0 = datatables_options["data"][0]
        assert row0["col1"] == '[1, 2, "three"]'
        assert row0["col1_display"] == '<code>[1, 2, "three"]</code>'

        row1 = datatables_options["data"][1]
        assert len(row1) == 2
        # Dict values get JSON serialized so SearchPanes can process them
        assert row1["col1"] == '{"a": "b"}'
        assert row1["col1_display"] == '<code>{\n "a": "b"\n}</code>'

        row2 = datatables_options["data"][2]
        assert len(row1) == 2
        assert row2["col1"] == "String 3"
        assert row2["col1_display"] == "String 3"

    def test_prep_datatables_options_escapes_html(self):
        from dallinger.experiment_server.dashboard import prep_datatables_options

        # Mixed data all gets treated as JSON
        table_data = {
            "data": [
                {"col1": [1, 2, "<span>three</span>"]},
                {"col1": {"<blink>a</blink>": "</td></tr></tbody></table>b"}},
                {"col1": "<script>alert();</script>"},
            ],
            "columns": [{"data": "col1", "name": "col1"}],
        }
        datatables_options = prep_datatables_options(table_data)

        col_info = datatables_options["columns"][0]
        assert col_info["name"] == "col1"
        assert col_info.get("render") is None
        assert col_info["data"] == {
            "_": "col1",
            "filter": "col1",
            "display": "col1_display",
        }
        assert col_info["searchPanes"]["orthogonal"] == {
            "display": "filter",
            "sort": "filter",
            "search": "filter",
            "type": "type",
        }

        row0 = datatables_options["data"][0]
        assert row0["col1"] == '[1, 2, "<span>three</span>"]'
        assert (
            row0["col1_display"]
            == '<code>[1, 2, "&lt;span&gt;three&lt;/span&gt;"]</code>'
        )

        row1 = datatables_options["data"][1]
        assert len(row1) == 2
        # Dict values get JSON serialized so SearchPanes can process them
        assert row1["col1"] == '{"<blink>a</blink>": "</td></tr></tbody></table>b"}'
        assert (
            row1["col1_display"]
            == '<code>{\n "&lt;blink&gt;a&lt;/blink&gt;": "&lt;/td&gt;&lt;/tr&gt;&lt;/tbody&gt;&lt;/table&gt;b"\n}</code>'
        )

        row2 = datatables_options["data"][2]
        assert len(row1) == 2
        assert row2["col1"] == "<script>alert();</script>"
        assert row2["col1_display"] == "&lt;script&gt;alert();&lt;/script&gt;"

    def test_database_output(self, a, active_config, mock_renderer):
        import json

        webapp, renderer = mock_renderer
        p = a.participant()
        webapp.get("/dashboard/database?table=participant")
        renderer.assert_called_once()
        render_args = renderer.call_args[1]
        dt_options = json.loads(render_args["datatables_options"])
        # We have two sets of buttons, exports and actions
        exports = dt_options["buttons"][0]
        actions = dt_options["buttons"][1]
        assert actions["text"] == "Actions"
        assert exports["text"] == "Export"
        # We are using a recruiter where compensation isn't possible
        assert render_args["is_sandbox"] is None
        assert "compensate" not in dt_options["buttons"][1]["buttons"]
        # We have one route based action
        assert actions["buttons"][0] == {
            "extend": "route_action",
            "text": "Fail Selected",
            "route_name": "dashboard_fail",
        }
        # We have a custom JSON export action
        assert "export_json" in exports["buttons"]

        # Let's look at the data
        data = dt_options["data"]
        assert len(data) == 1
        participant_data = data[0]
        assert participant_data["id"] == p.id
        assert participant_data["object_type"] == "Participant"
        assert participant_data["assignment_id"] == p.assignment_id

    def test_actions_with_mturk(self, a, active_config, mock_renderer):
        webapp, renderer = mock_renderer
        active_config.extend({"mode": "live", "recruiter": "mturk"})
        webapp.get("/dashboard/database?table=participant")
        render_args = renderer.call_args[1]
        assert render_args["is_sandbox"] is False

        active_config.extend({"mode": "sandbox", "recruiter": "mturk"})
        webapp.get("/dashboard/database?table=participant")
        render_args = renderer.call_args[1]
        assert render_args["is_sandbox"] is True

    def test_output_with_custom_actions(self, a, active_config, mock_renderer):
        import json

        webapp, renderer = mock_renderer
        with mock.patch(
            "dallinger.experiment.Experiment.dashboard_database_actions"
        ) as actions:
            actions.return_value = [
                {"name": "special_action", "title": "Special Action"}
            ]
            webapp.get("/dashboard/database?table=participant")
            render_args = renderer.call_args[1]
            dt_options = json.loads(render_args["datatables_options"])
            actions = dt_options["buttons"][1]
            assert actions["buttons"] == [
                {
                    "extend": "route_action",
                    "text": "Special Action",
                    "route_name": "special_action",
                }
            ]


@pytest.mark.usefixtures("experiment_dir_merged")
class TestDashboardDatabaseActions(object):
    def test_action_routes_require_login(self, webapp):
        assert (
            webapp.post("/dashboard/database/action/dashboard_fail").status_code == 401
        )

    def test_disallowed_action(self, webapp_admin):
        resp = webapp_admin.post("/dashboard/database/action/evil_action", json={})
        resp.status_code == 403
        assert resp.json["status"] == "error"
        assert "Access to evil_action not allowed" in resp.json["html"]

    def test_missing_action(self, webapp_admin):
        with mock.patch(
            "dallinger.experiment.Experiment.dashboard_database_actions"
        ) as actions:
            actions.return_value = [
                {"name": "missing_action", "title": "Missing Action"}
            ]
            resp = webapp_admin.post(
                "/dashboard/database/action/missing_action", json={}
            )
            resp.status_code == 404
            assert resp.json["status"] == "error"
            assert "Method missing_action not found" in resp.json["html"]

    def test_custom_action(self, webapp_admin):
        from dallinger.experiment import Experiment

        with mock.patch.object(Experiment, "dashboard_database_actions") as actions:
            actions.return_value = [
                {"name": "custom_test_action", "title": "Custom Action"}
            ]
            Experiment.custom_test_action = mock.Mock("Custom Action")
            Experiment.custom_test_action.return_value = {"message": "Way to go!"}
            resp = webapp_admin.post(
                "/dashboard/database/action/custom_test_action", json=[]
            )
            del Experiment.custom_test_action
        resp.status_code == 200
        assert resp.json == {"status": "success", "message": "Way to go!"}

    def test_fail_route(self, webapp_admin):
        resp = webapp_admin.post(
            "/dashboard/database/action/dashboard_fail",
            json=[{"id": 1, "object_type": "Participant"}],
        )
        resp.status_code == 200
        assert resp.json == {"status": "success", "message": "No nodes found to fail"}

    def test_fail_route_fails_participant(self, webapp_admin, a, db_session):
        p = a.participant()
        p_id = p.id
        assert p.failed is False
        resp = webapp_admin.post(
            "/dashboard/database/action/dashboard_fail",
            json=[{"id": p_id, "object_type": "Participant"}],
        )
        resp.status_code == 200
        assert resp.json == {"status": "success", "message": "Failed 1 Participants"}
        from dallinger.models import Participant

        p = db_session.query(Participant).get(p_id)
        assert p.failed is True
