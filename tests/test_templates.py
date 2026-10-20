import os
from types import SimpleNamespace

import jinja2

import dallinger

TEMPLATES_DIR = os.path.join(
    os.path.dirname(dallinger.__file__), "frontend", "templates"
)
JQUERY = "scripts/jquery-4.0.0.min.js"
SESSION_SCRIPT = "scripts/dallinger-realtime.js"


def render(child_template, realtime_games=(), has_experiment=True):
    environment = jinja2.Environment(
        loader=jinja2.ChoiceLoader(
            [
                jinja2.DictLoader({"child.html": child_template}),
                jinja2.FileSystemLoader(TEMPLATES_DIR),
            ]
        )
    )
    environment.globals.update(
        url_for=lambda endpoint, filename: f"/static/{filename}",
        get_from_config=lambda key: None,
        # None matches a deployment that is not using idle hibernation.
        presence_settings=lambda: None,
    )
    if has_experiment:
        environment.globals["experiment"] = SimpleNamespace(
            realtime_games=list(realtime_games)
        )
    return environment.get_template("child.html").render()


def test_layout_loads_jquery_before_dallinger_scripts():
    html = render('{% extends "base/layout.html" %}')
    assert html.count(JQUERY) == 1
    assert html.index(JQUERY) < html.index("scripts/dallinger2.js")


def test_layout_lets_child_templates_omit_jquery():
    html = render(
        '{% extends "base/layout.html" %}'
        "{% block jquery %}{% endblock %}"
        "{% block libs %}{{ super() }}<script>child</script>{% endblock %}"
    )
    assert JQUERY not in html
    assert "scripts/dallinger2.js" in html
    assert "<script>child</script>" in html


def test_layout_loads_the_session_script_after_dallinger2_for_game_types():
    html = render('{% extends "base/layout.html" %}', realtime_games=[object])
    assert html.count(SESSION_SCRIPT) == 1
    assert html.index("scripts/dallinger2.js") < html.index(SESSION_SCRIPT)


def test_layout_leaves_out_the_session_script_without_game_types():
    html = render('{% extends "base/layout.html" %}')
    assert SESSION_SCRIPT not in html


def test_layout_renders_without_an_experiment_in_its_context():
    html = render('{% extends "base/layout.html" %}', has_experiment=False)
    assert "scripts/dallinger2.js" in html
    assert SESSION_SCRIPT not in html
