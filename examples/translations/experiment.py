import wallace
from wallace.experiments import Experiment
from wallace.recruiters import SimulatedRecruiter
from wallace.agents import Agent
from wallace.sources import Source
from wallace.models import Transformation
import requests
import json
import time
import re
import os
import random


class Translations(Experiment):
    def __init__(self, session):
        super(Translations, self).__init__(session)

        self.task = "Translations"
        self.num_agents = 10
        self.num_steps = self.num_agents - 1
        self.network = wallace.networks.Chain(self.session)
        self.process = wallace.processes.RandomWalkFromSource(self.network)
        self.agent_type = SimulatedAgent
        self.recruiter = SimulatedRecruiter

        # Setup for first time experiment is accessed
        if not self.network.sources:
            source = WarOfTheGhostsSource()
            self.network.add_source_global(source)
            print "Added initial source: " + str(source)

        # Open recruitment
        self.recruiter().open_recruitment(self)

    def newcomer_arrival_trigger(self, newcomer):

        # Set the newcomer to invisible.
        newcomer.is_visible = False

        self.network.add_agent(newcomer)

        # If this is the first participant, link them to the source.
        if len(self.network.agents) == 0:
            source = self.network.sources[0]
            source.connect_to(newcomer)
            self.network.db.commit()

        # Run the next step of the process.
        self.process.step()

        newcomer.receive_all()

        # Trigger experiment-specific behavior that happens on creation
        newcomer.is_visible = True
        self.network.db.add(newcomer)
        self.network.db.commit()

        if self.is_experiment_over():
            # If the experiment is over, stop recruiting and export the data.
            self.recruiter().close_recruitment(self)
        else:
            # Otherwise recruit a new participant.
            self.recruiter().recruit_new_participants(self, n=1)

    def is_experiment_over(self):
        return len(self.network.vectors) == self.num_agents


class SimulatedAgent(Agent):
    """A simulated agent that translates between French and English."""

    __mapper_args__ = {"polymorphic_identity": "simulated_agent"}

    def update(self, info_in):

        # Apply the translation transformation.
        transformation1 = TranslationTransformation(info_in=info_in, node=self)
        transformation1.apply()


class WarOfTheGhostsSource(Source):
    """A source that transmits the War of Ghosts story from Bartlett (1932).
    """

    __mapper_args__ = {"polymorphic_identity": "war_of_the_ghosts_source"}

    @staticmethod
    def _data(length):
        with open("static/stimuli/ghosts.md", "r") as f:
            return f.read()


class TranslationTransformation(Transformation):
    """Translates from English to Latin or Latin to English."""

    __mapper_args__ = {"polymorphic_identity": "translation_tranformation"}

    def apply(self):

        # Detect the language.
        api_key = "AIzaSyBTyfWACesHGvIPrWksUOABTg7R-I_PAW4"
        base_url = "https://www.googleapis.com/language/translate/v2"
        payload = {
            "key": api_key,
            "q": self.info_in.contents}
        r = requests.get(base_url + "/detect", params=payload)
        print r.text
        r_dict = json.loads(r.text)
        source = str(r_dict["data"]["detections"][0][0]["language"])

        # Tranlsate en->es and es->en.
        if source == "en":
            destination = "la"
        elif source == "la":
            destination = "en"

        payload = {
            "key": api_key,
            "q": self.info_in.contents,
            "source": source,
            "target": destination}
        r = requests.get(base_url, params=payload)
        r_dict = json.loads(r.text)
        print r_dict
        translation = r_dict[
            "data"]["translations"][0]["translatedText"].encode("utf-8")

        # Mutate
        dictionary_path = os.path.join(
            "static", "dictionaries", destination + ".txt")
        with open(dictionary_path) as f:
            dictionary = f.read().split()

        words = list(set([w for w in re.split('\W', translation)]))
        for word in words:
            if random.random() < 0.02:
                new_word = random.choice(dictionary)
                translation = translation.replace(word, new_word)

        time.sleep(1)

        # Create a new info
        info_out = wallace.models.Info(
            origin=self.node,
            contents=translation)

        self.info_out = info_out

        return info_out


if __name__ == "__main__":
    session = wallace.db.init_db(drop_all=False)
    experiment = Translations(session)
