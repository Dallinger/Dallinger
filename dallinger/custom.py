"""Import custom routes into the experiment server."""

from datetime import datetime
from json import dumps
import logging
from operator import attrgetter
import os
import requests
import traceback

from flask import (
    Blueprint,
    request,
    Response,
    send_from_directory,
    render_template
)
from psiturk.db import db_session as session_psiturk
from psiturk.db import init_db
from psiturk.psiturk_config import PsiturkConfig
from psiturk.user_utils import PsiTurkAuthorization
from rq import get_current_job
from rq import Queue
from sqlalchemy.orm.exc import NoResultFound
from worker import conn

import dallinger
from dallinger import db
from dallinger import models

# Load the configuration options.
config = PsiturkConfig()
config.load_config()
myauth = PsiTurkAuthorization(config)

# Set logging options.
LOG_LEVELS = [
    logging.DEBUG,
    logging.INFO,
    logging.WARNING,
    logging.ERROR,
    logging.CRITICAL
]
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
    'custom_code',
    __name__,
    template_folder='templates',
    static_folder='static'
)

# Initialize the Dallinger database.
session = db.session

# Connect to the Redis queue for notifications.
q = Queue(connection=conn)

# Load the experiment.
experiment = dallinger.experiments.load()

"""Define some canned response types."""


def success_response(field=None, data=None, request_type=""):
    """Return a generic success response."""
    data_out = {}
    data_out["status"] = "success"
    if field:
        data_out[field] = data
    print("{} request successful.".format(request_type))
    js = dumps(data_out, default=date_handler)
    return Response(js, status=200, mimetype='application/json')


def error_response(error_type="Internal server error",
                   error_text=None,
                   status=400,
                   participant=None):
    """Return a generic server error response."""
    traceback.print_exc()
    print("Error: {}.".format(error_type))

    page = error_page(
        error_text=error_text,
        error_type=error_type,
        participant=participant)

    data = {
        "status": "error",
        "html": page
    }
    return Response(dumps(data), status=status, mimetype='application/json')


def error_page(participant=None, error_text=None, compensate=True,
               error_type="default"):
    """Render HTML for error page."""
    if error_text is None:

        error_text = """There has been an error and so you are unable to
        continue, sorry! If possible, please return the assignment so someone
        else can work on it."""

    if compensate:
        error_text += """ Please use the information below to contact us
        about compensation"""

    if participant is not None:
        hit_id = participant.hit_id,
        assignment_id = participant.assignment_id,
        worker_id = participant.worker_id
    else:
        hit_id = 'unknown'
        assignment_id = 'unknown'
        worker_id = 'unknown'

    return render_template(
        'error_dallinger.html',
        error_text=error_text,
        compensate=compensate,
        contact_address=config.get(
            'HIT Configuration', 'contact_email_on_error'),
        error_type=error_type,
        hit_id=hit_id,
        assignment_id=assignment_id,
        worker_id=worker_id
    )


"""Define functions for handling requests."""


@custom_code.teardown_request
def shutdown_session(_=None):
    """Rollback and close session at end of a request."""
    session.remove()
    db.logger.debug('Closing Dallinger DB session at flask request end')


"""Define routes for managing an experiment and the participants."""


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

    return success_response(request_type="launch")


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
    return Response(
        dumps({
            "status": "success",
            "summary": experiment(session).log_summary()
        }),
        status=200,
        mimetype='application/json'
    )


@custom_code.route('/quitter', methods=['POST'])
def quitter():
    """Overide the psiTurk quitter route."""
    exp = experiment(session)
    exp.log("Quitter route was hit.")

    return Response(
        dumps({
            "status": "success"
        }),
        status=200,
        mimetype='application/json'
    )


@custom_code.route('/experiment_property/<prop>', methods=['GET'])
@custom_code.route('/experiment/<prop>', methods=['GET'])
def experiment_property(prop):
    """Get a property of the experiment by name."""
    exp = experiment(session)
    p = getattr(exp, prop)
    return success_response(field=prop, data=p, request_type=prop)


@custom_code.route("/ad_address/<mode>/<hit_id>", methods=["GET"])
def ad_address(mode, hit_id):
    """Get the address of the ad on AWS.

    This is used at the end of the experiment to send participants
    back to AWS where they can complete and submit the HIT.
    """
    if mode == "debug":
        address = '/complete'
    elif mode in ["sandbox", "live"]:
        username = os.getenv('psiturk_access_key_id',
                             config.get("psiTurk Access",
                                        "psiturk_access_key_id"))
        password = os.getenv('psiturk_secret_access_id',
                             config.get("psiTurk Access",
                                        "psiturk_secret_access_id"))
        try:
            req = requests.get(
                'https://api.psiturk.org/api/ad/lookup/' + hit_id,
                auth=(username, password))
        except Exception:
            raise ValueError('api_server_not_reachable')
        else:
            if req.status_code == 200:
                hit_address = req.json()['ad_id']
            else:
                raise ValueError("something here")
        if mode == "sandbox":
            address = ('https://sandbox.ad.psiturk.org/complete/' +
                       str(hit_address))
        elif mode == "live":
            address = 'https://ad.psiturk.org/complete/' + str(hit_address)
    else:
        raise ValueError("Unknown mode: {}".format(mode))
    return success_response(field="address",
                            data=address,
                            request_type="ad_address")


@custom_code.route("/<page>", methods=["GET"])
def get_page(page):
    """Return the requested page."""
    return render_template(page + ".html")


@custom_code.route("/<directory>/<page>", methods=["GET"])
def get_page_from_directory(directory, page):
    """Get a page from a given directory."""
    return render_template(directory + '/' + page + '.html')


@custom_code.route("/consent")
def consent():
    """Return the consent form. Here for backwards-compatibility with 2.x."""
    return render_template(
        "consent.html",
        hit_id=request.args['hit_id'],
        assignment_id=request.args['assignment_id'],
        worker_id=request.args['worker_id'],
        mode=request.args['mode']
    )


"""Routes for reading and writing to the database."""


def request_parameter(parameter, parameter_type=None, default=None,
                      optional=False):
    """Get a parameter from a request.

    parameter is the name of the parameter you are looking for
    parameter_type is the type the parameter should have
    default is the value the parameter takes if it has not been passed

    If the parameter is not found and no default is specified,
    or if the parameter is found but is of the wrong type
    then a Response object is returned
    """
    exp = experiment(session)

    # get the parameter
    try:
        value = request.values[parameter]
    except KeyError:
        # if it isnt found use the default, or return an error Response
        if default is not None:
            return default
        elif optional:
            return None
        else:
            msg = "{} {} request, {} not specified".format(
                request.url, request.method, parameter)
            return error_response(error_type=msg)

    # check the parameter type
    if parameter_type is None:
        # if no parameter_type is required, return the parameter as is
        return value
    elif parameter_type == "int":
        # if int is required, convert to an int
        try:
            value = int(value)
            return value
        except ValueError:
            msg = "{} {} request, non-numeric {}: {}".format(
                request.url, request.method, parameter, value)
            return error_response(error_type=msg)
    elif parameter_type == "known_class":
        # if its a known class check against the known classes
        try:
            value = exp.known_classes[value]
            return value
        except KeyError:
            msg = "{} {} request, unknown_class: {} for parameter {}".format(
                request.url, request.method, value, parameter)
            return error_response(error_type=msg)
    elif parameter_type == "bool":
        # if its a boolean, convert to a boolean
        if value in ["True", "False"]:
            return value == "True"
        else:
            msg = "{} {} request, non-boolean {}: {}".format(
                request.url, request.method, parameter, value)
            return error_response(error_type=msg)
    else:
        msg = "/{} {} request, unknown parameter type: {} for parameter {}"\
            .format(request.url, request.method, parameter_type, parameter)
        return error_response(error_type=msg)


def assign_properties(thing):
    """Assign properties to an object.

    When creating something via a post request (e.g. a node), you can pass the
    properties of the object in the request. This function gets those values
    from the request and fills in the relevant columns of the table.
    """
    for p in range(5):
        property_name = "property" + str(p + 1)
        property = request_parameter(parameter=property_name, optional=True)
        if property:
            setattr(thing, property_name, property)

    session.commit()


@custom_code.route("/participant/<worker_id>/<hit_id>/<assignment_id>/<mode>",
                   methods=["POST"])
def create_participant(worker_id, hit_id, assignment_id, mode):
    """Create a participant.

    This route will be hit very early on as any nodes the participant creates
    will be defined in reference to the participant object.
    You must specify the worker_id, hit_id, assignment_id and mode in the url.
    """
    # check this worker hasn't already taken part
    parts = models.Participant.query.filter_by(worker_id=worker_id).all()
    if parts:
        print("participant already exists!")
        return Response(status=200)

    # make the participant
    participant = models.Participant(worker_id=worker_id,
                                     assignment_id=assignment_id,
                                     hit_id=hit_id,
                                     mode=mode)
    session.add(participant)
    session.commit()

    # make a psiturk participant too, for now
    from psiturk.models import Participant as PsiturkParticipant
    psiturk_participant = PsiturkParticipant(workerid=worker_id,
                                             assignmentid=assignment_id,
                                             hitid=hit_id)
    session_psiturk.add(psiturk_participant)
    session_psiturk.commit()

    # return the data
    return success_response(field="participant",
                            data=participant.__json__(),
                            request_type="participant post")


@custom_code.route("/participant/<participant_id>", methods=["GET"])
def get_participant(participant_id):
    """Get the participant with the given id."""
    try:
        ppt = models.Participant.query.filter_by(id=participant_id).one()
    except NoResultFound:
        return error_response(
            error_type="/participant GET: no participant found",
            status=403)

    # return the data
    return success_response(field="participant",
                            data=ppt.__json__(),
                            request_type="participant get")


@custom_code.route("/network/<network_id>", methods=["GET"])
def get_network(network_id):
    """Get the network with the given id."""
    try:
        net = models.Network.query.filter_by(id=network_id).one()
    except NoResultFound:
        return error_response(
            error_type="/network GET: no network found",
            status=403)

    # return the data
    return success_response(field="network",
                            data=net.__json__(),
                            request_type="network get")


@custom_code.route("/question/<participant_id>", methods=["POST"])
def create_question(participant_id):
    """Send a POST request to the question table.

    Questions store information at the participant level, not the node
    level.
    You should pass the question (string) number (int) and response
    (string) as arguments.
    """
    # Get the participant.
    try:
        ppt = models.Participant.query.filter_by(id=participant_id).one()
    except NoResultFound:
        return error_response(error_type="/question POST no participant found",
                              status=403)

    # Make sure the participant status is "working"
    if ppt.status != "working":
        error_type = "/question POST, status = {}".format(ppt.status)
        return error_response(error_type=error_type,
                              participant=ppt)

    question = request_parameter(parameter="question")
    response = request_parameter(parameter="response")
    number = request_parameter(parameter="number", parameter_type="int")
    for x in [question, response, number]:
        if type(x) == Response:
            return x

    try:
        # execute the request
        models.Question(participant=ppt, question=question,
                        response=response, number=number)
        session.commit()
    except Exception:
        return error_response(error_type="/question POST server error",
                              status=403)

    # return the data
    return success_response(request_type="question post")


@custom_code.route("/node/<int:node_id>/neighbors", methods=["GET"])
def node_neighbors(node_id):
    """Send a GET request to the node table.

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
    node_type = request_parameter(parameter="node_type",
                                  parameter_type="known_class",
                                  default=models.Node)
    failed = request_parameter(parameter="failed",
                               parameter_type="bool",
                               default=False)
    connection = request_parameter(parameter="connection", default="to")
    for x in [node_type, failed, connection]:
        if type(x) == Response:
            return x

    # make sure the node exists
    node = models.Node.query.get(node_id)
    if node is None:
        return error_response(
            error_type="/node/neighbors, node does not exist",
            error_text="/node/{}/neighbors, node {} does not exist"
            .format(node_id))

    # get its neighbors
    nodes = node.neighbours(
        type=node_type,
        failed=failed,
        connection=connection)

    try:
        # ping the experiment
        exp.node_get_request(
            node=node,
            nodes=nodes)
        session.commit()
    except Exception:
        return error_response(error_type="exp.node_get_request")

    return success_response(field="nodes",
                            data=[n.__json__() for n in nodes],
                            request_type="neighbors")


@custom_code.route("/node/<participant_id>", methods=["POST"])
def create_node(participant_id):
    """Send a POST request to the node table.

    This makes a new node for the participant, it calls:
        1. exp.get_network_for_participant
        2. exp.create_node
        3. exp.add_node_to_network
        4. exp.node_post_request
    """
    exp = experiment(session)

    # Get the participant.
    try:
        participant = models.Participant.\
            query.filter_by(id=participant_id).one()
    except NoResultFound:
        return error_response(error_type="/node POST no participant found",
                              status=403)

    # replace any duplicate assignments
    check_for_duplicate_assignments(participant)

    # Make sure the participant status is working
    if participant.status != "working":
        error_type = "/node POST, status = {}".format(participant.status)
        return error_response(error_type=error_type,
                              participant=participant)

    try:
        # execute the request
        network = exp.get_network_for_participant(participant=participant)

        if network is None:
            return Response(dumps({"status": "error"}), status=403)

        node = exp.create_node(
            participant=participant,
            network=network)

        assign_properties(node)

        exp.add_node_to_network(
            node=node,
            network=network)

        session.commit()

        # ping the experiment
        exp.node_post_request(participant=participant, node=node)
        session.commit()
    except Exception:
        return error_response(error_type="/node POST server error",
                              status=403,
                              participant=participant)

    # return the data
    return success_response(field="node",
                            data=node.__json__(),
                            request_type="/node POST")


@custom_code.route("/node/<int:node_id>/vectors", methods=["GET"])
def node_vectors(node_id):
    """Get the vectors of a node.

    You must specify the node id in the url.
    You can pass direction (incoming/outgoing/all) and failed
    (True/False/all).
    """
    exp = experiment(session)
    # get the parameters
    direction = request_parameter(parameter="direction", default="all")
    failed = request_parameter(parameter="failed",
                               parameter_type="bool", default=False)
    for x in [direction, failed]:
        if type(x) == Response:
            return x

    # execute the request
    node = models.Node.query.get(node_id)
    if node is None:
        return error_response(error_type="/node/vectors, node does not exist")

    try:
        vectors = node.vectors(direction=direction, failed=failed)
        exp.vector_get_request(node=node, vectors=vectors)
        session.commit()
    except Exception:
        return error_response(error_type="/node/vectors GET server error",
                              status=403,
                              participant=node.participant)

    # return the data
    return success_response(field="vectors",
                            data=[v.__json__() for v in vectors],
                            request_type="vector get")


@custom_code.route("/node/<int:node_id>/connect/<int:other_node_id>",
                   methods=["POST"])
def connect(node_id, other_node_id):
    """Connect to another node.

    The ids of both nodes must be speficied in the url.
    You can also pass direction (to/from/both) as an argument.
    """
    exp = experiment(session)

    # get the parameters
    direction = request_parameter(parameter="direction", default="to")
    if type(direction == Response):
        return direction

    # check the nodes exist
    node = models.Node.query.get(node_id)
    if node is None:
        return error_response(error_type="/node/connect, node does not exist")

    other_node = models.Node.query.get(other_node_id)
    if other_node is None:
        return error_response(
            error_type="/node/connect, other node does not exist",
            participant=node.participant)

    # execute the request
    try:
        vectors = node.connect(whom=other_node, direction=direction)
        for v in vectors:
            assign_properties(v)

        # ping the experiment
        exp.vector_post_request(
            node=node,
            vectors=vectors)

        session.commit()
    except Exception:
        return error_response(error_type="/vector POST server error",
                              status=403,
                              participant=node.participant)

    return success_response(field="vectors",
                            data=[v.__json__() for v in vectors],
                            request_type="vector post")


@custom_code.route("/info/<int:node_id>/<int:info_id>", methods=["GET"])
def get_info(node_id, info_id):
    """Get a specific info.

    Both the node and info id must be specified in the url.
    """
    exp = experiment(session)

    # check the node exists
    node = models.Node.query.get(node_id)
    if node is None:
        return error_response(error_type="/info, node does not exist")

    # execute the experiment method:
    info = models.Info.query.get(info_id)
    if info is None:
        return error_response(error_type="/info GET, info does not exist",
                              participant=node.participant)
    elif (info.origin_id != node.id and
          info.id not in
            [t.info_id for t in node.transmissions(direction="incoming",
                                                   status="received")]):
        return error_response(error_type="/info GET, forbidden info",
                              status=403,
                              participant=node.participant)

    try:
        # ping the experiment
        exp.info_get_request(node=node, infos=info)
        session.commit()
    except Exception:
        return error_response(error_type="/info GET server error",
                              status=403,
                              participant=node.participant)

    # return the data
    return success_response(field="info",
                            data=info.__json__(),
                            request_type="info get")


@custom_code.route("/node/<int:node_id>/infos", methods=["GET"])
def node_infos(node_id):
    """Get all the infos of a node.

    The node id must be specified in the url.
    You can also pass info_type.
    """
    exp = experiment(session)

    # get the parameters
    info_type = request_parameter(parameter="info_type",
                                  parameter_type="known_class",
                                  default=models.Info)
    if type(info_type) == Response:
        return info_type

    # check the node exists
    node = models.Node.query.get(node_id)
    if node is None:
        return error_response(error_type="/node/infos, node does not exist")

    try:
        # execute the request:
        infos = node.infos(type=info_type)

        # ping the experiment
        exp.info_get_request(
            node=node,
            infos=infos)

        session.commit()
    except Exception:
        return error_response(error_type="/node/infos GET server error",
                              status=403,
                              participant=node.participant)

    return success_response(field="infos",
                            data=[i.__json__() for i in infos],
                            request_type="infos")


@custom_code.route("/node/<int:node_id>/received_infos", methods=["GET"])
def node_received_infos(node_id):
    """Get all the infos a node has been sent and has received.

    You must specify the node id in the url.
    You can also pass the info type.
    """
    exp = experiment(session)

    # get the parameters
    info_type = request_parameter(parameter="info_type",
                                  parameter_type="known_class",
                                  default=models.Info)
    if type(info_type) == Response:
        return info_type

    # check the node exists
    node = models.Node.query.get(node_id)
    if node is None:
        return error_response(error_type="/node/infos, node does not exist")

    # execute the request:
    infos = node.received_infos(type=info_type)

    try:
        # ping the experiment
        exp.info_get_request(
            node=node,
            infos=infos)

        session.commit()
    except Exception:
        return error_response(error_type="info_get_request error",
                              status=403,
                              participant=node.participant)

    return success_response(field="infos",
                            data=[i.__json__() for i in infos],
                            request_type="received infos")


@custom_code.route("/info/<int:node_id>", methods=["POST"])
def info_post(node_id):
    """Create an info.

    The node id must be specified in the url.

    You must pass contents as an argument.
    info_type is an additional optional argument.
    If info_type is a custom subclass of Info it must be
    added to the known_classes of the experiment class.
    """
    exp = experiment(session)

    # get the parameters
    info_type = request_parameter(parameter="info_type",
                                  parameter_type="known_class",
                                  default=models.Info)
    contents = request_parameter(parameter="contents")
    for x in [info_type, contents]:
        if type(x) == Response:
            return x

    # check the node exists
    node = models.Node.query.get(node_id)
    if node is None:
        return error_response(error_type="/info POST, node does not exist")

    try:
        # execute the request
        info = info_type(origin=node, contents=contents)
        assign_properties(info)

        # ping the experiment
        exp.info_post_request(
            node=node,
            info=info)

        session.commit()
    except Exception:
        return error_response(error_type="/info POST server error",
                              status=403,
                              participant=node.participant)

    # return the data
    return success_response(field="info",
                            data=info.__json__(),
                            request_type="info post")


@custom_code.route("/node/<int:node_id>/transmissions", methods=["GET"])
def node_transmissions(node_id):
    """Get all the transmissions of a node.

    The node id must be specified in the url.
    You can also pass direction (to/from/all) or status (all/pending/received)
    as arguments.
    """
    exp = experiment(session)

    # get the parameters
    direction = request_parameter(parameter="direction", default="incoming")
    status = request_parameter(parameter="status", default="all")
    for x in [direction, status]:
        if type(x) == Response:
            return x

    # check the node exists
    node = models.Node.query.get(node_id)
    if node is None:
        return error_response(
            error_type="/node/transmissions, node does not exist")

    # execute the request
    transmissions = node.transmissions(direction=direction, status=status)

    try:
        if direction in ["incoming", "all"] and status in ["pending", "all"]:
            node.receive()
            session.commit()
        # ping the experiment
        exp.transmission_get_request(node=node, transmissions=transmissions)
        session.commit()
    except Exception:
        return error_response(
            error_type="/node/transmissions GET server error",
            status=403,
            participant=node.participant)

    # return the data
    return success_response(field="transmissions",
                            data=[t.__json__() for t in transmissions],
                            request_type="transmissions")


@custom_code.route("/node/<int:node_id>/transmit", methods=["POST"])
def node_transmit(node_id):
    """Transmit to another node.

    The sender's node id must be specified in the url.

    As with node.transmit() the key parameters are what and to_whom.
    However, the values these accept are more limited than for the back end
    due to the necessity of serialization.

    If what and to_whom are not specified they will default to None.
    Alternatively you can pass an int (e.g. '5') or a class name (e.g.
    'Info' or 'Agent'). Passing an int will get that info/node, passing
    a class name will pass the class. Note that if the class you are specifying
    is a custom class it will need to be added to the dictionary of
    known_classes in your experiment code.

    You may also pass the values property1, property2, property3, property4
    and property5. If passed this will fill in the relevant values of the
    transmissions created with the values you specified.

    For example, to transmit all infos of type Meme to the node with id 10:
    reqwest({
        url: "/node/" + my_node_id + "/transmit",
        method: 'post',
        type: 'json',
        data: {
            what: "Meme",
            to_whom: 10,
        },
    });
    """
    exp = experiment(session)

    what = request_parameter(parameter="what", optional=True)
    to_whom = request_parameter(parameter="to_whom", optional=True)

    # check the node exists
    node = models.Node.query.get(node_id)
    if node is None:
        return error_response(error_type="/node/transmit, node does not exist")

    # create what
    if what is not None:
        try:
            what = int(what)
            what = models.Info.get(what)
            if what is None:
                return error_response(
                    error_type="/node/transmit POST, info does not exist",
                    participant=node.participant)
        except Exception:
            try:
                what = exp.known_classes[what]
            except Exception:
                return error_response(
                    error_type="/node/transmit POST, info does not exist",
                    participant=node.participant)

    # create to_whom
    if to_whom is not None:
        try:
            to_whom = int(to_whom)
            to_whom = models.Node.get(to_whom)
            if what is None:
                return error_response(
                    error_type="/node/transmit POST, info does not exist",
                    participant=node.participant)
        except Exception:
            try:
                to_whom = exp.known_classes[to_whom]
            except Exception:
                return error_response(
                    error_type="/node/transmit POST, info does not exist",
                    participant=node.participant)

    # execute the request
    try:
        transmissions = node.transmit(what=what, to_whom=to_whom)
        for t in transmissions:
            assign_properties(t)
        session.commit()
        # ping the experiment
        exp.transmission_post_request(
            node=node,
            transmissions=transmissions)
        session.commit()
    except Exception:
        return error_response(error_type="/node/transmit POST, server error",
                              participant=node.participant)

    # return the data
    return success_response(field="transmissions",
                            data=[t.__json__() for t in transmissions],
                            request_type="transmit")


@custom_code.route("/node/<int:node_id>/transformations", methods=["GET"])
def transformation_get(node_id):
    """Get all the transformations of a node.

    The node id must be specified in the url.

    You can also pass transformation_type.
    """
    exp = experiment(session)

    # get the parameters
    transformation_type = request_parameter(parameter="transformation_type",
                                            parameter_type="known_class",
                                            default=models.Transformation)
    if type(transformation_type) == Response:
        return transformation_type

    # check the node exists
    node = models.Node.query.get(node_id)
    if node is None:
        return error_response(
            error_type="/node/transformations, node does not exist")

    # execute the request
    transformations = node.transformations(
        transformation_type=transformation_type)
    try:
        # ping the experiment
        exp.transformation_get_request(node=node,
                                       transformations=transformations)
        session.commit()
    except Exception:
        return error_response(error_type="/node/tranaformations GET failed",
                              participant=node.participant)

    # return the data
    return success_response(field="transformations",
                            data=[t.__json__() for t in transformations],
                            request_type="transformations")


@custom_code.route(
    "/transformation/<int:node_id>/<int:info_in_id>/<int:info_out_id>",
    methods=["POST"])
def transformation_post(node_id, info_in_id, info_out_id):
    """Transform an info.

    The ids of the node, info in and info out must all be in the url.
    You can also pass transformation_type.
    """
    exp = experiment(session)

    # Get the parameters.
    transformation_type = request_parameter(parameter="transformation_type",
                                            parameter_type="known_class",
                                            default=models.Transformation)
    if type(transformation_type) == Response:
        return transformation_type

    # Check that the node etc. exists.
    node = models.Node.query.get(node_id)
    if node is None:
        return error_response(
            error_type="/transformation POST, node does not exist")

    info_in = models.Info.query.get(info_in_id)
    if info_in is None:
        return error_response(
            error_type="/transformation POST, info_in does not exist",
            participant=node.participant)

    info_out = models.Info.query.get(info_out_id)
    if info_out is None:
        return error_response(
            error_type="/transformation POST, info_out does not exist",
            participant=node.participant)

    try:
        # execute the request
        transformation = transformation_type(info_in=info_in,
                                             info_out=info_out)
        assign_properties(transformation)
        session.commit()

        # ping the experiment
        exp.transformation_post_request(node=node,
                                        transformation=transformation)
        session.commit()
    except Exception:
        return error_response(error_type="/tranaformation POST failed",
                              participant=node.participant)

    # return the data
    return success_response(field="transformation",
                            data=transformation.__json__(),
                            request_type="transformation post")


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

    return success_response(request_type="notification")


def check_for_duplicate_assignments(participant):
    """Check that the assignment_id of the participant is unique.

    If it isnt the older participants will be failed.
    """
    participants = models.Participant.query.filter_by(
        assignment_id=participant.assignment_id).all()
    duplicates = [p for p in participants if (p.id != participant.id and
                                              p.status == "working")]
    for d in duplicates:
        q.enqueue(worker_function, "AssignmentAbandoned", None, d.id)


@db.scoped_session_decorator
def worker_function(event_type, assignment_id, participant_id):
    """Process the notification."""
    db.logger.debug("rq: worker_function working on job id: %s",
                    get_current_job().id)
    db.logger.debug('rq: Received Queue Length: %d (%s)', len(q),
                    ', '.join(q.job_ids))

    exp = experiment(session)
    key = "-----"

    exp.log("Received an {} notification for assignment {}, participant {}"
            .format(event_type, assignment_id, participant_id), key)

    if assignment_id is not None:
        # save the notification to the notification table
        notif = models.Notification(
            assignment_id=assignment_id,
            event_type=event_type)
        session.add(notif)
        session.commit()

        # try to identify the participant
        participants = models.Participant.query\
            .filter_by(assignment_id=assignment_id)\
            .all()

        # if there are multiple participants select the most recent
        if len(participants) > 1:
            if event_type in ['AssignmentAbandoned', 'AssignmentReturned']:
                participants = [p for p in participants if
                                p.status == "working"]
                if participants:
                    participant = min(participants,
                                      key=attrgetter('creation_time'))
                else:
                    return None
            else:
                participant = max(participants,
                                  key=attrgetter('creation_time'))

        # if there are none (this is also bad news) print an error
        elif len(participants) == 0:
            exp.log("Warning: No participants associated with this "
                    "assignment_id. Notification will not be processed.", key)
            return None

        # if theres only one participant (this is good) select them
        else:
            participant = participants[0]

    elif participant_id is not None:
        participant = models.Participant.query\
            .filter_by(id=participant_id).all()[0]
    else:
        raise ValueError(
            "Error: worker_function needs either an assignment_id or a "
            "participant_id, they cannot both be None")

    participant_id = participant.id

    if event_type == 'AssignmentAccepted':
        pass

    elif event_type == 'AssignmentAbandoned':
        if participant.status == "working":
            participant.end_time = datetime.now()
            participant.status = "abandoned"
            exp.assignment_abandoned(participant=participant)

    elif event_type == 'AssignmentReturned':
        if participant.status == "working":
            participant.end_time = datetime.now()
            participant.status = "returned"
            exp.assignment_returned(participant=participant)

    elif event_type == 'AssignmentSubmitted':
        if participant.status == "working":
            participant.end_time = datetime.now()
            participant.status = "submitted"

            # Approve the assignment.
            exp.recruiter().approve_hit(assignment_id)
            participant.base_pay = config.get(
                'HIT Configuration', 'base_payment')

            # Check that the participant's data is okay.
            worked = exp.data_check(participant=participant)

            # If it isn't, fail their nodes and recruit a replacement.
            if not worked:
                participant.status = "bad_data"
                exp.data_check_failed(participant=participant)
                exp.recruiter().recruit_participants(n=1)
            else:
                # If their data is ok, pay them a bonus.
                # Note that the bonus is paid before the attention check.
                bonus = exp.bonus(participant=participant)
                participant.bonus = bonus
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
                    exp.log("Attention check failed.", key)
                    participant.status = "did_not_attend"
                    exp.attention_check_failed(participant=participant)
                    exp.recruiter().recruit_participants(n=1)
                else:
                    # All good. Possibly recruit more participants.
                    exp.log("All checks passed.", key)
                    participant.status = "approved"
                    exp.submission_successful(participant=participant)
                    exp.recruit()

    elif event_type == "NotificationMissing":
        if participant.status == "working":
            participant.end_time = datetime.now()
            participant.status = "missing_notification"

    else:
        exp.log("Error: unknown event_type {}".format(event_type), key)

    session.commit()


def date_handler(obj):
    """Serialize dates."""
    return obj.isoformat() if hasattr(obj, 'isoformat') else obj
