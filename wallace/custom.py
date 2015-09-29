"""Import custom routes into the experiment server."""

from flask import Blueprint, request, Response, send_from_directory, \
    jsonify, render_template

from psiturk.psiturk_config import PsiturkConfig
from psiturk.user_utils import PsiTurkAuthorization
from psiturk.db import init_db

# Database setup
from psiturk.db import db_session as session_psiturk
from psiturk.models import Participant
from json import dumps

from wallace import db, models

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
    data = {"status": "success"}
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
    data = {"status": "success", "summary": exp.log_summary()}
    js = dumps(data)
    return Response(js, status=200, mimetype='application/json')


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


@custom_code.route("/node", methods=["POST", "GET"])
def node():
    """ Send GET or POST requests to the node table.

    POST requests call the node_post_request method
    in Experiment, which, by deafult, makes a new node
    for the participant. This request returns a
    description of the new node.
    Required arguments: participant_id

    GET requests call the node_get_request method
    in Experiment, which, by default, call the
    neighbours method of the node making the request.
    This request returns a list of descriptions of
    the nodes (even if there is only one).
    Required arguments: participant_id, node_id
    Optional arguments: type, failed, connection
    """
    exp = experiment(session)
    try:
        participant_id = request.values["participant_id"]
        key = participant_id[0:5]
    except:
        exp.log("/node request failed: participant_id not specified")
        page = error_page(error_type="/node, participant_id not specified")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=403, mimetype='application/json')

    if request.method == "GET":
        try:
            node_id = request.values["node_id"]
        except:
            exp.log("/node GET request failed: node_id not specified", key)
            page = error_page(error_type="/node GET, node_id not specified")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')
        if not node_id.isdigit():
            exp.log(
                "Malformed node_id: {}".format(node_id),
                key)
            page = error_page(error_type="/node GET, malformed node_id")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')
        exp.log("Received a /node GET request from node {}".format(node_id), key)
        try:
            type = request.values["type"]
            if type in exp.trusted_strings:
                type = exp.evaluate(type)
            else:
                exp.log("/node GET request failed: bad type {}".format(type), key)
                page = error_page(error_type="/node GET, bad type")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=403, mimetype='application/json')
        except:
            type = None
        try:
            failed = request.values["failed"]
        except:
            failed = False
        try:
            connection = request.values["connection"]
        except:
            connection = "to"

        exp.log("Getting requested nodes", key)
        nodes = exp.node_get_request(participant_id=participant_id, node_id=node_id, type=type, failed=failed, connection=connection)

        exp.log("Creating data to return", key)
        data = []
        for n in nodes:
            data.append({
                "id": n.id,
                "type": n.type,
                "network_id": n.network_id,
                "creation_time": n.creation_time,
                "time_of_death": n.receive_time,
                "failed": n.failed,
                "participant_id": n.participant_id,
                "property1": n.property1,
                "property2": n.property2,
                "property3": n.property3,
                "property4": n.property4,
                "property5": n.property5
            })
        data = {"status": "success", "nodes": data}

        exp.log("Data successfully created, returning.", key)
        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')

    elif request.method == "POST":
        exp.log("Received a /node POST request from participant {}".format(participant_id), key)
        exp.log("Checking participant exists", key)
        participant = Participant.query.\
            filter(Participant.uniqueid == participant_id).all()
        if len(participant) == 0:
            exp.log("Error: No participants with that id. Returning status 403", key)
            page = error_page(error_text="You cannot continue because your worker id does not match anyone in our records.", error_type="/agents no participant found")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')
        if len(participant) > 1:
            exp.log("Error: Multiple participants with that id. Returning status 403", key)
            page = error_page(error_text="You cannot continue because your worker id is the same as someone else's.", error_type="/agents multiple participants found")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')
        participant = participant[0]

        exp.log("Checking participant status", key)
        if participant.status not in [1, 2]:
            exp.log("Error: Participant status is {} they should not have been able to contact this route. Returning error_wallace.html.".format(participant.status), key)
            if participant.status in [3, 4, 5, 100, 101, 102, 105]:
                page = error_page(participant=participant, error_text="You cannot continue because we have received a notification from AWS that you have already submitted the assignment.'", error_type="/agents POST, status = {}".format(participant.status))
            elif participant.status == 103:
                page = error_page(participant=participant, error_text="You cannot continue because we have received a notification from AWS that you have returned the assignment.'", error_type="/agents POST, status = {}".format(participant.status))
            elif participant.status == 104:
                page = error_page(participant=participant, error_text="You cannot continue because we have received a notification from AWS that your assignment has expired.", error_type="/agents POST, status = {}".format(participant.status))
            elif participant.status == 106:
                page = error_page(participant=participant, error_text="You cannot continue because we have received a notification from AWS that your assignment has been assigned to someone else.", error_type="/agents POST, status = {}".format(participant.status))
            else:
                page = error_page(participant=participant, error_type="/agents POST, status = {}".format(participant.status))

            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')

        exp.log("All checks passed: posting new node", key)
        node = exp.node_post_request(participant_id=participant_id)
        session.commit()

        if node is None:
            exp.log("Node not made for participant, hopefully because they are finished, returning status 403", key)
            js = dumps({"status": "error"})
            return Response(js, status=403)

        exp.log("Node successfully posted, creating data to return", key)
        data = {
            "id": node.id,
            "type": node.type,
            "network_id": node.network_id,
            "creation_time": node.creation_time,
            "time_of_death": node.time_of_death,
            "failed": node.failed,
            "participant_id": node.participant_id,
            "property1": node.property1,
            "property2": node.property2,
            "property3": node.property3,
            "property4": node.property4,
            "property5": node.property5
        }
        data = {"status": "success", "node": data}

        exp.log("Data successfully created, returning.", key)
        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')


@custom_code.route("/transmissions",
                   defaults={"transmission_id": None},
                   methods=["POST", "GET"])
@custom_code.route("/transmissions/<transmission_id>", methods=["GET"])
def api_transmission(transmission_id):
    """Receive or send/create transmissions."""
    exp = experiment(session)

    # check that a destination is specified
    try:
        destination_id = request.values['destination_id']
    except:
        page = error_page(error_type="/transmissions GET/POST, no destination id")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=403, mimetype='application/json')

    # Ensure that destination_id is a number.
    if not destination_id.isdigit():
        exp.log(
            "Malformed destination id: {}".format(destination_id),
            destination_id)
        page = error_page(error_type="/transmissions GET/POST, malformed destination id")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=403, mimetype='application/json')

    if request.method == 'GET':
        exp.log("Recevied a Transmission GET request", destination_id)

        # Given a receiving agent, get its pending transmissions
        if transmission_id is None:
            exp.log("Getting all pending transmissions", destination_id)
            pending_transmissions = models.Transmission\
                .query\
                .filter_by(destination_id=destination_id,
                           receive_time=None)\
                .all()

        # Or given a id, get the transmission with the given id
        else:
            exp.log("Getting transmission {}".format(transmission_id), destination_id)
            try:
                transmission = models.Transmission\
                    .query\
                    .filter_by(id=transmission_id)\
                    .one()
            except:
                exp.log("Error: Transmission {} does not exist. Returning status 403".format(transmission_id), destination_id)
                page = error_page(error_type="/transmissions GET, transmission does not exist")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=403, mimetype='application/json')
            pending_transmissions = [transmission]

        exp.log("Running transmission_reception_trigger", destination_id)
        try:
            exp.transmission_reception_trigger(pending_transmissions)
            session.commit()
        except:
            session.commit()
            exp.log("Error while running transmission_reception_trigger", destination_id)
            page = error_page(error_type="/transmissions GET, transmission_reception_trigger")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')

        # Build a dict with info about the transmissions
        data_transmissions = []
        for t in pending_transmissions:
            data_transmissions.append({
                "id": t.id,
                "info_id": t.info_id,
                "origin_id": t.origin_id,
                "destination_id": t.destination_id,
                "creation_time": t.creation_time,
                "receive_time": t.receive_time
            })
        data = {"status": "success", "transmissions": data_transmissions}

        exp.log("Returning transmissions, status 200", destination_id)

        def date_handler(obj):
            return obj.isoformat() if hasattr(obj, 'isoformat') else obj

        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')

    if request.method == "POST":

        try:
            # Ensure that origin_id is a number.
            origin_id = request.values['origin_id']
            if not origin_id.isdigit():
                exp.log(
                    "Malformed id: {}".format(origin_id),
                    destination_id)
                page = error_page(error_type="/transmissions POST, malformed origin id")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=403, mimetype='application/json')

            # Ensure that info_id is a number.
            info_id = request.values['info_id']
            if not info_id.isdigit():
                exp.log(
                    "Malformed id: {}".format(info_id),
                    destination_id)
                page = error_page(error_type="/transmissions POST, malformed info id")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=403, mimetype='application/json')

        except:
            exp.log("Error: Recevied a transmission POST request, but origin_id, destination_id or info_id not specified. Returning status 403")
            page = error_page(error_type="/transmissions POST, missing request id")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')

        exp.log("Received a transmission post request to send info {} from node {} to node {}".format(info_id, origin_id, destination_id), origin_id)

        try:
            info = models.Info\
                .query\
                .filter_by(id=info_id)\
                .one()
        except:
            exp.log("Error: Info {} does not exist, returning status 403".format(info_id), origin_id)
            page = error_page(error_type="/transmissions POST, info does not exist")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')

        try:
            origin = models.Node\
                .query.filter_by(id=origin_id)\
                .one()
        except:
            exp.log("Error: Node {} does not exist, returning status 403".format(origin_id), origin_id)
            page = error_page(error_type="/transmissions POST, origin does not exist")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')

        try:
            destination = nodes.Agent\
                .query.filter_by(id=destination_id)\
                .one()
        except:
            exp.log("Error: Node {} does not exist, returning status 403".format(destination_id), origin_id)
            page = error_page(error_type="/transmissions POST, doestination does not exist")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')

        exp.log("Creating transmission", origin_id)
        try:
            transmission = origin.transmit(what=info, to_whom=destination)
            session.commit()
        except:
            session.commit()
            exp.log("Transmission failed", origin_id)
            page = error_page(error_type="/transmissions POST, transmission failed")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')

        exp.log("Transmission successful, returning transmission id and status = 200")
        data = {"status": "success", 'id': transmission.id}
        js = dumps(data)
        return Response(js, status=200, mimetype='application/json')


@custom_code.route("/information",
                   defaults={"info_id": None},
                   methods=["POST", "GET"])
@custom_code.route("/information/<info_id>", methods=["GET"])
def api_info(info_id):
    """Create and access informaiton."""
    exp = experiment(session)

    def date_handler(obj):
        return obj.isoformat() if hasattr(obj, 'isoformat') else obj

    if request.method == 'GET':

        if info_id is not None:

            exp.log("Received an /information GET request for info {}".format(info_id), info_id)

            # Ensure that info_id is a number.
            if not info_id.isdigit():
                exp.log(
                    "Malformed id: {}; from info GET.".format(info_id))
                page = error_page(error_type="/information GET, malformed info id")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=403, mimetype='application/json')

            try:
                info = models.Info.query.filter_by(id=info_id).one()
            except:
                exp.log("Error: Info {} does not exist, returning status = 403")
                page = error_page(error_type="/information GET, info does not exist")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=403, mimetype='application/json')

            data = {
                "status": "success",
                'info_id': info_id,
                'contents': info.contents,
                'origin_id': info.origin_id,
                'creation_time': info.creation_time,
                'type': info.type
            }

            js = dumps(data, default=date_handler)

            exp.log("Success: returning info, status = 200", info_id)
            return Response(js, status=200, mimetype='application/json')

        else:

            try:
                # Ensure that origin_id is a number.
                origin_id = request.values['origin_id']
                if not origin_id.isdigit():
                    exp.log(
                        "Malformed id: {}; from info GET2.".format(origin_id))
                    page = error_page(error_type="/information GET, malformed origin id")
                    js = dumps({"status": "error", "html": page})
                    return Response(js, status=403, mimetype='application/json')

            except:
                exp.log("Error: Received an information get request but neither info_id or origin_id specified. Returning status 403")
                page = error_page(error_type="/information GET, no info or origin id")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=403, mimetype='application/json')

            exp.log("Received an /information GET request from node {}".format(origin_id), origin_id)

            infos = models.Info\
                .query\
                .filter_by(origin_id=origin_id)\
                .all()

            if infos:
                data_information = []
                for i in infos:
                    data_information.append({
                        "info_id": i.id,
                        "type": i.type,
                        "origin_id": i.origin_id,
                        "creation_time": i.creation_time,
                        "contents": i.contents
                    })

                js = dumps({"status": "success", "information": data_information}, default=date_handler)

                exp.log("Success: Returning infos, status = 200", origin_id)
                return Response(js, status=200, mimetype='application/json')
            else:
                exp.log("Warning: Node {} has no infos. Returning status 200".format(origin_id), origin_id)
                return Response(status=200)

    if request.method == "POST":

        try:
            # Ensure that origin_id is a number.
            origin_id = request.values['origin_id']
            if not origin_id.isdigit():
                exp.log(
                    "Malformed id: {}; from info POST.".format(origin_id))
                page = error_page(error_type="/information POST, malformed origin id")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=403, mimetype='application/json')

        except:
            exp.log("Error: received information POST request, but origin_id not specified. Returning status 403")
            page = error_page(error_type="/information POST, no origin id")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')

        try:
            cnts = urllib.unquote(request.values['contents']).decode('utf8')
        except:
            exp.log("Error: received information POST request from Node {}, but contents not specified. Returning status 403".format(origin_id), origin_id)
            page = error_page(error_type="/information POST, no contents")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')
        info_type = request.values['info_type']
        exp.log("Received an information post request from node {}".format(origin_id), origin_id)

        try:
            node = models.Node\
                .query\
                .filter_by(id=origin_id)\
                .one()
        except:
            exp.log("Error: Node {} does not exist, returning status = 403".format(origin_id), origin_id)
            page = error_page(error_type="/information POST, origin does not exist")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')

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
            exp.log("Error: Requested info_type does not exist, returning status = 403", origin_id)
            page = error_page(error_type="/information POST, bad info type")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')

        exp.log("Making info", origin_id)
        info = cls(
            origin=node,
            contents=cnts)

        # Trigger experiment-specific behavior that happens on creationg
        exp.log("Info successfully made, running information creation trigger", origin_id)
        try:
            exp.information_creation_trigger(info)
            session.commit()
        except:
            session.commit()
            page = error_page(error_type="/information POST, information_creation_trigger")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')

        data = {"status": "success", 'id': info.id}
        js = dumps(data)
        exp.log("Success, returning info id, status = 200", origin_id)
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
        participant_id = participant.uniqueid

        # Assign participant status 100.
        participant.status = 100
        session_psiturk.commit()

        # Recruit new participants.
        exp.participant_submission_trigger(
            participant_id=participant_id,
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

    notif = models.Notification(assignment_id=assignment_id, event_type=event_type)
    session.add(notif)
    session.commit()

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
                    session_psiturk.commit()
                    for node in models.Node.query.filter_by(participant_id=participant.uniqueid, failed=False).all():
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

    participant_id = participant.uniqueid
    key = participant_id[0:5]

    exp.log("{} notification received".format(event_type), key)

    if event_type == 'AssignmentAbandoned':
        if participant.status != 104:
            participant.status = 104
            session_psiturk.commit()
            exp.log("Failing all participant's nodes", key)
            nodes = models.Node\
                .query\
                .filter_by(participant_id=participant_id, failed=False)\
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
                .filter_by(participant_id=participant_id, failed=False)\
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


def error_page(participant=None, error_text=None, compensate=True,
               error_type="default"):
    """Render HTML for error page."""
    if error_text is None:
        if compensate:
            error_text = 'There has been an error and so you are unable to continue, sorry! \
                If possible, please return the assignment so someone else can work on it. \
                Please use the information below to contact us about compensation'
        else:
            error_text = 'There has been an error and so you are unable to continue, sorry! \
                If possible, please return the assignment so someone else can work on it.'

    if participant is not None:
        return render_template(
            'error_wallace.html',
            error_text=error_text,
            compensate=compensate,
            contact_address=config.get('HIT Configuration', 'contact_email_on_error'),
            error_type=error_type,
            hit_id=participant.hitid,
            assignment_id=participant.assignmentid,
            worker_id=participant.workerid
        )
    else:
        return render_template(
            'error_wallace.html',
            error_text=error_text,
            compensate=compensate,
            contact_address=config.get('HIT Configuration', 'contact_email_on_error'),
            error_type=error_type,
            hit_id='unknown',
            assignment_id='unknown',
            worker_id='unknown'
        )
