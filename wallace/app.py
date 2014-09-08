from flask import Flask, request, json, Response
import experiments
import agents
import db

app = Flask(__name__)
session = db.init_db(drop_all=True)


@app.route('/')
def index():
    return 'Index page'


@app.route("/agents", methods=["POST", "GET"])
def api_agent_create():

    experiment = experiments.Demo1(session)

    if request.method == 'POST':

        # Create the newcomer and insert into the network
        newcomer = agents.Agent()
        experiment.network.add_agent(newcomer)

        # Trigger experiment-specific behavior that happens on arrival
        experiment.newcomer_arrival_trigger(newcomer)

        # Return a response
        data = {'agents': {'uuid': newcomer.uuid}}
        js = json.dumps(data)
        resp = Response(js, status=200, mimetype='application/json')
        return resp

    if request.method == "GET":
        data_agents = [agent.uuid for agent in experiment.network.agents]
        data = {"agents": data_agents}
        js = json.dumps(data)
        resp = Response(js, status=200, mimetype='application/json')
        return resp


if __name__ == "__main__":
    app.debug = True
    app.run()
