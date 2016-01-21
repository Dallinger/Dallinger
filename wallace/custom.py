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
import logging
from operator import attrgetter
import datetime
from json import dumps

from rq import Queue, get_current_job
from worker import conn

from sqlalchemy import and_, exc
from sqlalchemy.orm.exc import NoResultFound

# Load the configuration options.
config = PsiturkConfig()
config.load_config()
myauth = PsiTurkAuthorization(config)

LOG_LEVELS = [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR,
              logging.CRITICAL]
LOG_LEVEL = LOG_LEVELS[config.getint('Server Parameters', 'loglevel')]
db.logger.setLevel(LOG_LEVEL)
if len(db.logger.handlers) == 0:
    ch = logging.StreamHandler()
    ch.setLevel(LOG_LEVEL)
    ch.setFormatter(
        logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    )
    db.logger.addHandler(ch)

# Explore the Blueprint.
custom_code = Blueprint(
    'custom_code', __name__,
    template_folder='templates',
    static_folder='static')

# Initialize the Wallace database.
session = db.session

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


@custom_code.teardown_request
def shutdown_session(_=None):
    ''' Rollback and close session at request end '''
    session.remove()
    db.logger.debug('Closing Wallace DB session at flask request end')


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


def request_parameter(request, parameter, parameter_type=None, default=None):
    """ Get a parameter from a request

    The request object itself must be passed.
    parameter is the name of the parameter you are looking for
    parameter_type is the type the parameter should have
    default is the value the parameter takes if it has not been passed

    If the parameter is not found and no default is specified,
    or if the parameter is found but is of the wrong type
    then a Response object is returned"""

    exp = experiment(session)

    # get the parameter
    try:
        value = request.values[parameter]
    except KeyError:
        # if it isnt found use the default, or return an error Response
        if default is not None:
            return default
        else:
            msg = "{} {} request, {} not specified".format(request.url, request.method, parameter)
            exp.log("Error: {}".format(msg))
            data = {
                "status": "error",
                "html": error_page(error_type=msg)
            }
            return Response(
                dumps(data),
                status=400,
                mimetype='application/json')

    # check the parameter type
    if parameter_type is None:
        # if no parameter_type is required, return the parameter as is
        return value
    elif parameter_type == int:
        # if int is required, convert to an int
        try:
            value = int(value)
            return value
        except ValueError:
            msg = "{} {} request, non-numeric {}: {}".format(request.url, request.method, parameter, value)
            exp.log("Error: {}".format(msg))
            data = {
                "status": "error",
                "html": error_page(error_type=msg)
            }
            return Response(
                dumps(data),
                status=400,
                mimetype='application/json')
    elif parameter_type == "known_class":
        # if its a known class check against the known classes
        try:
            value = exp.known_classes[value]
            return value
        except KeyError:
            msg = "{} {} request, unknown_class: {} for parameter {}".format(request.url, request.method, value, parameter)
            exp.log("Error: {}".format(msg))
            data = {
                "status": "error",
                "html": error_page(error_type=msg)
            }
            return Response(
                dumps(data),
                status=400,
                mimetype='application/json')
    elif parameter_type == bool:
        # if its a boolean, convert to a boolean
        if value in ["True", "False"]:
            return value == "True"
        else:
            msg = "{} {} request, non-boolean {}: {}".format(request.url, request.method, parameter, value)
            exp.log("Error: {}".format(msg))
            data = {
                "status": "error",
                "html": error_page(error_type=msg)
            }
            return Response(
                dumps(data),
                status=400,
                mimetype='application/json')
    else:
        msg = "/{} {} request, unknown parameter type: {} for parameter {}".format(request.url, request.method, parameter_type, parameter)
        exp.log("Error: {}".format(msg))
        data = {
            "status": "error",
            "html": error_page(error_type=msg)
        }
        return Response(
            dumps(data),
            status=400,
            mimetype='application/json')


@custom_code.route("/node/<int:node_id>/neighbors", methods=["GET"])
def node_neighbors(node_id):
    """ Send a GET request to the node table.

    This calls the neighbours method of the node
    making the request and returns a list of descriptions of
    the nodes (even if there is only one).
    Required arguments: participant_id, node_id
    Optional arguments: type, failed, connection

    After getting the neighbours it also calls
    exp.node_get_request()
    """
    exp = experiment(session)

    # get the parameters
    node_type = request_parameter(request=request, parameter="node_type", parameter_type="known_class", default=models.Node)
    failed = request_parameter(request=request, parameter="failed", parameter_type=bool, default=False)
    vector_failed = request_parameter(request=request, parameter="vector_failed", parameter_type=bool, default=False)
    connection = request_parameter(request=request, parameter="connection", default="to")

    for x in [node_type, failed, vector_failed, connection]:
        if type(x) == Response:
            return x

    exp.log("/node GET request. Params: node: {}, node_type: {}, \
             failed: {}, vector_failed: {}, connection: {}"
            .format(node_id, node_type, failed, vector_failed, connection))

    # make sure the node exists
    node = models.Node.query.get(node_id)
    if node is None:
        exp.log("Error: /node/{}/neighbors, node {} does not exist".format(node_id))
        page = error_page(error_type="/node/neighbors, node does not exist")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=400, mimetype='application/json')

    # get its neighbors
    nodes = node.neighbours(
        type=node_type,
        failed=failed,
        vector_failed=vector_failed,
        connection=connection)

    # ping the experiment
    exp.node_get_request(
        node=node,
        nodes=nodes)
    session.commit()

    # return the data
    data = []
    for n in nodes:
        data.append(n.__json__())
    data = {"status": "success", "nodes": data}
    exp.log("/node/neighbors request successful.")
    return Response(
        dumps(data, default=date_handler),
        status=200,
        mimetype='application/json')


@custom_code.route("/node/<participant_id>", methods=["POST"])
def create_node(participant_id):
    """ Send a POST request to the node table.

    This makes a new node for the participant, it calls:
        1. exp.get_network_for_participant
        2. exp.make_node_for_participant
        3. exp.add_node_to_network
        4. exp.node_post_request
    """
    exp = experiment(session)

    # Get the participant.
    try:
        participant = Participant.query.filter_by(uniqueid=participant_id).one()
    except NoResultFound:
        exp.log("Error: /node POST request from unrecognized participant_id {}.".format(participant_id))
        page = error_page(
            error_text="You cannot continue because your worker id does not match anyone in our records.",
            error_type="/node POST no participant found")
        data = {
            "status": "error",
            "html": page
        }
        return Response(dumps(data), status=403, mimetype='application/json')

    # replace any duplicate assignments
    check_for_duplicate_assignments(participant)

    # Make sure the participant status is 1 or 2.
    if participant.status not in [1, 2]:

        exp.log("Error: Participant status is {} they should not have been able to contact this route.".format(participant.status))
        error_type = "/node POST, status = {}".format(participant.status)

        if participant.status in [3, 4, 5, 100, 101, 102, 105]:
            error_text = "You cannot continue because we have received a notification from AWS that you have already submitted the assignment.'"

        elif participant.status == 103:
            error_text = "You cannot continue because we have received a notification from AWS that you have returned the assignment.'"

        elif participant.status == 104:
            error_text = "You cannot continue because we have received a notification from AWS that your assignment has expired."

        elif participant.status == 106:
            error_text = "You cannot continue because we have received a notification from AWS that your assignment has been assigned to someone else."

        else:
            error_text = None

        page = error_page(
            participant=participant,
            error_text=error_text,
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
    exp.log("/node POST request. Params: participant_id: {}".format(participant_id))
    network = exp.get_network_for_participant(participant_id=participant_id)

    if network is None:
        exp.log("No networks available for participant.")
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

    # ping the experument
    exp.node_post_request(participant_id=participant_id, node=node)
    session.commit()

    # return the data
    data = node.__json__()
    data = {"status": "success", "node": data}
    exp.log("/node POST request successful.")
    js = dumps(data, default=date_handler)
    return Response(js, status=200, mimetype='application/json')


@custom_code.route("/node/<int:node_id>/vectors", methods=["GET"])
def node_vectors(node_id):
    exp = experiment(session)

    # get the parameters
    direction = request_parameter(request=request, parameter="direction", default="all")
    if type(direction) == Response:
        return direction

    failed = request_parameter(request=request, parameter="failed", parameter_type=bool, default=False)
    if type(failed) == Response:
        return failed

    # execute the request
    exp.log("/vector GET request. Params: node_id: {}, other_node_id: {}, \
             direction: {}, failed: {}"
            .format(node_id, direction, failed))
    node = models.Node.query.get(node_id)
    if node is None:
        exp.log("Error: /node/{}/vectors, node {} does not exist".format(node_id))
        page = error_page(error_type="/node/vectors, node does not exist")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=400, mimetype='application/json')

    vectors = node.vectors(direction=direction, failed=failed)

    # ping the experument
    exp.vector_get_request(node=node, vectors=vectors)
    session.commit()

    # return the data
    data = []
    for v in vectors:
        data.append(v.__json__())
    data = {
        "status": "success",
        "vectors": data
    }
    exp.log("/vector GET request successful.")
    js = dumps(data, default=date_handler)
    return Response(js, status=200, mimetype='application/json')


@custom_code.route("/node/<int:node_id>/connect/<int:other_node_id>", methods=["POST"])
def connect(node_id, other_node_id):
    exp = experiment(session)

    # get the parameters
    direction = request_parameter(request=request, parameter="direction", default="to")
    if type(direction == Response):
        return direction

    exp.log("/vector POST request. Params: node_id: {}, other_node_id: {}, \
             direction: {}"
            .format(node_id, other_node_id, direction))

    # check the nodes exist
    node = models.Node.query.get(node_id)
    if node is None:
        exp.log("Error: /node/{}/connect, node {} does not exist".format(node_id, node_id))
        page = error_page(error_type="/node/connect, node does not exist")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=400, mimetype='application/json')

    other_node = models.Node.query.get(other_node_id)
    if other_node is None:
        exp.log("Error: /node/{}/connect, other_node {} does not exist".format(node_id, other_node_id))
        page = error_page(error_type="/node/connect, other node does not exist")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=400, mimetype='application/json')

    # execute the request
    vectors = node.connect(whom=other_node, direction=direction)

    # ping the experiment
    exp.vector_post_request(
        node=node,
        vectors=vectors)

    session.commit()

    # return the data
    data = []
    for v in vectors:
        data.append(v.__json__())
    exp.log("/vector POST request successful")
    data = {"status": "success", "vectors": data}
    js = dumps(data, default=date_handler)
    return Response(js, status=200, mimetype='application/json')


@custom_code.route("/info/<int:node_id>/<int:info_id>", methods=["GET"])
def get_info(node_id, info_id):
    exp = experiment(session)

    exp.log("/info GET request. Params: node_id: {}, info_id: {}."
            .format(node_id, info_id))

    # check the node exists
    node = models.Node.query.get(node_id)
    if node is None:
        exp.log("Error: /info/{}, node {} does not exist".format(node_id, node_id))
        page = error_page(error_type="/info, node does not exist")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=400, mimetype='application/json')

    # execute the experiment method:
    info = models.Info.query.get(info_id)
    if info is None:
        exp.log("Error: /info GET request, info {} does not exist".format(info_id))
        page = error_page(error_type="/info GET, info does not exist")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=400, mimetype='application/json')
    elif info.origin_id != node.id and info.id not in [t.info_id for t in node.transmissions(direction="incoming", status="received")]:
        exp.log("Error: /info GET request, info not available to requesting node")
        page = error_page(error_type="/info GET, forbidden info")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=403, mimetype='application/json')

    # ping the experiment
    exp.info_get_request(node=node, info=info)
    session.commit()

    # return the data
    data = info.__json__()
    data = {"status": "success", "info": data}
    exp.log("/info GET request successful.")
    js = dumps(data, default=date_handler)
    return Response(js, status=200, mimetype='application/json')


@custom_code.route("/node/<int:node_id>/infos", methods=["GET"])
def node_infos(node_id):
    exp = experiment(session)

    # get the parameters
    info_type = request_parameter(request=request, parameter="info_type", parameter_type="known_class", default=models.Info)
    if type(info_type) == Response:
        return info_type

    exp.log("/node/infos request. Params: node_id: {}, info_type: {}"
            .format(node_id, info_type))

    # check the node exists
    node = models.Node.query.get(node_id)
    if node is None:
        exp.log("Error: /node/{}/infos, node does not exist".format(node_id))
        page = error_page(error_type="/node/infos, node does not exist")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=400, mimetype='application/json')

    # execute the request:
    infos = node.infos(type=info_type)

    # ping the experiment
    exp.info_get_request(
        node=node,
        infos=infos)

    session.commit()

    # parse the data for returning
    data = []
    for i in infos:
        data.append(i.__json__())
    data = {"status": "success", "infos": data}

    # return the data
    exp.log("/node/infos request successful.")
    js = dumps(data, default=date_handler)
    return Response(js, status=200, mimetype='application/json')


@custom_code.route("/node/<int:node_id>/received_infos", methods=["GET"])
def node_received_infos(node_id):
    exp = experiment(session)

    # get the parameters
    info_type = request_parameter(request=request, parameter="info_type", parameter_type="known_class", default=models.Info)
    if type(info_type) == Response:
        return info_type

    exp.log("/node/received_infos request. Params: node_id: {}, info_type: {}"
            .format(node_id, info_type))

    # check the node exists
    node = models.Node.query.get(node_id)
    if node is None:
        exp.log("Error: /node/{}/infos, node does not exist".format(node_id))
        page = error_page(error_type="/node/infos, node does not exist")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=400, mimetype='application/json')

    # execute the request:
    infos = node.received_infos(type=info_type)

    # ping the experiment
    exp.info_get_request(
        node=node,
        infos=infos)

    session.commit()

    # parse the data for returning
    data = []
    for i in infos:
        data.append(i.__json__())
    data = {"status": "success", "infos": data}

    # return the data
    exp.log("/node/received_infos GET request successful.")
    js = dumps(data, default=date_handler)
    return Response(js, status=200, mimetype='application/json')


@custom_code.route("/info/<int:node_id>", methods=["POST"])
def info_post(node_id):
    exp = experiment(session)

    # get the parameters
    info_type = request_parameter(request=request, parameter="info_type", parameter_type="known_class", default="Info")
    if type(info_type) == Response:
        return info_type

    contents = request_parameter(request=request, parameter="contents")
    if type(contents) == Response:
        return contents

    exp.log("/info POST request. Params: node_id: {}, info_type: {}, \
             contents: {}"
            .format(node_id, info_type, contents))

    # check the node exists
    node = models.Node.query.get(node_id)
    if node is None:
        exp.log("Error: /info/{} POST, node does not exist".format(node_id))
        page = error_page(error_type="/info POST, node does not exist")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=400, mimetype='application/json')

    # execute the request
    info = info_type(origin=node, contents=contents)
    session.commit()

    # ping the experiment
    exp.info_post_request(
        node=node,
        info=info)

    session.commit()

    # return the data
    data = info.__json__()
    data = {"status": "success", "info": data}
    exp.log("/info POST request successful.")
    js = dumps(data, default=date_handler)
    return Response(js, status=200, mimetype='application/json')


@custom_code.route("/node/<int:node_id>/transmissions", methods=["GET"])
def node_transmissions(node_id):
    exp = experiment(session)

    # get the parameters
    direction = request_parameter(request=request, parameter="direction", default="to")
    if type(direction) == Response:
        return direction

    status = request_parameter(request=request, parameter="status", default="all")
    if type(status) == Response:
        return status

    exp.log("/transmission GET request. Params: node_id: {}, direction: {}, \
             status: {}"
            .format(node_id, direction, status))

    # check the node exists
    node = models.Node.query.get(node_id)
    if node is None:
        exp.log("Error: /node/{}/transmissions, node does not exist".format(node_id))
        page = error_page(error_type="/node/transmissions, node does not exist")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=400, mimetype='application/json')

    # execute the request
    transmissions = node.transmissions(direction=direction, status=status)

    if direction in ["incoming", "all"] and status in ["pending", "all"]:
        node.receive()
        session.commit()

    # ping the experiment
    exp.transmission_get_request(node=node, transmissions=transmissions)
    session.commit()

    # return the data
    data = []
    for t in transmissions:
        data.append(t.__json__())
    data = {"status": "success", "transmissions": data}
    exp.log("/transmission GET request successful.")
    js = dumps(data, default=date_handler)
    return Response(js, status=200, mimetype='application/json')


@custom_code.route("/node/<int:node_id>/transmit", methods=["POST"])
def node_transmit(node_id):
    exp = experiment(session)

    # get the parameters
    info_id = request_parameter(request=request, parameter="info_id", parameter_type=int, default=None)
    if type(info_id) == Response:
        return info_id

    if info_id is None:
        what = request_parameter(request=request, parameter="what", default=None)
        if type(what) == Response:
            return what
    else:
        what = models.Info.get(info_id)
        if what is None:
            exp.log("Error: /node/transmit POST request, info {} does not exist".format(info_id))
            page = error_page(error_type="/node/transmit POST, info does not exist")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=400, mimetype='application/json')

    destination_id = request_parameter(request=request, parameter="destination_id", parameter_type=int, default=None)
    if type(destination_id) == Response:
        return destination_id

    if destination_id is None:
        to_whom = request_parameter(request=request, parameter="to_whom", default=None)
        if type(to_whom) == Response:
            return to_whom
    else:
        to_whom = models.Node.get(destination_id)
        if to_whom is None:
            exp.log("Error: /node/transmit POST request, destination node {} does not exist".format(info_id))
            page = error_page(error_type="/node/transmit POST, destination does not exist")
            js = dumps({"status": "error", "html": page})
            return Response(js, status=400, mimetype='application/json')

    exp.log("/node/transmit request. Params: node_id: {}, what: {}, \
             to_whom: {}"
            .format(node_id, what, to_whom))

    # check the node exists
    node = models.Node.query.get(node_id)
    if node is None:
        exp.log("Error: /node/{}/transmit, node does not exist".format(node_id))
        page = error_page(error_type="/node/transmit, node does not exist")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=400, mimetype='application/json')

    # execute the request
    transmissions = node.transmit(what=what, to_whom=to_whom)
    session.commit()

    # ping the experiment
    exp.transmission_post_request(
        node=node,
        transmissions=transmissions)
    session.commit()

    # return the data
    data = []
    for t in transmissions:
        data.append(t.__json__())
    data = {"status": "success", "transmissions": data}
    exp.log("/node/transmit request successful.")
    js = dumps(data, default=date_handler)
    return Response(js, status=200, mimetype='application/json')


@custom_code.route("/node/<int:node_id>/transformations", methods=["GET"])
def transformation_get(node_id):
    exp = experiment(session)

    # get the parameters
    transformation_type = request_parameter(request=request, parameter="transformation_type", parameter_type="known_class", default=models.Transformation)
    if type(transformation_type) == Response:
        return transformation_type

    exp.log("/transformation GET request. Params: node_id: {}, transformation_type: {}"
            .format(node_id, transformation_type))

    # check the node exists
    node = models.Node.query.get(node_id)
    if node is None:
        exp.log("Error: /node/{}/transformations node does not exist".format(node_id))
        page = error_page(error_type="/node/transformations, node does not exist")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=400, mimetype='application/json')

    # execute the request
    transformations = node.transformations(transformation_type=transformation_type)

    # ping the experiment
    exp.transformation_get_request(node=node, transformations=transformations)
    session.commit()

    # return the data
    data = []
    for t in transformations:
        data.append(t.__json__())
    data = {"status": "success", "transformations": data}
    js = dumps(data, default=date_handler)
    exp.log("/transformation GET request successful.")
    return Response(js, status=200, mimetype='application/json')


@custom_code.route("/transformation/<int:node_id>/<int:info_in_id>/<int:info_out_id>", methods=["POST"])
def transformation_post(node_id, info_in_id, info_out_id):
    exp = experiment(session)

    #get the parameters
    transformation_type = request_parameter(request=request, parameter="transformation_type", parameter_type="known_class", default="Transformation")
    if type(transformation_type) == Response:
        return transformation_type

    exp.log("/transformation POST request. Params: node_id: {}, info_in_id: {}, \
             info_out_id: {}"
            .format(node_id, info_in_id, info_out_id))

    # check the node etc exists
    node = models.Node.query.get(node_id)
    if node is None:
        exp.log("Error: /transformation/ POST, node {} does not exist".format(node_id))
        page = error_page(error_type="/transformation POST, node does not exist")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=400, mimetype='application/json')

    info_in = models.Info.query.get(info_in_id)
    if info_in is None:
        exp.log("Error: /transformation/ POST, info_in {} does not exist".format(info_in_id))
        page = error_page(error_type="/transformation POST, info_in does not exist")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=400, mimetype='application/json')

    info_out = models.Info.query.get(info_out_id)
    if info_out is None:
        exp.log("Error: /transformation/ POST, info_out {} does not exist".format(info_out_id))
        page = error_page(error_type="/transformation POST, info_out does not exist")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=400, mimetype='application/json')

    if node_id != info_out.origin_id:
        exp.log("Error: /transformation POST request, node not origin of info_out")
        page = error_page(error_type="/transformation POST, node not origin of info_out")
        js = dumps({"status": "error", "html": page})
        return Response(js, status=403, mimetype='application/json')

    # execute the request
    transformation = transformation_type(info_in=info_in, info_out=info_out)
    session.commit()

    # ping the experiment
    exp.transformation_post_request(node=node, transformation=transformation)
    session.commit()

    # return the data
    data = transformation.__json__()
    data = {"status": "success", "transformation": data}
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
    db.logger.debug('rq: Queueing %s with id: %s for worker_function',
                    event_type, assignment_id)
    q.enqueue(worker_function, event_type, assignment_id, None)
    db.logger.debug('rq: Submitted Queue Length: %d (%s)', len(q),
                    ', '.join(q.job_ids))

    return Response(
        dumps({"status": "success"}),
        status=200,
        mimetype='application/json')


def check_for_duplicate_assignments(participant):
    participants = Participant.query.filter_by(assignmentid=participant.assignmentid).all()
    duplicates = [p for p in participants if p.uniqueid != participant.uniqueid and p.status < 100]
    for d in duplicates:
        q.enqueue(worker_function, "AssignmentAbandoned", None, d.uniqueid)


@db.scoped_session_decorator
def worker_function(event_type, assignment_id, participant_id):
    """Process the notification."""
    db.logger.debug("rq: worker_function working on job id: %s", get_current_job().id)
    db.logger.debug('rq: Received Queue Length: %d (%s)', len(q),
                    ', '.join(q.job_ids))

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

    elif event_type == "NotificationMissing":
        participant.status = 106
        session_psiturk.commit()
        session.commit()

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
