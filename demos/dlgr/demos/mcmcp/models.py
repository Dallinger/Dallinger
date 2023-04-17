import json
import random

from sqlalchemy import Boolean
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql.expression import cast

from dallinger.models import Info, Transformation
from dallinger.nodes import Agent, Source


class MCMCPAgent(Agent):
    __mapper_args__ = {"polymorphic_identity": "MCMCP_agent"}

    def update(self, infos):
        info = infos[0]
        self.replicate(info)
        new_info = AnimalInfo(origin=self, contents=info.perturbed_contents())
        Perturbation(info_in=info, info_out=new_info)

    def _what(self):
        infos = self.infos()
        return [i for i in infos if i.chosen][0]


class AnimalSource(Source):
    """A source that transmits animal shapes."""

    __mapper_args__ = {"polymorphic_identity": "animal_source"}

    def create_information(self):
        """Create a new Info.

        transmit() -> _what() -> create_information().
        """
        return AnimalInfo(origin=self, contents=None)


class AnimalInfo(Info):
    """An Info that can be chosen."""

    __mapper_args__ = {"polymorphic_identity": "vector_info"}

    @hybrid_property
    def chosen(self):
        """Use property1 to store whether an info was chosen."""
        try:
            return bool(self.property1)
        except TypeError:
            return None

    @chosen.setter
    def chosen(self, chosen):
        """Assign chosen to property1."""
        self.property1 = repr(chosen)

    @chosen.expression
    def chosen(self):
        """Retrieve chosen via property1."""
        return cast(self.property1, Boolean)

    properties = {
        "foot_spread": [0, 1],
        "body_height": [0.1, 1.5],
        "body_tilt": [-15, 45],
        "tail_length": [0.05, 1.2],
        "tail_angle": [-45, 190],
        "neck_length": [0, 2.5],
        "neck_angle": [90, 180],
        "head_length": [0.05, 0.75],
        "head_angle": [5, 80],
    }

    def __init__(self, origin, contents=None, **kwargs):
        if contents is None:
            data = {}
            for prop, prop_range in self.properties.items():
                data[prop] = random.uniform(prop_range[0], prop_range[1])
            contents = json.dumps(data)

        super(AnimalInfo, self).__init__(origin, contents, **kwargs)

    def perturbed_contents(self):
        """Perturb the given animal."""
        animal = json.loads(self.contents)

        for prop, prop_range in self.properties.items():
            range = prop_range[1] - prop_range[0]
            jittered = animal[prop] + random.gauss(0, 0.1 * range)
            animal[prop] = max(min(jittered, prop_range[1]), prop_range[0])

        return json.dumps(animal)


class Perturbation(Transformation):
    """A perturbation is a transformation that perturbs the contents."""

    __mapper_args__ = {"polymorphic_identity": "perturbation"}
