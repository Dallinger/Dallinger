import wallace
from wallace.experiments import Experiment
from wallace.recruiters import SimulatedRecruiter
from wallace.models import Transformation, Info, Agent, Source
from collections import OrderedDict


class SubstitutionCiphersExperiment(Experiment):
    def __init__(self, session):
        super(SubstitutionCiphersExperiment, self).__init__(session)

        self.task = "SubstitutionCipher"
        self.num_agents = 10
        self.num_steps = self.num_agents - 1
        self.network = wallace.networks.FullyConnected(self.session)
        self.process = wallace.processes.RandomWalkFromSource(self.network)
        self.agent_type = SimulatedAgent
        self.recruiter = SimulatedRecruiter

        # Setup for first time experiment is accessed
        if not self.network.nodes(type=Source):
            source = WarOfTheGhostsSource()
            self.network.add(source)
            self.save(source)
            source.connect_to(self.network.nodes(type=Agent))
            self.save()
            print "Added initial source: " + str(source)

        # Open recruitment
        self.recruiter().open_recruitment(self)

    def newcomer_arrival_trigger(self, newcomer):

        self.network.add_agent(newcomer)
        self.save()

        # If this is the first participant, link them to the source.
        if len(self.network.nodes(type=Agent)) == 1:
            source = self.network.nodes(type=Source)[0]
            source.connect_to(newcomer)
            self.save()

        # Run the next step of the process.
        self.process.step()

        newcomer.receive()

        if self.is_experiment_over():
            # If the experiment is over, stop recruiting and export the data.
            self.recruiter().close_recruitment(self)
        else:
            # Otherwise recruit a new participant.
            self.recruiter().recruit_new_participants(self, n=1)

    def is_experiment_over(self):
        return len(self.network.vectors) == self.num_agents


class SimulatedAgent(Agent):
    """A simulated agent that applies a substitution cipher to the text."""

    __mapper_args__ = {"polymorphic_identity": "simulated_agent"}

    def update(self, infos):
        for info in infos:
            # Apply the translation transformation.
            transformation1 = SubstitutionCipher(info_in=info, node=self)
            transformation1.apply()


class WarOfTheGhostsSource(Source):
    """A source that transmits the War of Ghosts story from Bartlett (1932).
    """

    __mapper_args__ = {"polymorphic_identity": "war_of_the_ghosts_source"}

    @staticmethod
    def _data(length):
        with open("static/stimuli/ghosts.md", "r") as f:
            return f.read()


class SubstitutionCipher(Transformation):
    """Translates from English to Latin or Latin to English."""

    __mapper_args__ = {"polymorphic_identity": "translation_tranformation"}

    alphabet = "abcdefghijklmnopqrstuvwxyz"
    keyword = "zebras"

    # Generate the ciphertext alphabet
    kw_unique = ''.join(OrderedDict.fromkeys(keyword).keys())
    non_keyword_letters = ''.join([l for l in alphabet if l not in kw_unique])
    ciphertext_alphabet = kw_unique + non_keyword_letters

    def apply(self):

        text = self.info_in.contents

        # Do the lower case.
        for i in range(len(self.alphabet)):
            text = text.replace(self.alphabet[i], self.ciphertext_alphabet[i])

        # And the upper case.
        alphabet_up = self.alphabet.upper()
        ciphertext_alphabet_up = self.ciphertext_alphabet.upper()
        for i in range(len(alphabet_up)):
            text = text.replace(alphabet_up[i], ciphertext_alphabet_up[i])

        # Create a new info
        info_out = Info(origin=self.node, contents=text)

        self.info_out = info_out

        return info_out


if __name__ == "__main__":
    session = wallace.db.init_db(drop_all=False)
    experiment = SubstitutionCiphersExperiment(session)
