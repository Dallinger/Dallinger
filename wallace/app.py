from flask import Flask
import experiments
import db

app = Flask(__name__)

session = db.init_db(drop_all=True)


@app.route('/')
def index():
    return 'Index page'


@app.route('/demo2')
def start():
    experiment = experiments.Demo2(session)
    experiment.add_and_trigger_sources()      # Add any sources
    process = experiment.process  # Step through the process
    for i in xrange(experiment.num_steps):
        process.step()


if __name__ == "__main__":
    app.run()
    print session
