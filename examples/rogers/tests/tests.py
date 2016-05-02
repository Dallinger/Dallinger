"""Test Rogers demo."""

from __future__ import print_function

import sys
import random
import traceback
from datetime import datetime
import subprocess
import re
import requests
import threading
import time

from wallace import db
from wallace.nodes import Agent, Source, Environment
from wallace.information import Gene, Meme, State
from wallace import models
from experiment import (
    RogersExperiment,
    RogersAgent,
    RogersAgentFounder,
    RogersSource,
    RogersEnvironment,
    LearningGene
)


def timenow():
    """A string representing the current date and time."""
    return datetime.now()


class TestRogers(object):

    sandbox = False

    if sandbox:

        autobots = 36

        sandbox_output = subprocess.check_output(
            "wallace sandbox",
            shell=True)

        m = re.search('Running as experiment (.*)...', sandbox_output)
        exp_id = m.group(1)
        url = "http://" + exp_id + ".herokuapp.com"

        # Open the logs in the browser.
        subprocess.call(
            "wallace logs --app " + exp_id,
            shell=True)

        def autobot(session, url, i):
            """Define the behavior of each worker."""
            time.sleep(i * 2)
            print("bot {} starting".format(i))
            start_time = timenow()

            my_id = str(i) + ':' + str(i)
            current_trial = 0

            # create participant
            headers = {
                'User-Agent': 'python',
                'Content-Type': 'application/x-www-form-urlencoded',
            }
            args = {
                'hitId': 'rogers-test-hit',
                'assignmentId': i,
                'workerId': i,
                'mode': 'sandbox'
            }
            session.get(url + '/exp', params=args, headers=headers)

            # send AssignmentAccepted notification
            args = {
                'Event.1.EventType': 'AssignmentAccepted',
                'Event.1.AssignmentId': i
            }
            session.post(url + '/notifications', data=args, headers=headers)

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
                    agent = session.post(url + '/node/' + my_id, headers=headers)
                    working = agent.status_code == 200
                    if working is True:
                        agent_id = agent.json()['node']['id']
                        args = {'info_type': "LearningGene"}
                        information = session.get(url + '/node/' + str(agent_id) + '/infos', params=args, headers=headers)
                        args = {'status': "pending", 'direction': "incoming"}
                        transmission = session.get(url + '/node/' + str(agent_id) + '/transmissions', params=args, headers=headers)
                        information2 = session.get(url + '/info/' + str(agent_id) + '/' + str(transmission.json()['transmissions'][0]['info_id']), headers=headers)
                        args = {'contents': 'blue', 'info_type': 'Meme'}
                        information3 = session.post(url + '/info/' + str(agent_id), data=args, headers=headers)
                except:
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
            args = {
                'Event.1.EventType': 'AssignmentSubmitted',
                'Event.1.AssignmentId': i
            }
            session.post(url + '/notifications', data=args, headers=headers)

            stop_time = timenow()
            print("Bot {} finished in {}".format(i, stop_time - start_time))
            return

        print("countdown before starting bots...")
        time.sleep(20)
        print("buffer ended, bots started")

        # create worker threads
        threads = []
        for i in range(autobots):
            with requests.Session() as session:
                t = threading.Thread(target=autobot, args=(session, url, i,))
                threads.append(t)
                t.start()

    else:

        def setup(self):
            self.db = db.init_db(drop_all=True)

        def teardown(self):
            self.db.rollback()
            self.db.close()

        def add(self, *args):
            self.db.add_all(args)
            self.db.commit()

        def test_run_rogers(self):

            """
            SIMULATE ROGERS
            """

            hit_id = str(random.random())

            overall_start_time = timenow()

            print("Running simulated experiment...", end="\r")
            sys.stdout.flush()

            exp_setup_start = timenow()
            exp = RogersExperiment(self.db)
            exp_setup_stop = timenow()

            exp_setup_start2 = timenow()
            exp = RogersExperiment(self.db)
            exp_setup_stop2 = timenow()

            p_ids = []
            p_times = []
            dum = timenow()
            assign_time = dum - dum
            process_time = dum - dum

            while exp.networks(full=False):

                num_completed_participants = len(exp.networks()[0].nodes(type=Agent))

                if p_times:
                    print("Running simulated experiment... participant {} of {}, {} participants failed. Prev time: {}".format(
                        num_completed_participants+1,
                        exp.networks()[0].max_size,
                        len(exp.networks()[0].nodes(failed=True)),
                        p_times[-1]),
                        end="\r")
                else:
                    print("Running simulated experiment... participant {} of {}, {} participants failed.".format(
                        num_completed_participants+1,
                        exp.networks()[0].max_size,
                        len(exp.networks()[0].nodes(failed=True))),
                        end="\r")
                sys.stdout.flush()

                worker_id = str(random.random())
                assignment_id = str(random.random())
                from psiturk.models import Participant
                p = Participant(workerid=worker_id, assignmentid=assignment_id, hitid=hit_id)
                self.db.add(p)
                self.db.commit()
                p_id = p.uniqueid
                p_ids.append(p_id)
                p_start_time = timenow()

                while True:
                    assign_start_time = timenow()
                    network = exp.get_network_for_participant(participant_id=p_id)
                    if network is None:
                        break
                    else:
                        agent = exp.make_node_for_participant(
                            participant_id=p_id,
                            network=network)
                        exp.add_node_to_network(
                            participant_id=p_id,
                            node=agent,
                            network=network)
                        self.db.commit()
                        exp.node_post_request(participant_id=p_id, node=agent)
                        self.db.commit()
                        assign_stop_time = timenow()
                        assign_time += (assign_stop_time - assign_start_time)

                        process_start_time = timenow()
                        agent.receive()
                        from operator import attrgetter
                        current_state = max(State.query.filter_by(network_id=agent.network_id).all(), key=attrgetter('creation_time')).contents
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
                        self.db.commit()
                        exp.info_post_request(
                            node=agent,
                            info=info)
                        #print("state: {}, answer: {}, score: {}, fitness {}".format(current_state, info.contents, agent.score, agent.fitness))
                        process_stop_time = timenow()
                        process_time += (process_stop_time - process_start_time)

                worked = exp.data_check(participant=p)
                assert worked
                bonus = exp.bonus(participant=p)
                assert bonus >= 0
                assert bonus <= 1
                attended = exp.attention_check(participant=p)
                if not attended:

                    participant_nodes = models.Node.query\
                        .filter_by(participant_id=p_id, failed=False)\
                        .all()
                    p.status = 102

                    for node in participant_nodes:
                        node.fail()

                    self.db.commit()
                else:
                    exp.submission_successful(participant=p)

                p_stop_time = timenow()
                p_times.append(p_stop_time - p_start_time)

            print("Running simulated experiment...      done!                                      ")
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
                assert len(agents) == network.max_size

                source = network.nodes(type=Source)
                assert len(source) == 1
                source = source[0]
                assert type(source) == RogersSource

                environment = network.nodes(type=Environment)
                assert len(environment) == 1
                environment = environment[0]
                assert type(environment) == RogersEnvironment

                vectors = network.vectors()

                role = network.role
                if role == "practice":
                    for agent in agents:
                        assert type(agent) == RogersAgentFounder
                elif role == "catch":
                    for agent in agents:
                        assert type(agent) == RogersAgentFounder
                else:
                    for agent in agents:
                        if agent.generation == 0:
                            assert type(agent) == RogersAgentFounder
                        else:
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
                        assert RogersAgent in [type(a) for a in agent.neighbors(connection="from")] or\
                            RogersAgentFounder in [type(a) for a in agent.neighbors(connection="from")]

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
                source = network.nodes(type=Source)[0]
                environment = network.nodes(type=Environment)[0]

                for v in vectors:
                    if isinstance(v.origin, Agent):
                        assert v.origin.generation == v.destination.generation - 1
                    else:
                        assert isinstance(v.origin, Source) or isinstance(v.origin, Environment)

                for agent in agents:
                    if agent.generation == 0:
                        assert len(models.Vector.query.filter_by(origin_id=source.id, destination_id=agent.id).all()) == 1
                    else:
                        assert len(models.Vector.query.filter_by(origin_id=source.id, destination_id=agent.id).all()) == 0

                for agent in agents:
                    assert len([v for v in vectors if v.origin_id == environment.id and v.destination_id == agent.id]) == 1

                for v in [v for v in vectors if v.origin_id == source.id]:
                    assert isinstance(v.destination, RogersAgentFounder)

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
                source = network.nodes(type=Source)[0]
                environment = network.nodes(type=Environment)[0]
                infos = network.infos()

                for agent in agents:
                    assert len([i for i in infos if i.origin_id == agent.id]) == 2
                    assert len([i for i in infos if i.origin_id == agent.id and isinstance(i, Gene)]) == 1
                    assert len([i for i in infos if i.origin_id == agent.id and isinstance(i, LearningGene)]) == 1
                    assert len([i for i in infos if i.origin_id == agent.id and isinstance(i, Meme)]) == 1

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
                source = network.nodes(type=Source)[0]
                environment = network.nodes(type=Environment)[0]
                infos = network.infos()
                transmissions = network.transmissions()

                for agent in agents:
                    in_ts = [t for t in transmissions if t.destination_id == agent.id]
                    types = [type(t.info) for t in in_ts]

                    assert len(in_ts) == 2
                    assert len([t for t in transmissions if t.destination_id == agent.id and t.status == "pending"]) == 0

                    lg = [i for i in infos if i.origin_id == agent.id and isinstance(i, LearningGene)]
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
            c = 0.3*b
            baseline = c+0.0001

            for n in p0_nodes:
                assert n.fitness == (baseline + 1 * b - is_asocial * c) ** e

            for network in [exp.networks()[0]]:

                agents = network.nodes(type=Agent)

                for agent in agents:
                    is_asocial = agent.infos(type=LearningGene)[0].contents == "asocial"
                    assert agent.fitness == ((baseline + agent.score*b - is_asocial*c) ** e)

            print("Testing fitness...                   done!")
            sys.stdout.flush()

            """
            TEST BONUS
            """

            print("Testing bonus payments...", end="\r")
            sys.stdout.flush()

            assert exp.bonus(participant=Participant.query.filter_by(uniqueid=p_ids[0]).all()[0]) == exp.bonus_payment

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
            test = [p.total_seconds() for p in p_times]
            print(test)
