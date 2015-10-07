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

from rq import Queue
from worker import conn

from sqlalchemy import and_, exc

import traceback

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

# Connect to the Redis queue for notifications.
q = Queue(connection=conn)

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
    exp.log("Launch route hit, initializing tables and opening recruitment.", "-----")
    init_db()
    exp.recruiter().open_recruitment(n=exp.initial_recruitment_size)

    session_psiturk.commit()
    session.commit()

    exp.log("Experiment successfully launched!", "-----")
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


"""
Database accessing routes
"""


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
    # load the experiment
    exp = experiment(session)

    # get the participant_id
    try:
        participant_id = request.values["participant_id"]
        key = participant_id[0:5]
    except:
        exp.log("Error: /node request, participant_id not specified")
        page = error_page(error_type="/node, participant_id not specified")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=403, mimetype='application/json')

    if request.method == "GET":

        # get the node_id
        try:
            node_id = request.values["node_id"]
            if not node_id.isdigit():
                exp.log("Error: /node GET request, non-numeric node_id: {}".format(node_id), key)
                page = error_page(error_type="/node GET, non-numeric node_id")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=403, mimetype='application/json')
        except:
            exp.log("Error: /node GET request, node_id not specified", key)
            page = error_page(error_type="/node GET, node_id not specified")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')

        # get type and check it is in trusted_strings
        try:
            node_type = request.values["node_type"]
            if node_type in exp.trusted_strings:
                node_type = exp.evaluate(node_type)
            else:
                exp.log("Error: /node GET request, untrusted node_type {}".format(node_type), key)
                page = error_page(error_type="/node GET, unstrusted node_type")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=403, mimetype='application/json')
        except:
            node_type = models.Node

        # get failed
        try:
            failed = request.values["failed"]
        except:
            failed = False

        # get vector_failed
        try:
            vector_failed = request.values["vector_failed"]
        except:
            vector_failed = False

        # get connection
        try:
            connection = request.values["connection"]
        except:
            connection = "to"

        # execute the request
        exp.log("/node GET request. Params: participant: {}, node: {}, node_type: {}, \
                 failed: {}, vector_failed: {}, connection: {}"
                .format(participant_id, node_id, node_type, failed, vector_failed, connection), key)
        node = models.Node.query.get(node_id)
        nodes = node.neighbours(type=node_type, failed=failed, vector_failed=vector_failed, connection=connection)

        # parse the data to return
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

        # return the data
        exp.log("/node GET request successful.", key)
        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')

    elif request.method == "POST":

        # get the participant
        participant = Participant.query.\
            filter(Participant.uniqueid == participant_id).all()
        if len(participant) == 0:
            exp.log("Error: /node POST request from unrecognized participant_id {}.".format(participant_id), key)
            page = error_page(error_text="You cannot continue because your worker id does not match anyone in our records.", error_type="/agents no participant found")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')
        participant = participant[0]

        check_for_duplicate_assignments(participant)

        # make sure their status is 1 or 2, otherwise they must have come here by mistake
        if participant.status not in [1, 2]:
            exp.log("Error: Participant status is {} they should not have been able to contact this route.".format(participant.status), key)
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

        # execute the request
        exp.log("/node POST request. Params: participant_id: {}".format(participant_id), key)
        network = exp.get_network_for_participant(participant_id=participant_id)
        if network is None:
            exp.log("No networks available for participant.", key)
            js = dumps({"status": "error"})
            return Response(js, status=403)
        else:
            node = exp.make_node_for_participant(participant_id=participant_id, network=network)
            exp.add_node_to_network(participant_id=participant_id, node=node, network=network)
        session.commit()

        # parse the data for returning
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

        # return the data
        exp.log("/node POST request successful.", key)
        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')


@custom_code.route("/vector", methods=["GET", "POST"])
def vector():
    """ Send GET or POST requests to the vector table.

    POST requests call the vector_post_request method
    in Experiment, which, by deafult, prompts one node to
    connect to or from another. This request returns a list of
    descriptions of the new vectors created.
    Required arguments: participant_id, node_id, other_node_id
    Optional arguments: direction.

    GET requests call the vector_get_request method
    in Experiment, which, by default, calls the node's
    vectors method if no other_node_id is specified,
    or its is_connected method if the other_node_id is
    specified. This request returns a list of
    descriptions of the vectors (even if there is only one),
    or a boolean, respectively.
    Required arguments: participant_id, node_id
    Optional arguments: other_node_id, failed, direction, vector_failed
    """
    # load the experiment
    exp = experiment(session)

    # get the participant_id
    try:
        participant_id = request.values["participant_id"]
        key = participant_id[0:5]
    except:
        exp.log("Error: /vector request, participant_id not specified")
        page = error_page(error_type="/vector, participant_id not specified")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=403, mimetype='application/json')

    # get the node_id
    try:
        node_id = request.values["node_id"]
        if not node_id.isdigit():
            exp.log(
                "Error: /vector request, non-numeric node_id: {}"
                .format(node_id), key)
            page = error_page(error_type="/vector, non-numeric node_id")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')
    except:
        exp.log("Error: /vector request, node_id not specified", key)
        page = error_page(error_type="/vector, node_id not specified")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=403, mimetype='application/json')

    if request.method == "GET":

        # get the other_node_id
        try:
            other_node_id = request.values["other_node_id"]
            if not other_node_id.isdigit():
                exp.log(
                    "Error: /vector GET request, non-numeric other_node_id: {}"
                    .format(other_node_id), key)
                page = error_page(error_type="/vector GET, non-numeric other_node_id")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=403, mimetype='application/json')
        except:
            other_node_id = None

        # if other_node_id is not None we return if the node
        # is_connected to the other_node
        if other_node_id is not None:

            # get the direction
            try:
                direction = request.values["direction"]
            except:
                direction = "to"

            # get the vector_failed
            try:
                vector_failed = request.values["vector_failed"]
            except:
                vector_failed = False

            # execute the experiment method
            exp.log("/vector GET request. Params: participant_id: {}, node_id: {}, other_node_id: {}, \
                     direction: {}, vector_failed: {}"
                    .format(participant_id, node_id, other_node_id, direction, vector_failed), key)
            node = models.Node.query.get(node_id)
            other_node = models.Node.query.get(other_node_id)
            is_connected = node.is_connected(whom=other_node, direction=direction, vector_failed=vector_failed)

            # return the data
            data = {"status": "success", "is_connected": is_connected}
            exp.log("/vector GET request successful.", key)
            js = dumps(data, default=date_handler)
            return Response(js, status=200, mimetype='application/json')

        # if other_node_id is None, we return a list of vectors
        else:

            # get the direction
            try:
                direction = request.values["direction"]
            except:
                direction = "all"

            # get failed
            try:
                failed = request.values["failed"]
            except:
                failed = False

            # execute the request
            exp.log("/vector GET request. Params: participant_id: {}, node_id: {}, other_node_id: {}, \
                     direction: {}, failed: {}"
                    .format(participant_id, node_id, other_node_id, direction, failed), key)
            node = models.Node.query.get(node_id)
            vectors = node.vectors(direction=direction, failed=failed)

            # parse the data for returning
            data = []
            for v in vectors:
                data.append({
                    "id": v.id,
                    "origin_id": v.origin_id,
                    "destination_id": v.destination_id,
                    "info_id": v.info_id,
                    "network_id": v.network_id,
                    "creation_time": v.creation_time,
                    "failed": v.failed,
                    "time_of_death": v.time_of_death,
                    "property1": v.property1,
                    "property2": v.property2,
                    "property3": v.property3,
                    "property4": v.property4,
                    "property5": v.property5
                })
            data = {"status": "success", "vectors": data}

            # return the data
            exp.log("/vector GET request successful.", key)
            js = dumps(data, default=date_handler)
            return Response(js, status=200, mimetype='application/json')

    elif request.method == "POST":

        # get the other_node_id
        try:
            other_node_id = request.values["other_node_id"]
            if not other_node_id.isdigit():
                exp.log(
                    "Error: /vector POST request, non-numeric other_node_id: {}"
                    .format(node_id), key)
                page = error_page(error_type="/vector POST, non-numeric other_node_id")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=403, mimetype='application/json')
        except:
            exp.log("Error: /vector POST request, other_node_id not specified", key)
            page = error_page(error_type="/vector, node_id not specified")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')

        # get the direction
        try:
            direction = request.values["direction"]
        except:
            direction = "to"

        # execute the request
        exp.log("/vector POST request. Params: participant_id: {}, node_id: {}, other_node_id: {}, \
                 direction: {}"
                .format(participant_id, node_id, other_node_id, direction), key)
        node = models.Node.query.get(node_id)
        other_node = models.Node.query.get(other_node_id)
        vectors = node.connect(whom=other_node, direction=direction)

        # parse the data for returning
        data = []
        for v in vectors:
            data.append({
                "id": v.id,
                "origin_id": v.origin_id,
                "destination_id": v.destination_id,
                "info_id": v.info_id,
                "network_id": v.network_id,
                "creation_time": v.creation_time,
                "failed": v.failed,
                "time_of_death": v.time_of_death,
                "property1": v.property1,
                "property2": v.property2,
                "property3": v.property3,
                "property4": v.property4,
                "property5": v.property5
            })

        # return data
        exp.log("/vector POST request successful", key)
        data = {"status": "success", "vectors": data}
        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')


@custom_code.route("/info", methods=["GET", "POST"])
def info():
    """ Send GET or POST requests to the info table.

    POST requests create a new info and return it to
    the front end.To create infos of custom classes
    you need to add the name of the class to the
    trusted_strings variable in the experiment class.
    Required arguments: participant_id, node_id, contents.
    Optional arguments: type.

    GET requests return a single info if an info_id is
    specified, otherwise they return a list of infos.
    Required arguments: participant_id, node_id
    Optional arguments: info_id, type.
    """
    # load the experiment
    exp = experiment(session)

    # get the participant_id
    try:
        participant_id = request.values["participant_id"]
        key = participant_id[0:5]
    except:
        exp.log("Error: /info request, participant_id not specified")
        page = error_page(error_type="/info, participant_id not specified")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=403, mimetype='application/json')

    # get the node_id
    try:
        node_id = request.values["node_id"]
        if not node_id.isdigit():
            exp.log(
                "Error: /info request, non-numeric node_id: {}".format(node_id),
                key)
            page = error_page(error_type="/info, non-numeric node_id")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')
    except:
        exp.log("Error: /info request, node_id not specified", key)
        page = error_page(error_type="/info, node_id not specified")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=403, mimetype='application/json')

    # get info_type
    try:
        info_type = request.values["info_type"]
    except:
        info_type = None
    if info_type is not None:
        if info_type in exp.trusted_strings:
            info_type = exp.evaluate(info_type)
        else:
            exp.log("Error: /info request, untrusted info_type {}".format(info_type), key)
            page = error_page(error_type="/info, untrusted type")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')

    if request.method == "GET":

        # get the info_id
        try:
            info_id = request.values["info_id"]
            if not info_id.isdigit():
                exp.log(
                    "Error: /info GET request, non-numeric info_id: {}".format(node_id),
                    key)
                page = error_page(error_type="/info GET, non-numeric info_id")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=403, mimetype='application/json')
        except:
            info_id = None

        # execute the experiment method:
        exp.log("/info GET request. Params: participant_id: {}, node_id: {}, info_type: {}, \
                 info_id: {}."
                .format(participant_id, node_id, info_type, info_id))
        node = models.Node.query.get(node_id)
        if info_id is None:
            infos = node.infos(type=info_type)

            # parse the data for returning
            data = []
            for i in infos:
                data.append({
                    "id": i.id,
                    "type": i.type,
                    "origin_id": i.origin_id,
                    "network_id": i.network_id,
                    "creation_time": i.creation_time,
                    "contents": i.contents,
                    "property1": i.property1,
                    "property2": i.property2,
                    "property3": i.property3,
                    "property4": i.property4,
                    "property5": i.property5
                })
            data = {"status": "success", "infos": data}
        else:
            info = models.Info.query.get(info_id)
            if info.origin_id != node_id:
                exp.log("Error: /info GET request, node not origin of requested info")
                page = error_page(error_type="/info GET, node not origin of requested info")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=403, mimetype='application/json')
            data = {
                "id": info.id,
                "type": info.type,
                "origin_id": info.origin_id,
                "network_id": info.network_id,
                "creation_time": info.creation_time,
                "contents": info.contents,
                "property1": info.property1,
                "property2": info.property2,
                "property3": info.property3,
                "property4": info.property4,
                "property5": info.property5
            }
            data = {"status": "success", "info": data}

        # return the data
        exp.log("/info GET request successful.", key)
        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')

    elif request.method == "POST":

        # get the contents
        try:
            contents = request.values["contents"]
        except:
            exp.log("Error: /info POST request, contents not specified", key)
            page = error_page(error_type="/info POST, contents not specified")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')

        # execute the experiment method:
        exp.log("/info POST request. Params: participant_id: {}, node_id: {}, info_type: {}, \
                 contents: {}"
                .format(participant_id, node_id, info_type, contents))
        node = models.Node.query.get(node_id)
        info = info_type(origin=node, contents=contents)
        session.commit()

        # parse the data for returning
        data = {
            "id": info.id,
            "type": info.type,
            "origin_id": info.origin_id,
            "network_id": info.network_id,
            "creation_time": info.creation_time,
            "contents": info.contents,
            "property1": info.property1,
            "property2": info.property2,
            "property3": info.property3,
            "property4": info.property4,
            "property5": info.property5
        }
        data = {"status": "success", "info": data}

        # return the data
        exp.log("/info POST request successful.", key)
        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')


@custom_code.route("/transmission", methods=["GET", "POST"])
def transmission():
    """ Send GET or POST requests to the transmission table.

    POST requests call the transmission_post_request method
    in Experiment, which, by deafult, prompts one node to
    transmit to another. This request returns a description
    of the new transmission.
    Required arguments: participant_id, node_id
    Optional arguments: destination_id, info_id.

    GET requests call the transmission_get_request method
    in Experiment, which, by default, calls the node's
    transmissions method. This request returns a list of
    descriptions of the transmissions (even if there is only one).
    Required arguments: participant_id, node_id
    Optional arguments: direction, status
    """

    # get the experiment
    exp = experiment(session)

    # get the participant_id
    try:
        participant_id = request.values["participant_id"]
        key = participant_id[0:5]
    except:
        exp.log("Error: /transmission request, participant_id not specified")
        page = error_page(error_type="/transmission, participant_id not specified")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=403, mimetype='application/json')

    # get the node_id
    try:
        node_id = request.values["node_id"]
        if not node_id.isdigit():
            exp.log(
                "Error: /transmission request, non-numeric node_id: {}"
                .format(node_id), key)
            page = error_page(error_type="/transmission, malformed node_id")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')
    except:
        exp.log("Error: /transmission request, node_id not specified", key)
        page = error_page(error_type="/transmission, node_id not specified")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=403, mimetype='application/json')

    if request.method == "GET":

        # get direction
        try:
            direction = request.values["direction"]
        except:
            direction = "outgoing"

        # get status
        try:
            status = request.values["status"]
        except:
            status = "all"

        # execute the experiment method
        exp.log("/transmission GET request. Params: participant_id: {}, node_id: {}, direction: {}, \
                 status: {}"
                .format(participant_id, node_id, direction, status))
        node = models.Node.query.get(node_id)
        transmissions = node.transmissions(direction=direction, status=status)

        if direction in ["incoming", "all"] and status in ["pending", "all"]:
            node.receive()

        # parse the data to return
        data = []
        for t in transmissions:
            data.append({
                "id": t.id,
                "vector_id": t.vector_id,
                "origin_id": t.origin_id,
                "destination_id": t.destination_id,
                "info_id": t.info_id,
                "network_id": t.network_id,
                "creation_time": t.creation_time,
                "receive_time": t.receive_time,
                "status": t.status,
                "property1": t.property1,
                "property2": t.property2,
                "property3": t.property3,
                "property4": t.property4,
                "property5": t.property5
            })
        data = {"status": "success", "transmissions": data}

        # return the data
        exp.log("/transmission GET request successful.", key)
        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')

    elif request.method == "POST":

        # get the info_id
        try:
            info_id = request.values["info_id"]
            if not info_id.isdigit():
                exp.log(
                    "Error: /transmission POST request, non-numeric info_id: {}"
                    .format(node_id), key)
                page = error_page(error_type="/transmission POST, non-numeric info_id")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=403, mimetype='application/json')
        except:
            info_id = None

        # get the destination_id
        try:
            destination_id = request.values["destination_id"]
            if not destination_id.isdigit():
                exp.log(
                    "Error: /transmission POST request, non-numeric destination_id: {}"
                    .format(node_id), key)
                page = error_page(error_type="/transmission POST, malformed destination_id")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=403, mimetype='application/json')
        except:
            destination_id = None

        # execute the experiment method
        exp.log("/transmission POST request. Params: participant_id: {}, node_id: {}, info_id: {}, \
                 destination_id: {}"
                .format(participant_id, node_id, info_id, destination_id))
        origin = models.Node.query.get(node_id)

        if info_id is None and destination_id is None:
            transmissions = origin.transmit()
        elif info_id is None and destination_id is not None:
            destination = models.Node.query.get(node_id)
            transmissions = origin.transmit(to_whom=destination)
        elif info_id is not None and destination_id is None:
            info = models.Info.query.get(info_id)
            transmissions = origin.transmit(what=info)
        else:
            destination = models.Node.query.get(node_id)
            info = models.Info.query.get(info_id)
            transmissions = origin.transmit(what=info, to_whom=destination)
        session.commit()

        # parse the data for returning
        data = []
        for t in transmissions:
            data.append({
                "id": transmission.id,
                "vector_id": transmission.vector_id,
                "origin_id": transmission.origin_id,
                "destination_id": transmission.destination_id,
                "info_id": transmission.info_id,
                "network_id": transmission.network_id,
                "creation_time": transmission.creation_time,
                "receive_time": transmission.receive_time,
                "status": transmission.status,
                "property1": transmission.property1,
                "property2": transmission.property2,
                "property3": transmission.property3,
                "property4": transmission.property4,
                "property5": transmission.property5
            })
        data = {"status": "success", "transmissions": data}

        # return the data
        exp.log("/transmission POST request successful.", key)
        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')


@custom_code.route("/transformation", methods=["GET", "POST"])
def transformation():
    """ Send GET or POST requests to the transmission table.

    POST requests call the transformation_post_request method
    in Experiment, which, by deafult, creates a new transformation.
    This request returns a description of the new transformation.
    Required arguments: participant_id, node_id, info_in_id, info_out_id
    Optional arguments: type

    GET requests call the transformation_get_request method
    in Experiment, which, by default, calls the node's
    transformations method. This request returns a list of
    descriptions of the transformations (even if there is only one).
    Required arguments: participant_id, node_id
    Optional arguments: transformation_type
    """

    # load the experiment
    exp = experiment(session)

    # get the participant_id
    try:
        participant_id = request.values["participant_id"]
        key = participant_id[0:5]
    except:
        exp.log("Error: /transformation request, participant_id not specified")
        page = error_page(error_type="/transformation, participant_id not specified")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=403, mimetype='application/json')

    # get the node_id
    try:
        node_id = request.values["node_id"]
        if not node_id.isdigit():
            exp.log(
                "Error: /transformation request, non-numeric node_id: {}"
                .format(node_id), key)
            page = error_page(error_type="/transformation, non-numeric node_id")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')
    except:
        exp.log("Error: /transformation request, node_id not specified", key)
        page = error_page(error_type="/transformation, node_id not specified")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=403, mimetype='application/json')

    # get the transformation_type
    try:
        transformation_type = request.values["transformation_type"]
        if transformation_type in exp.trusted_strings:
            transformation_type = exp.evaluate(transformation_type)
        else:
            exp.log("Error: /transformation request, untrusted transformation_type {}".format(transformation_type), key)
            page = error_page(error_type="/transformation, unstrusted transformation_type")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')
    except:
        transformation_type = models.Transformation

    if request.method == "GET":

        # execute the experiment method
        exp.log("/transformation GET request. Params: participant_id: {}, node_id: {}, transformation_type: {}"
                .format(participant_id, node_id, transformation_type))
        node = models.Node.query.get(node_id)
        transformations = node.transformations(transformation_type=transformation_type)

        # parse the data to return
        data = []
        for t in transformations:
            data.append({
                "id": t.id,
                "info_in_id": t.info_in_id,
                "info_out_id": t.info_out_id,
                "node_id": t.node_id,
                "network_id": t.network_id,
                "creation_time": t.creation_time,
                "property1": t.property1,
                "property2": t.property2,
                "property3": t.property3,
                "property4": t.property4,
                "property5": t.property5
            })
        data = {"status": "success", "transformations": data}

        # return the data
        exp.log("/transformation GET request successful.", key)
        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')

    if request.method == "POST":

        # get the info_in_id
        try:
            info_in_id = request.values["info_in_id"]
            if not info_in_id.isdigit():
                exp.log(
                    "Error: /transformation POST request, non-numeric info_in_id: {}"
                    .format(info_in_id), key)
                page = error_page(error_type="/transformation, non-numeric info_in_id")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=403, mimetype='application/json')
        except:
            exp.log("Error: /transformation POST request, info_in_id not specified", key)
            page = error_page(error_type="/transformation POST, info_in_id not specified")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')

        # get the info_out_id
        try:
            info_out_id = request.values["info_out_id"]
            if not info_out_id.isdigit():
                exp.log(
                    "Error: /transformation POST request, non-numeric info_out_id: {}"
                    .format(info_out_id), key)
                page = error_page(error_type="/transformation, non-numeric info_out_id")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=403, mimetype='application/json')
        except:
            exp.log("Error: /transformation POST request, info_out_id not specified", key)
            page = error_page(error_type="/transformation POST, info_out_id not specified")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')

        # execute the experiment method
        exp.log("/transformation POST request. Params: participant_id: {}, node_id: {}, info_in_id: {}, \
                 info_out_id: {}"
                .format(participant_id, node_id, info_in_id, info_out_id))
        info_in = models.Info.query.get(info_in_id)
        info_out = models.Info.query.get(info_out_id)

        if node_id != info_out.origin_id:
            exp.log("Error: /transformation POST request, node not origin of info_out", key)
            page = error_page(error_type="/transformation POST, node not origin of info_out")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')

        transformation = transformation_type(info_in=info_in, info_out=info_out)
        session.commit()

        # parse the data for returning
        data = {
            "id": transformation.id,
            "type": transformation.type,
            "info_in_id": transformation.info_in_id,
            "info_out_id": transformation.info_out_id,
            "network_id": transformation.network_id,
            "creation_time": transformation.creation_time,
            "property1": transformation.property1,
            "property2": transformation.property2,
            "property3": transformation.property3,
            "property4": transformation.property4,
            "property5": transformation.property5
        }
        data = {"status": "success", "transformation": data}

        # return success
        exp.log("/transformation POST request successful.")
        js = dumps(data, default=date_handler)
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
    event_type = request.values['Event.1.EventType']
    assignment_id = request.values['Event.1.AssignmentId']

    # Add the notification to the queue.
    q.enqueue(worker_function, event_type, assignment_id, None)

    return Response(
        dumps({"status": "success"}),
        status=200,
        mimetype='application/json')


def check_for_duplicate_assignments(participant):
    participants = Participant.query.filter_by(assignmentid=participant.assignmentid).all()
    duplicates = [p for p in participants if p.uniqueid != participant.uniqueid and p.status < 100]
    for d in duplicates:
        q.enqueue(worker_function, "AssignmentAbandoned", None, d.uniqueid)


def worker_function(event_type, assignment_id, participant_id):
    """Process the notification."""
    exp = experiment(session)
    key = "-----"

    exp.log("Received an {} notification for assignment {}, participant {}".format(event_type, assignment_id, participant_id), key)

    if assignment_id is not None:
        # save the notification to the notification table
        notif = models.Notification(
            assignment_id=assignment_id,
            event_type=event_type)
        session.add(notif)
        session.commit()

        # try to identify the participant
        participants = Participant.query.\
            filter(Participant.assignmentid == assignment_id).\
            all()

        # if there are multiple participants (this is bad news) select the most recent
        if len(participants) > 1:
            participant = max(participants, key=attrgetter('beginhit'))
            exp.log("Warning: Multiple participants associated with this assignment_id. Assuming it concerns the most recent.", key)

        # if there are none (this is also bad news) print an error
        elif len(participants) == 0:
            exp.log("Warning: No participants associated with this assignment_id. Notification will not be processed.", key)
            participant = None

        # if theres only one participant (this is good) select them
        else:
            participant = participants[0]
    elif participant_id is not None:
        participant = Participant.query.filter_by(uniqueid=participant_id).all()[0]
    else:
        participant = None

    if participant is not None:
        participant_id = participant.uniqueid
        key = participant_id[0:5]
        exp.log("Participant identified as {}.".format(participant_id), key)

        if event_type == 'AssignmentAccepted':
            exp.accepted_notification(participant)

        if event_type == 'AssignmentAbandoned':
            if participant.status < 100:
                exp.log("Running abandoned_notification in experiment", key)
                exp.abandoned_notification(participant)
            else:
                exp.log("Participant status > 100 ({}), doing nothing.".format(participant.status), key)

        elif event_type == 'AssignmentReturned':
            if participant.status < 100:
                exp.log("Running returned_notification in experiment", key)
                exp.returned_notification(participant)
            else:
                exp.log("Participant status > 100 ({}), doing nothing.".format(participant.status), key)

        elif event_type == 'AssignmentSubmitted':
            if participant.status < 100:
                exp.log("Running submitted_notification in experiment", key)
                exp.submitted_notification(participant)
            else:
                exp.log("Participant status > 100 ({}), doing nothing.".format(participant.status), key)
        else:
            exp.log("Warning: unknown event_type {}".format(event_type), key)


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


def date_handler(obj):
    return obj.isoformat() if hasattr(obj, 'isoformat') else obj
