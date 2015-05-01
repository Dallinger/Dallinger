# this file imports custom routes into the experiment server
from flask import Blueprint, request, jsonify, Response, abort

from psiturk.psiturk_config import PsiturkConfig
from psiturk.experiment_errors import ExperimentError
from psiturk.user_utils import PsiTurkAuthorization

# Database setup
from psiturk.db import db_session as session_psiturk
from psiturk.models import Participant
from json import dumps

from wallace import db, agents, models, information
from wallace.models import Agent

import imp
import inspect
import urllib
import hashlib
import random

# load the configuration options
config = PsiturkConfig()
config.load_config()
myauth = PsiTurkAuthorization(config)

# explore the Blueprint
custom_code = Blueprint(
    'custom_code', __name__,
    template_folder='templates',
    static_folder='static')

# Initialize the Wallace db
session = db.init_db(drop_all=False)

# Specify the experiment.
try:
    exp = imp.load_source('experiment', "wallace_experiment.py")
    classes = inspect.getmembers(exp, inspect.isclass)
    exps = [c for c in classes
            if (c[1].__bases__[0].__name__ in "Experiment")]
    this_experiment = exps[0][0]
    mod = __import__('wallace_experiment', fromlist=[this_experiment])
    experiment = getattr(mod, this_experiment)
except ImportError:
    print "Error: Could not import experiment."

# Launch the experiment.
exp = experiment(session)
exp.recruiter().open_recruitment(exp)


###########################################################
#  serving warm, fresh, & sweet custom, user-provided routes
#  add them here
###########################################################

# ----------------------------------------------
# example computing bonus
# ----------------------------------------------
@custom_code.route('/compute_bonus', methods=['GET'])
def compute_bonus():
    exp = experiment(session)
    # check that user provided the correct keys
    # errors will not be that gracefull here if being
    # accessed by the Javascrip client
    if 'uniqueId' not in request.args:
        raise ExperimentError('improper_inputs')
    uniqueId = request.args['uniqueId']

    try:

        # Compute the bonus using experiment-specific logic.
        bonus = exp.bonus(
            participant_uuid=hashlib.sha512(uniqueId).hexdigest())

        # lookup user in database
        user = Participant.query.\
            filter(Participant.uniqueid == uniqueId).\
            one()
        user.bonus = bonus
        session_psiturk.add(user)
        session_psiturk.commit()
        resp = {"bonusComputed": "success"}
        return jsonify(**resp)
    except Exception, e:
        print e
        abort(404)  # again, bad to display HTML, but...


@custom_code.route("/agents", methods=["POST", "GET"])
def api_agent_create():

    exp = experiment(session)

    if request.method == 'POST':

        # Figure out whether this MTurk participant is allowed to create
        # another agent in this experiment.
        participant_uuid = hashlib.sha512(
            request.values["unique_id"]).hexdigest()

        try:
            newcomer = exp.assign_agent_to_participant(participant_uuid)
            data = {'agents': {'uuid': newcomer.uuid}}
            js = dumps(data)
            return Response(js, status=200, mimetype='application/json')
        except:
            return Response(status=403)

    if request.method == "GET":
        data_agents = [agent.uuid for agent in exp.network.nodes(type=Agent)]
        data = {"agents": data_agents}
        js = dumps(data)
        return Response(js, status=200, mimetype='application/json')


@custom_code.route("/transmissions",
                   defaults={"transmission_uuid": None},
                   methods=["POST", "GET"])
@custom_code.route("/transmissions/<transmission_uuid>", methods=["GET"])
def api_transmission(transmission_uuid):

    exp = experiment(session)
    session.commit()

    if request.method == 'GET':

        # Given a receiving agent, get its pending transmissions
        if transmission_uuid is None:
            print "no transmission uuid specified"
            pending_transmissions = models.Transmission\
                .query\
                .filter_by(destination_uuid=request.values['destination_uuid'])\
                .filter_by(receive_time=None)\
                .order_by(models.Transmission.transmit_time)\
                .all()

        # Or given a uuid, get the transmission with the given id
        else:
            transmission = models.Transmission\
                .query\
                .filter_by(uuid=transmission_uuid)\
                .one()
            pending_transmissions = [transmission]

        exp.transmission_reception_trigger(pending_transmissions)

        # Build a dict with info about the transmissions
        data_transmissions = []
        data = []
        for i in xrange(len(pending_transmissions)):
            t = pending_transmissions[i]

            data_transmissions.append({
                "uuid": t.uuid,
                "info_uuid": t.info_uuid,
                "origin_uuid": t.origin_uuid,
                "destination_uuid": t.destination_uuid,
                "transmit_time": t.transmit_time,
                "receive_time": t.receive_time
            })
            data = {"transmissions": data_transmissions}

        if not data:
            print "{} made a GET request for transmissions, ".format(
                request.values['destination_uuid']) + \
                "but there were no transmissions to get."

        js = dumps(data)
        return Response(js, status=200, mimetype='application/json')

    if request.method == "POST":

        info = models.Info\
            .query\
            .filter_by(uuid=request.values['info_uuid'])\
            .one()

        destination = agents.Agent\
            .query\
            .filter_by(uuid=request.values['destination_uuid'])\
            .one()

        transmission = models.Transmission(info=info, destination=destination)

        session.add(transmission)
        session.commit()

        data = {'uuid': transmission.uuid}
        js = dumps(data)

        return Response(js, status=200, mimetype='application/json')


@custom_code.route("/information",
                   defaults={"info_uuid": None},
                   methods=["POST", "GET"])
@custom_code.route("/information/<info_uuid>", methods=["GET"])
def api_info(info_uuid):

    exp = experiment(session)

    if request.method == 'GET':

        if info_uuid is not None:

            info = models.Info.query.filter_by(uuid=info_uuid).one()

            data = {
                'info_uuid': info_uuid,
                'contents': info.contents,
                'origin_uuid': info.origin_uuid,
                'creation_time': info.creation_time,
                'type': info.type
            }
            js = dumps(data)

            return Response(js, status=200, mimetype='application/json')

        else:

            infos = models.Info\
                .query\
                .filter_by(origin_uuid=request.values['origin_uuid'])\
                .order_by(models.Info.creation_time)\
                .all()

            data_information = []
            for i in xrange(len(infos)):
                info = infos[i]

                data_information.append({
                    "info_uuid": info.uuid,
                    "type": info.type,
                    "origin_uuid": info.origin_uuid,
                    "creation_time": info.creation_time,
                    "contents": info.contents
                })

            js = dumps({"information": data_information})
            return Response(js, status=200, mimetype='application/json')

    if request.method == "POST":

        if 'origin_uuid' in request.values:

            # models
            node = models.Node\
                .query\
                .filter_by(uuid=request.values['origin_uuid'])\
                .one()

            cnts = urllib.unquote(request.values['contents']).decode('utf8')

            # Create an Info of the requested type.
            info_type = request.values['info_type']

            if (info_type is None) or (info_type == "base"):
                cls = models.Info

            elif info_type == "meme":
                cls = information.Meme

            elif info_type == "gene":
                cls = information.Gene

            elif info_type == "state":
                cls = information.State

            else:
                raise ValueError("Requested info_type does not exist.")

            info = cls(
                origin=node,
                contents=cnts)

            session.add(info)
            session.commit()

            # Trigger experiment-specific behavior that happens on creationg
            exp.information_creation_trigger(info)

            data = {'uuid': info.uuid}
            js = dumps(data)

            return Response(js, status=200, mimetype='application/json')


@custom_code.route("/notifications", methods=["POST", "GET"])
def api_notifications():

    exp = experiment(session)

    print "Received a notification:"
    for v in request.values:
        print v
    print "---"

    event_type = request.values['Event.1.EventType']

    if event_type == 'AssignmentAccepted':
        print "Participant accepted assignment."

    elif event_type in ['AssignmentAbandoned', 'AssignmentReturned']:

        print "Participant stopped working."

        # Get the assignment id.
        print "Assignment ID:"
        assignment_id = request.values['Event.1.AssignmentId']
        print assignment_id

        # Transform the assignment id to the SHA512 hash of the unique id
        # from the psiTurk table.
        participant = Participant.query.\
            filter(Participant.assignmentid == assignment_id).\
            one()

        participant_uuid = hashlib.sha512(participant.uniqueid).hexdigest()

        # Get the all nodes associated with the participant.
        nodes = models.Node\
            .query\
            .filter_by(participant_uuid=participant_uuid)\
            .all()

        for node in nodes:
            print "Failing node {}.".format(node)
            node.fail()

    elif event_type == 'HITReviewable':
        # Accept the HIT.

        # Reward the bonus.

        # Recruit new participants.
        exp.participant_completion_trigger()

    return Response(
        dumps({"status": "success"}), status=200, mimetype='application/json')

    # all_event_types = [
    #     "AssignmentAccepted",
    #     "AssignmentAbandoned",
    #     "AssignmentReturned",
    #     "AssignmentSubmitted",
    #     "HITReviewable",
    #     "HITExpired",
    # ]
