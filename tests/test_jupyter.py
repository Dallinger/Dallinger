from unittest import mock

import pytest

try:
    import ipywidgets
except ImportError:
    ipywidgets = None


@pytest.mark.skipif(ipywidgets is None, reason="ipywidgets is not installed")
class TestExperimentWidget(object):
    @pytest.fixture
    def exp(self):
        from dallinger.experiment import Experiment

        return Experiment()

    def test_experiment_initializes_widget(self, exp):
        assert exp.widget is not None

    def test_experiment_updates_widget_status(self, exp):
        exp.update_status("Testing")
        assert exp.widget.status == "Testing"
        assert "Testing" in exp.widget.children[0].value

    def test_experiment_displays_widget(self, exp):
        with mock.patch("IPython.display.display") as display:
            exp._ipython_display_()
            display.assert_called_once_with(exp.widget)

    def test_widget_children_no_config(self, exp):
        assert exp.widget.children[1].children[0].value == "Not loaded."

    def test_widget_children_with_config(self, active_config, exp):
        assert exp.widget.children[1].children[0].value != "Not loaded."
