"""Import custom routes into the experiment server."""

from flask import Blueprint, request, jsonify, Response, abort

from psiturk.psiturk_config import PsiturkConfig
from psiturk.experiment_errors import ExperimentError
from psiturk.user_utils import PsiTurkAuthorization

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


@custom_code.route('/launch', methods=['POST'])
def launch():
    """Launch the experiment."""
    exp = experiment(session)
    exp.recruiter().open_recruitment(n=exp.initial_recruitment_size)


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

        if verbose:
            print ">>>>{} Received POST request to /agents for participant {}".format(key, unique_id)

        participant = Participant.query.\
            filter(Participant.uniqueid == unique_id).\
            one()
        if verbose:
            print ">>>>{} Successfully located participant".format(key)

        if participant.status not in [1, 2]:
            if verbose:
                print ">>>>{} Participant status is {} - no new nodes will be made for them".\
                    format(key, participant.status)
            return Response(status=403)

        if config.getboolean('Database Parameters', 'anonymize_data'):
            if verbose:
                print ">>>>{} hashing participant id".format(key)
            participant_uuid = hashlib.sha512(unique_id).hexdigest()
        else:
            participant_uuid = unique_id

        if verbose:
            print ">>>>{} Participant status is {}, assigning them a new node".format(key, participant.status)
        newcomer = exp.assign_agent_to_participant(participant_uuid)

        if newcomer is not None:
            if verbose:
                print ">>>>{} Participant has been assigned Node {}".format(key, newcomer.uuid)
            data = {'agents': {'uuid': newcomer.uuid}}
            js = dumps(data)
            if verbose:
                print ">>>>{} Returning status 200".format(key)
            return Response(js, status=200, mimetype='application/json')
        else:
            if exp.verbose:
                print ">>>>{} Node failed to be made for participant".format(key)
                print ">>>>{} Returning status 403"
            return Response(status=403)


@custom_code.route("/transmissions",
                   defaults={"transmission_uuid": None},
                   methods=["POST", "GET"])
@custom_code.route("/transmissions/<transmission_uuid>", methods=["GET"])
def api_transmission(transmission_uuid):
    """Create a transmission."""
    exp = experiment(session)
    session.commit()

    if request.method == 'GET':

        # Given a receiving agent, get its pending transmissions
        if transmission_uuid is None:
            pending_transmissions = models.Transmission\
                .query\
                .filter_by(destination_uuid=request.values['destination_uuid'])\
                .filter_by(receive_time=None)\
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
                "creation_time": t.creation_time,
                "receive_time": t.receive_time
            })
            data = {"transmissions": data_transmissions}

        if not data:
            print "{} made a GET request for transmissions, ".format(
                request.values['destination_uuid']) + \
                "but there were no transmissions to get."

        def date_handler(obj):
            return obj.isoformat() if hasattr(obj, 'isoformat') else obj

        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')

    if request.method == "POST":

        info = models.Info\
            .query\
            .filter_by(uuid=request.values['info_uuid'])\
            .one()

        destination = nodes.Agent\
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
    """Create and access informaiton."""
    exp = experiment(session)

    def date_handler(obj):
        return obj.isoformat() if hasattr(obj, 'isoformat') else obj

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

            js = dumps(data, default=date_handler)

            return Response(js, status=200, mimetype='application/json')

        else:

            infos = models.Info\
                .query\
                .filter_by(origin_uuid=request.values['origin_uuid'])\
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

            js = dumps({"information": data_information}, default=date_handler)
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

            def date_handler(obj):
                return obj.isoformat() if hasattr(obj, 'isoformat') else obj

            js = dumps(data, default=date_handler)

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
    verbose = exp.verbose

    event_type = request.values['Event.1.EventType']

    if verbose:
        print ">>>>????? Received an {} notification, identifying participant...".format(event_type)

    # Get the assignment id.
    assignment_id = request.values['Event.1.AssignmentId']
    print "Assignmet id is {}, available ids are: {}".format(assignment_id, [a.assignmentid for a in Participant.query.all()])

    # Transform the assignment id to the SHA512 hash of the unique id from the
    # psiTurk table.
    try:
        participants = Participant.query.\
            filter(Participant.assignmentid == assignment_id).\
            all()

        participant = max(participants, key=attrgetter('beginhit'))

        key = participant.uniqueid[0:5]
        if verbose:
            print ">>>>{} Participant identified as {}".format(key, participant.uniqueid)

        # Anonymize the data by storing a SHA512 hash of the psiturk uniqueid.
        if config.getboolean('Database Parameters', 'anonymize_data'):
            participant_uuid = hashlib.sha512(participant.uniqueid).hexdigest()
        else:
            participant_uuid = participant.uniqueid

    except:
        if verbose:
            print ">>>>????? unable to identify participant."
            print ">>>>????? returning error, status 200"
        return Response(
            dumps({"status": "error"}),
            status=200,
            mimetype='application/json')

    print "Triggered event of type {} for assignment {}".format(
        event_type, assignment_id)

    if event_type == 'AssignmentAccepted':
        pass

    elif event_type in ['AssignmentAbandoned', 'AssignmentReturned']:

        if event_type == 'AssignmentAbandoned':
            if verbose:
                print ">>>>{} status set to 8".format(key)
            participant.status = 8
        else:
            if verbose:
                print ">>>>{} status set to 6".format(key)
            participant.status = 6

        session_psiturk.commit()

        if verbose:
            print ">>>>{} Failing all participant's nodes".format(key)

        # Get the all nodes associated with the participant.
        nodes = models.Node\
            .query\
            .filter_by(participant_uuid=participant_uuid, failed=False)\
            .all()

        for node in nodes:
            print ">>>>{} Failing node {}.".format(key, node)
            node.fail()

        session.commit()

    elif event_type == 'AssignmentSubmitted':

        # Skip if the participant's status is 5 or greater (credited).
        if participant.status < 5:

            if verbose:
                print ">>>>{} status is {}, setting status to 5, running participant_completion_trigger".format(key, participant.status)

            # Assign participant status 4.
            participant.status = 5
            session_psiturk.add(participant)
            session_psiturk.commit()

            # Recruit new participants.
            exp.participant_completion_trigger(
                participant_uuid=participant_uuid,
                assignment_id=assignment_id)
        else:
            if verbose:
                print ">>>>{} Participant status is {}, doing nothing.".format(key, participant.status)

    if verbose:
        print ">>>>{} Returning success, status 200".format(key)
    return Response(
        dumps({"status": "success"}),
        status=200,
        mimetype='application/json')

    # all_event_types = [
    #     "AssignmentAccepted",
    #     "AssignmentAbandoned",
    #     "AssignmentReturned",
    #     "AssignmentSubmitted",
    #     "HITReviewable",
    #     "HITExpired",
    # ]
