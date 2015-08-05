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

verbose = True


def log(text):
    if verbose:
        print ">>>> {}".format(text)
        sys.stdout.flush()

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
    init_db()  # Initialize psiTurk tables.
    exp.recruiter().open_recruitment(n=exp.initial_recruitment_size)

    session_psiturk.commit()
    session.commit()

    print "Received the launch signal."

    # Return a response.
    data = {"status": "launched"}
    js = dumps(data)
    return Response(js, status=200, mimetype='application/json')


@custom_code.route('/compute_bonus', methods=['GET'])
def compute_bonus():
    """Compute the bonus."""
    exp = experiment(session)
    if 'uniqueId' not in request.args:
        raise ExperimentError('improper_inputs')
    uniqueId = request.args['uniqueId']

    # Anonymize the data by storing a SHA512 hash of the psiturk uniqueid.
    if config.getboolean('Database Parameters', 'anonymize_data'):
        p_uuid = hashlib.sha512(uniqueId).hexdigest()
    else:
        p_uuid = uniqueId

    try:
        # Compute the bonus using experiment-specific logic.
        bonus = exp.bonus(
            participant_uuid=p_uuid)

        session.commit()

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


@custom_code.route("/agents", methods=["POST"])
def api_agent_create():
    """Sending a POST request to /agents triggers the creation of a new agent"""

    exp = experiment(session)
    verbose = exp.verbose

    if request.method == 'POST':
        unique_id = request.values["unique_id"]
        key = unique_id[0:5]

        log("{} Received POST request to /agents for participant {}".format(key, unique_id))

        participant = Participant.query.\
            filter(Participant.uniqueid == unique_id).\
            one()
        log("{} Successfully located participant".format(key))

        if participant.status not in [1, 2]:
            log("{} Participant status is {} - no new nodes will be made for them".
                format(key, participant.status))
            return Response(status=403)

        if config.getboolean('Database Parameters', 'anonymize_data'):
            log("{} hashing participant id".format(key))
            participant_uuid = hashlib.sha512(unique_id).hexdigest()
        else:
            participant_uuid = unique_id

        log("{} Participant status is {}, assigning them a new node".format(key, participant.status))
        newcomer = exp.assign_agent_to_participant(participant_uuid)

        session.commit()

        if newcomer is not None:
            log("{} Participant has been assigned Node {}".format(key, newcomer.uuid))
            data = {'agents': {'uuid': newcomer.uuid}}
            js = dumps(data)
            log("{} Returning status 200".format(key))
            return Response(js, status=200, mimetype='application/json')
        else:
            log("{} Node failed to be made for participant".format(key))
            log("{} Returning status 403")
            return Response(status=403)


@custom_code.route("/transmissions",
                   defaults={"transmission_uuid": None},
                   methods=["POST", "GET"])
@custom_code.route("/transmissions/<transmission_uuid>", methods=["GET"])
def api_transmission(transmission_uuid):
    """Create a transmission."""
    exp = experiment(session)

    if request.method == 'GET':

        log("       Recevied a Transmission GET request")

        # Given a receiving agent, get its pending transmissions
        if transmission_uuid is None:
            log("       Getting all pending transmissions")
            pending_transmissions = models.Transmission\
                .query\
                .filter_by(destination_uuid=request.values['destination_uuid'],
                           receive_time=None)\
                .all()

        # Or given a uuid, get the transmission with the given id
        else:
            log("       Getting transmission {}".format(transmission_uuid))
            try:
                transmission = models.Transmission\
                    .query\
                    .filter_by(uuid=transmission_uuid)\
                    .one()
            except:
                log("       Transmission does not exist, critical error")
                return Response(status=403)
            pending_transmissions = [transmission]

        log("       {}".format(pending_transmissions))
        log("       Running transmission_reception_trigger")
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

        log("       returning transmissions, status 200")

        def date_handler(obj):
            return obj.isoformat() if hasattr(obj, 'isoformat') else obj

        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')

    if request.method == "POST":

        log("       Received a transmission post Request")

        try:
            info = models.Info\
                .query\
                .filter_by(uuid=request.values['info_uuid'])\
                .one()
        except:
            log("       Info does not exist, critical error, returning status 403")
            return Response(status=403)

        try:
            origin = models.Node\
                .query.filter_by(uuid=request.values['origin_uuid'])\
                .one()
        except:
            log("       Origin does not exist, critical error, returning status 403")
            return Response(status=403)

        try:
            destination = nodes.Agent\
                .query.filter_by(uuid=request.values['destination_uuid'])\
                .one()
        except:
            log("       Desintation does not exist, critical error, returning status 403")
            return Response(status=403)

        log("       Transmitting...")
        transmission = origin.transmit(what=info, to_whom=destination)

        session.commit()

        data = {'uuid': transmission.uuid}
        js = dumps(data)

        log("       Returning transmission uuid, status = 200")
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

        log("       Recevied an information GET request")

        if info_uuid is not None:

            log("       Getting requested info")
            try:
                info_uuid = int(info_uuid)
            except:
                log("       info_uuid {} is not an int, critical error, returning status 403".format(info_uuid))
                return Response(status=403)
            try:
                info = models.Info.query.filter_by(uuid=info_uuid).one()
            except:
                log("       Info does not exist, critical error, returning status = 403")
                return Response(status=403)

            data = {
                'info_uuid': info_uuid,
                'contents': info.contents,
                'origin_uuid': info.origin_uuid,
                'creation_time': info.creation_time,
                'type': info.type
            }

            js = dumps(data, default=date_handler)

            log("       returning info, status = 200")

            return Response(js, status=200, mimetype='application/json')

        else:

            log("       Getting all infos")

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

                log("       returning infos, status = 200")
                return Response(js, status=200, mimetype='application/json')
            else:
                log("       there were no infos to get! Returning status 200")
                return Response(status=200)

    if request.method == "POST":

        log("       Received an information POST request")

        try:
            origin_uuid = request.values['origin_uuid']
        except:
            log("       origin uuid not specified, critical error, returning status = 403")
            return Response(status=403)
        try:
            origin_uuid = int(origin_uuid)
        except:
            log("       origin uuid {} is not an int, ciritical error, returning status 403".format(origin_uuid))
            return Response(status=403)

        # models
        try:
            node = models.Node\
                .query\
                .filter_by(uuid=origin_uuid)\
                .one()
        except:
            log("       Origin node does not exist, critical error, returning status = 403")
            return Response(status=403)

        try:
            cnts = urllib.unquote(request.values['contents']).decode('utf8')
        except:
            log("       Contents do not exist or cannot be decoded, critical error, returning status = 403")
            return Response(status=403)

        # Create an Info of the requested type.
        try:
            info_type = request.values['info_type']
        except:
            log("       info_type not specified, critical error, returning status = 403")
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
            log("Requested info_type does not exist., returning status = 403")
            return Response(status=403)

        log("       making info")
        info = cls(
            origin=node,
            contents=cnts)

        # Trigger experiment-specific behavior that happens on creationg
        log("       running information creation trigger")
        exp.information_creation_trigger(info)
        session.commit()

        data = {'uuid': info.uuid}

        js = dumps(data)

        log("       returning info uuid, status = 200")

        return Response(js, status=200, mimetype='application/json')


@custom_code.route("/nudge", methods=["POST"])
def nudge():
    """Call the participant completion trigger for everyone who finished."""
    exp = experiment(session)

    print "Nudging the experiment along."

    # If a participant is hung at status 4, we must have missed the
    # notification saying they had submited, so we bump them to status 5
    # and run the completion trigger.
    participants = Participant.query.filter_by(status=4).all()

    for participant in participants:

        print "Nudging participant {}".format(participant)

        # Anonymize the data by storing a SHA512 hash of the psiturk uniqueid.
        if config.getboolean('Database Parameters', 'anonymize_data'):
            participant_uuid = hashlib.sha512(participant.uniqueid).hexdigest()
        else:
            participant_uuid = participant.uniqueid

        # Assign participant status 4.
        participant.status = 5
        session_psiturk.add(participant)
        session_psiturk.commit()

        # Recruit new participants.
        exp.participant_completion_trigger(
            participant_uuid=participant_uuid,
            assignment_id=participant.assignmentid)

    # If a participant has status 3, but has an endhit time, something must
    # have gone awry, so we bump the status to 5 and call it a day.
    participants = Participant.query.filter(
        and_(
            Participant.status == 3,
            Participant.endhit != None)).all()

    for participant in participants:

        print "Bumping {} from status 3 (with endhit time) to 5."

        participant.status = 5
        session_psiturk.add(participant)
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

    log("????? Received an {} notification, identifying participant...".format(event_type))

    assignment_id = request.values['Event.1.AssignmentId']

    # Transform the assignment id to the SHA512 hash of the unique id from the
    # psiTurk table.
    try:
        participants = Participant.query.\
            filter(Participant.assignmentid == assignment_id).\
            all()

        participant = max(participants, key=attrgetter('beginhit'))

        key = participant.uniqueid[0:5]
        log("{} Participant identified as {}".format(key, participant.uniqueid))

        # Anonymize the data by storing a SHA512 hash of the psiturk uniqueid.
        if config.getboolean('Database Parameters', 'anonymize_data'):
            participant_uuid = hashlib.sha512(participant.uniqueid).hexdigest()
        else:
            participant_uuid = participant.uniqueid

    except:
        log("????? unable to identify participant.")
        log("????? returning error, status 200")
        return Response(status=200)

    log("{} {} notification received".format(key, event_type))

    if event_type == 'AssignmentAccepted':
        pass

    elif event_type == 'AssignmentAbandoned':
        if participant.status != 'abandoned':
            participant.status = 'abandoned'
            session_psiturk.commit()
            log("{} Failing all participant's nodes".format(key))
            nodes = models.Node\
                .query\
                .filter_by(participant_uuid=participant_uuid, failed=False)\
                .all()
            for node in nodes:
                node.fail()
            session.commit()

    elif event_type == 'AssignmentReturned':
        if participant.status != 'returned':
            participant.status = 'returned'
            session_psiturk.commit()
            log("{} Failing all participant's nodes".format(key))
            nodes = models.Node\
                .query\
                .filter_by(participant_uuid=participant_uuid, failed=False)\
                .all()
            for node in nodes:
                node.fail()
            session.commit()

    elif event_type == 'AssignmentSubmitted':

        # Skip if the participant has already submitted.
        if participant.status != 'submitted':

            log("{} status is {}, setting status to submitted, running participant_completion_trigger".format(key, participant.status))
            participant.status = 'submitted'
            session_psiturk.commit()

            exp.participant_completion_trigger(
                participant_uuid=participant_uuid,
                assignment_id=assignment_id)

        else:
            log("{} Participant status is {}, doing nothing.".format(key, participant.status))

    else:
        log("{} Warning: no response for event_type {}".format(key, event_type))

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
    log("Quitter route was hit.")
