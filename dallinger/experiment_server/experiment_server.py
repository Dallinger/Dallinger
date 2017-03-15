""" This module provides the backend Flask server that serves an experiment. """

from datetime import datetime
from json import dumps
from operator import attrgetter
import re
import traceback
import user_agents

from flask import (
    abort,
    Flask,
    make_response,
    render_template,
    render_template_string,
    request,
    Response,
    send_from_directory,
)
from jinja2 import TemplateNotFound
from rq import get_current_job
from rq import Queue
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy import exc
from sqlalchemy import func
from sqlalchemy.sql.expression import true

from dallinger import db
from dallinger import experiment
from dallinger import models
from dallinger.heroku.worker import conn
from dallinger.compat import unicode
from dallinger.config import get_config

from .utils import nocache


config = get_config()
if not config.ready:
    config.load()

# Initialize the Dallinger database.
session = db.session

# Connect to the Redis queue for notifications.
q = Queue(connection=conn)

app = Flask('Experiment_Server')

Experiment = experiment.load()


"""Load the experiment's extra routes, if any."""

try:
    from dallinger_experiment import extra_routes
except ImportError:
    pass
else:
    app.register_blueprint(extra_routes)


"""Basic routes."""


@app.route('/')
def index():
    """Index route"""
    abort(404)


@app.route('/robots.txt')
def static_robots_txt():
    """Serve robots.txt from static file."""
    return send_from_directory('static', 'robots.txt')


@app.route('/favicon.ico')
def static_favicon():
    return send_from_directory('static', 'favicon.ico', mimetype='image/x-icon')


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
        "html": unicode(page)
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

    return make_response(
        render_template(
            'error.html',
            error_text=error_text,
            compensate=compensate,
            contact_address=config.get('contact_email_on_error'),
            error_type=error_type,
            hit_id=hit_id,
            assignment_id=assignment_id,
            worker_id=worker_id
        ),
        500,
    )


class ExperimentError(Exception):
    """
    Error class for experimental errors, such as subject not being found in
    the database.
    """
    def __init__(self, value):
        experiment_errors = dict(
            status_incorrectly_set=1000,
            hit_assign_worker_id_not_set_in_mturk=1001,
            hit_assign_worker_id_not_set_in_consent=1002,
            hit_assign_worker_id_not_set_in_exp=1003,
            hit_assign_appears_in_database_more_than_once=1004,
            already_started_exp=1008,
            already_started_exp_mturk=1009,
            already_did_exp_hit=1010,
            tried_to_quit=1011,
            intermediate_save=1012,
            improper_inputs=1013,
            browser_type_not_allowed=1014,
            api_server_not_reachable=1015,
            ad_not_found=1016,
            error_setting_worker_complete=1017,
            hit_not_registered_with_ad_server=1018,
            template_unsafe=1019,
            insert_mode_failed=1020,
            page_not_found=404,
            in_debug=2005,
            unknown_error=9999
        )
        self.value = value
        self.errornum = experiment_errors[self.value]
        self.template = "error.html"

    def __str__(self):
        return repr(self.value)


@app.errorhandler(ExperimentError)
def handle_exp_error(exception):
    """Handle errors by sending an error page."""
    app.logger.error(
        "%s (%s) %s", exception.value, exception.errornum, str(dict(request.args)))
    return error_page(error_type=exception.value)


"""Define functions for handling requests."""


@app.teardown_request
def shutdown_session(_=None):
    """Rollback and close session at end of a request."""
    session.remove()
    db.logger.debug('Closing Dallinger DB session at flask request end')


"""Define routes for managing an experiment and the participants."""


@app.route('/launch', methods=['POST'])
def launch():
    """Launch the experiment."""
    exp = Experiment(db.init_db(drop_all=False))
    exp.log("Launching experiment...", "-----")
    url_info = exp.recruiter().open_recruitment(n=exp.initial_recruitment_size)
    session.commit()

    return success_response("recruitment_url", url_info, request_type="launch")


@app.route('/ad', methods=['GET'])
@nocache
def advertisement():
    """
    This is the url we give for the ad for our 'external question'.  The ad has
    to display two different things: This page will be called from within
    mechanical turk, with url arguments hitId, assignmentId, and workerId.
    If the worker has not yet accepted the hit:
        These arguments will have null values, we should just show an ad for
        the experiment.
    If the worker has accepted the hit:
        These arguments will have appropriate values and we should enter the
        person in the database and provide a link to the experiment popup.
    """
    user_agent_string = request.user_agent.string
    user_agent_obj = user_agents.parse(user_agent_string)
    browser_ok = True
    for rule in config.get('browser_exclude_rule', '').split(','):
        myrule = rule.strip()
        if myrule in ["mobile", "tablet", "touchcapable", "pc", "bot"]:
            if (myrule == "mobile" and user_agent_obj.is_mobile) or\
               (myrule == "tablet" and user_agent_obj.is_tablet) or\
               (myrule == "touchcapable" and user_agent_obj.is_touch_capable) or\
               (myrule == "pc" and user_agent_obj.is_pc) or\
               (myrule == "bot" and user_agent_obj.is_bot):
                browser_ok = False
        elif myrule in user_agent_string:
            browser_ok = False

    if not browser_ok:
        # Handler for IE users if IE is not supported.
        raise ExperimentError('browser_type_not_allowed')

    if not ('hitId' in request.args and 'assignmentId' in request.args):
        raise ExperimentError('hit_assign_worker_id_not_set_in_mturk')
    hit_id = request.args['hitId']
    assignment_id = request.args['assignmentId']
    already_in_db = False
    if 'workerId' in request.args:
        worker_id = request.args['workerId']
        # First check if this workerId has completed the task before (v1).
        nrecords = models.Participant.query.\
            filter(models.Participant.assignment_id != assignment_id).\
            filter(models.Participant.worker_id == worker_id).\
            count()

        if nrecords > 0:  # Already completed task
            already_in_db = True
    else:  # If worker has not accepted the hit
        worker_id = None
    try:
        part = models.Participant.query.\
            filter(models.Participant.hit_id == hit_id).\
            filter(models.Participant.assignment_id == assignment_id).\
            filter(models.Participant.worker_id == worker_id).\
            one()
        status = part.status
    except exc.SQLAlchemyError:
        status = None

    debug_mode = config.get('mode') == 'debug'
    if ((status == 'working' and part.end_time is not None) or
            (debug_mode and status in ('submitted', 'approved'))):
        # They've done the debriefing but perhaps haven't submitted the HIT
        # yet.. Turn asignmentId into original assignment id before sending it
        # back to AMT
        is_sandbox = config.get('mode') == "sandbox"
        if is_sandbox:
            external_submit_url = "https://workersandbox.mturk.com/mturk/externalSubmit"
        else:
            external_submit_url = "https://www.mturk.com/mturk/externalSubmit"
        return render_template(
            'thanks.html',
            is_sandbox=is_sandbox,
            hitid=hit_id,
            assignmentid=assignment_id,
            workerid=worker_id,
            mode=config.get('mode'),
            external_submit_url=external_submit_url,
        )
    if status == 'working':
        # Once participants have finished the instructions, we do not allow
        # them to start the task again.
        raise ExperimentError('already_started_exp_mturk')
    elif already_in_db and not debug_mode:
        raise ExperimentError('already_did_exp_hit')
    elif not status or debug_mode:
        # Participant has not yet agreed to the consent. They might not
        # even have accepted the HIT.
        with open('templates/ad.html', 'r') as temp_file:
            ad_string = temp_file.read()
        ad_string = insert_mode(ad_string, config.get('mode'))
        return render_template_string(
            ad_string,
            hitid=hit_id,
            assignmentid=assignment_id,
            workerid=worker_id
        )
    else:
        raise ExperimentError('status_incorrectly_set')


@app.route('/summary', methods=['GET'])
def summary():
    """Summarize the participants' status codes."""
    state = {
        "status": "success",
        "summary": Experiment(session).log_summary(),
        "completed": False,
    }
    unfilled_nets = models.Network.query.filter(
        models.Network.full != true()
    ).with_entities(models.Network.id, models.Network.max_size).all()
    working = models.Participant.query.filter_by(
        status='working'
    ).with_entities(func.count(models.Participant.id)).scalar()
    state['unfilled_networks'] = len(unfilled_nets)
    nodes_remaining = 0
    required_nodes = 0
    if state['unfilled_networks'] == 0:
        if working == 0:
            state['completed'] = True
    else:
        for net in unfilled_nets:
            node_count = models.Node.query.filter_by(
                network_id=net.id
            ).with_entities(func.count(models.Node.id)).scalar()
            net_size = net.max_size
            required_nodes += net_size
            nodes_remaining += net_size - node_count
    state['nodes_remaining'] = nodes_remaining
    state['required_nodes'] = required_nodes

    return Response(
        dumps(state),
        status=200,
        mimetype='application/json'
    )


@app.route('/experiment_property/<prop>', methods=['GET'])
@app.route('/experiment/<prop>', methods=['GET'])
def experiment_property(prop):
    """Get a property of the experiment by name."""
    exp = Experiment(session)
    p = getattr(exp, prop)
    return success_response(field=prop, data=p, request_type=prop)


@app.route("/<page>", methods=["GET"])
def get_page(page):
    """Return the requested page."""
    try:
        return render_template(page + ".html")
    except TemplateNotFound:
        abort(404)


@app.route("/<directory>/<page>", methods=["GET"])
def get_page_from_directory(directory, page):
    """Get a page from a given directory."""
    return render_template(directory + '/' + page + '.html')


@app.route("/consent")
def consent():
    """Return the consent form. Here for backwards-compatibility with 2.x."""
    return render_template(
        "consent.html",
        hit_id=request.args['hit_id'],
        assignment_id=request.args['assignment_id'],
        worker_id=request.args['worker_id'],
        mode=config.get('mode')
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
    exp = Experiment(session)

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


@app.route("/participant/<worker_id>/<hit_id>/<assignment_id>/<mode>",
           methods=["POST"])
def create_participant(worker_id, hit_id, assignment_id, mode):
    """Create a participant.

    This route is hit early on. Any nodes the participant creates will be
    defined in reference to the participant object. You must specify the
    worker_id, hit_id, assignment_id, and mode in the url.
    """
    already_participated = models.Participant.query.\
        filter_by(worker_id=worker_id).one_or_none()

    if already_participated:
        db.logger.warning("Worker has already participated.")
        return error_response(
            error_type="/participant POST: worker has already participated.",
            status=403)

    duplicate = models.Participant.query.\
        filter_by(
            assignment_id=assignment_id,
            status="working")\
        .one_or_none()

    if duplicate:
        msg = """
            AWS has reused assignment_id while existing participant is
            working. Replacing older participant {}.
        """
        app.logger.warning(msg.format(duplicate.id))
        q.enqueue(worker_function, "AssignmentReassigned", None, duplicate.id)

    # Create the new participant.
    participant = models.Participant(
        worker_id=worker_id,
        assignment_id=assignment_id,
        hit_id=hit_id,
        mode=mode
    )
    session.add(participant)
    session.commit()

    # return the data
    return success_response(
        field="participant",
        data=participant.__json__(),
        request_type="participant post"
    )


@app.route("/participant/<participant_id>", methods=["GET"])
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


@app.route("/network/<network_id>", methods=["GET"])
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


@app.route("/question/<participant_id>", methods=["POST"])
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

    # Make sure the participant status is "working" or we're in debug mode
    if ppt.status != "working" and config.get('mode', None) != 'debug':
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


@app.route("/node/<int:node_id>/neighbors", methods=["GET"])
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
    exp = Experiment(session)

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


@app.route("/node/<participant_id>", methods=["POST"])
def create_node(participant_id):
    """Send a POST request to the node table.

    This makes a new node for the participant, it calls:
        1. exp.get_network_for_participant
        2. exp.create_node
        3. exp.add_node_to_network
        4. exp.node_post_request
    """
    exp = Experiment(session)

    # Get the participant.
    try:
        participant = models.Participant.\
            query.filter_by(id=participant_id).one()
    except NoResultFound:
        return error_response(error_type="/node POST no participant found",
                              status=403)

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


@app.route("/node/<int:node_id>/vectors", methods=["GET"])
def node_vectors(node_id):
    """Get the vectors of a node.

    You must specify the node id in the url.
    You can pass direction (incoming/outgoing/all) and failed
    (True/False/all).
    """
    exp = Experiment(session)
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


@app.route("/node/<int:node_id>/connect/<int:other_node_id>",
           methods=["POST"])
def connect(node_id, other_node_id):
    """Connect to another node.

    The ids of both nodes must be speficied in the url.
    You can also pass direction (to/from/both) as an argument.
    """
    exp = Experiment(session)

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


@app.route("/info/<int:node_id>/<int:info_id>", methods=["GET"])
def get_info(node_id, info_id):
    """Get a specific info.

    Both the node and info id must be specified in the url.
    """
    exp = Experiment(session)

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


@app.route("/node/<int:node_id>/infos", methods=["GET"])
def node_infos(node_id):
    """Get all the infos of a node.

    The node id must be specified in the url.
    You can also pass info_type.
    """
    exp = Experiment(session)

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


@app.route("/node/<int:node_id>/received_infos", methods=["GET"])
def node_received_infos(node_id):
    """Get all the infos a node has been sent and has received.

    You must specify the node id in the url.
    You can also pass the info type.
    """
    exp = Experiment(session)

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


@app.route("/info/<int:node_id>", methods=["POST"])
def info_post(node_id):
    """Create an info.

    The node id must be specified in the url.

    You must pass contents as an argument.
    info_type is an additional optional argument.
    If info_type is a custom subclass of Info it must be
    added to the known_classes of the experiment class.
    """
    exp = Experiment(session)

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


@app.route("/node/<int:node_id>/transmissions", methods=["GET"])
def node_transmissions(node_id):
    """Get all the transmissions of a node.

    The node id must be specified in the url.
    You can also pass direction (to/from/all) or status (all/pending/received)
    as arguments.
    """
    exp = Experiment(session)

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


@app.route("/node/<int:node_id>/transmit", methods=["POST"])
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
    exp = Experiment(session)

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


@app.route("/node/<int:node_id>/transformations", methods=["GET"])
def transformation_get(node_id):
    """Get all the transformations of a node.

    The node id must be specified in the url.

    You can also pass transformation_type.
    """
    exp = Experiment(session)

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


@app.route(
    "/transformation/<int:node_id>/<int:info_in_id>/<int:info_out_id>",
    methods=["POST"])
def transformation_post(node_id, info_in_id, info_out_id):
    """Transform an info.

    The ids of the node, info in and info out must all be in the url.
    You can also pass transformation_type.
    """
    exp = Experiment(session)

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


@app.route("/notifications", methods=["POST", "GET"])
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


def _debug_notify(assignment_id, participant_id=None,
                  event_type='AssignmentSubmitted'):
    return worker_function(event_type, assignment_id, participant_id)


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


@app.route('/worker_complete', methods=['GET'])
@db.scoped_session_decorator
def worker_complete():
    """Complete worker."""
    if 'uniqueId' not in request.args:
        status = "bad request"
    else:
        participant = models.Participant.query.filter_by(
            unique_id=request.args['uniqueId'],
        ).all()[0]
        participant.end_time = datetime.now()
        session.add(participant)
        session.commit()
        status = "success"
    if config.get('mode') == "debug":
        # Trigger notification directly in debug mode,
        # because there won't be one from MTurk
        _debug_notify(
            assignment_id=participant.assignment_id,
            participant_id=participant.id,
        )
    return success_response(field="status",
                            data=status,
                            request_type="worker complete")


@db.scoped_session_decorator
def worker_function(event_type, assignment_id, participant_id):
    """Process the notification."""
    try:
        db.logger.debug("rq: worker_function working on job id: %s",
                        get_current_job().id)
        db.logger.debug('rq: Received Queue Length: %d (%s)', len(q),
                        ', '.join(q.job_ids))
    except AttributeError:
        db.logger.debug('Debug worker_function called synchronously')

    exp = Experiment(session)
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

        # if there are one or more participants select the most recent
        if participants:
            participant = max(participants,
                              key=attrgetter('creation_time'))

        # if there are none print an error
        else:
            exp.log("Warning: No participants associated with this "
                    "assignment_id. Notification will not be processed.", key)
            return None

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
        if participant.status in ["working", "returned", "abandoned"]:
            participant.end_time = datetime.now()
            participant.status = "submitted"
            session.commit()

            # Approve the assignment.
            exp.recruiter().approve_hit(assignment_id)
            participant.base_pay = config.get('base_payment')

            # Check that the participant's data is okay.
            worked = exp.data_check(participant=participant)

            # If it isn't, fail their nodes and recruit a replacement.
            if not worked:
                participant.status = "bad_data"
                exp.data_check_failed(participant=participant)
                session.commit()
                exp.recruiter().recruit(n=1)
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
                    session.commit()
                    exp.recruiter().recruit(n=1)
                else:
                    # All good. Possibly recruit more participants.
                    exp.log("All checks passed.", key)
                    participant.status = "approved"
                    exp.submission_successful(participant=participant)
                    session.commit()
                    exp.recruit()

    elif event_type == "NotificationMissing":
        if participant.status == "working":
            participant.end_time = datetime.now()
            participant.status = "missing_notification"

    elif event_type == "AssignmentReassigned":
        participant.end_time = datetime.now()
        participant.status = "replaced"
        exp.assignment_reassigned(participant=participant)

    else:
        exp.log("Error: unknown event_type {}".format(event_type), key)

    session.commit()


def date_handler(obj):
    """Serialize dates."""
    return obj.isoformat() if hasattr(obj, 'isoformat') else obj


# Insert "mode" into pages so it's carried from page to page done server-side
# to avoid breaking backwards compatibility with old templates.
def insert_mode(page_html, mode):
    """Insert mode."""
    match_found = False
    matches = re.finditer('workerId={{ workerid }}', page_html)
    match = None
    for match in matches:
        match_found = True
    if match_found:
        new_html = page_html[:match.end()] + "&mode=" + mode +\
            page_html[match.end():]
        return new_html
    else:
        raise ExperimentError("insert_mode_failed")
