import os

import jinja2

import dallinger

TEMPLATES_DIR = os.path.join(
    os.path.dirname(dallinger.__file__), "frontend", "templates"
)
JQUERY = "scripts/jquery-3.7.1.min.js"


def render(child_template):
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
