from flask import Flask, request, json, Response
import experiments
import agents
import db
import models

app = Flask(__name__)
session = db.init_db(drop_all=True)

experiment = experiments.Demo1


@app.route('/')
def index():
    return 'Index page'


@app.route("/agents", methods=["POST", "GET"])
def api_agent_create():

    exp = experiment(session)

    if request.method == 'POST':

        # Create the newcomer and insert into the network
        newcomer = agents.Agent()
        exp.network.add_agent(newcomer)

        # Trigger experiment-specific behavior that happens on arrival
        exp.newcomer_arrival_trigger(newcomer)

        # Return a response
        data = {'agents': {'uuid': newcomer.uuid}}
        js = json.dumps(data)
        resp = Response(js, status=200, mimetype='application/json')
        return resp

    if request.method == "GET":
        data_agents = [agent.uuid for agent in exp.network.agents]
        data = {"agents": data_agents}
        js = json.dumps(data)
        resp = Response(js, status=200, mimetype='application/json')
        return resp


@app.route("/transmissions", defaults={"transmission_uuid": None}, methods=["POST", "GET"])
@app.route("/transmissions/<transmission_uuid>", methods=["GET"])
def api_transmission(transmission_uuid):

    exp = experiment(session)

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

        js = json.dumps(data)
        resp = Response(js, status=200, mimetype='application/json')
        return resp

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

        exp.session.add(transmission)
        exp.session.commit()

        data = {'uuid': transmission.uuid}
        js = json.dumps(data)

        resp = Response(js, status=200, mimetype='application/json')
        return resp


@app.route("/information", defaults={"info_uuid": None}, methods=["POST"])
@app.route("/information/<info_uuid>", methods=["GET"])
def api_info(info_uuid):

    exp = experiment(session)

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
            js = json.dumps(data)

            resp = Response(js, status=200, mimetype='application/json')
            return resp

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

            exp.session.add(info)
            exp.session.commit()

            data = {'uuid': info.uuid}
            js = json.dumps(data)

            resp = Response(js, status=200, mimetype='application/json')
            return resp


if __name__ == "__main__":
    app.debug = True
    app.run()
