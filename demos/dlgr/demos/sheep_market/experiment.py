"""The Sheep Market."""

import json

from flask import abort, jsonify, render_template
from jinja2 import TemplateNotFound

from dallinger.experiment import Experiment, experiment_route
from dallinger.models import Info
from dallinger.networks import Empty


class SheepMarket(Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session=None):
        """Call the same function in the super (see experiments.py in dallinger).

        A few properties are then overwritten.
        Finally, setup() is called.
        """
        super(SheepMarket, self).__init__(session)
        self.experiment_repeats = 1
        self.initial_recruitment_size = 2
        if session:
            self.setup()

    def create_network(self):
        """Return a new network."""
        return Empty(max_size=2)

    @experiment_route("/drawings")
    @classmethod
    def getdrawings(cls):
        """Get all the drawings."""
        infos = Info.query.all()
        sketches = [json.loads(info.contents) for info in infos]
        return jsonify(drawings=sketches)

    @experiment_route("/gallery")
    @classmethod
    def viewdrawings(cls):
        """Render the gallery."""
        try:
            return render_template("gallery.html")
        except TemplateNotFound:
            abort(404)
