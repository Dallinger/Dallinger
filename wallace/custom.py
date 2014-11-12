# this file imports custom routes into the experiment server

from flask import Blueprint, request, jsonify, Response, abort

from psiturk.psiturk_config import PsiturkConfig
from psiturk.experiment_errors import ExperimentError
from psiturk.user_utils import PsiTurkAuthorization

# # Database setup
from psiturk.db import db_session
from psiturk.models import Participant
from json import dumps, loads

from wallace import db, agents, models

# load the configuration options
config = PsiturkConfig()
config.load_config()
myauth = PsiTurkAuthorization(config)

# explore the Blueprint
custom_code = Blueprint(
    'custom_code', __name__,
    template_folder='templates',
    static_folder='static')

# Initialize the Wallace db
db_session_w = db.init_db(drop_all=False)

# Specify the experiment.
try:
    this_experiment = config.get('Experiment Configuration', 'experiment')
    mod = __import__('custom_experiments', fromlist=[this_experiment])
    experiment = getattr(mod, this_experiment)
except ImportError:
    print "Error: Could not import experiment."


###########################################################
#  serving warm, fresh, & sweet custom, user-provided routes
#  add them here
###########################################################

# ----------------------------------------------
# example computing bonus
# ----------------------------------------------
@custom_code.route('/compute_bonus', methods=['GET'])
def compute_bonus():
    # check that user provided the correct keys
    # errors will not be that gracefull here if being
    # accessed by the Javascrip client
    if 'uniqueId' not in request.args:
        raise ExperimentError('improper_inputs')
    uniqueId = request.args['uniqueId']

    try:
        # lookup user in database
        user = Participant.query.\
            filter(Participant.uniqueid == uniqueId).\
            one()
        user_data = loads(user.datastring)  # load datastring from JSON
        bonus = 0

        for record in user_data['data']:  # for line in data file
            trial = record['trialdata']
            if trial['phase'] == 'TEST':
                if trial['hit'] is True:
                    bonus += 0.02
        user.bonus = bonus
        db_session.add(user)
        db_session.commit()
        resp = {"bonusComputed": "success"}
        return jsonify(**resp)
    except:
        abort(404)  # again, bad to display HTML, but...


@custom_code.route('/launch', methods=["POST"])
def launch():
    exp = experiment(db_session_w)

    # Submit the first HIT
    exp.recruiter().open_recruitment(exp)

    # Return a response.
    data = {"status": "launched"}
    js = dumps(data)
    return Response(js, status=200, mimetype='application/json')


@custom_code.route("/agents", methods=["POST", "GET"])
def api_agent_create():

    exp = experiment(db_session_w)

    if request.method == 'POST':

        # Create the newcomer and trigger experiment-specific behavior
        newcomer = exp.agent_type()
        exp.newcomer_arrival_trigger(newcomer)

        # Return a response
        data = {'agents': {'uuid': newcomer.uuid}}
        js = dumps(data)
        return Response(js, status=200, mimetype='application/json')

    if request.method == "GET":
        data_agents = [agent.uuid for agent in exp.network.agents]
        data = {"agents": data_agents}
        js = dumps(data)
        return Response(js, status=200, mimetype='application/json')


@custom_code.route("/transmissions",
                   defaults={"transmission_uuid": None},
                   methods=["POST", "GET"])
@custom_code.route("/transmissions/<transmission_uuid>", methods=["GET"])
def api_transmission(transmission_uuid):

    exp = experiment(db_session_w)

    if request.method == 'GET':

        # Given a receiving agent, get its pending transmissions
        if transmission_uuid is None:
            print "no transmission uuid specified"
            pending_transmissions = models.Transmission\
                .query\
                .filter_by(destination_uuid=request.args['destination_uuid'])\
                .filter_by(receive_time=None)\
                .order_by(models.Transmission.transmit_time)\
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
        for i in xrange(len(pending_transmissions)):
            t = pending_transmissions[i]

            data_transmissions.append({
                "uuid": t.uuid,
                "info_uuid": t.info_uuid,
                "origin_uuid": t.origin_uuid,
                "destination_uuid": t.destination_uuid,
                "transmit_time": t.transmit_time,
                "receive_time": t.receive_time
            })
            data = {"transmissions": data_transmissions}

        js = dumps(data)
        return Response(js, status=200, mimetype='application/json')

    if request.method == "POST":

        info = models.Info\
            .query\
            .filter_by(uuid=request.args['info_uuid'])\
            .one()

        destination = agents.Agent\
            .query\
            .filter_by(uuid=request.args['destination_uuid'])\
            .one()

        transmission = models.Transmission(info=info, destination=destination)

        db_session_w.add(transmission)
        db_session_w.commit()

        data = {'uuid': transmission.uuid}
        js = dumps(data)

        return Response(js, status=200, mimetype='application/json')


@custom_code.route("/information",
                   defaults={"info_uuid": None},
                   methods=["POST"])
@custom_code.route("/information/<info_uuid>", methods=["GET"])
def api_info(info_uuid):

    exp = experiment(db_session_w)

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
            js = dumps(data)

            return Response(js, status=200, mimetype='application/json')

    if request.method == "POST":

        if 'origin_uuid' in request.args:

            # models
            node = models.Node\
                .query\
                .filter_by(uuid=request.args['origin_uuid'])\
                .one()

            info = models.Info(
                origin=node,
                contents=request.args['contents'])

            db_session_w.add(info)
            db_session_w.commit()

            # Trigger experiment-specific behavior that happens on creationg
            exp.information_creation_trigger(info)

            data = {'uuid': info.uuid}
            js = dumps(data)

            return Response(js, status=200, mimetype='application/json')
