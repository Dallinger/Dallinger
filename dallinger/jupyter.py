from ipywidgets import widgets
from jinja2 import Template
from traitlets import observe, Unicode

from dallinger.config import get_config

header_template = Template(
    """
<h2>{{ name }}</h2>
<div>Status: {{ status }}</div>
{% if app_id %}<div>App ID: {{ app_id }}</div>{% endif %}
"""
)

config_template = Template(
    """
<table style="min-width: 50%">
{% for k, v in config %}
<tr>
<th>{{ k }}</th>
<td>{{ v }}</td>
</tr>
{% endfor %}
</table>
"""
)


class ExperimentWidget(widgets.VBox):

    status = Unicode("Unknown")

    def __init__(self, exp):
        self.exp = exp
        super(ExperimentWidget, self).__init__()
        self.render()

    @property
    def config_tab(self):
        config = get_config()
        if config.ready:
            config_items = list(config.as_dict().items())
            config_items.sort()
            config_tab = widgets.HTML(config_template.render(config=config_items))
        else:
            config_tab = widgets.HTML("Not loaded.")
        return config_tab

    @observe("status")
    def render(self, change=None):
        header = widgets.HTML(
            header_template.render(
                name=self.exp.task, status=self.status, app_id=self.exp.app_id
            )
        )

        tabs = widgets.Tab(children=[self.config_tab])
        tabs.set_title(0, "Configuration")
        self.children = [header, tabs]
