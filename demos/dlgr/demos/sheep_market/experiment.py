"""Bartlett's trasmission chain experiment from Remembering (1932)."""

from dallinger.networks import Empty
from dallinger.experiment import Experiment
from dallinger.models import Info
from jinja2 import TemplateNotFound
from flask import (
    abort,
    Blueprint,
    jsonify,
    render_template
)
import json


class SheepMarket(Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session=None):
        """Call the same function in the super (see experiments.py in dallinger).

        A few properties are then overwritten.
        Finally, setup() is called.
        """
        super(SheepMarket, self).__init__(session)
        self.experiment_repeats = 1
        self.initial_recruitment = 10000
        if session:
            self.setup()

    def create_network(self):
        """Return a new network."""
        return Empty(max_size=10000)


extra_routes = Blueprint(
    'extra_routes',
    __name__,
    template_folder='templates',
    static_folder='static')


@extra_routes.route('/drawings')
def getdrawings():
    """Get all the drawings."""
    infos = Info.query.all()
    sketches = [json.loads(info.contents) for info in infos]
    return jsonify(drawings=sketches)


@extra_routes.route('/gallery')
def viewdrawings():
    """Render the gallery."""
    try:
        return render_template('gallery.html')
    except TemplateNotFound:
        abort(404)
