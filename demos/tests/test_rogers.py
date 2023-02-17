"""Test Rogers demo."""

from __future__ import print_function

import os
import random
import re
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime

import pytest
import requests
from dlgr.demos.rogers.experiment import RogersExperiment
from dlgr.demos.rogers.models import (
    LearningGene,
    RogersAgent,
    RogersEnvironment,
    RogersSource,
)

from dallinger import models
from dallinger.information import Gene, Meme, State
from dallinger.nodes import Agent, Source


def timenow():
    """A string representing the current date and time."""
    return datetime.now()


@pytest.fixture(scope="class")
def rogers_dir(root):
    os.chdir(os.path.join(os.path.dirname(__file__), "..", "dlgr/demos/rogers"))
    yield
    os.chdir(root)


@pytest.mark.usefixtures("rogers_dir")
class TestRogers(object):
    @pytest.fixture
    def rogers_config(self, active_config):
        from dlgr.demos.rogers.experiment import extra_parameters

        extra_parameters()
        active_config.set("experiment_repeats", 10)
        active_config.set("practice_repeats", 0)
        active_config.set("practice_difficulty", 0.80)
        active_config.set("difficulties", "0.525, 0.5625, 0.65")
        active_config.set("catch_difficulty", 0.80)
        active_config.set("min_acceptable_performance", 0.833333333333333)
        active_config.set("generation_size", 2)
        active_config.set("generations", 3)
        active_config.set("bonus_payment", 1.0)
        yield active_config

    def test_run_rogers(self, rogers_config, db_session):
        """
        SIMULATE ROGERS
        """

        hit_id = str(random.random())

        overall_start_time = timenow()

        print("Running simulated experiment...", end="\r")
        sys.stdout.flush()

        exp_setup_start = timenow()
        exp = RogersExperiment(db_session)
        exp_setup_stop = timenow()

        exp_setup_start2 = timenow()
        exp = RogersExperiment(db_session)
        exp_setup_stop2 = timenow()

        p_ids = []
        p_times = []
        dum = timenow()
        assign_time = dum - dum
        process_time = dum - dum

        while exp.networks(full=False):

            num_completed_participants = len(exp.networks()[0].nodes(type=Agent))

            if p_times:
                print(
                    "Running simulated experiment... participant {} of {}, "
                    "{} participants failed. Prev time: {}".format(
                        num_completed_participants + 1,
                        exp.networks()[0].max_size,
                        len(exp.networks()[0].nodes(failed=True)),
                        p_times[-1],
                    ),
                    end="\r",
                )
            else:
                print(
                    "Running simulated experiment... participant {} of {}, "
                    "{} participants failed.".format(
                        num_completed_participants + 1,
                        exp.networks()[0].max_size,
                        len(exp.networks()[0].nodes(failed=True)),
                    ),
                    end="\r",
                )
            sys.stdout.flush()

            worker_id = str(random.random())
            assignment_id = str(random.random())
            from dallinger.models import Participant

            p = Participant(
                recruiter_id="hotair",
                worker_id=worker_id,
                assignment_id=assignment_id,
                hit_id=hit_id,
                mode="debug",
            )
            db_session.add(p)
            db_session.commit()
            p_id = p.id
            p_ids.append(p_id)
            p_start_time = timenow()

            while True:
                assign_start_time = timenow()
                network = exp.get_network_for_participant(participant=p)
                if network is None:
                    break
                else:
                    agent = exp.create_node(participant=p, network=network)
                    exp.add_node_to_network(node=agent, network=network)
                    db_session.commit()
                    exp.node_post_request(participant=p, node=agent)
                    db_session.commit()
                    assign_stop_time = timenow()
                    assign_time += assign_stop_time - assign_start_time

                    process_start_time = timenow()
                    agent.receive()
                    from operator import attrgetter

                    current_state = max(
                        network.nodes(type=RogersEnvironment)[0].infos(),
                        key=attrgetter("id"),
                    ).contents
                    if float(current_state) >= 0.5:
                        right_answer = "blue"
                        wrong_answer = "yellow"
                    else:
                        right_answer = "yellow"
                        wrong_answer = "blue"
                    if num_completed_participants == 0:
                        info = Meme(origin=agent, contents=right_answer)
                    else:
                        if random.random() < 0.9:
                            info = Meme(origin=agent, contents=right_answer)
                        else:
                            info = Meme(origin=agent, contents=wrong_answer)
                    db_session.commit()
                    exp.info_post_request(node=agent, info=info)
                    # print("state: {}, answer: {}, score: {}, fitness {}".format(
                    #     current_state, info.contents, agent.score, agent.fitness))
                    process_stop_time = timenow()
                    process_time += process_stop_time - process_start_time

            worked = exp.data_check(participant=p)
            assert worked
            bonus = exp.bonus(participant=p)
            assert bonus >= 0
            assert bonus <= 1
            attended = exp.attention_check(participant=p)
            if not attended:

                participant_nodes = models.Node.query.filter_by(
                    participant_id=p_id, failed=False
                ).all()
                p.status = 102

                for node in participant_nodes:
                    node.fail()

                db_session.commit()
            else:
                p.status = "approved"
                exp.submission_successful(participant=p)

            p_stop_time = timenow()
            p_times.append(p_stop_time - p_start_time)

        print("Running simulated experiment...      done!")
        sys.stdout.flush()

        overall_stop_time = timenow()

        assert len(exp.networks()) == exp.practice_repeats + exp.experiment_repeats

        """
        TEST NODES
        """

        print("Testing nodes...", end="\r")
        sys.stdout.flush()

        for network in [exp.networks()[0]]:
            agents = network.nodes(type=Agent)
            sources = network.nodes(type=Source)
            assert len(sources) == 2
            assert len(network.nodes(type=RogersSource)) == 1
            assert len(network.nodes(type=RogersEnvironment)) == 1
            assert len(agents) + len(sources) == network.max_size

            source = network.nodes(type=RogersSource)
            assert len(source) == 1
            source = source[0]
            assert type(source) == RogersSource

            environment = network.nodes(type=RogersEnvironment)
            assert len(environment) == 1
            environment = environment[0]
            assert type(environment) == RogersEnvironment

            vectors = network.vectors()

            for agent in agents:
                assert type(agent) == RogersAgent

            for agent in agents:
                if agent.generation == 0:
                    assert len(agent.vectors(direction="incoming")) == 2
                    assert agent.is_connected(direction="from", whom=source)
                    assert agent.is_connected(direction="from", whom=environment)
                else:
                    assert len(agent.vectors(direction="incoming")) in [2, 3]
                    assert not agent.is_connected(direction="from", whom=source)
                    assert agent.is_connected(direction="from", whom=environment)
                    assert RogersAgent in [
                        type(a) for a in agent.neighbors(direction="from")
                    ]

        print("Testing nodes...                     done!")
        sys.stdout.flush()

        """
        TEST VECTORS
        """

        print("Testing vectors...", end="\r")
        sys.stdout.flush()

        for network in [exp.networks()[0]]:
            agents = network.nodes(type=Agent)
            vectors = network.vectors()
            source = network.nodes(type=RogersSource)[0]
            environment = network.nodes(type=RogersEnvironment)[0]

            for v in vectors:
                if isinstance(v.origin, Agent):
                    assert v.origin.generation == v.destination.generation - 1
                else:
                    assert isinstance(v.origin, Source) or isinstance(
                        v.origin, RogersEnvironment
                    )
            for agent in agents:
                if agent.generation == 0:
                    assert (
                        len(
                            models.Vector.query.filter_by(
                                origin_id=source.id, destination_id=agent.id
                            ).all()
                        )
                        == 1  # noqa
                    )
                else:
                    assert (
                        len(
                            models.Vector.query.filter_by(
                                origin_id=source.id, destination_id=agent.id
                            ).all()
                        )
                        == 0  # noqa
                    )

            for agent in agents:
                assert (
                    len(
                        [
                            v
                            for v in vectors
                            if v.origin_id == environment.id
                            and v.destination_id == agent.id  # noqa
                        ]
                    )
                    == 1  # noqa
                )

            for v in [v for v in vectors if v.origin_id == source.id]:
                assert isinstance(v.destination, RogersAgent)

        print("Testing vectors...                   done!")
        sys.stdout.flush()

        """
        TEST INFOS
        """

        print("Testing infos...", end="\r")
        sys.stdout.flush()

        for network in [exp.networks()[0]]:

            agents = network.nodes(type=Agent)
            vectors = network.vectors()
            source = network.nodes(type=RogersSource)[0]
            environment = network.nodes(type=RogersEnvironment)[0]
            infos = network.infos()

            for agent in agents:
                assert len([i for i in infos if i.origin_id == agent.id]) == 2
                assert (
                    len(
                        [
                            i
                            for i in infos
                            if i.origin_id == agent.id and isinstance(i, Gene)
                        ]
                    )
                    == 1  # noqa
                )
                assert (
                    len(
                        [
                            i
                            for i in infos
                            if i.origin_id == agent.id and isinstance(i, LearningGene)
                        ]
                    )
                    == 1  # noqa
                )
                assert (
                    len(
                        [
                            i
                            for i in infos
                            if i.origin_id == agent.id and isinstance(i, Meme)
                        ]
                    )
                    == 1  # noqa
                )

        print("Testing infos...                     done!")
        sys.stdout.flush()

        """
        TEST TRANSMISSIONS
        """

        print("Testing transmissions...", end="\r")
        sys.stdout.flush()

        for network in [exp.networks()[0]]:

            agents = network.nodes(type=Agent)
            vectors = network.vectors()
            source = network.nodes(type=RogersSource)[0]
            environment = network.nodes(type=RogersEnvironment)[0]
            infos = network.infos()
            transmissions = network.transmissions()

            for agent in agents:
                in_ts = [t for t in transmissions if t.destination_id == agent.id]
                types = [type(t.info) for t in in_ts]

                assert len(in_ts) == 2
                assert (
                    len(
                        [
                            t
                            for t in transmissions
                            if t.destination_id == agent.id and t.status == "pending"
                        ]
                    )
                    == 0  # noqa
                )

                lg = [
                    i
                    for i in infos
                    if i.origin_id == agent.id and isinstance(i, LearningGene)
                ]
                assert len(lg) == 1
                lg = lg[0]

                if lg.contents == "asocial":
                    assert State in types
                    assert LearningGene in types
                    assert Meme not in types
                else:
                    assert State not in types
                    assert LearningGene in types
                    assert Meme in types

        print("Testing transmissions...             done!")

        """
        TEST FITNESS
        """

        print("Testing fitness...", end="\r")
        sys.stdout.flush()

        p0_nodes = models.Node.query.filter_by(participant_id=p_ids[0]).all()

        assert len(p0_nodes) == len(exp.networks())

        is_asocial = True
        e = 2
        b = 1
        c = 0.3 * b
        baseline = c + 0.0001

        for n in p0_nodes:
            assert n.fitness == (baseline + 1 * b - is_asocial * c) ** e

        for network in [exp.networks()[0]]:

            agents = network.nodes(type=Agent)

            for agent in agents:
                is_asocial = agent.infos(type=LearningGene)[0].contents == "asocial"
                assert agent.fitness == (
                    (baseline + agent.score * b - is_asocial * c) ** e
                )

        print("Testing fitness...                   done!")
        sys.stdout.flush()

        """
        TEST BONUS
        """

        print("Testing bonus payments...", end="\r")
        sys.stdout.flush()

        assert (
            exp.bonus(participant=Participant.query.filter_by(id=p_ids[0]).all()[0])
            == exp.bonus_payment  # noqa
        )

        print("Testing bonus payments...            done!")
        sys.stdout.flush()

        print("All tests passed: good job!")

        print("Timings:")
        overall_time = overall_stop_time - overall_start_time
        print("Overall time to simulate experiment: {}".format(overall_time))
        setup_time = exp_setup_stop - exp_setup_start
        print("Experiment setup(): {}".format(setup_time))
        print("Experiment load: {}".format(exp_setup_stop2 - exp_setup_start2))
        print("Participant assignment: {}".format(assign_time))
        print("Participant processing: {}".format(process_time))
        for i in range(len(p_times)):
            if i == 0:
                total_time = p_times[i]
            else:
                total_time += p_times[i]
            print("Participant {}: {}, total: {}".format(i, p_times[i], total_time))

        print("#########")
        test = [p_time.total_seconds() for p_time in p_times]
        print(test)


class TestRogersSandbox(object):
    def autobot(self, session, url, i):
        """Define the behavior of each worker."""
        time.sleep(i * 2)
        print("bot {} starting".format(i))
        start_time = timenow()

        my_id = str(i) + ":" + str(i)
        current_trial = 0

        # create participant
        headers = {
            "User-Agent": "python",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        args = {
            "hitId": "rogers-test-hit",
            "assignmentId": i,
            "workerId": i,
            "mode": "sandbox",
        }
        session.get(url + "/exp", params=args, headers=headers)

        # send AssignmentAccepted notification
        args = {"Event.1.EventType": "AssignmentAccepted", "Event.1.AssignmentId": i}
        session.post(url + "/notifications", data=args, headers=headers)

        # work through the trials
        working = True
        while working is True:
            current_trial += 1
            agent = None
            transmission = None
            information = None
            information2 = None
            information3 = None
            try:
                agent = session.post(url + "/node/" + my_id, headers=headers)
                working = agent.status_code == 200
                if working is True:
                    agent_id = agent.json()["node"]["id"]
                    args = {"info_type": "LearningGene"}
                    information = session.get(
                        url + "/node/" + str(agent_id) + "/infos",
                        params=args,
                        headers=headers,
                    )
                    args = {"status": "pending", "direction": "incoming"}
                    transmission = session.get(
                        url + "/node/" + str(agent_id) + "/transmissions",
                        params=args,
                        headers=headers,
                    )
                    information2 = session.get(
                        url
                        + "/info/"  # noqa
                        + str(agent_id)  # noqa
                        + "/"  # noqa
                        + str(  # noqa
                            transmission.json()["transmissions"][0]["info_id"]
                        ),
                        headers=headers,
                    )
                    args = {"contents": "blue", "info_type": "Meme"}
                    information3 = session.post(
                        url + "/info/" + str(agent_id), data=args, headers=headers
                    )
            except Exception:
                working = False
                print("critical error for bot {}".format(i))
                print("bot {} is on trial {}".format(i, current_trial))
                print("bot {} agent request: {}".format(i, agent))
                print("bot {} information request: {}".format(i, information))
                print("bot {} transmission request: {}".format(i, transmission))
                print("bot {} 2nd information request: {}".format(i, information2))
                print("bot {} 3rd information request: {}".format(i, information3))
                traceback.print_exc()

        # send AssignmentSubmitted notification
        args = {"Event.1.EventType": "AssignmentSubmitted", "Event.1.AssignmentId": i}
        session.post(url + "/notifications", data=args, headers=headers)

        stop_time = timenow()
        print("Bot {} finished in {}".format(i, stop_time - start_time))
        return

    @pytest.mark.skip(reason="Preserving for future development work only.")
    def test_against_sandbox(self):
        autobots = 36
        sandbox_output = subprocess.check_output(["dallinger", "sandbox"])

        m = re.search("Running as experiment (.*)...", sandbox_output)
        exp_id = m.group(1)
        url = "http://" + exp_id + ".herokuapp.com"

        # Open the logs in the browser.
        subprocess.call(["dallinger", "log", "--app", exp_id])
        print("countdown before starting bots...")
        time.sleep(20)
        print("buffer ended, bots started")

        # create worker threads
        threads = []
        for i in range(autobots):
            with requests.Session() as session:
                t = threading.Thread(target=self.autobot, args=(session, url, i))
                threads.append(t)
                t.start()
