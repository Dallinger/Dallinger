"""Import custom routes into the experiment server."""

from flask import Blueprint, request, jsonify, Response, abort

from psiturk.psiturk_config import PsiturkConfig
from psiturk.experiment_errors import ExperimentError
from psiturk.user_utils import PsiTurkAuthorization
from psiturk.db import init_db

# Database setup
from psiturk.db import db_session as session_psiturk
from psiturk.models import Participant
from json import dumps

from wallace import db, nodes, models, information

import imp
import inspect
import urllib
import hashlib
from operator import attrgetter

from sqlalchemy import and_

import sys

# Load the configuration options.
config = PsiturkConfig()
config.load_config()
myauth = PsiTurkAuthorization(config)

# Explore the Blueprint.
custom_code = Blueprint(
    'custom_code', __name__,
    template_folder='templates',
    static_folder='static')

# Initialize the Wallace database.
session = db.get_session()

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


@custom_code.route('/launch', methods=['POST'])
def launch():
    """Launch the experiment."""
    exp = experiment(db.init_db(drop_all=False))
    exp.log("Launch route hit, laucnhing experiment", "-----")
    exp.log("Experiment launching, initiailizing tables", "-----")
    init_db()  # Initialize psiTurk tables.
    exp.log("Experiment launching, opening recruitment", "-----")
    exp.recruiter().open_recruitment(n=exp.initial_recruitment_size)

    session_psiturk.commit()
    session.commit()

    exp.log("Experiment successfully launched, retuning status 200", "-----")
    # Return a response.
    data = {"status": "launched"}
    js = dumps(data)
    return Response(js, status=200, mimetype='application/json')


@custom_code.route('/compute_bonus', methods=['GET'])
def compute_bonus():
    """Overide the psiTurk compute_bonus route."""
    raise RuntimeError(">>>>> ----- Error: Do not use the compute_bonus route, this is handled by assignment submitted notifications")
    return Response(status=200)


@custom_code.route("/agents", methods=["POST"])
def api_agent_create():
    """Sending a POST request to /agents triggers the creation of a new agent"""

    exp = experiment(session)

    if request.method == 'POST':
        unique_id = request.values["unique_id"]
        key = unique_id[0:5]

        exp.log("Received POST request to /agents for participant {}".format(unique_id), key)

        participant = Participant.query.\
            filter(Participant.uniqueid == unique_id).\
            one()
        exp.log("Successfully located participant", key)

        if participant.status not in [1, 2]:
            exp.log("Participant status is {} - no new nodes will be made for them".
                    format(participant.status), key)
            return Response(status=403)

        if config.getboolean('Database Parameters', 'anonymize_data'):
            exp.log("hashing participant id", key)
            participant_uuid = hashlib.sha512(unique_id).hexdigest()
        else:
            participant_uuid = unique_id

        exp.log("Participant status is {}, assigning them a new node".format(participant.status), key)
        newcomer = exp.assign_agent_to_participant(participant_uuid)

        session.commit()

        if newcomer is not None:
            exp.log("Participant has been assigned Node {}".format(newcomer.uuid), key)
            data = {'agents': {'uuid': newcomer.uuid}}
            js = dumps(data)
            exp.log("Returning status 200", key)
            return Response(js, status=200, mimetype='application/json')
        else:
            exp.log("Node failed to be made for participant", key)
            exp.log("Returning status 403", key)
            return Response(status=403)


@custom_code.route("/transmissions",
                   defaults={"transmission_uuid": None},
                   methods=["POST", "GET"])
@custom_code.route("/transmissions/<transmission_uuid>", methods=["GET"])
def api_transmission(transmission_uuid):
    """Create a transmission."""
    exp = experiment(session)

    if request.method == 'GET':

        exp.log("Recevied a Transmission GET request")

        # Given a receiving agent, get its pending transmissions
        if transmission_uuid is None:
            exp.log("       Getting all pending transmissions")
            pending_transmissions = models.Transmission\
                .query\
                .filter_by(destination_uuid=request.values['destination_uuid'],
                           receive_time=None)\
                .all()

        # Or given a uuid, get the transmission with the given id
        else:
            exp.log("       Getting transmission {}".format(transmission_uuid))
            try:
                transmission = models.Transmission\
                    .query\
                    .filter_by(uuid=transmission_uuid)\
                    .one()
            except:
                exp.log("       Transmission does not exist, critical error")
                return Response(status=403)
            pending_transmissions = [transmission]

        exp.log("       {}".format(pending_transmissions))
        exp.log("       Running transmission_reception_trigger")
        exp.transmission_reception_trigger(pending_transmissions)

        session.commit()

        # Build a dict with info about the transmissions
        data_transmissions = []
        for t in pending_transmissions:
            data_transmissions.append({
                "uuid": t.uuid,
                "info_uuid": t.info_uuid,
                "origin_uuid": t.origin_uuid,
                "destination_uuid": t.destination_uuid,
                "creation_time": t.creation_time,
                "receive_time": t.receive_time
            })
        data = {"transmissions": data_transmissions}

        exp.log("       returning transmissions, status 200")

        def date_handler(obj):
            return obj.isoformat() if hasattr(obj, 'isoformat') else obj

        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')

    if request.method == "POST":

        exp.log("       Received a transmission post Request")

        try:
            info = models.Info\
                .query\
                .filter_by(uuid=request.values['info_uuid'])\
                .one()
        except:
            exp.log("       Info does not exist, critical error, returning status 403")
            return Response(status=403)

        try:
            origin = models.Node\
                .query.filter_by(uuid=request.values['origin_uuid'])\
                .one()
        except:
            exp.log("       Origin does not exist, critical error, returning status 403")
            return Response(status=403)

        try:
            destination = nodes.Agent\
                .query.filter_by(uuid=request.values['destination_uuid'])\
                .one()
        except:
            exp.log("       Desintation does not exist, critical error, returning status 403")
            return Response(status=403)

        exp.log("       Transmitting...")
        transmission = origin.transmit(what=info, to_whom=destination)

        session.commit()

        data = {'uuid': transmission.uuid}
        js = dumps(data)

        exp.log("       Returning transmission uuid, status = 200")
        return Response(js, status=200, mimetype='application/json')


@custom_code.route("/information",
                   defaults={"info_uuid": None},
                   methods=["POST", "GET"])
@custom_code.route("/information/<info_uuid>", methods=["GET"])
def api_info(info_uuid):
    """Create and access informaiton."""
    exp = experiment(session)

    def date_handler(obj):
        return obj.isoformat() if hasattr(obj, 'isoformat') else obj

    if request.method == 'GET':

        exp.log("       Recevied an information GET request")

        if info_uuid is not None:

            exp.log("       Getting requested info")
            try:
                info_uuid = int(info_uuid)
            except:
                exp.log("       info_uuid {} is not an int, critical error, returning status 403".format(info_uuid))
                return Response(status=403)
            try:
                info = models.Info.query.filter_by(uuid=info_uuid).one()
            except:
                exp.log("       Info does not exist, critical error, returning status = 403")
                return Response(status=403)

            data = {
                'info_uuid': info_uuid,
                'contents': info.contents,
                'origin_uuid': info.origin_uuid,
                'creation_time': info.creation_time,
                'type': info.type
            }

            js = dumps(data, default=date_handler)

            exp.log("       returning info, status = 200")

            return Response(js, status=200, mimetype='application/json')

        else:

            exp.log("       Getting all infos")

            infos = models.Info\
                .query\
                .filter_by(origin_uuid=request.values['origin_uuid'])\
                .all()

            if infos:
                data_information = []
                for i in infos:
                    data_information.append({
                        "info_uuid": i.uuid,
                        "type": i.type,
                        "origin_uuid": i.origin_uuid,
                        "creation_time": i.creation_time,
                        "contents": i.contents
                    })

                js = dumps({"information": data_information}, default=date_handler)

                exp.log("       returning infos, status = 200")
                return Response(js, status=200, mimetype='application/json')
            else:
                exp.log("       there were no infos to get! Returning status 200")
                return Response(status=200)

    if request.method == "POST":

        exp.log("       Received an information POST request")

        try:
            origin_uuid = request.values['origin_uuid']
        except:
            exp.log("       origin uuid not specified, critical error, returning status = 403")
            return Response(status=403)
        try:
            origin_uuid = int(origin_uuid)
        except:
            exp.log("       origin uuid {} is not an int, ciritical error, returning status 403".format(origin_uuid))
            return Response(status=403)

        # models
        try:
            node = models.Node\
                .query\
                .filter_by(uuid=origin_uuid)\
                .one()
        except:
            exp.log("       Origin node does not exist, critical error, returning status = 403")
            return Response(status=403)

        try:
            cnts = urllib.unquote(request.values['contents']).decode('utf8')
        except:
            exp.log("       Contents do not exist or cannot be decoded, critical error, returning status = 403")
            return Response(status=403)

        # Create an Info of the requested type.
        try:
            info_type = request.values['info_type']
        except:
            exp.log("       info_type not specified, critical error, returning status = 403")
            return Response(status=403)

        if (info_type is None) or (info_type == "base"):
            cls = models.Info

        elif info_type == "meme":
            cls = information.Meme

        elif info_type == "gene":
            cls = information.Gene

        elif info_type == "state":
            cls = information.State

        else:
            exp.log("Requested info_type does not exist., returning status = 403")
            return Response(status=403)

        exp.log("       making info")
        info = cls(
            origin=node,
            contents=cnts)

        # Trigger experiment-specific behavior that happens on creationg
        exp.log("       running information creation trigger")
        exp.information_creation_trigger(info)
        session.commit()

        data = {'uuid': info.uuid}

        js = dumps(data)

        exp.log("       returning info uuid, status = 200")

        return Response(js, status=200, mimetype='application/json')


@custom_code.route("/nudge", methods=["POST"])
def nudge():
    """Call the participant submission trigger for everyone who finished."""
    exp = experiment(session)

    exp.log("Nudging the experiment along.")

    # If a participant is hung at status 4, we must have missed the
    # notification saying they had submitted, so we bump them to status 100
    # and run the submission trigger.
    participants = Participant.query.filter_by(status=4).all()

    for participant in participants:

        exp.log("Nudging participant {}".format(participant))

        # Anonymize the data by storing a SHA512 hash of the psiturk uniqueid.
        if config.getboolean('Database Parameters', 'anonymize_data'):
            participant_uuid = hashlib.sha512(participant.uniqueid).hexdigest()
        else:
            participant_uuid = participant.uniqueid

        # Assign participant status 100.
        participant.status = 100
        session_psiturk.commit()

        # Recruit new participants.
        exp.participant_submission_trigger(
            participant_uuid=participant_uuid,
            assignment_id=participant.assignmentid)

    # If a participant has status 3, but has an endhit time, something must
    # have gone awry, so we bump the status to 100 and call it a day.
    participants = Participant.query.filter(
        and_(
            Participant.status == 3,
            Participant.endhit != None)).all()

    for participant in participants:

        exp.log("Bumping {} from status 3 (with endhit time) to 100.")

        participant.status = 100
        session_psiturk.commit()

    return Response(
        dumps({"status": "success"}),
        status=200,
        mimetype='application/json')


@custom_code.route("/notifications", methods=["POST", "GET"])
def api_notifications():
    """Receive notifications from MTurk REST notifications."""

    exp = experiment(session)

    event_type = request.values['Event.1.EventType']

    exp.log("Received an {} notification, identifying participant...".format(event_type))

    assignment_id = request.values['Event.1.AssignmentId']

    if event_type == 'AssignmentAccepted':
        exp.log("AssignmentAccepted notification received")
        return Response(status=200)

    # Transform the assignment id to the SHA512 hash of the unique id from the
    # psiTurk table.
    try:
        participants = Participant.query.\
            filter(Participant.assignmentid == assignment_id).\
            all()

        participant = max(participants, key=attrgetter('beginhit'))

        key = participant.uniqueid[0:5]
        exp.log("Participant identified as {}".format(participant.uniqueid), key)

        # Anonymize the data by storing a SHA512 hash of the psiturk uniqueid.
        if config.getboolean('Database Parameters', 'anonymize_data'):
            participant_uuid = hashlib.sha512(participant.uniqueid).hexdigest()
        else:
            participant_uuid = participant.uniqueid

    except:
        exp.log("unable to identify participant.")
        exp.log("returning error, status 200")
        return Response(status=200)

    exp.log("{} notification received".format(event_type), key)

    if event_type == 'AssignmentAbandoned':
        if participant.status != 104:
            participant.status = 104
            session_psiturk.commit()
            exp.log("Failing all participant's nodes", key)
            nodes = models.Node\
                .query\
                .filter_by(participant_uuid=participant_uuid, failed=False)\
                .all()
            for node in nodes:
                node.fail()
            session.commit()

    elif event_type == 'AssignmentReturned':
        if participant.status != 103:
            participant.status = 103
            session_psiturk.commit()
            exp.log("Failing all participant's nodes", key)
            nodes = models.Node\
                .query\
                .filter_by(participant_uuid=participant_uuid, failed=False)\
                .all()
            for node in nodes:
                node.fail()
            session.commit()

    elif event_type == 'AssignmentSubmitted':

        # Skip if the participant has already submitted.
        if participant.status < 100:

            exp.log("status is {}, setting status to 100, running participant_completion_trigger".format(participant.status), key)
            participant.status = 100
            session_psiturk.commit()

            exp.participant_submission_trigger(
                participant=participant)

        else:
            exp.log("Participant status is {}, doing nothing.".format(participant.status), key)

    else:
        exp.log("Warning: no response for event_type {}".format(event_type), key)

    return Response(status=200)

    # all_event_types = [
    #     "AssignmentAccepted",
    #     "AssignmentAbandoned",
    #     "AssignmentReturned",
    #     "AssignmentSubmitted",
    #     "HITReviewable",
    #     "HITExpired",
    # ]


@custom_code.route('/quitter', methods=['POST'])
def quitter():
    """Overide the psiTurk quitter route."""
    exp = experiment(session)
    exp.log("Quitter route was hit.")
    return Response(
        dumps({"status": "success"}),
        status=200,
        mimetype='application/json')
