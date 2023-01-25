import os.path

from dallinger.config import get_config
from dallinger.experiment import Experiment, experiment_route
from dallinger.experiment_server.dashboard import dashboard_tab


class TestExperiment(Experiment):
    _completed = None

    def __init__(self, session=None):
        try:
            super(TestExperiment, self).__init__(session)
        except TypeError:
            self.practice_repeats = 0
            self.verbose = True
            if session:
                self.session = session
                self.configure()
        self.experiment_repeats = 1
        self.quorum = 1
        if session:
            self.setup()

    @classmethod
    def extra_parameters(cls):
        config = get_config()
        config.register("custom_parameter2", bool, [])

    @classmethod
    def config_defaults(cls):
        return {"duration": 12345.0}

    @property
    def public_properties(self):
        return {"exists": True}

    def create_network(self):
        """Return a new network."""
        from dallinger.networks import Star

        return Star(max_size=2)

    def is_complete(self):
        config = get_config()
        return config.get("_is_completed", None)

    @classmethod
    def test_task(cls):
        return True

    @experiment_route("/custom_route")
    @classmethod
    def custom_route(cls):
        return "A custom route for {}.".format(cls.__name__)

    @dashboard_tab("Custom Tab", after_route="monitoring")
    @classmethod
    def custom_dashboard(cls):
        return "A custom dashboard for {}.".format(cls.__name__)


class ZSubclassThatSortsLower(TestExperiment):
    @classmethod
    def extra_files(cls):
        return [
            (os.path.realpath(__file__), "/static/different.txt"),
            (
                os.path.join(os.path.dirname(os.path.realpath(__file__)), "templates"),
                "/static/different",
            ),
        ]


def extra_parameters():
    config = get_config()
    config.register("custom_parameter", int, [])
    config.register("_is_completed", bool, [])


def extra_files():
    return [
        (os.path.realpath(__file__), "/static/expfile.txt"),
        (
            os.path.join(os.path.dirname(os.path.realpath(__file__)), "templates"),
            "/static/copied_templates",
        ),
    ]
