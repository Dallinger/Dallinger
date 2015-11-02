"""Import custom routes into the experiment server."""

from flask import Blueprint, request, Response, send_from_directory, \
    jsonify, render_template

from psiturk.psiturk_config import PsiturkConfig
from psiturk.user_utils import PsiTurkAuthorization
from psiturk.db import init_db
from psiturk.db import db_session as session_psiturk
from psiturk.models import Participant

from wallace import db, models

import imp
import inspect
from operator import attrgetter
import datetime
from json import dumps

from rq import Queue
from worker import conn

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

    exp.log("Launching experiment...", "-----")
    init_db()
    exp.recruiter().open_recruitment(n=exp.initial_recruitment_size)
    session_psiturk.commit()
    session.commit()

    exp.log("...experiment launched.", "-----")

    data = {
        "status": "success"
    }
    return Response(dumps(data), status=200, mimetype='application/json')


@custom_code.route('/compute_bonus', methods=['GET'])
def compute_bonus():
    """Overide the psiTurk compute_bonus route."""
    data = {
        "bonusComputed": "success"
    }
    return Response(dumps(data), status=200)


@custom_code.route('/summary', methods=['GET'])
def summary():
    """Summarize the participants' status codes."""
    exp = experiment(session)
    data = {
        "status": "success",
        "summary": exp.log_summary()
    }
    return Response(dumps(data), status=200, mimetype='application/json')


@custom_code.route('/worker_complete', methods=['GET'])
def worker_complete():
    """Overide the psiTurk worker_complete route.

    This skirts around an issue where the participant's status reverts to 3
    because of rogue calls to this route. It does this by changing the status
    only if it's not already >= 100.
    """
    exp = experiment(session)

    if 'uniqueId' not in request.args:
        data = {"status": "bad request"}
        return jsonify(**data)

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

        data = {
            "status": status
        }
        return jsonify(**data)


"""
Routes for reading and writing to the database.
"""


@custom_code.route("/node/<participant_id>", methods=["POST", "GET"])
def node(participant_id):
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

    # Get the participant_id.
    key = participant_id[0:5]

    if request.method == "GET":

        # Get the node_id.
        try:
            node_id = request.values["node_id"]
            if not node_id.isdigit():
                msg = "/node GET request, non-numeric node_id"
                exp.log("Error: {}".format(node_id), key)
                data = {
                    "status": "error",
                    "html": error_page(error_type=msg)
                }
                return Response(
                    dumps(data),
                    status=400,
                    mimetype='application/json')
        except KeyError:
            msg = "/node GET request, node_id not specified"
            exp.log("Error: {}".format(msg), key)
            data = {
                "status": "error",
                "html": error_page(error_type=msg)
            }
            return Response(
                dumps(data),
                status=400,
                mimetype='application/json')

        # Get type and ensure that it is of a known class.
        try:
            node_type = request.values["node_type"]
            try:
                node_type = exp.known_classes[node_type]
            except KeyError:
                msg = "/node GET request, unknown node_type"
                exp.log("Error: {} {}".format(msg, node_type), key)
                data = {
                    "status": "error",
                    "html": error_page(error_type=msg)
                }
                return Response(
                    dumps(data),
                    status=400,
                    mimetype='application/json')
        except KeyError:
            node_type = models.Node

        # Get failed parameter.
        try:
            failed = request.values["failed"]
        except KeyError:
            failed = False

        # Get vector_failed parameter.
        try:
            vector_failed = request.values["vector_failed"]
        except KeyError:
            vector_failed = False

        # Get connection parameter.
        try:
            connection = request.values["connection"]
        except KeyError:
            connection = "to"

        # Execute the request.
        exp.log("/node GET request. Params: participant: {}, node: {}, node_type: {}, \
                 failed: {}, vector_failed: {}, connection: {}"
                .format(participant_id, node_id, node_type, failed, vector_failed, connection), key)
        node = models.Node.query.get(node_id)
        nodes = node.neighbours(
            type=node_type,
            failed=failed,
            vector_failed=vector_failed,
            connection=connection)

        exp.node_get_request(
            participant_id=participant_id,
            node=node,
            nodes=nodes)

        session.commit()

        # parse the data to return
        data = []
        for n in nodes:
            data.append(n.__json__())
        data = {"status": "success", "nodes": data}

        exp.log("/node GET request successful.", key)

        return Response(
            dumps(data, default=date_handler),
            status=200,
            mimetype='application/json')

    elif request.method == "POST":

        # Get the participant.
        participant = Participant.query.\
            filter(Participant.uniqueid == participant_id).all()

        if len(participant) == 0:

            exp.log("Error: /node POST request from unrecognized participant_id {}.".format(participant_id), key)
            page = error_page(
                error_text="You cannot continue because your worker id does not match anyone in our records.",
                error_type="/agents no participant found")
            data = {
                "status": "error",
                "html": page
            }
            return Response(dumps(data), status=403, mimetype='application/json')

        participant = participant[0]

        check_for_duplicate_assignments(participant)

        # Make sure their status is 1 or 2. Otherwise, they must have come
        # here by mistake.
        if participant.status not in [1, 2]:

            exp.log("Error: Participant status is {} they should not have been able to contact this route.".format(participant.status), key)
            error_type = "/agents POST, status = {}".format(participant.status)

            if participant.status in [3, 4, 5, 100, 101, 102, 105]:
                page = error_page(
                    participant=participant,
                    error_text="You cannot continue because we have received a notification from AWS that you have already submitted the assignment.'",
                    error_type=error_type)

            elif participant.status == 103:
                page = error_page(
                    participant=participant,
                    error_text="You cannot continue because we have received a notification from AWS that you have returned the assignment.'",
                    error_type=error_type)

            elif participant.status == 104:
                page = error_page(
                    participant=participant,
                    error_text="You cannot continue because we have received a notification from AWS that your assignment has expired.",
                    error_type=error_type)

            elif participant.status == 106:
                page = error_page(
                    participant=participant,
                    error_text="You cannot continue because we have received a notification from AWS that your assignment has been assigned to someone else.",
                    error_type=error_type)

            else:
                page = error_page(
                    participant=participant,
                    error_type=error_type)

            data = {
                "status": "error",
                "html": page
            }
            return Response(
                dumps(data),
                status=400,
                mimetype='application/json')

        # execute the request
        exp.log("/node POST request. Params: participant_id: {}".format(participant_id), key)
        network = exp.get_network_for_participant(participant_id=participant_id)

        if network is None:
            exp.log("No networks available for participant.", key)
            return Response(dumps({"status": "error"}), status=403)

        else:
            node = exp.make_node_for_participant(
                participant_id=participant_id,
                network=network)

            exp.add_node_to_network(
                participant_id=participant_id,
                node=node,
                network=network)

        session.commit()

        exp.node_post_request(participant_id=participant_id, node=node)
        session.commit()

        # parse the data for returning
        data = node.__json__()
        data = {"status": "success", "node": data}

        # return the data
        exp.log("/node POST request successful.", key)
        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')


@custom_code.route("/vector/<participant_id>/<int:node_id>", methods=["GET", "POST"])
def vector(participant_id, node_id):
    """ Send GET or POST requests to the vector table.

    POST requests prompt one node to
    connect to or from another. This request returns a list of
    descriptions of the new vectors created.
    Required arguments: participant_id, node_id, other_node_id
    Optional arguments: direction.

    GET requests return a list of vectors that connect at the
    requesting node. If the other_node_id is specified it returns
    only vectors that join the requesting node to the other node.
    This request returns a list of descriptions of the vectors
    (even if there is only one).
    Required arguments: participant_id, node_id
    Optional arguments: other_node_id, failed, direction
    """
    # load the experiment
    exp = experiment(session)

    # get the key
    key = participant_id[0:5]

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
                return Response(js, status=400, mimetype='application/json')
        except KeyError:
            other_node_id = None

        # get the direction
        try:
            direction = request.values["direction"]
        except KeyError:
            direction = "all"

        # get failed
        try:
            failed = request.values["failed"]
        except KeyError:
            failed = False

        # execute the request
        exp.log("/vector GET request. Params: participant_id: {}, node_id: {}, other_node_id: {}, \
                 direction: {}, failed: {}"
                .format(participant_id, node_id, other_node_id, direction, failed), key)
        node = models.Node.query.get(node_id)
        vectors = node.vectors(direction=direction, failed=failed)
        if other_node_id is not None:
            vectors = [v for v in vectors if v.origin_id == other_node_id or v.destination_id == other_node_id]

        exp.vector_get_request(participant_id=participant_id, node=node, vectors=vectors)
        session.commit()

        # parse the data for returning
        data = []
        for v in vectors:
            data.append(v.__json__())

        data = {
            "status": "success",
            "vectors": data
        }

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
                return Response(js, status=400, mimetype='application/json')
        except KeyError:
            exp.log("Error: /vector POST request, other_node_id not specified", key)
            page = error_page(error_type="/vector, node_id not specified")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=400, mimetype='application/json')

        # get the direction
        try:
            direction = request.values["direction"]
        except KeyError:
            direction = "to"

        # execute the request
        exp.log("/vector POST request. Params: participant_id: {}, node_id: {}, other_node_id: {}, \
                 direction: {}"
                .format(participant_id, node_id, other_node_id, direction), key)
        node = models.Node.query.get(node_id)
        other_node = models.Node.query.get(other_node_id)
        vectors = node.connect(whom=other_node, direction=direction)

        exp.vector_post_request(
            participant_id=participant_id,
            node=node,
            vectors=vectors)

        session.commit()

        # parse the data for returning
        data = []
        for v in vectors:
            data.append(v.__json__())

        # return data
        exp.log("/vector POST request successful", key)
        data = {"status": "success", "vectors": data}
        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')


@custom_code.route("/info/<participant_id>/<int:node_id>", methods=["GET", "POST"])
def info(participant_id, node_id):
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

    # get the key
    key = participant_id[0:5]

    # get info_type
    try:
        info_type = request.values["info_type"]
    except KeyError:
        info_type = None
    if info_type is not None:
        try:
            info_type = exp.known_classes[info_type]
        except KeyError:
            exp.log("Error: /info request, unknown info_type {}".format(info_type), key)
            page = error_page(error_type="/info, unknown type")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=400, mimetype='application/json')

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
                return Response(js, status=400, mimetype='application/json')
        except KeyError:
            info_id = None

        # execute the experiment method:
        exp.log("/info GET request. Params: participant_id: {}, node_id: {}, info_type: {}, \
                 info_id: {}."
                .format(participant_id, node_id, info_type, info_id), key)
        node = models.Node.query.get(node_id)

        if info_id is None:
            infos = node.infos(type=info_type)

            exp.info_get_request(
                participant_id=participant_id,
                node=node,
                infos=infos)

            session.commit()

            # parse the data for returning
            data = []

            for i in infos:
                data.append(i.__json__())
            data = {"status": "success", "infos": data}
        else:
            info = models.Info.query.get(info_id)
            if info.origin_id != node.id and info.id not in [t.info_id for t in node.transmissions(direction="incoming", status="received")]:
                exp.log("Error: /info GET request, info not available to requesting node", key)
                page = error_page(error_type="/info GET, info not available")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=403, mimetype='application/json')

            exp.info_get_request(participant_id=participant_id, node=node, info=info)
            session.commit()

            data = info.__json__()
            data = {"status": "success", "info": data}

        # return the data
        exp.log("/info GET request successful.", key)
        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')

    elif request.method == "POST":

        # get the contents
        try:
            contents = request.values["contents"]
        except KeyError:
            exp.log("Error: /info POST request, contents not specified", key)
            page = error_page(error_type="/info POST, contents not specified")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=400, mimetype='application/json')

        # execute the experiment method:
        exp.log("/info POST request. Params: participant_id: {}, node_id: {}, info_type: {}, \
                 contents: {}"
                .format(participant_id, node_id, info_type, contents), key)
        node = models.Node.query.get(node_id)
        info = info_type(origin=node, contents=contents)
        session.commit()

        exp.info_post_request(
            participant_id=participant_id,
            node=node,
            info=info)

        session.commit()

        # parse the data for returning
        data = info.__json__()
        data = {"status": "success", "info": data}

        # return the data
        exp.log("/info POST request successful.", key)
        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')


@custom_code.route("/transmission/<participant_id>/<int:node_id>", methods=["GET", "POST"])
def transmission(participant_id, node_id):
    """Send GET or POST requests to the transmission table.

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
    exp = experiment(session)

    # get the key
    key = participant_id[0:5]

    if request.method == "GET":

        # get direction
        try:
            direction = request.values["direction"]
        except KeyError:
            direction = "outgoing"

        # get status
        try:
            status = request.values["status"]
        except KeyError:
            status = "all"

        # execute the experiment method
        exp.log("/transmission GET request. Params: participant_id: {}, node_id: {}, direction: {}, \
                 status: {}"
                .format(participant_id, node_id, direction, status), key)
        node = models.Node.query.get(node_id)
        transmissions = node.transmissions(direction=direction, status=status)

        if direction in ["incoming", "all"] and status in ["pending", "all"]:
            node.receive()
            session.commit()

        exp.transmission_get_request(participant_id=participant_id, node=node, transmissions=transmissions)
        session.commit()

        # parse the data to return
        data = []
        for t in transmissions:
            data.append(t.__json__())
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
                return Response(js, status=400, mimetype='application/json')
        except KeyError:
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
                return Response(js, status=400, mimetype='application/json')
        except KeyError:
            destination_id = None

        # execute the experiment method
        exp.log("/transmission POST request. Params: participant_id: {}, node_id: {}, info_id: {}, \
                 destination_id: {}"
                .format(participant_id, node_id, info_id, destination_id), key)

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

        exp.transmission_post_request(
            participant_id=participant_id,
            node=node,
            transmissions=transmissions)

        session.commit()

        # parse the data for returning
        data = []
        for t in transmissions:
            data.append(t.__json__())
        data = {"status": "success", "transmissions": data}

        # return the data
        exp.log("/transmission POST request successful.", key)
        js = dumps(data, default=date_handler)
        return Response(js, status=200, mimetype='application/json')


@custom_code.route("/transformation/<participant_id>/<int:node_id>", methods=["GET", "POST"])
def transformation(participant_id, node_id):
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

    # get the key
    key = participant_id[0:5]

    # get the transformation_type
    try:
        transformation_type = request.values["transformation_type"]
        try:
            transformation_type = exp.known_classes[transformation_type]
        except KeyError:
            exp.log("Error: /transformation request, unknown transformation_type {}".format(transformation_type), key)
            page = error_page(error_type="/transformation, unknown transformation_type")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=400, mimetype='application/json')
    except KeyError:
        transformation_type = models.Transformation

    if request.method == "GET":

        # execute the experiment method
        exp.log("/transformation GET request. Params: participant_id: {}, node_id: {}, transformation_type: {}"
                .format(participant_id, node_id, transformation_type), key)
        node = models.Node.query.get(node_id)
        transformations = node.transformations(transformation_type=transformation_type)

        exp.transformation_get_request(participant_id=participant_id, node=node, transformations=transformations)
        session.commit()

        # parse the data to return
        data = []
        for t in transformations:
            data.append(t.__json__())
        data = {"status": "success", "transformations": data}

        js = dumps(data, default=date_handler)

        exp.log("/transformation GET request successful.", key)
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
                return Response(js, status=400, mimetype='application/json')
        except KeyError:
            exp.log("Error: /transformation POST request, info_in_id not specified", key)
            page = error_page(error_type="/transformation POST, info_in_id not specified")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=400, mimetype='application/json')

        # get the info_out_id
        try:
            info_out_id = request.values["info_out_id"]
            if not info_out_id.isdigit():
                exp.log(
                    "Error: /transformation POST request, non-numeric info_out_id: {}"
                    .format(info_out_id), key)
                page = error_page(error_type="/transformation, non-numeric info_out_id")
                js = dumps({"status": "error", "html": page})
                return Response(js, status=400, mimetype='application/json')
        except KeyError:
            exp.log("Error: /transformation POST request, info_out_id not specified", key)
            page = error_page(error_type="/transformation POST, info_out_id not specified")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=400, mimetype='application/json')

        # execute the experiment method
        exp.log("/transformation POST request. Params: participant_id: {}, node_id: {}, info_in_id: {}, \
                 info_out_id: {}"
                .format(participant_id, node_id, info_in_id, info_out_id), key)
        info_in = models.Info.query.get(info_in_id)
        info_out = models.Info.query.get(info_out_id)

        if node_id != info_out.origin_id:
            exp.log("Error: /transformation POST request, node not origin of info_out", key)
            page = error_page(error_type="/transformation POST, node not origin of info_out")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=403, mimetype='application/json')

        transformation = transformation_type(info_in=info_in, info_out=info_out)
        session.commit()

        exp.transformation_post_request(participant_id=participant_id, node=node, transformation=transformation)
        session.commit()

        # parse the data for returning
        data = transformation.__json__()
        data = {"status": "success", "transformation": data}

        # return success
        exp.log("/transformation POST request successful.", key)
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
        participants = Participant.query\
            .filter_by(assignmentid=assignment_id)\
            .all()

        # if there are multiple participants select the most recent
        if len(participants) > 1:
            if event_type in ['AssignmentAbandoned', 'AssignmentReturned']:
                participants = [p for p in participants if p.status < 100]
                if participants:
                    participant = min(participants, key=attrgetter('beginhit'))
                else:
                    return None
            else:
                participant = max(participants, key=attrgetter('beginhit'))

        # if there are none (this is also bad news) print an error
        elif len(participants) == 0:
            exp.log("Warning: No participants associated with this assignment_id. Notification will not be processed.", key)
            return None

        # if theres only one participant (this is good) select them
        else:
            participant = participants[0]

    elif participant_id is not None:
        participant = Participant.query.filter_by(uniqueid=participant_id).all()[0]
    else:
        raise ValueError("Error: worker_function needs either an assignment_id or a \
                          participant_id, they cannot both be None")

    participant_id = participant.uniqueid
    key = participant_id[0:5]

    if event_type == 'AssignmentAccepted':
        pass

    elif event_type == 'AssignmentAbandoned':
        if participant.status < 100:
            fail_participant(exp, participant, 104, msg="Assignment abandoned.")

    elif event_type == 'AssignmentReturned':
        if participant.status < 100:
            fail_participant(exp, participant, 103, msg="Assignment returned.")

    elif event_type == 'AssignmentSubmitted':
        if participant.status < 100:

            # Approve the assignment.
            exp.recruiter().approve_hit(assignment_id)

            # Check that the participant's data is okay.
            worked = exp.data_check(participant=participant)

            # If it isn't, fail their nodes and recruit a replacement.
            if not worked:
                fail_participant(exp, participant, 105, msg="Participant failed data check.")
                exp.recruiter().recruit_participants(n=1)
            else:
                # If their data is ok, pay them a bonus.
                # Note that the bonus is paid before the attention check.
                bonus = exp.bonus(participant=participant)
                if bonus >= 0.01:
                    exp.log("Bonus = {}: paying bonus".format(bonus), key)
                    exp.recruiter().reward_bonus(
                        assignment_id,
                        bonus,
                        exp.bonus_reason())
                else:
                    exp.log("Bonus = {}: NOT paying bonus".format(bonus), key)

                # Perform an attention check.
                attended = exp.attention_check(participant=participant)

                # If they fail the attention check, fail nodes and replace.
                if not attended:
                    fail_participant(
                        exp,
                        participant,
                        102,
                        msg="Attention check failed")
                    exp.recruiter().recruit_participants(n=1)
                else:
                    # All good. Possibly recruit more participants.
                    exp.log("All checks passed.", key)

                    participant.status = 101
                    session_psiturk.commit()

                    exp.submission_successful(participant=participant)
                    session.commit()

                    exp.recruit()

            exp.log_summary()
    else:
        exp.log("Error: unknown event_type {}".format(event_type), key)


def fail_participant(exp, participant, new_status, msg=""):
    """Fail the participants' nodes and set their status to >101."""
    participant_id = participant.uniqueid
    key = participant_id[0:5]

    participant_nodes = models.Node.query\
        .filter_by(participant_id=participant_id, failed=False)\
        .all()

    exp.log(msg, key)
    participant.status = new_status
    session_psiturk.commit()

    for node in participant_nodes:
        node.fail()

    session.commit()


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

        error_text = """There has been an error and so you are unable to
        continue, sorry! If possible, please return the assignment so someone
        else can work on it."""

        if compensate:
            error_text += """Please use the information below to contact us
            about compensation"""

    if participant is not None:
        hit_id = participant.hitid,
        assignment_id = participant.assignmentid,
        worker_id = participant.workerid
    else:
        hit_id = 'unknown'
        assignment_id = 'unknown'
        worker_id = 'unknown'

    return render_template(
        'error_wallace.html',
        error_text=error_text,
        compensate=compensate,
        contact_address=config.get(
            'HIT Configuration', 'contact_email_on_error'),
        error_type=error_type,
        hit_id=hit_id,
        assignment_id=assignment_id,
        worker_id=worker_id
    )


def date_handler(obj):
    """Serialize dates."""
    return obj.isoformat() if hasattr(obj, 'isoformat') else obj
