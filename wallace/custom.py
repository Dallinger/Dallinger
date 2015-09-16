"""Import custom routes into the experiment server."""

from flask import Blueprint, request, Response, send_from_directory, jsonify

from psiturk.psiturk_config import PsiturkConfig
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
from operator import attrgetter
import datetime

from sqlalchemy import and_, exc

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


@custom_code.route('/robots.txt')
def static_from_root():
    """"Serve robots.txt from static file."""
    return send_from_directory('static', request.path[1:])


@custom_code.route('/launch', methods=['POST'])
def launch():
    """Launch the experiment."""
    exp = experiment(db.init_db(drop_all=False))
    exp.log("Launch route hit, laucnhing experiment", "-----")
    exp.log("Experiment launching, initiailizing tables", "-----")
    init_db()
    exp.log("Experiment launching, opening recruitment", "-----")
    exp.recruiter().open_recruitment(n=exp.initial_recruitment_size)

    session_psiturk.commit()
    session.commit()

    exp.log("Experiment successfully launched, retuning status 200", "-----")
    data = {"status": "launched"}
    js = dumps(data)
    return Response(js, status=200, mimetype='application/json')


@custom_code.route('/compute_bonus', methods=['GET'])
def compute_bonus():
    """Overide the psiTurk compute_bonus route."""
    return Response(dumps({"bonusComputed": "success"}), status=200)


@custom_code.route('/summary', methods=['GET'])
def summary():
    """Summarize the participants' status codes."""
    exp = experiment(session)
    data = {"status": exp.log_summary()}
    js = dumps(data)
    return Response(js, status=200, mimetype='application/json')


@custom_code.route('/auto_recruit', defaults={"value": None}, methods=['GET', 'POST'])
def auto_recruit(value):
    auto_recruit = config.get('Experiment Configuration', 'auto_recruit')
    exp = experiment(session)
    if request.method == "GET":
        exp.log("Received a GET request to /auto_recruit. Returning {}".format(auto_recruit))
        data = {'auto_recruit': auto_recruit}
        js = dumps(data)
        return Response(js, status=200, mimetype='application/json')
    if request.method == "POST":
        value = request.values["value"]
        exp.log("Received a POST request to /auto_recruit.")
        if value is None:
            if auto_recruit:
                config.set("Experiment Configuration", "auto_Recruit", "false")
            else:
                config.set("Experiment Configuration", "auto_Recruit", "true")
            exp.log("New value for auto_recruit not specified, so inverting to {}".format(not auto_recruit))
            return Response(status=200)
        elif value in ["True", "False"]:
            value = value == "True"
            if value:
                config.set("Experiment Configuration", "auto_Recruit", "true")
                exp.log("Auto_recruit set to True")
            else:
                config.set("Experiment Configuration", "auto_Recruit", "false")
                exp.log("Auto_recruit set to False")
            return Response(status=200)
        else:
            exp.log("{} is not a valid value for auto_recruit, doing nothing".format(value))
            return Response(status=200)


@custom_code.route('/worker_complete', methods=['GET'])
def worker_complete():
    """Overide the psiTurk worker_complete route.

    This skirts around an issue where the participant's status reverts to 3
    because of rogue calls to this route. It does this by changing the status
    only if it's not already >= 100.
    """
    exp = experiment(session)

    if 'uniqueId' not in request.args:
        resp = {"status": "bad request"}
        return jsonify(**resp)
    else:
        unique_id = request.args['uniqueId']
        exp.log("Completed experiment %s" % unique_id)
        try:
            user = Participant.query.\
                filter(Participant.uniqueid == unique_id).one()
            if user.status < 100:
                user.status = 3
                user.endhit = datetime.datetime.now()
                session_psiturk.add(user)
                session_psiturk.commit()
            status = "success"
        except exc.SQLAlchemyError:
            status = "database error"
        resp = {"status": status}
        return jsonify(**resp)


@custom_code.route("/agents", methods=["POST"])
def api_agent_create():
    """A route that triggers creation of a new agent."""
    exp = experiment(session)

    if request.method == 'POST':
        participant_uuid = request.values["unique_id"]
        key = participant_uuid[0:5]

        exp.log("Received POST request to /agents for participant {}".format(participant_uuid), key)
        participant = Participant.query.\
            filter(Participant.uniqueid == participant_uuid).all()
        if len(participant) == 0:
            exp.log("Error: No participants with that id. Returning status 403", key)
            return Response(status=403)
        if len(participant) > 1:
            exp.log("Error: Multiple participants with that id. Returning status 403", key)
            return Response(status=403)
        participant = participant[0]

        exp.log("Checking participant status", key)
        if participant.status not in [1, 2]:
            exp.log("Error: Participant status is {} they should not have been able to contact this route. Returning status 403.".
                    format(participant.status), key)
            return Response(status=403)

        exp.log("Assigning participant a new node".format(participant.status), key)
        newcomer = exp.assign_agent_to_participant(participant_uuid)
        session.commit()

        if newcomer is not None:
            exp.log("Participant has been assigned Node {}, returning status 200".format(newcomer.uuid), key)
            data = {'agents': {'uuid': newcomer.uuid}}
            js = dumps(data)
            return Response(js, status=200, mimetype='application/json')
        else:
            exp.log("Node not made for participant, hopefully because they are finished, returning status 403", key)
            return Response(status=403)


@custom_code.route("/transmissions",
                   defaults={"transmission_uuid": None},
                   methods=["POST", "GET"])
@custom_code.route("/transmissions/<transmission_uuid>", methods=["GET"])
def api_transmission(transmission_uuid):
    """Create a transmission."""
    exp = experiment(session)

    if request.method == 'GET':

        destination_uuid = request.values['destination_uuid']

        # Ensure that destination_uuid is a number.
        if not destination_uuid.isdigit():
            exp.log(
                "Malformed uuid: {}".format(destination_uuid),
                destination_uuid)
            return Response(status=403)

        exp.log("Recevied a Transmission GET request", destination_uuid)

        # Given a receiving agent, get its pending transmissions
        if transmission_uuid is None:
            exp.log("Getting all pending transmissions", destination_uuid)
            pending_transmissions = models.Transmission\
                .query\
                .filter_by(destination_uuid=destination_uuid,
                           receive_time=None)\
                .all()

        # Or given a uuid, get the transmission with the given id
        else:
            exp.log("Getting transmission {}".format(transmission_uuid), destination_uuid)
            try:
                transmission = models.Transmission\
                    .query\
                    .filter_by(uuid=transmission_uuid)\
                    .one()
            except:
                exp.log("Error: Transmission {} does not exist. Returning status 403".format(transmission_uuid), destination_uuid)
                return Response(status=403)
            pending_transmissions = [transmission]

        exp.log("Running transmission_reception_trigger", destination_uuid)
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

        exp.log("Returning transmissions, status 200", destination_uuid)

        def date_handler(obj):
            return obj.isoformat() if hasattr(obj, 'isoformat') else obj

        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')

    if request.method == "POST":

        try:
            # Ensure that destination_uuid is a number.
            destination_uuid = request.values['destination_uuid']
            if not destination_uuid.isdigit():
                exp.log(
                    "Malformed uuid: {}".format(destination_uuid),
                    destination_uuid)
                return Response(status=403)

            # Ensure that origin_uuid is a number.
            origin_uuid = request.values['origin_uuid']
            if not origin_uuid.isdigit():
                exp.log(
                    "Malformed uuid: {}".format(origin_uuid),
                    destination_uuid)
                return Response(status=403)

            # Ensure that info_uuid is a number.
            info_uuid = request.values['info_uuid']
            if not info_uuid.isdigit():
                exp.log(
                    "Malformed uuid: {}".format(info_uuid),
                    destination_uuid)
                return Response(status=403)

        except:
            exp.log("Error: Recevied a transmission POST request, but origin_uuid, destination_uuid or info_uuid not specified. Returning status 403")
            return Response(status=403)

        exp.log("Received a transmission post request to send info {} from node {} to node {}".format(info_uuid, origin_uuid, destination_uuid), origin_uuid)

        try:
            info = models.Info\
                .query\
                .filter_by(uuid=info_uuid)\
                .one()
        except:
            exp.log("Error: Info {} does not exist, returning status 403".format(info_uuid), origin_uuid)
            return Response(status=403)

        try:
            origin = models.Node\
                .query.filter_by(uuid=origin_uuid)\
                .one()
        except:
            exp.log("Error: Node {} does not exist, returning status 403".format(origin_uuid), origin_uuid)
            return Response(status=403)

        try:
            destination = nodes.Agent\
                .query.filter_by(uuid=destination_uuid)\
                .one()
        except:
            exp.log("Error: Node {} does not exist, returning status 403".format(destination_uuid), origin_uuid)
            return Response(status=403)

        exp.log("Transmitting...", origin_uuid)
        transmission = origin.transmit(what=info, to_whom=destination)
        session.commit()

        data = {'uuid': transmission.uuid}
        js = dumps(data)
        exp.log("Transmission successful, returning transmission uuid and status = 200")
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

            exp.log("Received an /information GET request for info {}".format(info_uuid), info_uuid)

            # Ensure that info_uuid is a number.
            if not info_uuid.isdigit():
                exp.log(
                    "Malformed uuid: {}; from info GET.".format(info_uuid))
                return Response(status=403)

            try:
                info = models.Info.query.filter_by(uuid=info_uuid).one()
            except:
                exp.log("Error: Info {} does not exist, returning status = 403")
                return Response(status=403)

            data = {
                'info_uuid': info_uuid,
                'contents': info.contents,
                'origin_uuid': info.origin_uuid,
                'creation_time': info.creation_time,
                'type': info.type
            }

            js = dumps(data, default=date_handler)

            exp.log("Success: returning info, status = 200", info_uuid)
            return Response(js, status=200, mimetype='application/json')

        else:

            try:
                # Ensure that origin_uuid is a number.
                origin_uuid = request.values['origin_uuid']
                if not origin_uuid.isdigit():
                    exp.log(
                        "Malformed uuid: {}; from info GET2.".format(origin_uuid))
                    return Response(status=403)

            except:
                exp.log("Error: Received an information get request but neither info_uuid or origin_uuid specified. Returning status 403")
                return Response(status=403)

            exp.log("Received an /information GET request from node {}".format(origin_uuid), origin_uuid)

            infos = models.Info\
                .query\
                .filter_by(origin_uuid=origin_uuid)\
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

                exp.log("Success: Returning infos, status = 200", origin_uuid)
                return Response(js, status=200, mimetype='application/json')
            else:
                exp.log("Warning: Node {} has no infos. Returning status 200".format(origin_uuid), origin_uuid)
                return Response(status=200)

    if request.method == "POST":

        try:
            # Ensure that origin_uuid is a number.
            origin_uuid = request.values['origin_uuid']
            if not origin_uuid.isdigit():
                exp.log(
                    "Malformed uuid: {}; from info POST.".format(origin_uuid))
                return Response(status=403)

        except:
            exp.log("Error: received information POST request, but origin_uuid not specified. Returning status 403")
            return Response(status=403)

        try:
            cnts = urllib.unquote(request.values['contents']).decode('utf8')
        except:
            exp.log("Error: received information POST request from Node {}, but contents not specified. Returning status 403".format(origin_uuid), origin_uuid)
            return Response(status=403)
        info_type = request.values['info_type']
        exp.log("Received an information post request from node {}".format(origin_uuid), origin_uuid)

        try:
            node = models.Node\
                .query\
                .filter_by(uuid=origin_uuid)\
                .one()
        except:
            exp.log("Error: Node {} does not exist, returning status = 403".format(origin_uuid), origin_uuid)
            return Response(status=403)

        # Create an Info of the requested type.
        if (info_type is None) or (info_type == "base"):
            cls = models.Info
        elif info_type == "meme":
            cls = information.Meme
        elif info_type == "gene":
            cls = information.Gene
        elif info_type == "state":
            cls = information.State
        else:
            exp.log("Error: Requested info_type does not exist, returning status = 403", origin_uuid)
            return Response(status=403)

        exp.log("Making info", origin_uuid)
        info = cls(
            origin=node,
            contents=cnts)

        # Trigger experiment-specific behavior that happens on creationg
        exp.log("Info successfully made, running information creation trigger", origin_uuid)
        exp.information_creation_trigger(info)
        session.commit()

        data = {'uuid': info.uuid}
        js = dumps(data)
        exp.log("Success, returning info uuid, status = 200", origin_uuid)
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
    """Receive MTurk REST notifications."""
    exp = experiment(session)
    event_type = request.values['Event.1.EventType']
    assignment_id = request.values['Event.1.AssignmentId']

    if event_type == 'AssignmentAccepted':
        exp.log("AssignmentAccepted notification received for assignment {}".format(assignment_id))
        participants = Participant.query.filter_by(assignmentid=assignment_id).all()
        if len(participants) > 1:
            exp.log("Warning: There are {} participants associated with this assignment, failing all but most recent".format(len(participants)))
            newest = max(participants, key=attrgetter('beginhit'))
            for participant in participants:
                if participant != newest and participant.status < 100:
                    exp.log("Failing nodes of participant {} and setting their status to 106".format(participant.uniqueid))
                    participant.status = 106
                    for node in models.Node.query.filter_by(participant_uuid=participant.uniqueid, failed=False).all():
                        node.fail()
            session.commit()
            session_psiturk.commit()
        return Response(status=200)

    participants = Participant.query.\
        filter(Participant.assignmentid == assignment_id).\
        all()

    if len(participants) > 1:
        participant = max(participants, key=attrgetter('beginhit'))

    elif len(participants) == 0:
        exp.log("Error: Received an {} notification, but unable to identify participant. Returning status 200".format(event_type))
        return Response(status=200)

    else:
        participant = participants[0]

    participant_uuid = participant.uniqueid
    key = participant_uuid[0:5]

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
        if participant.status < 100:  # Skip if already submitted.
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


@custom_code.route('/quitter', methods=['POST'])
def quitter():
    """Overide the psiTurk quitter route."""
    exp = experiment(session)
    exp.log("Quitter route was hit.")
    return Response(
        dumps({"status": "success"}),
        status=200,
        mimetype='application/json')
